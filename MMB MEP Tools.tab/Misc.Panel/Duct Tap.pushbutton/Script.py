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
Tap LT
pyRevit tool for Revit 2025 and later

Workflow:
1. Select the MAIN duct.
2. Select the BRANCH duct.
3. Locate the open branch connector closest to the main duct.
4. Create a native Revit take-off fitting.
5. Exit silently.

Behaviour:
- Silent exit after successful creation
- Silent exit when Escape is pressed
- Error message only when creation fails
- Newly created tap remains selected
"""

from pyrevit import revit, forms

from Autodesk.Revit.DB import (
    ConnectorType,
    Domain,
    ElementId,
    LocationCurve,
    Transaction,
    TransactionStatus
)

from Autodesk.Revit.DB.Mechanical import Duct

from Autodesk.Revit.UI.Selection import (
    ISelectionFilter,
    ObjectType
)

from Autodesk.Revit.Exceptions import (
    OperationCanceledException
)

from System.Collections.Generic import List


# ============================================================
# REVIT REFERENCES
# ============================================================

uidoc = revit.uidoc
doc = revit.doc


# ============================================================
# SETTINGS
# ============================================================

# True:
# The selected branch duct must have an open end connector.
#
# False:
# If no open connector is available, all end connectors
# will be considered.
REQUIRE_OPEN_BRANCH_CONNECTOR = True


# ============================================================
# SELECTION FILTER
# ============================================================

class DuctSelectionFilter(ISelectionFilter):
    """
    Permit selection of standard Revit duct elements only.

    This filter intentionally avoids:
    - Category.Id.IntegerValue
    - ElementId.Value
    - Document object comparisons

    This makes the filter suitable for Revit 2025 and later.
    """

    def AllowElement(self, element):

        if element is None:
            return False

        try:
            return isinstance(element, Duct)
        except:
            return False

    def AllowReference(self, reference, position):
        return False


# ============================================================
# CONNECTOR FUNCTIONS
# ============================================================

def get_connector_manager(element):
    """
    Return the connector manager belonging to an MEP element.
    """

    if element is None:
        return None

    # Regular duct, pipe, conduit or cable tray
    try:
        connector_manager = element.ConnectorManager

        if connector_manager is not None:
            return connector_manager
    except:
        pass

    # Family instance fallback
    try:
        mep_model = element.MEPModel

        if mep_model is not None:
            return mep_model.ConnectorManager
    except:
        pass

    return None


def get_end_connectors(element):
    """
    Return physical HVAC end connectors belonging to the duct.

    Logical connectors and non-HVAC connectors are ignored.
    """

    connector_manager = get_connector_manager(element)

    if connector_manager is None:
        return []

    try:
        connector_set = connector_manager.Connectors
    except:
        return []

    result = []

    for connector in connector_set:

        if connector is None:
            continue

        # Only physical end connectors
        try:
            if connector.ConnectorType != ConnectorType.End:
                continue
        except:
            continue

        # Only HVAC connectors
        try:
            if connector.Domain != Domain.DomainHvac:
                continue
        except:
            continue

        result.append(connector)

    return result


def get_open_end_connectors(element):
    """
    Return HVAC end connectors that are not currently connected.
    """

    result = []

    for connector in get_end_connectors(element):

        try:
            if not connector.IsConnected:
                result.append(connector)
        except:
            continue

    return result


# ============================================================
# GEOMETRY FUNCTIONS
# ============================================================

def get_duct_curve(duct):
    """
    Return the centreline curve of a standard Revit duct.
    """

    if duct is None:
        raise Exception(
            "The selected duct could not be retrieved."
        )

    try:
        location = duct.Location
    except:
        location = None

    if location is None:
        raise Exception(
            "The selected main duct does not have a valid location."
        )

    if not isinstance(location, LocationCurve):
        raise Exception(
            "The selected main duct does not have a valid centreline."
        )

    try:
        curve = location.Curve
    except:
        curve = None

    if curve is None:
        raise Exception(
            "The main duct centreline could not be retrieved."
        )

    return curve


def distance_to_curve(point, curve):
    """
    Calculate the shortest distance from a connector origin
    to the physical, bounded main duct centreline.

    If projection is outside the bounded curve, the nearest
    main duct endpoint is used.
    """

    start_point = curve.GetEndPoint(0)
    end_point = curve.GetEndPoint(1)

    distance_to_start = point.DistanceTo(start_point)
    distance_to_end = point.DistanceTo(end_point)

    endpoint_distance = min(
        distance_to_start,
        distance_to_end
    )

    try:
        projection = curve.Project(point)

        if projection is None:
            return endpoint_distance

        projected_point = projection.XYZPoint

        if projected_point is None:
            return endpoint_distance

        projection_parameter = projection.Parameter

        start_parameter = curve.GetEndParameter(0)
        end_parameter = curve.GetEndParameter(1)

        minimum_parameter = min(
            start_parameter,
            end_parameter
        )

        maximum_parameter = max(
            start_parameter,
            end_parameter
        )

        if (
            projection_parameter >= minimum_parameter and
            projection_parameter <= maximum_parameter
        ):
            return point.DistanceTo(projected_point)

    except:
        pass

    return endpoint_distance


def get_closest_branch_connector(branch_duct, main_duct):
    """
    Find the branch connector closest to the physical extent
    of the main duct.

    Open connectors are prioritised.
    """

    main_curve = get_duct_curve(main_duct)

    open_connectors = get_open_end_connectors(branch_duct)

    if open_connectors:

        candidate_connectors = open_connectors

    elif REQUIRE_OPEN_BRANCH_CONNECTOR:

        raise Exception(
            "The selected branch duct has no open end connector.\n\n"
            "Disconnect one end of the branch duct and run Tap LT again."
        )

    else:

        candidate_connectors = get_end_connectors(branch_duct)

    if not candidate_connectors:
        raise Exception(
            "No valid HVAC end connector was found on the branch duct."
        )

    closest_connector = None
    closest_distance = float("inf")

    for connector in candidate_connectors:

        try:
            connector_origin = connector.Origin

            distance = distance_to_curve(
                connector_origin,
                main_curve
            )

            if distance < closest_distance:
                closest_distance = distance
                closest_connector = connector

        except:
            continue

    if closest_connector is None:
        raise Exception(
            "Tap LT could not identify a suitable connector "
            "on the branch duct."
        )

    return closest_connector


# ============================================================
# VALIDATION
# ============================================================

def validate_selection(main_duct, branch_duct):
    """
    Validate the selected main duct and branch duct.

    No Document object comparison is performed because the
    elements are already returned by the active document.
    """

    if main_duct is None:
        raise Exception(
            "The main duct could not be retrieved."
        )

    if branch_duct is None:
        raise Exception(
            "The branch duct could not be retrieved."
        )

    try:
        same_element = main_duct.Id == branch_duct.Id
    except:
        same_element = False

    if same_element:
        raise Exception(
            "The main duct and branch duct cannot be the same element."
        )

    try:
        main_is_duct = isinstance(main_duct, Duct)
    except:
        main_is_duct = False

    if not main_is_duct:
        raise Exception(
            "The first selected element is not a standard Revit duct."
        )

    try:
        branch_is_duct = isinstance(branch_duct, Duct)
    except:
        branch_is_duct = False

    if not branch_is_duct:
        raise Exception(
            "The second selected element is not a standard Revit duct."
        )

    main_connectors = get_end_connectors(main_duct)

    if not main_connectors:
        raise Exception(
            "No valid HVAC connector was found on the main duct."
        )

    branch_connectors = get_end_connectors(branch_duct)

    if not branch_connectors:
        raise Exception(
            "No valid HVAC connector was found on the branch duct."
        )


# ============================================================
# TAKE-OFF CREATION
# ============================================================

def create_takeoff(main_duct, branch_connector):
    """
    Create a native Revit take-off fitting.

    First argument:
        Open connector belonging to the branch duct.

    Second argument:
        Main duct used as the trunk.
    """

    return doc.Create.NewTakeoffFitting(
        branch_connector,
        main_duct
    )


# ============================================================
# ERROR MESSAGE
# ============================================================

def show_error(error):
    """
    Show an error only when the tap cannot be created.

    Successful creation and Escape remain silent.
    """

    try:
        error_message = str(error)
    except:
        error_message = ""

    if not error_message:
        error_message = (
            "Revit could not create the take-off fitting."
        )

    forms.alert(
        "Tap LT could not create the connection.\n\n"
        "{0}\n\n"
        "Please check the following:\n"
        "• Select the main duct first.\n"
        "• Select the branch duct second.\n"
        "• The branch duct has an open end connector.\n"
        "• Both selected elements are standard Revit ducts.\n"
        "• The main duct type has a suitable junction "
        "routing preference.\n"
        "• A compatible take-off family is loaded.\n"
        "• The take-off family supports the selected duct shapes.\n"
        "• The take-off family supports the branch angle.".format(
            error_message
        ),
        title="Tap LT",
        warn_icon=True
    )


# ============================================================
# SELECT ELEMENT
# ============================================================

def pick_duct(prompt):
    """
    Prompt the user to select one standard Revit duct.

    Escape is handled by the main command.
    """

    selection_filter = DuctSelectionFilter()

    selected_reference = uidoc.Selection.PickObject(
        ObjectType.Element,
        selection_filter,
        prompt
    )

    if selected_reference is None:
        return None

    return doc.GetElement(
        selected_reference.ElementId
    )


# ============================================================
# MAIN COMMAND
# ============================================================

def main():

    # --------------------------------------------------------
    # STEP 1: SELECT MAIN DUCT
    # --------------------------------------------------------

    try:
        main_duct = pick_duct(
            "Select the MAIN duct"
        )

    except OperationCanceledException:
        # Silent Escape
        return

    except:
        # Silent exit for selection cancellation
        return

    if main_duct is None:
        return

    # --------------------------------------------------------
    # STEP 2: SELECT BRANCH DUCT
    # --------------------------------------------------------

    try:
        branch_duct = pick_duct(
            "Select the BRANCH duct"
        )

    except OperationCanceledException:
        # Silent Escape
        return

    except:
        # Silent exit for selection cancellation
        return

    if branch_duct is None:
        return

    # --------------------------------------------------------
    # STEP 3: VALIDATE SELECTION
    # --------------------------------------------------------

    try:
        validate_selection(
            main_duct,
            branch_duct
        )

    except Exception as error:
        show_error(error)
        return

    # --------------------------------------------------------
    # STEP 4: FIND CLOSEST OPEN BRANCH CONNECTOR
    # --------------------------------------------------------

    try:
        branch_connector = get_closest_branch_connector(
            branch_duct,
            main_duct
        )

    except Exception as error:
        show_error(error)
        return

    # --------------------------------------------------------
    # STEP 5: CREATE TAKE-OFF FITTING
    # --------------------------------------------------------

    transaction = Transaction(
        doc,
        "Tap LT"
    )

    takeoff = None

    try:
        transaction.Start()

        takeoff = create_takeoff(
            main_duct,
            branch_connector
        )

        if takeoff is None:
            raise Exception(
                "Revit did not return a take-off fitting."
            )

        doc.Regenerate()

        transaction.Commit()

    except Exception as error:

        try:
            if transaction.GetStatus() == TransactionStatus.Started:
                transaction.RollBack()
        except:
            try:
                transaction.RollBack()
            except:
                pass

        show_error(error)
        return

    # --------------------------------------------------------
    # STEP 6: SELECT THE NEWLY CREATED TAP
    # --------------------------------------------------------

    try:
        selected_ids = List[ElementId]()
        selected_ids.Add(takeoff.Id)

        uidoc.Selection.SetElementIds(
            selected_ids
        )

    except:
        pass

    # --------------------------------------------------------
    # STEP 7: SILENT SUCCESSFUL EXIT
    # --------------------------------------------------------

    return


# ============================================================
# RUN COMMAND
# ============================================================

if __name__ == "__main__":
    main()