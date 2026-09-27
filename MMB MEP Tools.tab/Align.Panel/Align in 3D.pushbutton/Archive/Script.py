# -*- coding: utf-8 -*-
"""Align in 3D

Click on a destination MEP family/element, then on an MEP family/element
you'd like to move. Based on their two closest connectors, the second
element is ROTATED to match the destination's orientation (pivoting
about its own closest connector), then shifted perpendicular onto the
destination connector's centerline - aligning it in both plan view and
section view (same line/height as the destination). It is NOT slid along
that line, so the connectors are not snapped/joined together, and
ConnectTo() is never called. Matches Naviate LT's behaviour.
"""

__title__ = "Align\nin 3D"
__author__ = "pyRevit"
__doc__ = ("Click on a destination MEP family, and then on an MEP family "
           "you'd like to move. Based on their two closest connectors, "
           "the second is aligned to the first in 3D space.")

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()


# ---------------------------------------------------------------------------
# Connector helpers
# ---------------------------------------------------------------------------

def get_connector_manager(element):
    """Return the ConnectorManager for an element, or None if it has none.
    Covers Pipe/Duct/Conduit/CableTray (+ flex variants) and any
    FamilyInstance that carries an MEPModel (fittings, equipment,
    accessories, air terminals, etc.)."""
    if element is None:
        return None
    if isinstance(element, DB.MEPCurve):
        return element.ConnectorManager
    if isinstance(element, DB.FamilyInstance):
        mep_model = element.MEPModel
        if mep_model is not None:
            return mep_model.ConnectorManager
    return None


def get_connectors(element):
    cm = get_connector_manager(element)
    if cm is None:
        return []
    return [c for c in cm.Connectors]


class MepSelectionFilter(ISelectionFilter):
    """Restrict picking to elements that actually expose connectors."""
    def AllowElement(self, element):
        return len(get_connectors(element)) > 0

    def AllowReference(self, reference, position):
        return True


def pick_mep_element(prompt):
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element,
            MepSelectionFilter(),
            prompt
        )
    except Exception:
        # user hit Escape / cancelled
        return None
    return doc.GetElement(ref.ElementId)


def closest_connector_pair(conns_a, conns_b):
    """Return (conn_a, conn_b) with the smallest origin-to-origin distance."""
    best_pair, best_dist = None, None
    for ca in conns_a:
        for cb in conns_b:
            d = ca.Origin.DistanceTo(cb.Origin)
            if best_dist is None or d < best_dist:
                best_dist, best_pair = d, (ca, cb)
    return best_pair


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def orthonormalize(z_axis, x_hint):
    """Build a right-handed orthonormal frame from a fixed Z axis and an
    X hint vector (projected perpendicular to Z)."""
    z_axis = z_axis.Normalize()
    x_proj = x_hint - z_axis.Multiply(x_hint.DotProduct(z_axis))
    if x_proj.GetLength() < 1e-9:
        fallback = DB.XYZ.BasisX if abs(z_axis.DotProduct(DB.XYZ.BasisX)) < 0.9 else DB.XYZ.BasisY
        x_proj = fallback - z_axis.Multiply(fallback.DotProduct(z_axis))
    x_axis = x_proj.Normalize()
    y_axis = z_axis.CrossProduct(x_axis)
    return x_axis, y_axis, z_axis


def signed_angle(v_from, v_to, axis):
    """Signed angle (radians) to rotate v_from onto v_to about axis."""
    v_from, v_to = v_from.Normalize(), v_to.Normalize()
    angle = v_from.AngleTo(v_to)
    if v_from.CrossProduct(v_to).DotProduct(axis) < 0:
        angle = -angle
    return angle


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def align_in_3d():
    dest_el = pick_mep_element("Select DESTINATION MEP family/element (stays put)")
    if not dest_el:
        script.exit()

    move_el = pick_mep_element("Select MEP family/element to MOVE and align")
    if not move_el:
        script.exit()

    if dest_el.Id == move_el.Id:
        forms.alert("Please pick two different elements.", exitscript=True)

    dest_conns = get_connectors(dest_el)
    move_conns = get_connectors(move_el)
    if not dest_conns or not move_conns:
        forms.alert("Both elements need at least one MEP connector.", exitscript=True)

    dest_conn, move_conn = closest_connector_pair(dest_conns, move_conns)

    dest_cs = dest_conn.CoordinateSystem   # BasisZ = connector direction
    move_cs = move_conn.CoordinateSystem

    # Target frame: origin at the destination connector, facing OPPOSITE
    # the destination connector's direction so the two connectors face
    # each other (a real pipe/duct joint always mates nose-to-nose).
    target_z = dest_cs.BasisZ.Negate()
    target_x, target_y, target_z = orthonormalize(target_z, dest_cs.BasisX)
    target_origin = dest_conn.Origin

    move_origin = move_conn.Origin
    move_z = move_cs.BasisZ
    move_x = move_cs.BasisX

    with DB.Transaction(doc, "Align in 3D") as t:
        t.Start()
        try:
            # 1) Rotate so the moving connector's axis matches target_z.
            #    Rotation axis passes through the connector origin, so
            #    that point does not shift during this step.
            angle_z = move_z.AngleTo(target_z)
            if angle_z > 1e-9:
                rot_axis = move_z.CrossProduct(target_z)
                if rot_axis.GetLength() < 1e-9:
                    fallback = DB.XYZ.BasisX if abs(move_z.DotProduct(DB.XYZ.BasisX)) < 0.9 else DB.XYZ.BasisY
                    rot_axis = move_z.CrossProduct(fallback)
                rot_axis = rot_axis.Normalize()
                axis_line = DB.Line.CreateBound(move_origin, move_origin + rot_axis)
                DB.ElementTransformUtils.RotateElement(doc, move_el.Id, axis_line, angle_z)
                rotation_tf = DB.Transform.CreateRotationAtPoint(rot_axis, angle_z, move_origin)
                move_x = rotation_tf.OfVector(move_x)

            # 2) Rotate about the now-aligned axis to match rotational
            #    orientation (twist) with the target X axis.
            move_x_proj = move_x - target_z.Multiply(move_x.DotProduct(target_z))
            if move_x_proj.GetLength() > 1e-9:
                twist_angle = signed_angle(move_x_proj, target_x, target_z)
                if abs(twist_angle) > 1e-9:
                    axis_line2 = DB.Line.CreateBound(move_origin, move_origin + target_z)
                    DB.ElementTransformUtils.RotateElement(doc, move_el.Id, axis_line2, twist_angle)

            # 3) Snap onto the destination connector's centerline, in the
            #    two directions PERPENDICULAR to that line only - this is
            #    what aligns the element in both plan view and section
            #    view simultaneously (same "line"/height as destination),
            #    without sliding it along that line toward the
            #    destination. The along-line distance is left untouched,
            #    so the two connectors do not move to touch/snap together.
            vec_to_target_line = move_origin - target_origin
            along = vec_to_target_line.DotProduct(target_z)
            perp_offset = vec_to_target_line - target_z.Multiply(along)
            if perp_offset.GetLength() > 1e-9:
                DB.ElementTransformUtils.MoveElement(doc, move_el.Id, perp_offset.Negate())

            t.Commit()
        except Exception as ex:
            t.RollBack()
            logger.error(ex)
            forms.alert("Align failed:\n{}".format(ex))
            script.exit()


if __name__ == "__main__":
    align_in_3d()
