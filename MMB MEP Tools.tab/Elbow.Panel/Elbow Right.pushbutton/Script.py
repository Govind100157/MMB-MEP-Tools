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

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Plumbing import Pipe, PipingSystemType
from Autodesk.Revit.DB.Mechanical import Duct, MechanicalSystemType
from Autodesk.Revit.DB.Electrical import Conduit, CableTray
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

from pyrevit import revit, script


doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()


# ============================================================
# SELECTION FILTER
# ============================================================

class MEPSelectionFilter(ISelectionFilter):

    def AllowElement(self, elem):
        return isinstance(
            elem,
            (
                Duct,
                Pipe,
                Conduit,
                CableTray
            )
        )

    def AllowReference(self, reference, position):
        return False


# ============================================================
# GENERAL HELPER FUNCTIONS
# ============================================================

def mm_to_internal(value_mm):
    return UnitUtils.ConvertToInternalUnits(
        value_mm,
        UnitTypeId.Millimeters
    )


def metres_to_internal(value_metres):
    return UnitUtils.ConvertToInternalUnits(
        value_metres,
        UnitTypeId.Meters
    )


def internal_to_mm(value):
    return UnitUtils.ConvertFromInternalUnits(
        value,
        UnitTypeId.Millimeters
    )


def get_stub_length_from_size(size_mm):
    """
    Stub-length rules for:
    Duct
    Pipe
    Cable tray
    """

    if size_mm <= 500.0:
        length_metres = 2.0

    elif size_mm <= 1000.0:
        length_metres = 4.0

    elif size_mm <= 1500.0:
        length_metres = 6.0

    elif size_mm <= 2000.0:
        length_metres = 8.0

    elif size_mm <= 2500.0:
        length_metres = 10.0

    elif size_mm <= 3000.0:
        length_metres = 12.0

    elif size_mm <= 3500.0:
        length_metres = 14.0

    elif size_mm <= 4000.0:
        length_metres = 16.0

    elif size_mm <= 4500.0:
        length_metres = 18.0

    elif size_mm <= 5000.0:
        length_metres = 20.0

    else:
        length_metres = 25.0

    return metres_to_internal(length_metres)


def get_element_level_id(elem):
    """
    Gets the reference level safely for all supported MEPCurves.
    """

    try:
        reference_level = elem.ReferenceLevel

        if reference_level:
            return reference_level.Id
    except:
        pass

    level_parameter_ids = [
        BuiltInParameter.RBS_START_LEVEL_PARAM,
        BuiltInParameter.RBS_REFERENCE_LEVEL_PARAM
    ]

    for parameter_id in level_parameter_ids:
        try:
            parameter = elem.get_Parameter(parameter_id)

            if parameter:
                level_id = parameter.AsElementId()

                if (
                    level_id
                    and level_id != ElementId.InvalidElementId
                ):
                    return level_id
        except:
            pass

    return ElementId.InvalidElementId


def get_end_connectors(elem):
    """
    Returns only physical end connectors.
    """

    result = []

    try:
        connector_manager = elem.ConnectorManager
    except:
        connector_manager = None

    if not connector_manager:
        return result

    for connector in connector_manager.Connectors:
        try:
            if connector.ConnectorType == ConnectorType.End:
                result.append(connector)
        except:
            continue

    return result


def get_nearest_open_connector(elem, picked_point):
    """
    Finds the nearest unconnected end connector to the clicked location.
    """

    nearest_connector = None
    minimum_distance = float("inf")

    for connector in get_end_connectors(elem):

        try:
            if connector.IsConnected:
                continue

            distance = connector.Origin.DistanceTo(picked_point)

            if distance < minimum_distance:
                minimum_distance = distance
                nearest_connector = connector

        except:
            continue

    return nearest_connector


def get_nearest_connector_pair(element_one, element_two):
    """
    Finds the closest available connector pair between two elements.
    """

    connector_one_best = None
    connector_two_best = None
    minimum_distance = float("inf")

    connectors_one = get_end_connectors(element_one)
    connectors_two = get_end_connectors(element_two)

    for connector_one in connectors_one:

        try:
            if connector_one.IsConnected:
                continue
        except:
            continue

        for connector_two in connectors_two:

            try:
                if connector_two.IsConnected:
                    continue
            except:
                continue

            try:
                if connector_one.Domain != connector_two.Domain:
                    continue
            except:
                pass

            distance = connector_one.Origin.DistanceTo(
                connector_two.Origin
            )

            if distance < minimum_distance:
                minimum_distance = distance
                connector_one_best = connector_one
                connector_two_best = connector_two

    return connector_one_best, connector_two_best


def get_default_system_type(is_duct=False, is_pipe=False):

    if is_duct:
        system_types = (
            FilteredElementCollector(doc)
            .OfClass(MechanicalSystemType)
            .ToElements()
        )

    elif is_pipe:
        system_types = (
            FilteredElementCollector(doc)
            .OfClass(PipingSystemType)
            .ToElements()
        )

    else:
        return ElementId.InvalidElementId

    if system_types:
        return system_types[0].Id

    return ElementId.InvalidElementId


def copy_parameter_value(
        source_element,
        destination_element,
        built_in_parameter):

    source_parameter = source_element.get_Parameter(
        built_in_parameter
    )

    destination_parameter = destination_element.get_Parameter(
        built_in_parameter
    )

    if not source_parameter:
        return

    if not destination_parameter:
        return

    if not source_parameter.HasValue:
        return

    if destination_parameter.IsReadOnly:
        return

    try:
        if source_parameter.StorageType == StorageType.Double:
            destination_parameter.Set(source_parameter.AsDouble())

        elif source_parameter.StorageType == StorageType.Integer:
            destination_parameter.Set(source_parameter.AsInteger())

        elif source_parameter.StorageType == StorageType.String:
            destination_parameter.Set(source_parameter.AsString())

        elif source_parameter.StorageType == StorageType.ElementId:
            destination_parameter.Set(source_parameter.AsElementId())

    except:
        pass


def create_elbow(element_one, element_two):
    """
    Creates an elbow between the closest open end connectors.
    """

    doc.Regenerate()

    connector_one, connector_two = get_nearest_connector_pair(
        element_one,
        element_two
    )

    if connector_one is None or connector_two is None:
        raise Exception(
            "Could not find a valid open connector pair."
        )

    connector_distance = connector_one.Origin.DistanceTo(
        connector_two.Origin
    )

    tolerance = mm_to_internal(2.0)

    if connector_distance > tolerance:
        raise Exception(
            "The closest connectors are not coincident. "
            "Connector distance: {:.3f} mm".format(
                internal_to_mm(connector_distance)
            )
        )

    elbow = doc.Create.NewElbowFitting(
        connector_one,
        connector_two
    )

    if elbow is None:
        raise Exception(
            "Revit could not create the elbow fitting."
        )

    return elbow


# ============================================================
# USER SELECTION
# ============================================================

try:
    picked_reference = uidoc.Selection.PickObject(
        ObjectType.Element,
        MEPSelectionFilter(),
        "Select a duct, pipe, cable tray, or conduit"
    )

    picked_point = picked_reference.GlobalPoint

except:
    script.exit()


element = doc.GetElement(picked_reference.ElementId)

if element is None:
    script.exit()


# ============================================================
# VALIDATE LOCATION CURVE
# ============================================================

if not isinstance(element.Location, LocationCurve):
    logger.error("Selected element does not have a LocationCurve.")
    script.exit()


# ============================================================
# FIND CONNECTOR CLOSEST TO CLICKED SIDE
# ============================================================

available_connector = get_nearest_open_connector(
    element,
    picked_point
)

if available_connector is None:
    logger.error(
        "No open end connector was found near the selected side."
    )
    script.exit()


# ============================================================
# CALCULATE ELEMENT DIRECTION
# ============================================================

curve = element.Location.Curve

point_zero = curve.GetEndPoint(0)
point_one = curve.GetEndPoint(1)

connector_origin = available_connector.Origin

if point_zero.DistanceTo(connector_origin) < point_one.DistanceTo(
        connector_origin):

    forward_direction = curve.Direction

else:
    forward_direction = curve.Direction.Negate()


# ============================================================
# CALCULATE RIGHT-HAND DIRECTION
# ============================================================

horizontal_forward = XYZ(
    forward_direction.X,
    forward_direction.Y,
    0.0
)

if horizontal_forward.GetLength() > 0.000001:
    horizontal_forward = horizontal_forward.Normalize()
else:
    horizontal_forward = XYZ.BasisX


# Naviate LT style convention for vertical elements
if abs(forward_direction.Z) > 0.99:

    right_vector = XYZ(-1.0, 0.0, 0.0)

else:

    right_vector = (
        XYZ.BasisZ
        .CrossProduct(horizontal_forward)
        .Normalize()
    )


# ============================================================
# DETERMINE STUB LENGTH
# ============================================================

segment_length = 0.0


if isinstance(element, Duct):

    duct_width = element.get_Parameter(
        BuiltInParameter.RBS_CURVE_WIDTH_PARAM
    )

    duct_diameter = element.get_Parameter(
        BuiltInParameter.RBS_CURVE_DIAMETER_PARAM
    )

    size_mm = 0.0

    if duct_diameter and duct_diameter.HasValue:
        size_mm = internal_to_mm(
            duct_diameter.AsDouble()
        )

    elif duct_width and duct_width.HasValue:
        size_mm = internal_to_mm(
            duct_width.AsDouble()
        )

    segment_length = get_stub_length_from_size(size_mm)


elif isinstance(element, Pipe):

    pipe_diameter = element.get_Parameter(
        BuiltInParameter.RBS_PIPE_DIAMETER_PARAM
    )

    size_mm = 0.0

    if pipe_diameter and pipe_diameter.HasValue:
        size_mm = internal_to_mm(
            pipe_diameter.AsDouble()
        )

    segment_length = get_stub_length_from_size(size_mm)


elif isinstance(element, CableTray):

    cable_tray_width = element.get_Parameter(
        BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM
    )

    size_mm = 0.0

    if cable_tray_width and cable_tray_width.HasValue:
        size_mm = internal_to_mm(
            cable_tray_width.AsDouble()
        )

    segment_length = get_stub_length_from_size(size_mm)


elif isinstance(element, Conduit):

    # Fixed 1 metre stub for every conduit diameter
    segment_length = metres_to_internal(1.0)


else:
    script.exit()


# ============================================================
# CALCULATE NEW STUB GEOMETRY
# ============================================================

start_point = available_connector.Origin

end_point = start_point + right_vector.Multiply(
    segment_length
)

level_id = get_element_level_id(element)

if level_id == ElementId.InvalidElementId:
    logger.error(
        "Could not determine the reference level."
    )
    script.exit()


# ============================================================
# CREATE STUB AND ELBOW
# ============================================================

transaction = Transaction(
    doc,
    "Elbow Right Tool"
)

transaction.Start()


try:

    new_element = None
    new_elbow = None

    # --------------------------------------------------------
    # DUCT
    # --------------------------------------------------------

    if isinstance(element, Duct):

        if element.MEPSystem:
            system_type_id = element.MEPSystem.GetTypeId()
        else:
            system_type_id = get_default_system_type(
                is_duct=True
            )

        if system_type_id == ElementId.InvalidElementId:
            raise Exception(
                "No valid duct system type was found."
            )

        new_element = Duct.Create(
            doc,
            system_type_id,
            element.DuctType.Id,
            level_id,
            start_point,
            end_point
        )

        copy_parameter_value(
            element,
            new_element,
            BuiltInParameter.RBS_CURVE_WIDTH_PARAM
        )

        copy_parameter_value(
            element,
            new_element,
            BuiltInParameter.RBS_CURVE_HEIGHT_PARAM
        )

        copy_parameter_value(
            element,
            new_element,
            BuiltInParameter.RBS_CURVE_DIAMETER_PARAM
        )

        doc.Regenerate()

        new_elbow = create_elbow(
            element,
            new_element
        )

    # --------------------------------------------------------
    # PIPE
    # --------------------------------------------------------

    elif isinstance(element, Pipe):

        if element.MEPSystem:
            system_type_id = element.MEPSystem.GetTypeId()
        else:
            system_type_id = get_default_system_type(
                is_pipe=True
            )

        if system_type_id == ElementId.InvalidElementId:
            raise Exception(
                "No valid pipe system type was found."
            )

        new_element = Pipe.Create(
            doc,
            system_type_id,
            element.PipeType.Id,
            level_id,
            start_point,
            end_point
        )

        copy_parameter_value(
            element,
            new_element,
            BuiltInParameter.RBS_PIPE_DIAMETER_PARAM
        )

        doc.Regenerate()

        new_elbow = create_elbow(
            element,
            new_element
        )

    # --------------------------------------------------------
    # CABLE TRAY
    # --------------------------------------------------------

    elif isinstance(element, CableTray):

        new_element = CableTray.Create(
            doc,
            element.GetTypeId(),
            start_point,
            end_point,
            level_id
        )

        copy_parameter_value(
            element,
            new_element,
            BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM
        )

        copy_parameter_value(
            element,
            new_element,
            BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM
        )

        doc.Regenerate()

        new_elbow = create_elbow(
            element,
            new_element
        )

    # --------------------------------------------------------
    # CONDUIT
    # --------------------------------------------------------

    elif isinstance(element, Conduit):

        new_element = Conduit.Create(
            doc,
            element.GetTypeId(),
            start_point,
            end_point,
            level_id
        )

        copy_parameter_value(
            element,
            new_element,
            BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM
        )

        doc.Regenerate()

        # This was missing in the original script.
        new_elbow = create_elbow(
            element,
            new_element
        )

    if new_element is None:
        raise Exception(
            "The new stub element was not created."
        )

    if new_elbow is None:
        raise Exception(
            "The elbow fitting was not created."
        )

    transaction.Commit()


except:
    try:
        if transaction and transaction.HasStarted():
            transaction.RollBack()
    except:
        pass