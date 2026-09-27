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
Rotate MEP Fitting 180 Degrees

Revit 2025 / pyRevit

Supported categories:
- Duct Fittings
- Pipe Fittings
- Cable Tray Fittings
- Conduit Fittings

Logic:
- Elbow with 2 connectors:
    Rotate around the connected connector's BasisZ axis.
    This keeps the connected end fixed and rotates the open end.

- Tee with 3 or more connectors:
    Find the two most collinear connectors and rotate around
    the tee run axis.

- Escape and unsupported cases exit silently.
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

from pyrevit import revit, script


doc = revit.doc
uidoc = revit.uidoc


# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

TOLERANCE = 1e-9
ROTATION_ANGLE = math.pi


# ------------------------------------------------------------
# CATEGORY HELPERS
# ------------------------------------------------------------

SUPPORTED_CATEGORIES = [
    BuiltInCategory.OST_DuctFitting,
    BuiltInCategory.OST_PipeFitting,
    BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_ConduitFitting
]


def get_category_id_value(category_id):
    """
    Revit 2024+ uses ElementId.Value.
    Older API versions use ElementId.IntegerValue.
    """

    try:
        return category_id.Value
    except:
        try:
            return category_id.IntegerValue
        except:
            return None


def get_bic_id_value(bic):
    """Convert a BuiltInCategory to its numerical value."""

    try:
        return int(bic)
    except:
        return None


def is_supported_fitting(element):
    """Check whether the element belongs to a supported fitting category."""

    if element is None:
        return False

    category = element.Category

    if category is None:
        return False

    element_category_value = get_category_id_value(category.Id)

    if element_category_value is None:
        return False

    for bic in SUPPORTED_CATEGORIES:

        bic_value = get_bic_id_value(bic)

        if bic_value == element_category_value:
            return True

    return False


# ------------------------------------------------------------
# SELECTION FILTER
# ------------------------------------------------------------

class FittingSelectionFilter(ISelectionFilter):

    def AllowElement(self, element):
        return is_supported_fitting(element)

    def AllowReference(self, reference, point):
        return False


# ------------------------------------------------------------
# CONNECTOR HELPERS
# ------------------------------------------------------------

def get_connectors(element):
    """Return all physical connectors belonging to the fitting."""

    connectors = []

    # FamilyInstance MEP fittings
    try:
        connector_manager = element.MEPModel.ConnectorManager

        if connector_manager:
            for connector in connector_manager.Connectors:
                connectors.append(connector)

            return connectors

    except:
        pass

    # Fallback for elements exposing ConnectorManager directly
    try:
        connector_manager = element.ConnectorManager

        if connector_manager:
            for connector in connector_manager.Connectors:
                connectors.append(connector)

    except:
        pass

    return connectors


def connector_is_connected(connector):
    """Safely determine whether a connector is connected."""

    try:
        return connector.IsConnected
    except:
        return False


def distance_between(point_1, point_2):
    """Return distance between two XYZ points."""

    try:
        return point_1.DistanceTo(point_2)
    except:
        return float("inf")


# ------------------------------------------------------------
# ELBOW LOGIC
# ------------------------------------------------------------

def find_elbow_pivot_connector(connectors, pick_point=None):
    """
    Determine which elbow connector must remain fixed.

    Priority:
    1. If exactly one connector is connected, use it.
    2. If more than one is connected, use the connector nearest
       the user's pick point.
    3. If neither is connected, use the connector nearest the
       user's pick point.
    4. Final fallback: use the first connector.
    """

    if not connectors:
        return None

    connected_connectors = [
        connector
        for connector in connectors
        if connector_is_connected(connector)
    ]

    # Normal elbow case:
    # one end connected and the other end open
    if len(connected_connectors) == 1:
        return connected_connectors[0]

    # If the click point is available, use the nearest suitable connector
    if pick_point is not None:

        candidates = (
            connected_connectors
            if connected_connectors
            else connectors
        )

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

    # Prefer a connected connector if available
    if connected_connectors:
        return connected_connectors[0]

    return connectors[0]


def get_elbow_rotation_axis(fitting, pick_point=None):
    """
    Create the elbow rotation axis through the pivot connector.

    Connector BasisZ represents the connector's longitudinal
    direction. Rotating around this axis keeps that connector's
    origin and direction unchanged.
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
# TEE LOGIC
# ------------------------------------------------------------

def get_tee_rotation_axis(fitting):
    """
    Determine the tee run axis.

    The two connector directions having the greatest absolute
    dot product are treated as the collinear run connectors.
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

    if best_connector_1 is None or best_connector_2 is None:
        return None

    point_1 = best_connector_1.Origin
    point_2 = best_connector_2.Origin

    if point_1.DistanceTo(point_2) < TOLERANCE:
        return None

    try:
        return Line.CreateBound(point_1, point_2)
    except:
        return None


# ------------------------------------------------------------
# GENERAL ROTATION AXIS
# ------------------------------------------------------------

def get_rotation_axis(fitting, pick_point=None):
    """Choose elbow or tee axis logic from connector count."""

    connectors = get_connectors(fitting)
    connector_count = len(connectors)

    if connector_count == 2:
        return get_elbow_rotation_axis(
            fitting,
            pick_point
        )

    if connector_count >= 3:
        return get_tee_rotation_axis(fitting)

    return None


# ------------------------------------------------------------
# MAIN COMMAND
# ------------------------------------------------------------

def main():

    try:
        reference = uidoc.Selection.PickObject(
            ObjectType.Element,
            FittingSelectionFilter(),
            "Select fitting to rotate 180 degrees"
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

    # The click position helps choose the pivot connector when
    # multiple connectors are connected.
    try:
        pick_point = reference.GlobalPoint
    except:
        pick_point = None

    rotation_axis = get_rotation_axis(
        fitting,
        pick_point
    )

    if rotation_axis is None:
        return

    transaction = Transaction(
        doc,
        "Rotate Fitting 180 Degrees"
    )

    try:
        transaction.Start()

        ElementTransformUtils.RotateElement(
            doc,
            fitting.Id,
            rotation_axis,
            ROTATION_ANGLE
        )

        doc.Regenerate()

        transaction.Commit()

    except:
        if transaction.HasStarted():
            transaction.RollBack()

        # Silent failure, with no pyRevit warning window
        return


# ------------------------------------------------------------
# RUN
# ------------------------------------------------------------

main()