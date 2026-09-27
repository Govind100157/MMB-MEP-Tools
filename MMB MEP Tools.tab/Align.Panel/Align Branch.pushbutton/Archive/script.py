# -*- coding: utf-8 -*-
"""
Align Branch (Naviate LT style, Revit 2025)
Pick MAIN then BRANCH (same category).
Moves branch so its centerline intersects main centerline.
Translation only: slope/angle unchanged.
"""

from pyrevit import revit, DB
from Autodesk.Revit.DB import ElementTransformUtils, XYZ, Transaction
from Autodesk.Revit.UI.Selection import ObjectType

def get_line_from_element(elem):
    loc = elem.Location
    if not hasattr(loc, "Curve") or loc.Curve is None:
        return None
    curve = loc.Curve
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    dir_vec = (p1 - p0)
    length = dir_vec.GetLength()
    if length < 1e-9:
        return None
    dir_unit = dir_vec.Normalize()
    return (p0, dir_unit)

def closest_points_between_lines(p1, u, p2, v):
    w0 = p1 - p2
    a = u.DotProduct(u)
    b = u.DotProduct(v)
    c = v.DotProduct(v)
    d = u.DotProduct(w0)
    e = v.DotProduct(w0)
    denom = a*c - b*b
    if abs(denom) < 1e-9:
        t = v.DotProduct(w0) / c if c > 1e-9 else 0.0
        pt2 = p2 + v.Multiply(t)
        s = u.DotProduct(pt2 - p1) / a if a > 1e-9 else 0.0
        pt1 = p1 + u.Multiply(s)
        return (pt1, pt2)
    s = (b*e - c*d) / denom
    t = (a*e - b*d) / denom
    pt1 = p1 + u.Multiply(s)
    pt2 = p2 + v.Multiply(t)
    return (pt1, pt2)

def validate_pair(main_elem, branch_elem):
    allowed_ids = [
        DB.BuiltInCategory.OST_PipeCurves.value__,
        DB.BuiltInCategory.OST_DuctCurves.value__,
        DB.BuiltInCategory.OST_Conduit.value__,
        DB.BuiltInCategory.OST_CableTray.value__
    ]
    if main_elem.Id == branch_elem.Id:
        return False
    if main_elem.Category is None or branch_elem.Category is None:
        return False
    main_cat_id = main_elem.Category.Id.IntegerValue
    branch_cat_id = branch_elem.Category.Id.IntegerValue
    if main_cat_id not in allowed_ids:
        return False
    if branch_cat_id not in allowed_ids:
        return False
    if main_cat_id != branch_cat_id:
        return False
    return True

def align_branch():
    uidoc = revit.uidoc
    doc = revit.doc

    try:
        ref_main = uidoc.Selection.PickObject(ObjectType.Element, "Select MAIN element")
        main_elem = doc.GetElement(ref_main.ElementId)
        ref_branch = uidoc.Selection.PickObject(ObjectType.Element, "Select BRANCH element")
        branch_elem = doc.GetElement(ref_branch.ElementId)
    except:
        return

    if not validate_pair(main_elem, branch_elem):
        return

    main_line = get_line_from_element(main_elem)
    branch_line = get_line_from_element(branch_elem)
    if main_line is None or branch_line is None:
        return

    p_main, u_main = main_line
    p_branch, u_branch = branch_line

    pt_branch, pt_main = closest_points_between_lines(p_branch, u_branch, p_main, u_main)
    move_vec = pt_main - pt_branch
    dist = move_vec.GetLength()
    if dist < 1e-6:
        return

    try:
        t = Transaction(doc, "Align Branch")
        t.Start()
        ElementTransformUtils.MoveElement(doc, branch_elem.Id, move_vec)
        t.Commit()
    except:
        return

if __name__ == "__main__":
    align_branch()
