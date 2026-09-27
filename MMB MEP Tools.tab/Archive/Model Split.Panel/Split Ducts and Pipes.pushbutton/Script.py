# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Mechanical import MechanicalUtils, Duct
from Autodesk.Revit.DB.Plumbing import PlumbingUtils, Pipe
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import revit, script
import math

# ----------------------------------------------------------
# USER INPUTS
# ----------------------------------------------------------
GAP_SIZE_MM = 50.0  # gap size in mm

# ----------------------------------------------------------
# SETUP
# ----------------------------------------------------------
doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()
output = script.get_output()

GAP_SIZE_INTERNAL = UnitUtils.ConvertToInternalUnits(
    GAP_SIZE_MM, UnitTypeId.Millimeters
)
HALF_GAP = GAP_SIZE_INTERNAL / 2.0

selection_ids = list(uidoc.Selection.GetElementIds())

if not selection_ids:
    script.exit("No elements selected.")

# ----------------------------------------------------------
# SORT ELEMENTS
# ----------------------------------------------------------
ducts = []
pipes = []
floors = []

for eid in selection_ids:
    elem = doc.GetElement(eid)
    if not elem or not elem.Category:
        continue

    cat = elem.Category.Id.IntegerValue

    if cat == int(BuiltInCategory.OST_DuctCurves):
        ducts.append(elem)
    elif cat == int(BuiltInCategory.OST_PipeCurves):
        pipes.append(elem)
    elif cat == int(BuiltInCategory.OST_Floors):
        floors.append(elem)

if not floors:
    script.exit("No floors selected.")

if not ducts and not pipes:
    script.exit("No ducts or pipes selected.")

logger.info(
    "Processing {} ducts, {} pipes, {} floors".format(
        len(ducts), len(pipes), len(floors)
    )
)

# ----------------------------------------------------------
# HELPER: INTERSECTION WITH FLOOR PLANE
# ----------------------------------------------------------
def get_line_plane_intersection(line, z_value):
    p0 = line.GetEndPoint(0)
    direction = line.Direction
    denom = direction.Z

    if abs(denom) < 1e-9:
        return None

    t = (z_value - p0.Z) / denom
    return p0 + (direction * t)

# ----------------------------------------------------------
# MAIN TRANSACTION
# ----------------------------------------------------------
modified_ducts = set()
modified_pipes = set()

with Transaction(doc, "Split Ducts and Pipes at Floors") as t:
    t.Start()

    # ---------------- DUCTS ----------------
    for duct in ducts:
        loc = duct.Location
        if not isinstance(loc, LocationCurve):
            continue

        curve = loc.Curve
        if not isinstance(curve, Line):
            continue

        duct_line = curve
        duct_len = curve.Length
        start_param = curve.GetEndParameter(0)
        end_param = curve.GetEndParameter(1)

        for floor in floors:
            bbox = floor.get_BoundingBox(None)
            if not bbox:
                continue

            floor_z = bbox.Max.Z
            inter_pt = get_line_plane_intersection(duct_line, floor_z)
            if not inter_pt:
                continue

            proj = curve.Project(inter_pt)
            if not proj:
                continue

            param = proj.Parameter
            if param <= start_param or param >= end_param:
                continue

            delta_param = HALF_GAP / duct_len
            p1 = param - delta_param
            p2 = param + delta_param

            if p1 <= start_param or p2 >= end_param:
                continue

            split_pt1 = duct_line.Evaluate(p1, False)
            split_pt2 = duct_line.Evaluate(p2, False)

            first_id = MechanicalUtils.BreakCurve(doc, duct.Id, split_pt1)
            second_id = MechanicalUtils.BreakCurve(doc, duct.Id, split_pt2)

            doc.Delete(second_id)

            modified_ducts.add(duct.Id)
            modified_ducts.add(first_id)

            logger.info(
                "Duct {} split at floor {}".format(
                    duct.Id.IntegerValue, floor.Id.IntegerValue
                )
            )

    # ---------------- PIPES ----------------
    for pipe in pipes:
        loc = pipe.Location
        if not isinstance(loc, LocationCurve):
            continue

        curve = loc.Curve
        if not isinstance(curve, Line):
            continue

        pipe_line = curve
        pipe_len = curve.Length
        start_param = curve.GetEndParameter(0)
        end_param = curve.GetEndParameter(1)

        for floor in floors:
            bbox = floor.get_BoundingBox(None)
            if not bbox:
                continue

            floor_z = bbox.Max.Z
            inter_pt = get_line_plane_intersection(pipe_line, floor_z)
            if not inter_pt:
                continue

            proj = curve.Project(inter_pt)
            if not proj:
                continue

            param = proj.Parameter
            if param <= start_param or param >= end_param:
                continue

            delta_param = HALF_GAP / pipe_len
            p1 = param - delta_param
            p2 = param + delta_param

            if p1 <= start_param or p2 >= end_param:
                continue

            split_pt1 = pipe_line.Evaluate(p1, False)
            split_pt2 = pipe_line.Evaluate(p2, False)

            first_id = PlumbingUtils.BreakCurve(doc, pipe.Id, split_pt1)
            second_id = PlumbingUtils.BreakCurve(doc, pipe.Id, split_pt2)

            doc.Delete(second_id)

            modified_pipes.add(pipe.Id)
            modified_pipes.add(first_id)

            logger.info(
                "Pipe {} split at floor {}".format(
                    pipe.Id.IntegerValue, floor.Id.IntegerValue
                )
            )

    t.Commit()

# ----------------------------------------------------------
# SUMMARY
# ----------------------------------------------------------
output.print_md(
    "**Completed**  \n"
    "- Modified Ducts: **{0}**  \n"
    "- Modified Pipes: **{1}**  \n"
    "- Gap Size: **{2} mm**".format(
        len(modified_ducts),
        len(modified_pipes),
        GAP_SIZE_MM
    )
)