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


import math

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
# CONSTANTS
# ============================================================

POINT_TOLERANCE = 0.0001
VECTOR_TOLERANCE = 0.000001
VERTICAL_TOLERANCE = 0.99


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
                CableTray,
                Conduit
            )
        )

    def AllowReference(self, reference, position):
        return False


# ============================================================
# UNIT CONVERSION
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


# ============================================================
# VECTOR HELPERS
# ============================================================

def is_valid_vector(vector):

    if vector is None:
        return False

    try:
        return vector.GetLength() > VECTOR_TOLERANCE
    except:
        return False


def normalised(vector):

    if not is_valid_vector(vector):
        return None

    try:
        return vector.Normalize()
    except:
        return None


def absolute_dot(vector_one, vector_two):

    vector_one = normalised(vector_one)
    vector_two = normalised(vector_two)

    if vector_one is None or vector_two is None:
        return 0.0

    try:
        return abs(
            vector_one.DotProduct(vector_two)
        )
    except:
        return 0.0


def project_vector_to_plane(vector, plane_normal):
    """
    Projects a vector onto the plane perpendicular to plane_normal.
    """

    vector = normalised(vector)
    plane_normal = normalised(plane_normal)

    if vector is None or plane_normal is None:
        return None

    projected = vector - plane_normal.Multiply(
        vector.DotProduct(plane_normal)
    )

    if not is_valid_vector(projected):
        return None

    return projected.Normalize()


# ============================================================
# STUB LENGTH
# ============================================================

def get_stub_length_from_size(size_mm):
    """
    Stub lengths for ducts, pipes and cable trays.
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


# ============================================================
# LEVEL HELPER
# ============================================================

def get_element_level_id(elem):
    """
    Gets the reference level for the selected MEP curve.
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


# ============================================================
# CONNECTOR HELPERS
# ============================================================

def get_end_connectors(elem):
    """
    Returns physical end connectors belonging to an MEP curve.
    """

    connectors = []

    try:
        connector_manager = elem.ConnectorManager
    except:
        connector_manager = None

    if connector_manager is None:
        return connectors

    try:
        for connector in connector_manager.Connectors:

            try:
                if connector.ConnectorType == ConnectorType.End:
                    connectors.append(connector)
            except:
                continue
    except:
        pass

    return connectors


def get_nearest_open_connector(elem, picked_point):
    """
    Finds the open connector nearest to the clicked side.
    """

    nearest_connector = None
    minimum_distance = float("inf")

    for connector in get_end_connectors(elem):

        try:
            if connector.IsConnected:
                continue

            distance = connector.Origin.DistanceTo(
                picked_point
            )

            if distance < minimum_distance:
                minimum_distance = distance
                nearest_connector = connector

        except:
            continue

    return nearest_connector


def get_connector_near_point(
        elem,
        target_point,
        require_open=True):
    """
    Refreshes and returns the connector nearest to a point.
    """

    nearest_connector = None
    minimum_distance = float("inf")

    for connector in get_end_connectors(elem):

        try:
            if require_open and connector.IsConnected:
                continue

            distance = connector.Origin.DistanceTo(
                target_point
            )

            if distance < minimum_distance:
                minimum_distance = distance
                nearest_connector = connector

        except:
            continue

    return nearest_connector


def get_nearest_connector_pair(element_one, element_two):
    """
    Finds the nearest compatible open connector pair.
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

            try:
                distance = connector_one.Origin.DistanceTo(
                    connector_two.Origin
                )
            except:
                continue

            if distance < minimum_distance:
                minimum_distance = distance
                connector_one_best = connector_one
                connector_two_best = connector_two

    return connector_one_best, connector_two_best


def get_connector_basis(connector):

    if connector is None:
        return None, None, None

    try:
        coordinate_system = connector.CoordinateSystem

        return (
            coordinate_system.BasisX,
            coordinate_system.BasisY,
            coordinate_system.BasisZ
        )

    except:
        return None, None, None


# ============================================================
# DUCT PROFILE HELPERS
# ============================================================

def get_connector_shape(connector):

    if connector is None:
        return None

    try:
        return connector.Shape
    except:
        return None


def requires_duct_roll_alignment(source_connector):
    """
    Round ducts do not require roll alignment.
    Rectangular and oval ducts do.
    """

    connector_shape = get_connector_shape(
        source_connector
    )

    if connector_shape is None:
        return False

    try:
        return connector_shape != ConnectorProfileType.Round
    except:
        return False


def calculate_duct_roll_score(
        source_connector,
        stub_connector,
        main_direction,
        stub_direction):
    """
    Scores the roll orientation of a vertical rectangular or oval stub.

    The preferred rectangular width direction is the common perpendicular
    direction between the main duct centreline and stub centreline.

    A secondary comparison uses the source connector orientation.
    """

    if source_connector is None:
        return -1.0

    if stub_connector is None:
        return -1.0

    main_direction = normalised(main_direction)
    stub_direction = normalised(stub_direction)

    if main_direction is None or stub_direction is None:
        return -1.0

    source_x, source_y, source_z = get_connector_basis(
        source_connector
    )

    stub_x, stub_y, stub_z = get_connector_basis(
        stub_connector
    )

    if stub_x is None or stub_y is None:
        return -1.0

    # Common perpendicular between the main direction and new stub.
    common_axis = main_direction.CrossProduct(
        stub_direction
    )

    if not is_valid_vector(common_axis):

        # This should normally only occur for parallel elements.
        common_axis = project_vector_to_plane(
            source_x,
            stub_direction
        )

    if common_axis is None or not is_valid_vector(common_axis):
        return -1.0

    common_axis = common_axis.Normalize()

    # Primary score:
    # Prefer the new duct BasisX to align with the common horizontal axis.
    width_score = absolute_dot(
        stub_x,
        common_axis
    )

    # Secondary source connector comparison.
    source_x_projected = project_vector_to_plane(
        source_x,
        stub_direction
    )

    source_y_projected = project_vector_to_plane(
        source_y,
        stub_direction
    )

    source_score = 0.0

    if source_x_projected is not None:

        source_score = max(
            source_score,
            absolute_dot(
                stub_x,
                source_x_projected
            )
        )

    if source_y_projected is not None:

        source_score = max(
            source_score,
            absolute_dot(
                stub_y,
                source_y_projected
            )
        )

    # Width/common-axis alignment is weighted more strongly.
    return (
        width_score * 10.0
        + source_score
    )


def align_vertical_duct_roll(
        source_duct,
        new_duct,
        connection_point,
        stub_end_point,
        main_direction):
    """
    Tests the four possible quarter-turn roll orientations.

    The new duct is temporarily rotated through:
    0 degrees
    90 degrees
    180 degrees
    270 degrees

    The best orientation is then applied before elbow creation.
    """

    source_connector = get_connector_near_point(
        source_duct,
        connection_point,
        require_open=True
    )

    if source_connector is None:
        return

    if not requires_duct_roll_alignment(
            source_connector
    ):
        return

    stub_axis_vector = (
        stub_end_point - connection_point
    )

    stub_direction = normalised(
        stub_axis_vector
    )

    if stub_direction is None:
        return

    # Apply this roll correction only when the newly created stub is vertical.
    if abs(stub_direction.Z) <= VERTICAL_TOLERANCE:
        return

    rotation_axis = Line.CreateBound(
        connection_point,
        stub_end_point
    )

    quarter_turn = math.pi / 2.0

    scores = []

    # Evaluate current orientation, then three additional quarter turns.
    for orientation_index in range(4):

        doc.Regenerate()

        refreshed_source_connector = get_connector_near_point(
            source_duct,
            connection_point,
            require_open=True
        )

        refreshed_stub_connector = get_connector_near_point(
            new_duct,
            connection_point,
            require_open=True
        )

        score = calculate_duct_roll_score(
            refreshed_source_connector,
            refreshed_stub_connector,
            main_direction,
            stub_direction
        )

        scores.append(score)

        if orientation_index < 3:

            ElementTransformUtils.RotateElement(
                doc,
                new_duct.Id,
                rotation_axis,
                quarter_turn
            )

            doc.Regenerate()

    # At this point the new duct is rotated by 270 degrees.
    # Rotate once more to return to its original orientation.
    ElementTransformUtils.RotateElement(
        doc,
        new_duct.Id,
        rotation_axis,
        quarter_turn
    )

    doc.Regenerate()

    best_orientation_index = 0
    best_score = scores[0]

    for index in range(1, len(scores)):

        if scores[index] > best_score:
            best_score = scores[index]
            best_orientation_index = index

    # Apply the selected roll from the original orientation.
    if best_orientation_index > 0:

        final_rotation = (
            quarter_turn
            * best_orientation_index
        )

        ElementTransformUtils.RotateElement(
            doc,
            new_duct.Id,
            rotation_axis,
            final_rotation
        )

        doc.Regenerate()


# ============================================================
# SYSTEM TYPE
# ============================================================

def get_default_system_type(
        is_duct=False,
        is_pipe=False):

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


# ============================================================
# PARAMETER COPYING
# ============================================================

def copy_parameter_value(
        source_element,
        destination_element,
        built_in_parameter):

    try:
        source_parameter = source_element.get_Parameter(
            built_in_parameter
        )

        destination_parameter = destination_element.get_Parameter(
            built_in_parameter
        )

    except:
        return

    if source_parameter is None:
        return

    if destination_parameter is None:
        return

    if not source_parameter.HasValue:
        return

    if destination_parameter.IsReadOnly:
        return

    try:

        if source_parameter.StorageType == StorageType.Double:

            destination_parameter.Set(
                source_parameter.AsDouble()
            )

        elif source_parameter.StorageType == StorageType.Integer:

            destination_parameter.Set(
                source_parameter.AsInteger()
            )

        elif source_parameter.StorageType == StorageType.String:

            destination_parameter.Set(
                source_parameter.AsString()
            )

        elif source_parameter.StorageType == StorageType.ElementId:

            destination_parameter.Set(
                source_parameter.AsElementId()
            )

    except:
        pass


# ============================================================
# ELBOW CREATION
# ============================================================

def create_elbow(element_one, element_two):
    """
    Creates an elbow between the nearest compatible open connectors.
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
            "Connectors are not coincident. "
            "Distance: {:.3f} mm".format(
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


element = doc.GetElement(
    picked_reference.ElementId
)

if element is None:
    script.exit()


# ============================================================
# VALIDATE LOCATION CURVE
# ============================================================

if not isinstance(element.Location, LocationCurve):

    logger.error(
        "Selected element does not have a LocationCurve."
    )

    script.exit()


# ============================================================
# SELECT CONNECTOR NEAREST TO CLICKED SIDE
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


connection_point = available_connector.Origin


# ============================================================
# CALCULATE MAIN ELEMENT DIRECTION
# ============================================================

curve = element.Location.Curve

point_zero = curve.GetEndPoint(0)
point_one = curve.GetEndPoint(1)

if point_zero.DistanceTo(
        connection_point) < point_one.DistanceTo(
            connection_point):

    forward_direction = curve.Direction

else:

    forward_direction = curve.Direction.Negate()


forward_direction = normalised(
    forward_direction
)

if forward_direction is None:

    logger.error(
        "Could not determine the selected element direction."
    )

    script.exit()


# ============================================================
# CALCULATE ELBOW UP DIRECTION
# ============================================================

if abs(forward_direction.Z) > VERTICAL_TOLERANCE:

    # Naviate LT behaviour for a vertical selected element.
    # The stub exits horizontally towards model south.
    elbow_up_vector = XYZ(
        0.0,
        -1.0,
        0.0
    )

else:

    # Horizontal or sloped selected element.
    # Elbow Up exits towards global positive Z.
    elbow_up_vector = XYZ.BasisZ


elbow_up_vector = elbow_up_vector.Normalize()


# ============================================================
# DETERMINE STUB LENGTH
# ============================================================

segment_length = 0.0


# ------------------------------------------------------------
# DUCT
# ------------------------------------------------------------

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

    segment_length = get_stub_length_from_size(
        size_mm
    )


# ------------------------------------------------------------
# PIPE
# ------------------------------------------------------------

elif isinstance(element, Pipe):

    pipe_diameter = element.get_Parameter(
        BuiltInParameter.RBS_PIPE_DIAMETER_PARAM
    )

    size_mm = 0.0

    if pipe_diameter and pipe_diameter.HasValue:

        size_mm = internal_to_mm(
            pipe_diameter.AsDouble()
        )

    segment_length = get_stub_length_from_size(
        size_mm
    )


# ------------------------------------------------------------
# CABLE TRAY
# ------------------------------------------------------------

elif isinstance(element, CableTray):

    cable_tray_width = element.get_Parameter(
        BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM
    )

    size_mm = 0.0

    if cable_tray_width and cable_tray_width.HasValue:

        size_mm = internal_to_mm(
            cable_tray_width.AsDouble()
        )

    segment_length = get_stub_length_from_size(
        size_mm
    )


# ------------------------------------------------------------
# CONDUIT
# ------------------------------------------------------------

elif isinstance(element, Conduit):

    segment_length = metres_to_internal(
        1.0
    )


else:
    script.exit()


if segment_length <= VECTOR_TOLERANCE:

    logger.error(
        "Could not determine a valid stub length."
    )

    script.exit()


# ============================================================
# CALCULATE STUB GEOMETRY
# ============================================================

start_point = connection_point

end_point = start_point + elbow_up_vector.Multiply(
    segment_length
)


# ============================================================
# LEVEL
# ============================================================

level_id = get_element_level_id(
    element
)

if level_id == ElementId.InvalidElementId:

    logger.error(
        "Could not determine the reference level."
    )

    script.exit()


# ============================================================
# TRANSACTION
# ============================================================

transaction = Transaction(
    doc,
    "Elbow Up Tool"
)

transaction.Start()


try:

    new_element = None
    new_elbow = None


    # ========================================================
    # DUCT
    # ========================================================

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

        # Correct the roll of rectangular or oval vertical stubs.
        # This occurs before elbow creation.
        align_vertical_duct_roll(
            element,
            new_element,
            start_point,
            end_point,
            forward_direction
        )

        doc.Regenerate()

        new_elbow = create_elbow(
            element,
            new_element
        )


    # ========================================================
    # PIPE
    # ========================================================

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


    # ========================================================
    # CABLE TRAY
    # ========================================================

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


    # ========================================================
    # CONDUIT
    # ========================================================

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

        new_elbow = create_elbow(
            element,
            new_element
        )


    # ========================================================
    # FINAL VALIDATION
    # ========================================================

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