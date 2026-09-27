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

from pyrevit import revit, script

from Autodesk.Revit.DB import (
    XYZ,
    Transaction,
    BuiltInParameter,
    UnitUtils,
    UnitTypeId,
    MEPCurve,
    FilteredElementCollector,
    ElementId
)

from Autodesk.Revit.DB.Mechanical import (
    Duct,
    MechanicalSystemType
)

from Autodesk.Revit.DB.Plumbing import (
    Pipe,
    PipingSystemType
)

from Autodesk.Revit.DB.Electrical import (
    Conduit,
    CableTray
)

from Autodesk.Revit.UI import Selection


doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()


# ------------------------------------------------------------------------------
# Helper: Get a usable level
# ------------------------------------------------------------------------------
def get_element_level(element):

    try:
        reference_level = element.ReferenceLevel

        if reference_level:
            return reference_level
    except:
        pass

    try:
        level_id = element.LevelId

        if level_id and level_id != ElementId.InvalidElementId:
            return doc.GetElement(level_id)
    except:
        pass

    return None


# ------------------------------------------------------------------------------
# Helper: Get default system type for undefined ducts and pipes
# ------------------------------------------------------------------------------
def get_default_system_type(element):

    if isinstance(element, Duct):

        system_types = list(
            FilteredElementCollector(doc)
            .OfClass(MechanicalSystemType)
        )

        if system_types:
            return system_types[0].Id

    elif isinstance(element, Pipe):

        system_types = list(
            FilteredElementCollector(doc)
            .OfClass(PipingSystemType)
        )

        if system_types:
            return system_types[0].Id

    return ElementId.InvalidElementId


# ------------------------------------------------------------------------------
# Helper: Get assigned system type or project default
# ------------------------------------------------------------------------------
def get_system_type_id(element):

    try:
        mep_system = element.MEPSystem

        if mep_system:
            system_type_id = mep_system.GetTypeId()

            if (
                system_type_id
                and system_type_id != ElementId.InvalidElementId
            ):
                return system_type_id
    except:
        pass

    return get_default_system_type(element)


# ------------------------------------------------------------------------------
# Helper: Calculate straight stub length
# ------------------------------------------------------------------------------
def compute_stub_length(element):

    # Conduit uses a fixed 1 metre stub
    if isinstance(element, Conduit):
        return UnitUtils.ConvertToInternalUnits(
            1.0,
            UnitTypeId.Meters
        )

    size_mm = 0.0

    if isinstance(element, Duct):

        diameter = element.get_Parameter(
            BuiltInParameter.RBS_CURVE_DIAMETER_PARAM
        )

        width = element.get_Parameter(
            BuiltInParameter.RBS_CURVE_WIDTH_PARAM
        )

        if diameter and diameter.HasValue:
            size_mm = UnitUtils.ConvertFromInternalUnits(
                diameter.AsDouble(),
                UnitTypeId.Millimeters
            )

        elif width and width.HasValue:
            size_mm = UnitUtils.ConvertFromInternalUnits(
                width.AsDouble(),
                UnitTypeId.Millimeters
            )

    elif isinstance(element, Pipe):

        diameter = element.get_Parameter(
            BuiltInParameter.RBS_PIPE_DIAMETER_PARAM
        )

        if diameter and diameter.HasValue:
            size_mm = UnitUtils.ConvertFromInternalUnits(
                diameter.AsDouble(),
                UnitTypeId.Millimeters
            )

    elif isinstance(element, CableTray):

        width = element.get_Parameter(
            BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM
        )

        if width and width.HasValue:
            size_mm = UnitUtils.ConvertFromInternalUnits(
                width.AsDouble(),
                UnitTypeId.Millimeters
            )

    if size_mm <= 500:
        metres = 2.0
    elif size_mm <= 1000:
        metres = 4.0
    elif size_mm <= 1500:
        metres = 6.0
    elif size_mm <= 2000:
        metres = 8.0
    elif size_mm <= 2500:
        metres = 10.0
    elif size_mm <= 3000:
        metres = 12.0
    elif size_mm <= 3500:
        metres = 14.0
    elif size_mm <= 4000:
        metres = 16.0
    elif size_mm <= 4500:
        metres = 18.0
    elif size_mm <= 5000:
        metres = 20.0
    else:
        metres = 25.0

    return UnitUtils.ConvertToInternalUnits(
        metres,
        UnitTypeId.Meters
    )


# ------------------------------------------------------------------------------
# Helper: Copy a parameter when possible
# ------------------------------------------------------------------------------
def copy_double_parameter(source, target, built_in_parameter):

    source_parameter = source.get_Parameter(
        built_in_parameter
    )

    target_parameter = target.get_Parameter(
        built_in_parameter
    )

    if (
        source_parameter
        and target_parameter
        and source_parameter.HasValue
        and not target_parameter.IsReadOnly
    ):
        try:
            target_parameter.Set(
                source_parameter.AsDouble()
            )
        except:
            pass


# ------------------------------------------------------------------------------
# Helper: Find the nearest open connector to a point
# ------------------------------------------------------------------------------
def get_nearest_open_connector(element, point):

    nearest_connector = None
    minimum_distance = float("inf")

    try:
        connectors = element.ConnectorManager.Connectors
    except:
        return None

    for connector in connectors:

        if connector.IsConnected:
            continue

        distance = connector.Origin.DistanceTo(point)

        if distance < minimum_distance:
            minimum_distance = distance
            nearest_connector = connector

    return nearest_connector


# ------------------------------------------------------------------------------
# Helper: Find connector nearest to a point
# ------------------------------------------------------------------------------
def get_connector_nearest_point(element, point):

    nearest_connector = None
    minimum_distance = float("inf")

    try:
        connectors = element.ConnectorManager.Connectors
    except:
        return None

    for connector in connectors:

        distance = connector.Origin.DistanceTo(point)

        if distance < minimum_distance:
            minimum_distance = distance
            nearest_connector = connector

    return nearest_connector


# ------------------------------------------------------------------------------
# Helper: Calculate horizontal outward direction
# ------------------------------------------------------------------------------
def get_horizontal_outward_direction(element, selected_connector):

    try:
        location_curve = element.Location.Curve
    except:
        return None

    if not location_curve:
        return None

    point_0 = location_curve.GetEndPoint(0)
    point_1 = location_curve.GetEndPoint(1)

    distance_to_point_0 = selected_connector.Origin.DistanceTo(
        point_0
    )

    distance_to_point_1 = selected_connector.Origin.DistanceTo(
        point_1
    )

    # Generate a direction travelling away from the selected end.
    if distance_to_point_0 <= distance_to_point_1:
        outward_direction = point_0 - point_1
    else:
        outward_direction = point_1 - point_0

    # Project the inclined direction onto the global XY plane.
    horizontal_direction = XYZ(
        outward_direction.X,
        outward_direction.Y,
        0.0
    )

    if horizontal_direction.IsZeroLength():
        return None

    return horizontal_direction.Normalize()


# ------------------------------------------------------------------------------
# Select inclined MEP element
# ------------------------------------------------------------------------------
try:
    reference = uidoc.Selection.PickObject(
        Selection.ObjectType.Element,
        "Select an inclined duct, pipe, conduit or cable tray"
    )

    click_point = reference.GlobalPoint

except:
    script.exit()


selected_element = doc.GetElement(
    reference.ElementId
)


if not isinstance(
    selected_element,
    (Duct, Pipe, Conduit, CableTray)
):
    script.exit()


mep_curve = selected_element


# ------------------------------------------------------------------------------
# Find the open connector nearest to the mouse click
# ------------------------------------------------------------------------------
closest_connector = get_nearest_open_connector(
    mep_curve,
    click_point
)


if not closest_connector:
    script.exit()


# ------------------------------------------------------------------------------
# Calculate horizontal straight-stub direction
# ------------------------------------------------------------------------------
horizontal_direction = get_horizontal_outward_direction(
    mep_curve,
    closest_connector
)


if not horizontal_direction:
    script.exit()


segment_length = compute_stub_length(
    mep_curve
)


start_point = closest_connector.Origin

end_point = start_point + horizontal_direction.Multiply(
    segment_length
)


# The horizontal stub remains at the selected connector elevation.
end_point = XYZ(
    end_point.X,
    end_point.Y,
    start_point.Z
)


# ------------------------------------------------------------------------------
# Get reference level
# ------------------------------------------------------------------------------
level = get_element_level(
    mep_curve
)


if not level:
    script.exit()


# ------------------------------------------------------------------------------
# Transaction
# ------------------------------------------------------------------------------
transaction = Transaction(
    doc,
    "Straight Stub From 45 Degree"
)

transaction.Start()


try:

    new_curve = None

    # --------------------------------------------------------------------------
    # DUCT
    # --------------------------------------------------------------------------
    if isinstance(mep_curve, Duct):

        system_type_id = get_system_type_id(
            mep_curve
        )

        if (
            not system_type_id
            or system_type_id == ElementId.InvalidElementId
        ):
            raise Exception(
                "No valid duct system type was found in the project."
            )

        new_curve = Duct.Create(
            doc,
            system_type_id,
            mep_curve.DuctType.Id,
            level.Id,
            start_point,
            end_point
        )

        copy_double_parameter(
            mep_curve,
            new_curve,
            BuiltInParameter.RBS_CURVE_WIDTH_PARAM
        )

        copy_double_parameter(
            mep_curve,
            new_curve,
            BuiltInParameter.RBS_CURVE_HEIGHT_PARAM
        )

        copy_double_parameter(
            mep_curve,
            new_curve,
            BuiltInParameter.RBS_CURVE_DIAMETER_PARAM
        )

    # --------------------------------------------------------------------------
    # PIPE
    # --------------------------------------------------------------------------
    elif isinstance(mep_curve, Pipe):

        system_type_id = get_system_type_id(
            mep_curve
        )

        if (
            not system_type_id
            or system_type_id == ElementId.InvalidElementId
        ):
            raise Exception(
                "No valid pipe system type was found in the project."
            )

        new_curve = Pipe.Create(
            doc,
            system_type_id,
            mep_curve.PipeType.Id,
            level.Id,
            start_point,
            end_point
        )

        copy_double_parameter(
            mep_curve,
            new_curve,
            BuiltInParameter.RBS_PIPE_DIAMETER_PARAM
        )

    # --------------------------------------------------------------------------
    # CONDUIT
    # --------------------------------------------------------------------------
    elif isinstance(mep_curve, Conduit):

        new_curve = Conduit.Create(
            doc,
            mep_curve.GetTypeId(),
            start_point,
            end_point,
            level.Id
        )

        copy_double_parameter(
            mep_curve,
            new_curve,
            BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM
        )

    # --------------------------------------------------------------------------
    # CABLE TRAY
    # --------------------------------------------------------------------------
    elif isinstance(mep_curve, CableTray):

        new_curve = CableTray.Create(
            doc,
            mep_curve.GetTypeId(),
            start_point,
            end_point,
            level.Id
        )

        copy_double_parameter(
            mep_curve,
            new_curve,
            BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM
        )

        copy_double_parameter(
            mep_curve,
            new_curve,
            BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM
        )

    if not new_curve:
        raise Exception(
            "The straight stub could not be created."
        )

    # Recalculate element geometry before reading connectors.
    doc.Regenerate()

    # --------------------------------------------------------------------------
    # Select explicit connector pair
    # --------------------------------------------------------------------------
    source_connector = closest_connector

    target_connector = get_connector_nearest_point(
        new_curve,
        start_point
    )

    if not source_connector or not target_connector:
        raise Exception(
            "The connectors required for the elbow were not found."
        )

    # --------------------------------------------------------------------------
    # Create elbow fitting
    # --------------------------------------------------------------------------
    doc.Create.NewElbowFitting(
        source_connector,
        target_connector
    )

    transaction.Commit()

    logger.info(
        "Straight horizontal stub and elbow created successfully."
    )


except:
    try:
        if transaction and transaction.HasStarted():
            transaction.RollBack()
    except:
        pass