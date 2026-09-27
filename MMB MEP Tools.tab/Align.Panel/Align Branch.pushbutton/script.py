# -*- coding: utf-8 -*-
#
# MMB MEP Tools
# Copyright (c) 2026 Govind Ranjith Kota
# All Rights Reserved.
#
# This software and its source code are proprietary and confidential.
# Unauthorized copying, modification, distribution, or use of this
# software, via any medium, is strictly prohibited without the
# express written permission of the copyright owner.
#
# Author: Govind Ranjith Kota
# Version: 1.0
#

"""
Align Branch
Naviate LT Style

Revit 2025+
Revit 2026+

Pick MAIN then BRANCH

Moves branch so its centreline intersects
the main centreline.

Translation only:
- No rotation
- No slope change
- No angle change
- Preserves exact element geometry
"""

from pyrevit import revit, DB
from Autodesk.Revit.DB import (
    ElementTransformUtils,
    Transaction
)
from Autodesk.Revit.UI.Selection import ObjectType


# ============================================================
# Constants
# ============================================================

EPS = 1e-9


# ============================================================
# Revit compatibility helpers
# ============================================================

def get_id_value(element_id):
    """
    Revit 2025 and later compatibility.
    """

    try:
        return int(element_id.Value)
    except:
        pass

    try:
        return int(element_id.IntegerValue)
    except:
        pass

    return None


def get_bic_value(bic):
    """
    BuiltInCategory compatibility.
    """

    try:
        return int(bic)
    except:
        pass

    try:
        return int(bic.value__)
    except:
        pass

    try:
        return get_id_value(DB.ElementId(bic))
    except:
        return None


# ============================================================
# Geometry helpers
# ============================================================

def safe_normalize(vector):
    """
    Safe normalize for Revit 2025/2026.
    """

    if vector is None:
        return None

    try:
        length = vector.GetLength()
    except:
        return None

    if length < EPS:
        return None

    try:
        return vector.Normalize()
    except:
        pass

    try:
        return vector.Divide(length)
    except:
        return None


def get_line_from_element(elem):
    """
    Gets a line definition from any straight
    MEP curve element.
    """

    if elem is None:
        return None

    try:
        loc = elem.Location
    except:
        return None

    if loc is None:
        return None

    try:
        curve = loc.Curve
    except:
        return None

    if curve is None:
        return None

    # Do NOT use isinstance(curve, DB.Line)
    # Revit 2026 can be inconsistent here

    try:
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
    except:
        return None

    dir_vec = p1 - p0

    try:
        length = dir_vec.GetLength()
    except:
        return None

    if length < EPS:
        return None

    dir_unit = safe_normalize(dir_vec)

    if dir_unit is None:
        return None

    return (p0, dir_unit)


# ============================================================
# Closest points between infinite lines
# ============================================================

def closest_points_between_lines(
        p1,
        u,
        p2,
        v):
    """
    Closest points between two infinite 3D lines.
    """

    try:

        w0 = p1 - p2

        a = u.DotProduct(u)
        b = u.DotProduct(v)
        c = v.DotProduct(v)
        d = u.DotProduct(w0)
        e = v.DotProduct(w0)

        denom = a * c - b * b

        if abs(denom) < EPS:

            if c > EPS:
                t = v.DotProduct(w0) / c
            else:
                t = 0.0

            pt2 = p2 + v.Multiply(t)

            if a > EPS:
                s = u.DotProduct(
                    pt2 - p1
                ) / a
            else:
                s = 0.0

            pt1 = p1 + u.Multiply(s)

            return (
                pt1,
                pt2
            )

        s = (
            b * e - c * d
        ) / denom

        t = (
            a * e - b * d
        ) / denom

        pt1 = p1 + u.Multiply(s)
        pt2 = p2 + v.Multiply(t)

        return (
            pt1,
            pt2
        )

    except:
        return None


# ============================================================
# Validation
# ============================================================

def validate_pair(
        main_elem,
        branch_elem):
    """
    Main and branch must:
    - be different
    - belong to same supported category
    """

    if main_elem is None:
        return False

    if branch_elem is None:
        return False

    try:
        if main_elem.Id == branch_elem.Id:
            return False
    except:
        return False

    try:
        if main_elem.Category is None:
            return False

        if branch_elem.Category is None:
            return False

    except:
        return False

    allowed_ids = [

        get_bic_value(
            DB.BuiltInCategory.OST_PipeCurves
        ),

        get_bic_value(
            DB.BuiltInCategory.OST_DuctCurves
        ),

        get_bic_value(
            DB.BuiltInCategory.OST_Conduit
        ),

        get_bic_value(
            DB.BuiltInCategory.OST_CableTray
        )
    ]

    try:
        main_cat = get_id_value(
            main_elem.Category.Id
        )

        branch_cat = get_id_value(
            branch_elem.Category.Id
        )

    except:
        return False

    if main_cat not in allowed_ids:
        return False

    if branch_cat not in allowed_ids:
        return False

    if main_cat != branch_cat:
        return False

    return True


# ============================================================
# Main command
# ============================================================

def align_branch():

    uidoc = revit.uidoc
    doc = revit.doc

    if uidoc is None:
        return

    if doc is None:
        return

    # --------------------------------------------------------
    # Selection
    # --------------------------------------------------------

    try:

        ref_main = uidoc.Selection.PickObject(
            ObjectType.Element,
            "Select MAIN element"
        )

        main_elem = doc.GetElement(
            ref_main.ElementId
        )

        ref_branch = uidoc.Selection.PickObject(
            ObjectType.Element,
            "Select BRANCH element"
        )

        branch_elem = doc.GetElement(
            ref_branch.ElementId
        )

    except:
        return

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    if not validate_pair(
            main_elem,
            branch_elem):
        return

    main_line = get_line_from_element(
        main_elem
    )

    branch_line = get_line_from_element(
        branch_elem
    )

    if main_line is None:
        return

    if branch_line is None:
        return

    p_main, u_main = main_line
    p_branch, u_branch = branch_line

    result = closest_points_between_lines(
        p_branch,
        u_branch,
        p_main,
        u_main
    )

    if result is None:
        return

    pt_branch, pt_main = result

    move_vec = pt_main - pt_branch

    try:
        dist = move_vec.GetLength()
    except:
        return

    if dist < 1e-6:
        return

    # --------------------------------------------------------
    # Move branch
    # --------------------------------------------------------

    t = None

    try:

        t = Transaction(
            doc,
            "Align Branch"
        )

        t.Start()

        ElementTransformUtils.MoveElement(
            doc,
            branch_elem.Id,
            move_vec
        )

        t.Commit()

    except:

        try:
            if t is not None:
                t.RollBack()
        except:
            pass

        return


# ============================================================
# Run silently
# ============================================================

if __name__ == "__main__":

    try:
        align_branch()
    except:
        pass
