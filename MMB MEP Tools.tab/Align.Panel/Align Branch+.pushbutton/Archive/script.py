# -*- coding: utf-8 -*-
"""
Align Branch+ Preserve Length with Pipe Gravity
Naviate LT style, Revit 2025

Pick MAIN then BRANCH.

Supported categories:
- Pipe
- Duct
- Cable Tray
- Conduit

Behaviour:
1. MAIN element remains fixed.
2. BRANCH centreline is logically aligned to intersect MAIN centreline.
3. BRANCH becomes perpendicular to MAIN in plan.
4. BRANCH original 3D length is preserved.
5. Ducts, cable trays and conduits use closest-direction slope logic.
6. Pipes use gravity logic:
   - Pipe branch slopes towards the main.
   - Far end of branch remains higher.
   - Logical intersection at main is lower.
7. Element is not recreated. LocationCurve is updated.
"""

from pyrevit import revit, DB, forms
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.DB import Transaction, XYZ


# ============================================================
# Tolerances
# ============================================================

MIN_LENGTH_TOL = 1e-9
XY_TOL = 1e-9


# ============================================================
# Basic helpers
# ============================================================

def safe_alert(msg):
    try:
        forms.alert(msg, exitscript=False)
    except:
        pass


def get_bic_int(bic):
    try:
        return bic.value__
    except:
        return int(bic)


def get_line_data(elem):
    """
    Gets start, end, direction and 3D length from a straight LocationCurve element.
    """
    if elem is None:
        return None

    loc = elem.Location

    if loc is None:
        return None

    if not hasattr(loc, "Curve"):
        return None

    curve = loc.Curve

    if curve is None:
        return None

    try:
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
    except:
        return None

    vec = p1 - p0
    length = vec.GetLength()

    if length < MIN_LENGTH_TOL:
        return None

    return {
        "start": p0,
        "end": p1,
        "dir": vec.Normalize(),
        "length": length,
        "curve": curve
    }


def project_to_xy(vec):
    return XYZ(vec.X, vec.Y, 0.0)


def normalize_xy(vec):
    xy = project_to_xy(vec)
    length = xy.GetLength()

    if length < XY_TOL:
        return None

    return xy.Normalize()


def reverse_xy(vec):
    return XYZ(-vec.X, -vec.Y, 0.0)


def dot_xy(a, b):
    return a.X * b.X + a.Y * b.Y


def dot_3d(a, b):
    return a.DotProduct(b)


def get_main_slope(main_dir):
    """
    Returns main slope as rise / horizontal run.

    main_dir is a unit vector.
    """
    main_xy_len = XYZ(main_dir.X, main_dir.Y, 0.0).GetLength()

    if main_xy_len < XY_TOL:
        return 0.0

    return main_dir.Z / main_xy_len


def make_3d_direction_from_xy_and_slope(xy_dir, slope_value):
    """
    Creates a 3D unit direction using:
    - XY direction
    - slope value as rise / horizontal run
    """
    raw = XYZ(
        xy_dir.X,
        xy_dir.Y,
        slope_value
    )

    if raw.GetLength() < MIN_LENGTH_TOL:
        return None

    return raw.Normalize()


def get_perpendicular_xy_options(main_dir):
    """
    Returns two possible horizontal perpendicular directions to main in plan.
    """
    main_xy = normalize_xy(main_dir)

    if main_xy is None:
        return None

    perp_1 = XYZ(-main_xy.Y, main_xy.X, 0.0).Normalize()
    perp_2 = XYZ(main_xy.Y, -main_xy.X, 0.0).Normalize()

    return perp_1, perp_2


def get_closest_perpendicular_xy(main_dir, reference_xy):
    """
    Picks the perpendicular XY direction closest to a reference XY direction.
    """
    options = get_perpendicular_xy_options(main_dir)

    if options is None:
        return None

    perp_1, perp_2 = options

    ref = normalize_xy(reference_xy)

    if ref is None:
        return perp_1

    dot_1 = dot_xy(ref, perp_1)
    dot_2 = dot_xy(ref, perp_2)

    if dot_1 >= dot_2:
        return perp_1
    else:
        return perp_2


# ============================================================
# Category helpers
# ============================================================

def get_category_id(elem):
    if elem is None:
        return None

    if elem.Category is None:
        return None

    return elem.Category.Id.IntegerValue


def is_pipe(elem):
    return get_category_id(elem) == get_bic_int(DB.BuiltInCategory.OST_PipeCurves)


# ============================================================
# Closest points between infinite 3D lines
# ============================================================

def closest_points_between_lines(p1, u, p2, v):
    """
    Finds closest points between two infinite 3D centre lines.

    Line 1:
        p1 + s * u

    Line 2:
        p2 + t * v

    u and v should be unit vectors.

    Returns:
        pt1, pt2, s_param, t_param

    s_param is the 3D signed distance from p1 to pt1 along u.
    """
    w0 = p1 - p2

    a = u.DotProduct(u)
    b = u.DotProduct(v)
    c = v.DotProduct(v)
    d = u.DotProduct(w0)
    e = v.DotProduct(w0)

    denom = a * c - b * b

    if abs(denom) < MIN_LENGTH_TOL:
        if c > MIN_LENGTH_TOL:
            t_param = v.DotProduct(w0) / c
        else:
            t_param = 0.0

        pt2 = p2 + v.Multiply(t_param)

        if a > MIN_LENGTH_TOL:
            s_param = u.DotProduct(pt2 - p1) / a
        else:
            s_param = 0.0

        pt1 = p1 + u.Multiply(s_param)

        return pt1, pt2, s_param, t_param

    s_param = (b * e - c * d) / denom
    t_param = (a * e - b * d) / denom

    pt1 = p1 + u.Multiply(s_param)
    pt2 = p2 + v.Multiply(t_param)

    return pt1, pt2, s_param, t_param


# ============================================================
# Target direction for ducts, trays and conduits
# ============================================================

def get_best_target_direction_standard(main_dir, branch_dir):
    """
    For ducts, cable trays and conduits.

    Requirements:
    - Perpendicular to main in plan
    - Uses main slope value
    - Chooses the closest 3D direction to current branch direction
    """
    options = get_perpendicular_xy_options(main_dir)

    if options is None:
        return None

    perp_1, perp_2 = options

    main_slope = get_main_slope(main_dir)

    candidates = []

    for xy_dir in [perp_1, perp_2]:
        d1 = make_3d_direction_from_xy_and_slope(xy_dir, main_slope)
        d2 = make_3d_direction_from_xy_and_slope(xy_dir, -main_slope)

        if d1 is not None:
            candidates.append(d1)

        if d2 is not None:
            candidates.append(d2)

    if len(candidates) == 0:
        return None

    best_dir = candidates[0]
    best_score = dot_3d(branch_dir, best_dir)

    for c in candidates:
        score = dot_3d(branch_dir, c)

        if score > best_score:
            best_score = score
            best_dir = c

    return best_dir.Normalize()


# ============================================================
# Target direction for pipes using gravity to main
# ============================================================

def get_target_direction_pipe_gravity(main_dir, branch_data, pt_branch, branch_param):
    """
    For pipes only.

    This makes the pipe branch behave closer to Naviate LT Align Branch+.

    Logic:
    - Branch is perpendicular to main in plan.
    - Branch uses the absolute slope magnitude of the main pipe.
    - Slope direction is chosen so the branch falls towards the logical main intersection.
    - Far end of the branch is higher.
    - Main side is lower.
    - Original 3D length is still preserved later.
    """

    branch_start = branch_data["start"]
    branch_end = branch_data["end"]
    branch_length = branch_data["length"]
    branch_dir = branch_data["dir"]

    main_slope = get_main_slope(main_dir)
    slope_mag = abs(main_slope)

    # If main is flat, pipe branch should also remain flat.
    if slope_mag < MIN_LENGTH_TOL:
        return get_best_target_direction_standard(main_dir, branch_dir)

    # Distances from the logical intersection point to each old endpoint.
    # These are used only to identify which side is the far side.
    dist_to_start = abs(branch_param)
    dist_to_end = abs(branch_length - branch_param)

    # Determine which side of the branch is the far side from the main intersection.
    end_side_is_far = dist_to_end >= dist_to_start

    if end_side_is_far:
        # The physical far end is the old end.
        # Desired direction from logical intersection towards far end.
        old_far_vec = XYZ(
            branch_end.X - pt_branch.X,
            branch_end.Y - pt_branch.Y,
            0.0
        )

        fallback_ref = branch_dir
        desired_dir_xy = normalize_xy(old_far_vec)

        if desired_dir_xy is None:
            desired_dir_xy = normalize_xy(fallback_ref)

        target_xy = get_closest_perpendicular_xy(main_dir, desired_dir_xy)

        if target_xy is None:
            return None

        # If end side is far, target direction from start to end should rise.
        target_slope = slope_mag

    else:
        # The physical far end is the old start.
        # Desired direction from logical intersection towards far start.
        old_far_vec = XYZ(
            branch_start.X - pt_branch.X,
            branch_start.Y - pt_branch.Y,
            0.0
        )

        desired_far_xy = normalize_xy(old_far_vec)

        if desired_far_xy is None:
            desired_far_xy = normalize_xy(reverse_xy(branch_dir))

        # target_dir is from start to end.
        # If start side is far, target direction should be opposite of far-side direction.
        if desired_far_xy is not None:
            desired_dir_xy = reverse_xy(desired_far_xy)
        else:
            desired_dir_xy = branch_dir

        target_xy = get_closest_perpendicular_xy(main_dir, desired_dir_xy)

        if target_xy is None:
            return None

        # If start side is far, target direction from start to end should fall.
        target_slope = -slope_mag

    target_dir = make_3d_direction_from_xy_and_slope(
        target_xy,
        target_slope
    )

    if target_dir is None:
        return None

    return target_dir.Normalize()


# ============================================================
# Validation
# ============================================================

def validate_pair(main_elem, branch_elem):
    allowed_ids = [
        get_bic_int(DB.BuiltInCategory.OST_PipeCurves),
        get_bic_int(DB.BuiltInCategory.OST_DuctCurves),
        get_bic_int(DB.BuiltInCategory.OST_CableTray),
        get_bic_int(DB.BuiltInCategory.OST_Conduit)
    ]

    if main_elem is None or branch_elem is None:
        safe_alert("Invalid selection.")
        return False

    if main_elem.Id == branch_elem.Id:
        safe_alert("Main and branch cannot be the same element.")
        return False

    if main_elem.Category is None or branch_elem.Category is None:
        safe_alert("Selected element does not have a valid category.")
        return False

    main_cat_id = main_elem.Category.Id.IntegerValue
    branch_cat_id = branch_elem.Category.Id.IntegerValue

    if main_cat_id not in allowed_ids:
        safe_alert("Main element must be Pipe, Duct, Cable Tray or Conduit.")
        return False

    if branch_cat_id not in allowed_ids:
        safe_alert("Branch element must be Pipe, Duct, Cable Tray or Conduit.")
        return False

    if main_cat_id != branch_cat_id:
        safe_alert("Main and branch must be from the same category.")
        return False

    return True


# ============================================================
# Curve updater
# ============================================================

def set_branch_curve(branch_elem, new_start, new_end):
    """
    Updates the branch LocationCurve.
    """
    loc = branch_elem.Location

    if loc is None:
        return False

    if not hasattr(loc, "Curve"):
        return False

    new_curve = DB.Line.CreateBound(new_start, new_end)
    loc.Curve = new_curve

    return True


# ============================================================
# Main command
# ============================================================

def align_branch_plus_preserve_length_pipe_gravity():
    uidoc = revit.uidoc
    doc = revit.doc

    try:
        ref_main = uidoc.Selection.PickObject(
            ObjectType.Element,
            "Select MAIN element"
        )
        main_elem = doc.GetElement(ref_main.ElementId)

        ref_branch = uidoc.Selection.PickObject(
            ObjectType.Element,
            "Select BRANCH element"
        )
        branch_elem = doc.GetElement(ref_branch.ElementId)

    except:
        return

    if not validate_pair(main_elem, branch_elem):
        return

    main_data = get_line_data(main_elem)
    branch_data = get_line_data(branch_elem)

    if main_data is None:
        safe_alert("Main element must be a straight linear element.")
        return

    if branch_data is None:
        safe_alert("Branch element must be a straight linear element.")
        return

    main_start = main_data["start"]
    main_dir = main_data["dir"]

    branch_start = branch_data["start"]
    branch_dir = branch_data["dir"]
    branch_length = branch_data["length"]

    main_xy = normalize_xy(main_dir)
    branch_xy = normalize_xy(branch_dir)

    if main_xy is None:
        safe_alert("Main element has no usable plan direction.")
        return

    if branch_xy is None:
        safe_alert("Branch element has no usable plan direction.")
        return

    # Find logical intersection between current branch infinite centreline
    # and main infinite centreline.
    pt_branch, pt_main, branch_param, main_param = closest_points_between_lines(
        branch_start,
        branch_dir,
        main_start,
        main_dir
    )

    # Category-specific target direction.
    if is_pipe(branch_elem):
        target_dir = get_target_direction_pipe_gravity(
            main_dir,
            branch_data,
            pt_branch,
            branch_param
        )
    else:
        target_dir = get_best_target_direction_standard(
            main_dir,
            branch_dir
        )

    if target_dir is None:
        safe_alert("Could not calculate target branch direction.")
        return

    # Length-preserving logic.
    # The logical intersection remains at pt_main.
    # branch_param controls where that logical intersection falls along the branch.
    logical_intersection = pt_main

    new_start = logical_intersection - target_dir.Multiply(branch_param)
    new_end = new_start + target_dir.Multiply(branch_length)

    new_length = (new_end - new_start).GetLength()

    if new_length < MIN_LENGTH_TOL:
        safe_alert("Calculated branch length is too small.")
        return

    try:
        t = Transaction(doc, "Align Branch+ Pipe Gravity")
        t.Start()

        success = set_branch_curve(
            branch_elem,
            new_start,
            new_end
        )

        if not success:
            t.RollBack()
            safe_alert("Could not update branch LocationCurve.")
            return

        t.Commit()

    except Exception as ex:
        try:
            if t.HasStarted():
                t.RollBack()
        except:
            pass

        safe_alert("Align Branch+ Pipe Gravity failed:\n\n{0}".format(str(ex)))
        return


# ============================================================
# Run
# ============================================================

if __name__ == "__main__":
    align_branch_plus_preserve_length_pipe_gravity()