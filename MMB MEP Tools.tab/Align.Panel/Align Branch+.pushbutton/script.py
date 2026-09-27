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
Align Branch+ | Revit 2025 and later
Naviate LT-style tool

Selection:
1. Select MAIN
2. Select BRANCH

Supported:
- Pipes
- Ducts
- Cable trays
- Conduits

Behaviour:
- Main remains unchanged.
- Branch becomes perpendicular to main in plan.
- Original branch 3D length is preserved.
- Branch is positioned so its infinite centreline logically intersects main.
- Pipes follow gravity towards main.
- Ducts, cable trays and conduits retain closest-direction behaviour.
- Escape and unsupported selections exit silently.
"""

from pyrevit import revit, DB
from Autodesk.Revit.DB import XYZ, Line, Transaction
from Autodesk.Revit.UI.Selection import ObjectType


# ============================================================
# Constants
# ============================================================

EPS = 1.0e-9
LENGTH_TOL = 1.0e-6


# ============================================================
# Revit version compatibility
# ============================================================

def get_id_value(element_id):
    """
    Revit 2025 and later use ElementId.Value.
    IntegerValue is retained as a fallback.
    """
    if element_id is None:
        return None

    try:
        return int(element_id.Value)
    except:
        pass

    try:
        return int(element_id.IntegerValue)
    except:
        return None


def get_bic_value(bic):
    """
    Safely returns the numeric BuiltInCategory value.
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


def get_category_value(element):
    """
    Safely returns the category ID of an element.
    """
    if element is None:
        return None

    try:
        if element.Category is None:
            return None

        return get_id_value(element.Category.Id)

    except:
        return None


PIPE_CATEGORY = get_bic_value(
    DB.BuiltInCategory.OST_PipeCurves
)

DUCT_CATEGORY = get_bic_value(
    DB.BuiltInCategory.OST_DuctCurves
)

CABLE_TRAY_CATEGORY = get_bic_value(
    DB.BuiltInCategory.OST_CableTray
)

CONDUIT_CATEGORY = get_bic_value(
    DB.BuiltInCategory.OST_Conduit
)

SUPPORTED_CATEGORIES = [
    PIPE_CATEGORY,
    DUCT_CATEGORY,
    CABLE_TRAY_CATEGORY,
    CONDUIT_CATEGORY
]


# ============================================================
# Safe geometry helpers
# ============================================================

def safe_length(vector):
    if vector is None:
        return 0.0

    try:
        return vector.GetLength()
    except:
        return 0.0


def safe_normalize(vector):
    """
    Safely normalises an XYZ vector.
    """
    if vector is None:
        return None

    length = safe_length(vector)

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


def project_to_xy(vector):
    if vector is None:
        return None

    try:
        return XYZ(vector.X, vector.Y, 0.0)
    except:
        return None


def normalize_xy(vector):
    return safe_normalize(project_to_xy(vector))


def reverse_xyz(vector):
    if vector is None:
        return None

    try:
        return XYZ(
            -vector.X,
            -vector.Y,
            -vector.Z
        )
    except:
        return None


def reverse_xy(vector):
    if vector is None:
        return None

    try:
        return XYZ(
            -vector.X,
            -vector.Y,
            0.0
        )
    except:
        return None


def dot_xy(vector_a, vector_b):
    if vector_a is None or vector_b is None:
        return 0.0

    try:
        return (
            vector_a.X * vector_b.X +
            vector_a.Y * vector_b.Y
        )
    except:
        return 0.0


def dot_3d(vector_a, vector_b):
    if vector_a is None or vector_b is None:
        return 0.0

    try:
        return vector_a.DotProduct(vector_b)
    except:
        return 0.0


# ============================================================
# Element geometry
# ============================================================

def get_line_data(element):
    """
    Gets line geometry without using isinstance().
    This avoids the Revit 2026 selection/validation issue.

    Returns:
        start
        end
        direction
        length
        curve
    """
    if element is None:
        return None

    try:
        location = element.Location
    except:
        return None

    if location is None:
        return None

    try:
        curve = location.Curve
    except:
        return None

    if curve is None:
        return None

    # Do not use:
    # isinstance(curve, DB.Line)
    #
    # Instead, verify that endpoint access is available.
    try:
        start = curve.GetEndPoint(0)
        end = curve.GetEndPoint(1)
    except:
        return None

    vector = end - start
    length = safe_length(vector)

    if length < EPS:
        return None

    direction = safe_normalize(vector)

    if direction is None:
        return None

    return {
        "start": start,
        "end": end,
        "direction": direction,
        "length": length,
        "curve": curve
    }


def is_pipe(element):
    return get_category_value(element) == PIPE_CATEGORY


def validate_pair(main_element, branch_element):
    """
    Validation occurs only after both selections.
    """
    if main_element is None or branch_element is None:
        return False

    try:
        if main_element.Id == branch_element.Id:
            return False
    except:
        return False

    main_category = get_category_value(main_element)
    branch_category = get_category_value(branch_element)

    if main_category not in SUPPORTED_CATEGORIES:
        return False

    if branch_category not in SUPPORTED_CATEGORIES:
        return False

    if main_category != branch_category:
        return False

    if get_line_data(main_element) is None:
        return False

    if get_line_data(branch_element) is None:
        return False

    return True


# ============================================================
# Closest points between infinite 3D lines
# ============================================================

def closest_points_between_lines(
        origin_1,
        direction_1,
        origin_2,
        direction_2):
    """
    Finds the closest points between two infinite 3D lines.

    Line 1:
        origin_1 + s * direction_1

    Line 2:
        origin_2 + t * direction_2

    Returns:
        point on line 1
        point on line 2
        s parameter
        t parameter
    """
    if (
        origin_1 is None or
        direction_1 is None or
        origin_2 is None or
        direction_2 is None
    ):
        return None

    try:
        w0 = origin_1 - origin_2

        a = direction_1.DotProduct(direction_1)
        b = direction_1.DotProduct(direction_2)
        c = direction_2.DotProduct(direction_2)
        d = direction_1.DotProduct(w0)
        e = direction_2.DotProduct(w0)

        denominator = a * c - b * b

        if abs(denominator) < EPS:
            if c > EPS:
                t_parameter = (
                    direction_2.DotProduct(w0) / c
                )
            else:
                t_parameter = 0.0

            point_2 = (
                origin_2 +
                direction_2.Multiply(t_parameter)
            )

            if a > EPS:
                s_parameter = (
                    direction_1.DotProduct(
                        point_2 - origin_1
                    ) / a
                )
            else:
                s_parameter = 0.0

            point_1 = (
                origin_1 +
                direction_1.Multiply(s_parameter)
            )

            return (
                point_1,
                point_2,
                s_parameter,
                t_parameter
            )

        s_parameter = (
            b * e - c * d
        ) / denominator

        t_parameter = (
            a * e - b * d
        ) / denominator

        point_1 = (
            origin_1 +
            direction_1.Multiply(s_parameter)
        )

        point_2 = (
            origin_2 +
            direction_2.Multiply(t_parameter)
        )

        return (
            point_1,
            point_2,
            s_parameter,
            t_parameter
        )

    except:
        return None


# ============================================================
# Slope helpers
# ============================================================

def get_slope(direction):
    """
    Returns rise divided by horizontal run.
    """
    if direction is None:
        return 0.0

    try:
        horizontal_vector = XYZ(
            direction.X,
            direction.Y,
            0.0
        )
    except:
        return 0.0

    horizontal_length = safe_length(horizontal_vector)

    if horizontal_length < EPS:
        return 0.0

    try:
        return direction.Z / horizontal_length
    except:
        return 0.0


def make_3d_direction(xy_direction, slope):
    """
    Creates a 3D unit vector using:
    - XY direction
    - slope as rise/horizontal run
    """
    xy_unit = normalize_xy(xy_direction)

    if xy_unit is None:
        return None

    try:
        raw_direction = XYZ(
            xy_unit.X,
            xy_unit.Y,
            slope
        )
    except:
        return None

    return safe_normalize(raw_direction)


def get_perpendicular_xy_options(main_direction):
    """
    Returns the two possible XY directions perpendicular
    to main in plan.
    """
    main_xy = normalize_xy(main_direction)

    if main_xy is None:
        return None

    option_1 = safe_normalize(
        XYZ(
            -main_xy.Y,
            main_xy.X,
            0.0
        )
    )

    option_2 = safe_normalize(
        XYZ(
            main_xy.Y,
            -main_xy.X,
            0.0
        )
    )

    if option_1 is None or option_2 is None:
        return None

    return option_1, option_2


def get_closest_perpendicular_xy(
        main_direction,
        reference_direction):
    """
    Chooses the perpendicular direction closest to
    the supplied reference direction.
    """
    options = get_perpendicular_xy_options(
        main_direction
    )

    if options is None:
        return None

    option_1, option_2 = options

    reference_xy = normalize_xy(
        reference_direction
    )

    if reference_xy is None:
        return option_1

    score_1 = dot_xy(
        reference_xy,
        option_1
    )

    score_2 = dot_xy(
        reference_xy,
        option_2
    )

    if score_1 >= score_2:
        return option_1

    return option_2


# ============================================================
# Duct, cable tray and conduit target direction
# ============================================================

def get_standard_target_direction(
        main_direction,
        branch_direction):
    """
    Previous accepted behaviour for:
    - Duct
    - Cable tray
    - Conduit

    The closest direction is selected from both perpendicular
    sides and both possible slope signs.
    """
    options = get_perpendicular_xy_options(
        main_direction
    )

    if options is None:
        return None

    perpendicular_1, perpendicular_2 = options
    main_slope = get_slope(main_direction)

    candidates = []

    for xy_direction in [
        perpendicular_1,
        perpendicular_2
    ]:
        candidate_1 = make_3d_direction(
            xy_direction,
            main_slope
        )

        candidate_2 = make_3d_direction(
            xy_direction,
            -main_slope
        )

        if candidate_1 is not None:
            candidates.append(candidate_1)

        if candidate_2 is not None:
            candidates.append(candidate_2)

    if not candidates:
        return None

    best_direction = candidates[0]
    best_score = dot_3d(
        branch_direction,
        best_direction
    )

    for candidate in candidates[1:]:
        score = dot_3d(
            branch_direction,
            candidate
        )

        if score > best_score:
            best_score = score
            best_direction = candidate

    return safe_normalize(best_direction)


# ============================================================
# Pipe gravity target direction
# ============================================================

def get_pipe_gravity_target_direction(
        main_direction,
        branch_data,
        old_point_on_branch,
        branch_parameter):
    """
    Pipe-only Naviate LT-style gravity logic.

    The pipe branch:
    - becomes perpendicular to main in plan
    - uses the absolute main slope magnitude
    - falls towards the logical main intersection
    - preserves its original 3D length later
    """
    if (
        main_direction is None or
        branch_data is None or
        old_point_on_branch is None
    ):
        return None

    branch_start = branch_data["start"]
    branch_end = branch_data["end"]
    branch_direction = branch_data["direction"]
    branch_length = branch_data["length"]

    slope_magnitude = abs(
        get_slope(main_direction)
    )

    # Flat main gives a flat pipe branch.
    if slope_magnitude < EPS:
        return get_standard_target_direction(
            main_direction,
            branch_direction
        )

    distance_to_start = abs(
        branch_parameter
    )

    distance_to_end = abs(
        branch_length - branch_parameter
    )

    end_side_is_farther = (
        distance_to_end >= distance_to_start
    )

    if end_side_is_farther:
        # Existing end is farther from main.
        # The end should remain the high side.
        far_reference = (
            branch_end - old_point_on_branch
        )

        far_reference_xy = normalize_xy(
            far_reference
        )

        if far_reference_xy is None:
            far_reference_xy = normalize_xy(
                branch_direction
            )

        target_xy = get_closest_perpendicular_xy(
            main_direction,
            far_reference_xy
        )

        if target_xy is None:
            return None

        target_slope = slope_magnitude

    else:
        # Existing start is farther from main.
        # The start should remain the high side.
        far_reference = (
            branch_start - old_point_on_branch
        )

        far_reference_xy = normalize_xy(
            far_reference
        )

        if far_reference_xy is None:
            far_reference_xy = normalize_xy(
                reverse_xyz(branch_direction)
            )

        target_reference_xy = reverse_xy(
            far_reference_xy
        )

        if target_reference_xy is None:
            target_reference_xy = branch_direction

        target_xy = get_closest_perpendicular_xy(
            main_direction,
            target_reference_xy
        )

        if target_xy is None:
            return None

        target_slope = -slope_magnitude

    return make_3d_direction(
        target_xy,
        target_slope
    )


# ============================================================
# Create length-preserving branch geometry
# ============================================================

def create_new_branch_geometry(
        logical_intersection,
        target_direction,
        old_branch_parameter,
        original_length):
    """
    Creates a new branch centreline that:
    - passes through the logical main intersection
    - preserves the original exact 3D branch length
    - keeps the logical intersection at the same relative
      position along the infinite branch line
    """
    if logical_intersection is None:
        return None

    if original_length < EPS:
        return None

    target_unit = safe_normalize(
        target_direction
    )

    if target_unit is None:
        return None

    try:
        new_start = (
            logical_intersection -
            target_unit.Multiply(old_branch_parameter)
        )

        new_end = (
            new_start +
            target_unit.Multiply(original_length)
        )
    except:
        return None

    calculated_length = safe_length(
        new_end - new_start
    )

    if calculated_length < EPS:
        return None

    if abs(
        calculated_length - original_length
    ) > LENGTH_TOL:
        return None

    return new_start, new_end


# ============================================================
# Update the branch curve
# ============================================================

def set_branch_curve(
        branch_element,
        new_start,
        new_end):
    """
    Safely updates the existing branch LocationCurve.
    """
    if branch_element is None:
        return False

    if new_start is None or new_end is None:
        return False

    if safe_length(new_end - new_start) < EPS:
        return False

    try:
        location = branch_element.Location
    except:
        return False

    if location is None:
        return False

    try:
        new_curve = Line.CreateBound(
            new_start,
            new_end
        )
    except:
        return False

    try:
        location.Curve = new_curve
        return True
    except:
        return False


# ============================================================
# Main command
# ============================================================

def align_branch_plus():
    uidoc = revit.uidoc
    doc = revit.doc

    if uidoc is None or doc is None:
        return

    # --------------------------------------------------------
    # Pick first, validate later.
    # No selection filter is used, so Revit 2025 and 2026
    # can select elements normally.
    # --------------------------------------------------------

    try:
        main_reference = (
            uidoc.Selection.PickObject(
                ObjectType.Element,
                "Select MAIN element"
            )
        )

        main_element = doc.GetElement(
            main_reference.ElementId
        )

        branch_reference = (
            uidoc.Selection.PickObject(
                ObjectType.Element,
                "Select BRANCH element"
            )
        )

        branch_element = doc.GetElement(
            branch_reference.ElementId
        )

    except:
        # Escape or selection cancellation.
        return

    # Validation happens after both picks.
    if not validate_pair(
        main_element,
        branch_element
    ):
        return

    main_data = get_line_data(
        main_element
    )

    branch_data = get_line_data(
        branch_element
    )

    if main_data is None or branch_data is None:
        return

    main_start = main_data["start"]
    main_direction = main_data["direction"]

    branch_start = branch_data["start"]
    branch_direction = branch_data["direction"]
    branch_length = branch_data["length"]

    if normalize_xy(main_direction) is None:
        return

    if normalize_xy(branch_direction) is None:
        return

    # --------------------------------------------------------
    # Find current logical intersection.
    # --------------------------------------------------------

    closest_result = closest_points_between_lines(
        branch_start,
        branch_direction,
        main_start,
        main_direction
    )

    if closest_result is None:
        return

    (
        old_point_on_branch,
        logical_point_on_main,
        branch_parameter,
        main_parameter
    ) = closest_result

    # --------------------------------------------------------
    # Select category-specific behaviour.
    # --------------------------------------------------------

    if is_pipe(branch_element):
        target_direction = (
            get_pipe_gravity_target_direction(
                main_direction,
                branch_data,
                old_point_on_branch,
                branch_parameter
            )
        )
    else:
        target_direction = (
            get_standard_target_direction(
                main_direction,
                branch_direction
            )
        )

    if target_direction is None:
        return

    # --------------------------------------------------------
    # Preserve exact original 3D branch length.
    # --------------------------------------------------------

    new_geometry = create_new_branch_geometry(
        logical_point_on_main,
        target_direction,
        branch_parameter,
        branch_length
    )

    if new_geometry is None:
        return

    new_start, new_end = new_geometry

    # --------------------------------------------------------
    # Modify branch.
    # --------------------------------------------------------

    transaction = None
    transaction_started = False

    try:
        transaction = Transaction(
            doc,
            "Align Branch+"
        )

        transaction.Start()
        transaction_started = True

        success = set_branch_curve(
            branch_element,
            new_start,
            new_end
        )

        if not success:
            transaction.RollBack()
            transaction_started = False
            return

        doc.Regenerate()

        # Check final length before commit.
        updated_data = get_line_data(
            branch_element
        )

        if updated_data is None:
            transaction.RollBack()
            transaction_started = False
            return

        updated_length = updated_data["length"]

        if abs(
            updated_length - branch_length
        ) > LENGTH_TOL:
            transaction.RollBack()
            transaction_started = False
            return

        transaction.Commit()
        transaction_started = False

    except:
        if transaction is not None and transaction_started:
            try:
                transaction.RollBack()
            except:
                pass

        return


# ============================================================
# Run silently
# ============================================================

if __name__ == "__main__":
    try:
        align_branch_plus()
    except:
        pass