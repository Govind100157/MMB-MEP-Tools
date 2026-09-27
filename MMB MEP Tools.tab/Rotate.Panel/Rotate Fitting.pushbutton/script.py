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
Rotate MEP Fitting by Selected Angle

Revit 2025 / pyRevit

Supported categories:
- Duct Fittings
- Pipe Fittings
- Cable Tray Fittings
- Conduit Fittings

Workflow:
1. User selects the rotation angle.
2. User picks a fitting.
3. The fitting rotates around the appropriate local geometric axis.

Elbow:
- Rotates around the selected pivot connector's BasisZ axis.
- If exactly one connector is connected, that connector remains fixed.
- If both connectors are connected, the connector nearest the pick
  position is used as the pivot.

Tee:
- Rotates around the two most collinear run connectors.

Cancel and Escape:
- Exit silently.
"""

import math

from Autodesk.Revit.DB import (
    BuiltInCategory,
    ElementTransformUtils,
    Line,
    Transaction
)

from Autodesk.Revit.UI.Selection import (
    ISelectionFilter,
    ObjectType
)

from Autodesk.Revit.Exceptions import OperationCanceledException

from pyrevit import revit, forms


# ------------------------------------------------------------
# REVIT CONTEXT
# ------------------------------------------------------------

doc = revit.doc
uidoc = revit.uidoc


# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

TOLERANCE = 1e-9

SUPPORTED_CATEGORIES = [
    BuiltInCategory.OST_DuctFitting,
    BuiltInCategory.OST_PipeFitting,
    BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_ConduitFitting
]


# Display text mapped to angle in degrees
ANGLE_OPTIONS = {
    "11.25 degrees": 11.25,
    "22.5 degrees": 22.5,
    "30 degrees": 30.0,
    "45 degrees": 45.0,
    "60 degrees": 60.0,
    "90 degrees": 90.0,
    "180 degrees": 180.0,
    "-90 degrees": -90.0,
    "-60 degrees": -60.0,
    "-45 degrees": -45.0,
    "-30 degrees": -30.0,
    "-22.5 degrees": -22.5,
    "-11.25 degrees": -11.25
}


# Keep the display order consistent with Naviate LT
ANGLE_OPTION_ORDER = [
    "11.25 degrees",
    "22.5 degrees",
    "30 degrees",
    "45 degrees",
    "60 degrees",
    "90 degrees",
    "180 degrees",
    "-90 degrees",
    "-60 degrees",
    "-45 degrees",
    "-30 degrees",
    "-22.5 degrees",
    "-11.25 degrees"
]


# Optional visual configuration
# Positive angles use dark text.
# Negative angles use red text/background emphasis where supported.
ANGLE_OPTION_CONFIG = {
    "11.25 degrees": {
        "background": "0xFFFFFFFF"
    },
    "22.5 degrees": {
        "background": "0xFFFFFFFF"
    },
    "30 degrees": {
        "background": "0xFFFFFFFF"
    },
    "45 degrees": {
        "background": "0xFFFFFFFF"
    },
    "60 degrees": {
        "background": "0xFFFFFFFF"
    },
    "90 degrees": {
        "background": "0xFFFFFFFF"
    },
    "180 degrees": {
        "background": "0xFFFFFFFF"
    },
    "-90 degrees": {
        "background": "0xFFFFEEEE"
    },
    "-60 degrees": {
        "background": "0xFFFFEEEE"
    },
    "-45 degrees": {
        "background": "0xFFFFEEEE"
    },
    "-30 degrees": {
        "background": "0xFFFFEEEE"
    },
    "-22.5 degrees": {
        "background": "0xFFFFEEEE"
    },
    "-11.25 degrees": {
        "background": "0xFFFFEEEE"
    }
}


# ------------------------------------------------------------
# CATEGORY HELPERS
# ------------------------------------------------------------

def get_category_id_value(category_id):
    """
    Return the numerical value of an ElementId.

    Revit 2024 and newer generally expose ElementId.Value.
    Older API versions use ElementId.IntegerValue.
    """

    try:
        return category_id.Value
    except:
        try:
            return category_id.IntegerValue
        except:
            return None


def get_built_in_category_value(built_in_category):
    """Return the numerical value of a BuiltInCategory."""

    try:
        return int(built_in_category)
    except:
        return None


def is_supported_fitting(element):
    """
    Check whether the selected element belongs to one of the
    supported MEP fitting categories.
    """

    if element is None:
        return False

    category = element.Category

    if category is None:
        return False

    element_category_value = get_category_id_value(category.Id)

    if element_category_value is None:
        return False

    for built_in_category in SUPPORTED_CATEGORIES:

        category_value = get_built_in_category_value(
            built_in_category
        )

        if category_value == element_category_value:
            return True

    return False


# ------------------------------------------------------------
# SELECTION FILTER
# ------------------------------------------------------------

class FittingSelectionFilter(ISelectionFilter):
    """Allow only supported MEP fitting categories."""

    def AllowElement(self, element):
        return is_supported_fitting(element)

    def AllowReference(self, reference, position):
        return False


# ------------------------------------------------------------
# ANGLE SELECTION
# ------------------------------------------------------------

def select_rotation_angle():
    """
    Display the rotation-angle selection window.

    Returns:
        Angle in radians, or None when cancelled.
    """

    try:
        selected_option = forms.CommandSwitchWindow.show(
            ANGLE_OPTION_ORDER,
            message="Choose Angle",
            title="Rotate Fitting",
            width=420,
            config=ANGLE_OPTION_CONFIG
        )

    except:
        # Fallback for pyRevit versions that do not support
        # title, width, or config in the same way.
        try:
            selected_option = forms.CommandSwitchWindow.show(
                ANGLE_OPTION_ORDER,
                message="Choose Angle"
            )
        except:
            return None

    if not selected_option:
        return None

    angle_degrees = ANGLE_OPTIONS.get(selected_option)

    if angle_degrees is None:
        return None

    return math.radians(angle_degrees)


# ------------------------------------------------------------
# CONNECTOR HELPERS
# ------------------------------------------------------------

def get_connectors(element):
    """
    Return all connectors belonging to the fitting.
    """

    connectors = []

    # FamilyInstance MEP fittings
    try:
        connector_manager = element.MEPModel.ConnectorManager

        if connector_manager is not None:

            for connector in connector_manager.Connectors:
                connectors.append(connector)

            return connectors

    except:
        pass

    # Fallback for elements exposing ConnectorManager directly
    try:
        connector_manager = element.ConnectorManager

        if connector_manager is not None:

            for connector in connector_manager.Connectors:
                connectors.append(connector)

    except:
        pass

    return connectors


def connector_is_connected(connector):
    """Safely check whether a connector is connected."""

    try:
        return connector.IsConnected
    except:
        return False


def distance_between(point_1, point_2):
    """Return the distance between two XYZ points."""

    try:
        return point_1.DistanceTo(point_2)
    except:
        return float("inf")


# ------------------------------------------------------------
# ELBOW ROTATION LOGIC
# ------------------------------------------------------------

def find_elbow_pivot_connector(connectors, pick_point=None):
    """
    Determine the elbow connector that must remain fixed.

    Priority:
    1. If exactly one connector is connected, use that connector.
    2. If multiple connectors are connected, use the connected
       connector nearest the user's click position.
    3. If no connectors are connected, use the connector nearest
       the user's click position.
    4. Final fallback is the first connector.
    """

    if not connectors:
        return None

    connected_connectors = []

    for connector in connectors:

        if connector_is_connected(connector):
            connected_connectors.append(connector)

    # One end connected and one end open
    if len(connected_connectors) == 1:
        return connected_connectors[0]

    # Use the picked position to determine the intended pivot
    if pick_point is not None:

        if connected_connectors:
            candidates = connected_connectors
        else:
            candidates = connectors

        nearest_connector = None
        nearest_distance = float("inf")

        for connector in candidates:

            current_distance = distance_between(
                connector.Origin,
                pick_point
            )

            if current_distance < nearest_distance:
                nearest_distance = current_distance
                nearest_connector = connector

        if nearest_connector is not None:
            return nearest_connector

    # Prefer a connected connector
    if connected_connectors:
        return connected_connectors[0]

    return connectors[0]


def get_elbow_rotation_axis(fitting, pick_point=None):
    """
    Create the elbow rotation axis.

    The axis:
    - Passes through the pivot connector origin.
    - Follows that connector's BasisZ direction.

    Rotating around this axis keeps the pivot connector origin
    and connector direction geometrically unchanged.
    """

    connectors = get_connectors(fitting)

    if len(connectors) != 2:
        return None

    pivot_connector = find_elbow_pivot_connector(
        connectors,
        pick_point
    )

    if pivot_connector is None:
        return None

    try:
        axis_origin = pivot_connector.Origin

        axis_direction = (
            pivot_connector
            .CoordinateSystem
            .BasisZ
            .Normalize()
        )

        if axis_direction.GetLength() < TOLERANCE:
            return None

        return Line.CreateBound(
            axis_origin,
            axis_origin + axis_direction
        )

    except:
        return None


# ------------------------------------------------------------
# TEE ROTATION LOGIC
# ------------------------------------------------------------

def get_tee_rotation_axis(fitting):
    """
    Determine the tee run axis.

    The two connectors with the greatest absolute dot product
    are treated as the collinear run connectors.
    """

    connectors = get_connectors(fitting)

    if len(connectors) < 3:
        return None

    best_connector_1 = None
    best_connector_2 = None
    best_alignment = -1.0

    for index_1 in range(len(connectors)):

        for index_2 in range(index_1 + 1, len(connectors)):

            connector_1 = connectors[index_1]
            connector_2 = connectors[index_2]

            try:
                direction_1 = (
                    connector_1
                    .CoordinateSystem
                    .BasisZ
                    .Normalize()
                )

                direction_2 = (
                    connector_2
                    .CoordinateSystem
                    .BasisZ
                    .Normalize()
                )

                alignment = abs(
                    direction_1.DotProduct(direction_2)
                )

                if alignment > best_alignment:
                    best_alignment = alignment
                    best_connector_1 = connector_1
                    best_connector_2 = connector_2

            except:
                continue

    if best_connector_1 is None:
        return None

    if best_connector_2 is None:
        return None

    point_1 = best_connector_1.Origin
    point_2 = best_connector_2.Origin

    if point_1.DistanceTo(point_2) < TOLERANCE:
        return None

    try:
        return Line.CreateBound(
            point_1,
            point_2
        )
    except:
        return None


# ------------------------------------------------------------
# GENERAL ROTATION AXIS
# ------------------------------------------------------------

def get_rotation_axis(fitting, pick_point=None):
    """
    Select the correct geometric rotation-axis calculation
    based on the fitting connector count.
    """

    connectors = get_connectors(fitting)
    connector_count = len(connectors)

    # Elbow
    if connector_count == 2:
        return get_elbow_rotation_axis(
            fitting,
            pick_point
        )

    # Tee or similar multi-port fitting
    if connector_count >= 3:
        return get_tee_rotation_axis(fitting)

    return None


# ------------------------------------------------------------
# TRANSACTION HELPER
# ------------------------------------------------------------

def transaction_has_started(transaction):
    """
    Safely determine whether the transaction has started.
    """

    try:
        return transaction.HasStarted()
    except:
        return False


# ------------------------------------------------------------
# MAIN COMMAND
# ------------------------------------------------------------

def main():

    # Step 1: Ask the user to select an angle
    rotation_angle = select_rotation_angle()

    if rotation_angle is None:
        return

    # Step 2: Ask the user to select a fitting
    try:
        reference = uidoc.Selection.PickObject(
            ObjectType.Element,
            FittingSelectionFilter(),
            "Select fitting to rotate"
        )

    except OperationCanceledException:
        # Silent exit when Escape is pressed
        return

    except:
        return

    if reference is None:
        return

    fitting = doc.GetElement(reference.ElementId)

    if not is_supported_fitting(fitting):
        return

    # The picked position helps determine which elbow
    # connector should remain stationary.
    try:
        pick_point = reference.GlobalPoint
    except:
        pick_point = None

    # Step 3: Calculate the geometric rotation axis
    rotation_axis = get_rotation_axis(
        fitting,
        pick_point
    )

    if rotation_axis is None:
        return

    # Step 4: Rotate the fitting
    transaction = Transaction(
        doc,
        "Rotate Fitting"
    )

    try:
        transaction.Start()

        ElementTransformUtils.RotateElement(
            doc,
            fitting.Id,
            rotation_axis,
            rotation_angle
        )

        doc.Regenerate()

        transaction.Commit()

    except:
        if transaction_has_started(transaction):
            transaction.RollBack()

        # Silent failure with no popup or pyRevit error window
        return


# ------------------------------------------------------------
# RUN
# ------------------------------------------------------------

main()