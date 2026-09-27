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

#Select destination family and then on an family/element you would like to move.


from math import pi

from Autodesk.Revit.DB import (
    Line,
    InsulationLiningBase
)

from Autodesk.Revit.UI.Selection import (
    ObjectType,
    ISelectionFilter
)

from Autodesk.Revit import Exceptions

from pyrevit import script, revit, forms


logger = script.get_logger()
uidoc = revit.uidoc
doc = revit.doc


# -----------------------------------------------------
# MEP Connector Helpers
# -----------------------------------------------------
def get_connector_manager(elem):
    """Return ConnectorManager for MEP curves and families."""

    try:
        return elem.ConnectorManager
    except:
        pass

    try:
        if elem.MEPModel:
            return elem.MEPModel.ConnectorManager
    except:
        pass

    raise AttributeError(
        "Selected element does not have a ConnectorManager."
    )


def get_connector_closest_to(connectors, point):
    """Return connector closest to picked point."""

    closest_connector = None
    min_distance = float("inf")

    for connector in connectors:
        distance = connector.Origin.DistanceTo(point)

        if distance < min_distance:
            min_distance = distance
            closest_connector = connector

    return closest_connector


# -----------------------------------------------------
# Selection Filter
# -----------------------------------------------------
class NoInsulation(ISelectionFilter):

    def AllowElement(self, elem):

        if isinstance(elem, InsulationLiningBase):
            return False

        try:
            get_connector_manager(elem)
            return True
        except:
            return False

    def AllowReference(self, reference, position):
        return True


# -----------------------------------------------------
# Main Function
# -----------------------------------------------------
def connect_to():

    # -------------------------------------------------
    # Pick destination element FIRST
    # -------------------------------------------------
    try:
        reference = uidoc.Selection.PickObject(
            ObjectType.Element,
            NoInsulation(),
            "Select destination element"
        )
    except Exceptions.OperationCanceledException:
        return

    target_element = doc.GetElement(reference.ElementId)
    target_point = reference.GlobalPoint

    # -------------------------------------------------
    # Pick element to move SECOND
    # -------------------------------------------------
    try:
        reference = uidoc.Selection.PickObject(
            ObjectType.Element,
            NoInsulation(),
            "Select element to move"
        )
    except Exceptions.OperationCanceledException:
        return

    moved_element = doc.GetElement(reference.ElementId)
    moved_point = reference.GlobalPoint

    # -------------------------------------------------
    # Same object check
    # -------------------------------------------------
    if moved_element.Id == target_element.Id:

        forms.alert(
            "You selected the same object twice.",
            title="Move Connect"
        )
        return

    # -------------------------------------------------
    # Connector Managers
    # -------------------------------------------------
    try:
        moved_manager = get_connector_manager(moved_element)
        target_manager = get_connector_manager(target_element)

    except Exception as ex:

        forms.alert(
            str(ex),
            title="Connector Error"
        )
        return

    # -------------------------------------------------
    # Closest unused connectors
    # -------------------------------------------------
    try:
        moved_connector = get_connector_closest_to(
            moved_manager.UnusedConnectors,
            moved_point
        )

        target_connector = get_connector_closest_to(
            target_manager.UnusedConnectors,
            target_point
        )

    except:

        forms.alert(
            "One element has no unused connector.",
            title="Connector Error"
        )
        return

    if not moved_connector or not target_connector:

        forms.alert(
            "No open connector found.",
            title="Connector Error"
        )
        return

    # -------------------------------------------------
    # Domain Check
    # -------------------------------------------------
    try:

        if moved_connector.Domain != target_connector.Domain:

            forms.alert(
                "Selected connectors belong to different domains.",
                title="Domain Error"
            )
            return

    except:

        forms.alert(
            "Unable to determine connector domain.",
            title="Domain Error"
        )
        return

    # -------------------------------------------------
    # Connector Directions
    # -------------------------------------------------
    try:

        moved_direction = (
            moved_connector.CoordinateSystem.BasisZ
        )

        target_direction = (
            target_connector.CoordinateSystem.BasisZ
        )

    except:

        forms.alert(
            "Unable to read connector direction.",
            title="Direction Error"
        )
        return

    # -------------------------------------------------
    # Move + Connect
    # -------------------------------------------------
    with revit.Transaction("Move Connect"):

        angle = moved_direction.AngleTo(target_direction)

        if abs(angle - pi) > 0.0001:

            if abs(angle) < 0.0001:
                vector = (
                    moved_connector
                    .CoordinateSystem
                    .BasisY
                )
            else:
                vector = moved_direction.CrossProduct(
                    target_direction
                )

            try:

                axis = Line.CreateBound(
                    moved_connector.Origin,
                    moved_connector.Origin + vector
                )

                moved_element.Location.Rotate(
                    axis,
                    angle - pi
                )

            except Exceptions.ArgumentsInconsistentException:

                logger.debug(
                    "Rotation skipped. "
                    "Vector={} Angle={}".format(
                        vector,
                        angle
                    )
                )

            except:
                pass

        try:

            move_vector = (
                target_connector.Origin
                - moved_connector.Origin
            )

            moved_element.Location.Move(
                move_vector
            )

        except Exception as ex:

            forms.alert(
                str(ex),
                title="Move Error"
            )
            return

        # ---------------------------------------------
        # Connect
        # ---------------------------------------------
        try:

            moved_connector.ConnectTo(
                target_connector
            )

        except Exception as ex:

            forms.alert(
                "ConnectTo failed:\n{}".format(ex),
                title="Connection Error"
            )


# -----------------------------------------------------
# Run Once
# -----------------------------------------------------
connect_to()