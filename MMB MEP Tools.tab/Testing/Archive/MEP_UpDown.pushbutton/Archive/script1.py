# -*- coding: utf-8 -*-
"""
MMB MEP Up/Down
Modeless pyRevit tool for Revit 2023 and later.

Supported:
    - Pipe
    - Duct
    - Cable Tray
    - Conduit

Workflow:
    1. Open MEP Up/Down.
    2. The window remains modeless.
    3. Split elements using Revit's standard Split command.
    4. Select one or more connected split MEP sections.
    5. Enter the offset and angle.
    6. Click Apply.

Operation:
    - Selected MEP curves move vertically as one group.
    - Internal fittings between selected curves move with the group.
    - Transitions are created only at the external boundaries.
    - Boundary fittings are replaced when required.
"""

from __future__ import division

import math
import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("System")

from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ConnectorType,
    ElementId,
    ElementTransformUtils,
    FailureProcessingResult,
    FailureSeverity,
    ForgeTypeId,
    IFailuresPreprocessor,
    Line,
    LocationCurve,
    Transaction,
    TransactionStatus,
    UnitUtils,
    XYZ
)

from Autodesk.Revit.DB.Plumbing import Pipe
from Autodesk.Revit.DB.Mechanical import Duct
from Autodesk.Revit.DB.Electrical import (
    Conduit,
    CableTray
)

from Autodesk.Revit.UI import (
    ExternalEvent,
    IExternalEventHandler
)

from pyrevit import forms


__title__ = "MEP Up/Down"
__author__ = "Govind Ranjith Kota"


SUPPORTED_CLASSES = (
    Pipe,
    Duct,
    Conduit,
    CableTray
)

TOLERANCE = 0.000001


# ==========================================================
# FAILURE HANDLING
# ==========================================================

class MEPFailurePreprocessor(IFailuresPreprocessor):

    def PreprocessFailures(self, failures_accessor):

        messages = list(
            failures_accessor.GetFailureMessages()
        )

        for message in messages:

            try:
                severity = message.GetSeverity()

                if severity == FailureSeverity.Warning:

                    failures_accessor.DeleteWarning(
                        message
                    )

            except Exception:
                pass

        return FailureProcessingResult.Continue


# ==========================================================
# ELEMENT ID HELPERS
# ==========================================================

def element_id_value(element_id):
    """
    Returns the numeric ElementId value.

    Revit 2024 and earlier commonly expose IntegerValue.
    Newer versions also expose Value.
    """

    try:
        return element_id.Value

    except Exception:
        return element_id.IntegerValue


def id_is_valid(element_id):

    if element_id is None:
        return False

    try:
        return (
            element_id
            != ElementId.InvalidElementId
        )

    except Exception:
        return False


def make_element_id(value):
    """
    Creates an ElementId safely across supported
    Revit versions.
    """

    try:
        return ElementId(value)

    except Exception:
        return ElementId(int(value))


# ==========================================================
# ELEMENT VALIDATION
# ==========================================================

def is_supported_curve(element):

    if element is None:
        return False

    if not isinstance(
        element,
        SUPPORTED_CLASSES
    ):
        return False

    if not isinstance(
        element.Location,
        LocationCurve
    ):
        return False

    if not isinstance(
        element.Location.Curve,
        Line
    ):
        return False

    return True


def category_id_value(category):

    if category is None:
        return None

    try:
        return category.Id.Value

    except Exception:
        try:
            return category.Id.IntegerValue

        except Exception:
            return None


def is_supported_fitting(element):

    if element is None:
        return False

    if element.Category is None:
        return False

    fitting_categories = [
        int(BuiltInCategory.OST_DuctFitting),
        int(BuiltInCategory.OST_PipeFitting),
        int(BuiltInCategory.OST_ConduitFitting),
        int(BuiltInCategory.OST_CableTrayFitting)
    ]

    current_category = category_id_value(
        element.Category
    )

    return current_category in fitting_categories


def same_mep_class(first, second):

    if isinstance(first, Pipe):
        return isinstance(second, Pipe)

    if isinstance(first, Duct):
        return isinstance(second, Duct)

    if isinstance(first, Conduit):
        return isinstance(second, Conduit)

    if isinstance(first, CableTray):
        return isinstance(second, CableTray)

    return False


# ==========================================================
# UNIT CONVERSION
# ==========================================================

def get_project_length_unit_id(doc):

    units = doc.GetUnits()

    try:
        from Autodesk.Revit.DB import SpecTypeId

        format_options = units.GetFormatOptions(
            SpecTypeId.Length
        )

        return format_options.GetUnitTypeId()

    except Exception:

        length_spec = ForgeTypeId(
            "autodesk.spec.aec:length-2.0.0"
        )

        format_options = units.GetFormatOptions(
            length_spec
        )

        return format_options.GetUnitTypeId()


def to_internal_units(doc, value):

    return UnitUtils.ConvertToInternalUnits(
        float(value),
        get_project_length_unit_id(doc)
    )


# ==========================================================
# CONNECTOR HELPERS
# ==========================================================

def get_connector_manager(element):

    if element is None:
        return None

    try:
        connector_manager = (
            element.ConnectorManager
        )

        if connector_manager is not None:
            return connector_manager

    except Exception:
        pass

    try:
        mep_model = element.MEPModel

        if mep_model is not None:
            return mep_model.ConnectorManager

    except Exception:
        pass

    return None


def get_connectors(element):

    connector_manager = get_connector_manager(
        element
    )

    if connector_manager is None:
        return []

    connectors = []

    for connector in connector_manager.Connectors:

        try:
            if (
                connector.ConnectorType
                == ConnectorType.End
            ):
                connectors.append(connector)

        except Exception:
            connectors.append(connector)

    return connectors


def copy_xyz(point):

    return XYZ(
        point.X,
        point.Y,
        point.Z
    )


def get_physical_references(connector):

    references = []

    if connector is None:
        return references

    for reference in connector.AllRefs:

        try:
            if (
                reference.Owner.Id
                == connector.Owner.Id
            ):
                continue

            references.append(reference)

        except Exception:
            continue

    return references


def nearest_connector(element, point):

    connectors = get_connectors(element)

    if not connectors:

        raise Exception(
            "No connectors found on element {0}.".format(
                element_id_value(element.Id)
            )
        )

    connectors.sort(
        key=lambda connector:
        connector.Origin.DistanceTo(point)
    )

    return connectors[0]


def disconnect_connectors(
    first_connector,
    second_connector
):

    if first_connector is None:
        return

    if second_connector is None:
        return

    try:
        if first_connector.IsConnectedTo(
            second_connector
        ):

            first_connector.DisconnectFrom(
                second_connector
            )

            return

    except Exception:
        pass

    try:
        first_connector.DisconnectFrom(
            second_connector
        )

    except Exception:
        pass


# ==========================================================
# SELECTION
# ==========================================================

def get_selected_mep_curves(
    uidoc,
    doc
):

    selected_elements = []

    selected_ids = list(
        uidoc.Selection.GetElementIds()
    )

    for element_id in selected_ids:

        element = doc.GetElement(
            element_id
        )

        if is_supported_curve(element):
            selected_elements.append(element)

    return selected_elements


def create_id_set(elements):

    result = set()

    for element in elements:

        result.add(
            element_id_value(element.Id)
        )

    return result


# ==========================================================
# INTERNAL FITTING ANALYSIS
# ==========================================================

def get_selected_curves_connected_to_fitting(
    fitting,
    selected_ids
):

    connected_selected_ids = set()

    for fitting_connector in get_connectors(
        fitting
    ):

        references = get_physical_references(
            fitting_connector
        )

        for reference in references:

            owner = reference.Owner

            owner_id = element_id_value(
                owner.Id
            )

            if owner_id in selected_ids:
                connected_selected_ids.add(
                    owner_id
                )

    return connected_selected_ids


def find_internal_fittings(
    selected_elements,
    selected_ids
):
    """
    Internal fittings connect at least two selected curves.

    Example:
        The elbow between two selected ducts is internal
        and must move with the selected ducts.
    """

    fitting_candidates = {}

    for selected_element in selected_elements:

        connectors = get_connectors(
            selected_element
        )

        for connector in connectors:

            references = get_physical_references(
                connector
            )

            for reference in references:

                owner = reference.Owner

                if not is_supported_fitting(owner):
                    continue

                fitting_candidates[
                    element_id_value(owner.Id)
                ] = owner

    internal_fittings = []

    for fitting in fitting_candidates.values():

        connected_selected_ids = (
            get_selected_curves_connected_to_fitting(
                fitting,
                selected_ids
            )
        )

        if len(connected_selected_ids) >= 2:
            internal_fittings.append(fitting)

    return internal_fittings


# ==========================================================
# BOUNDARY FITTING ANALYSIS
# ==========================================================

def find_unselected_curve_through_fitting(
    fitting,
    selected_ids
):
    """
    Searches a boundary fitting for the unselected MEP curve
    connected to the opposite side.
    """

    for fitting_connector in get_connectors(
        fitting
    ):

        references = get_physical_references(
            fitting_connector
        )

        for reference in references:

            owner = reference.Owner

            owner_id = element_id_value(
                owner.Id
            )

            if owner_id in selected_ids:
                continue

            if not is_supported_curve(owner):
                continue

            return {
                "outer_element_id":
                    owner.Id,
                "outer_origin":
                    copy_xyz(reference.Origin),
                "fitting_id":
                    fitting.Id
            }

    return None


def find_group_boundaries(
    selected_elements,
    selected_ids,
    internal_fitting_ids
):
    """
    Detects the external boundaries of a selected group.

    A boundary may be:
        - An open connector.
        - A direct connection to an unselected MEP curve.
        - A connection through a boundary fitting to an
          unselected MEP curve.
    """

    boundaries = []
    recorded_boundaries = set()

    for selected_element in selected_elements:

        connectors = get_connectors(
            selected_element
        )

        for selected_connector in connectors:

            selected_origin = copy_xyz(
                selected_connector.Origin
            )

            boundary_key = (
                element_id_value(
                    selected_element.Id
                ),
                round(selected_origin.X, 6),
                round(selected_origin.Y, 6),
                round(selected_origin.Z, 6)
            )

            if boundary_key in recorded_boundaries:
                continue

            references = get_physical_references(
                selected_connector
            )

            # Open connector at a split boundary.
            if not references:

                recorded_boundaries.add(
                    boundary_key
                )

                boundaries.append({
                    "selected_element_id":
                        selected_element.Id,
                    "selected_origin":
                        selected_origin,
                    "outer_element_id":
                        ElementId.InvalidElementId,
                    "outer_origin":
                        None,
                    "boundary_fitting_id":
                        ElementId.InvalidElementId
                })

                continue

            boundary_found = False

            for reference in references:

                owner = reference.Owner

                owner_id = element_id_value(
                    owner.Id
                )

                # Connected directly to another selected curve.
                if owner_id in selected_ids:
                    continue

                # Connected to an internal fitting.
                if owner_id in internal_fitting_ids:
                    continue

                outer_element_id = (
                    ElementId.InvalidElementId
                )

                outer_origin = None

                boundary_fitting_id = (
                    ElementId.InvalidElementId
                )

                # Direct selected-to-unselected connection.
                if is_supported_curve(owner):

                    outer_element_id = owner.Id

                    outer_origin = copy_xyz(
                        reference.Origin
                    )

                    boundary_found = True

                # Selected curve connected through fitting.
                elif is_supported_fitting(owner):

                    boundary_result = (
                        find_unselected_curve_through_fitting(
                            owner,
                            selected_ids
                        )
                    )

                    if boundary_result is None:
                        continue

                    outer_element_id = (
                        boundary_result[
                            "outer_element_id"
                        ]
                    )

                    outer_origin = (
                        boundary_result[
                            "outer_origin"
                        ]
                    )

                    boundary_fitting_id = (
                        boundary_result[
                            "fitting_id"
                        ]
                    )

                    boundary_found = True

                if boundary_found:

                    recorded_boundaries.add(
                        boundary_key
                    )

                    boundaries.append({
                        "selected_element_id":
                            selected_element.Id,
                        "selected_origin":
                            selected_origin,
                        "outer_element_id":
                            outer_element_id,
                        "outer_origin":
                            outer_origin,
                        "boundary_fitting_id":
                            boundary_fitting_id
                    })

                    break

    return boundaries


# ==========================================================
# PARAMETER HELPERS
# ==========================================================

def get_builtin_parameter_by_name(
    element,
    parameter_name
):
    """
    Retrieves a BuiltInParameter using getattr.

    This prevents errors when a parameter identifier is not
    available in a specific Revit API version.
    """

    try:
        built_in_parameter = getattr(
            BuiltInParameter,
            parameter_name,
            None
        )

        if built_in_parameter is None:
            return None

        return element.get_Parameter(
            built_in_parameter
        )

    except Exception:
        return None


def get_reference_level_id(element):
    """
    Returns the reference level without directly accessing
    unavailable BuiltInParameter members.

    Compatible with Revit 2023 and later.
    """

    # Method 1: LevelId property.
    try:
        level_id = element.LevelId

        if id_is_valid(level_id):
            return level_id

    except Exception:
        pass

    # Method 2: ReferenceLevel property.
    try:
        reference_level = element.ReferenceLevel

        if reference_level is not None:

            level_id = reference_level.Id

            if id_is_valid(level_id):
                return level_id

    except Exception:
        pass

    # Method 3: Version-safe BuiltInParameter lookup.
    parameter_names = [
        "RBS_START_LEVEL_PARAM",
        "RBS_REFERENCE_LEVEL_PARAM",
        "INSTANCE_REFERENCE_LEVEL_PARAM",
        "FAMILY_LEVEL_PARAM",
        "SCHEDULE_LEVEL_PARAM"
    ]

    for parameter_name in parameter_names:

        parameter = get_builtin_parameter_by_name(
            element,
            parameter_name
        )

        if parameter is None:
            continue

        try:
            level_id = parameter.AsElementId()

            if id_is_valid(level_id):
                return level_id

        except Exception:
            continue

    # Method 4: Display-name fallback.
    parameter_labels = [
        "Reference Level",
        "Level",
        "Start Level",
        "Base Level"
    ]

    for parameter_label in parameter_labels:

        try:
            parameter = element.LookupParameter(
                parameter_label
            )

            if parameter is None:
                continue

            level_id = parameter.AsElementId()

            if id_is_valid(level_id):
                return level_id

        except Exception:
            continue

    return ElementId.InvalidElementId


def get_system_type_id(element):
    """
    Returns the pipe or duct system type using version-safe
    parameter lookup.
    """

    if isinstance(element, Pipe):

        parameter_names = [
            "RBS_PIPING_SYSTEM_TYPE_PARAM"
        ]

    elif isinstance(element, Duct):

        parameter_names = [
            "RBS_DUCT_SYSTEM_TYPE_PARAM"
        ]

    else:
        return ElementId.InvalidElementId

    for parameter_name in parameter_names:

        parameter = get_builtin_parameter_by_name(
            element,
            parameter_name
        )

        if parameter is None:
            continue

        try:
            system_type_id = (
                parameter.AsElementId()
            )

            if id_is_valid(system_type_id):
                return system_type_id

        except Exception:
            continue

    # MEPSystem property fallback.
    try:
        mep_system = element.MEPSystem

        if mep_system is not None:

            system_type_id = (
                mep_system.GetTypeId()
            )

            if id_is_valid(system_type_id):
                return system_type_id

    except Exception:
        pass

    return ElementId.InvalidElementId


def copy_double_parameter_by_name(
    source,
    target,
    parameter_name
):

    try:
        built_in_parameter = getattr(
            BuiltInParameter,
            parameter_name,
            None
        )

        if built_in_parameter is None:
            return

        source_parameter = source.get_Parameter(
            built_in_parameter
        )

        target_parameter = target.get_Parameter(
            built_in_parameter
        )

        if source_parameter is None:
            return

        if target_parameter is None:
            return

        if target_parameter.IsReadOnly:
            return

        target_parameter.Set(
            source_parameter.AsDouble()
        )

    except Exception:
        pass


def copy_curve_size(
    source,
    target
):
    """
    Copies dimensions from the source MEP curve
    to the newly created transition.
    """

    if isinstance(source, Pipe):

        copy_double_parameter_by_name(
            source,
            target,
            "RBS_PIPE_DIAMETER_PARAM"
        )

    elif isinstance(source, Duct):

        copy_double_parameter_by_name(
            source,
            target,
            "RBS_CURVE_DIAMETER_PARAM"
        )

        copy_double_parameter_by_name(
            source,
            target,
            "RBS_CURVE_WIDTH_PARAM"
        )

        copy_double_parameter_by_name(
            source,
            target,
            "RBS_CURVE_HEIGHT_PARAM"
        )

    elif isinstance(source, Conduit):

        copy_double_parameter_by_name(
            source,
            target,
            "RBS_CONDUIT_DIAMETER_PARAM"
        )

    elif isinstance(source, CableTray):

        copy_double_parameter_by_name(
            source,
            target,
            "RBS_CABLETRAY_WIDTH_PARAM"
        )

        copy_double_parameter_by_name(
            source,
            target,
            "RBS_CABLETRAY_HEIGHT_PARAM"
        )


# ==========================================================
# TRANSITION CREATION
# ==========================================================

def create_curve_like(
    doc,
    source,
    start_point,
    end_point
):
    """
    Creates a fresh MEP curve matching the source curve.

    Fresh creation avoids copying invalid connector
    relationships from connected MEP curves.
    """

    transition_length = (
        start_point.DistanceTo(end_point)
    )

    if transition_length <= TOLERANCE:

        raise Exception(
            "Transition length is too small."
        )

    type_id = source.GetTypeId()

    level_id = get_reference_level_id(
        source
    )

    if not id_is_valid(level_id):

        raise Exception(
            "Reference level could not be determined "
            "for element {0}.".format(
                element_id_value(source.Id)
            )
        )

    if isinstance(source, Pipe):

        system_type_id = get_system_type_id(
            source
        )

        if not id_is_valid(system_type_id):

            raise Exception(
                "Pipe system type could not be determined."
            )

        created_element = Pipe.Create(
            doc,
            system_type_id,
            type_id,
            level_id,
            start_point,
            end_point
        )

    elif isinstance(source, Duct):

        system_type_id = get_system_type_id(
            source
        )

        if not id_is_valid(system_type_id):

            raise Exception(
                "Duct system type could not be determined."
            )

        created_element = Duct.Create(
            doc,
            system_type_id,
            type_id,
            level_id,
            start_point,
            end_point
        )

    elif isinstance(source, Conduit):

        created_element = Conduit.Create(
            doc,
            type_id,
            start_point,
            end_point,
            level_id
        )

    elif isinstance(source, CableTray):

        created_element = CableTray.Create(
            doc,
            type_id,
            start_point,
            end_point,
            level_id
        )

    else:

        raise Exception(
            "Unsupported MEP element type."
        )

    copy_curve_size(
        source,
        created_element
    )

    return created_element


# ==========================================================
# GEOMETRY HELPERS
# ==========================================================

def get_inward_direction(
    selected_element,
    boundary_point
):
    """
    Returns the direction from the external boundary
    towards the interior of the selected MEP section.
    """

    curve = selected_element.Location.Curve

    start = curve.GetEndPoint(0)
    end = curve.GetEndPoint(1)

    start_distance = start.DistanceTo(
        boundary_point
    )

    end_distance = end.DistanceTo(
        boundary_point
    )

    if start_distance <= end_distance:
        direction = end - start

    else:
        direction = start - end

    if direction.GetLength() <= TOLERANCE:

        raise Exception(
            "Unable to determine boundary direction."
        )

    return direction.Normalize()


def shorten_boundary_curve(
    element,
    boundary_point,
    horizontal_run
):
    """
    Shortens a selected boundary curve towards the interior
    of the selected group.
    """

    curve = element.Location.Curve

    start = curve.GetEndPoint(0)
    end = curve.GetEndPoint(1)

    inward_direction = get_inward_direction(
        element,
        boundary_point
    )

    shortened_point = (
        boundary_point
        + inward_direction.Multiply(
            horizontal_run
        )
    )

    start_distance = start.DistanceTo(
        boundary_point
    )

    end_distance = end.DistanceTo(
        boundary_point
    )

    if start_distance <= end_distance:

        fixed_point = end

        if (
            shortened_point.DistanceTo(
                fixed_point
            )
            <= TOLERANCE
        ):

            raise Exception(
                "A selected boundary section is too short."
            )

        element.Location.Curve = (
            Line.CreateBound(
                shortened_point,
                fixed_point
            )
        )

    else:

        fixed_point = start

        if (
            fixed_point.DistanceTo(
                shortened_point
            )
            <= TOLERANCE
        ):

            raise Exception(
                "A selected boundary section is too short."
            )

        element.Location.Curve = (
            Line.CreateBound(
                fixed_point,
                shortened_point
            )
        )

    return copy_xyz(shortened_point)


# ==========================================================
# GROUP OFFSET OPERATION
# ==========================================================

def apply_to_selected_group(
    doc,
    selected_elements,
    offset,
    angle
):
    """
    Applies a vertical offset to one connected selected group.
    """

    selected_ids = create_id_set(
        selected_elements
    )

    internal_fittings = find_internal_fittings(
        selected_elements,
        selected_ids
    )

    internal_fitting_ids = create_id_set(
        internal_fittings
    )

    boundaries = find_group_boundaries(
        selected_elements,
        selected_ids,
        internal_fitting_ids
    )

    if len(boundaries) != 2:

        raise Exception(
            "Select one connected MEP group with exactly "
            "two external boundaries. Boundaries found: {0}".format(
                len(boundaries)
            )
        )

    if abs(angle - 90.0) <= TOLERANCE:
        horizontal_run = 0.0

    else:
        horizontal_run = (
            abs(offset)
            / math.tan(
                math.radians(angle)
            )
        )

    vertical_vector = XYZ(
        0.0,
        0.0,
        offset
    )

    boundary_data = []
    boundary_fitting_values = set()

    # ------------------------------------------------------
    # Store boundary information
    # ------------------------------------------------------

    for boundary in boundaries:

        boundary_data.append({
            "selected_element_id":
                boundary["selected_element_id"],

            "selected_origin":
                copy_xyz(
                    boundary["selected_origin"]
                ),

            "outer_element_id":
                boundary["outer_element_id"],

            "outer_origin":
                copy_xyz(
                    boundary["outer_origin"]
                )
                if boundary["outer_origin"] is not None
                else None,

            "boundary_fitting_id":
                boundary["boundary_fitting_id"]
        })

        boundary_fitting_id = boundary[
            "boundary_fitting_id"
        ]

        if id_is_valid(boundary_fitting_id):

            boundary_fitting_values.add(
                element_id_value(
                    boundary_fitting_id
                )
            )

    # ------------------------------------------------------
    # Delete boundary fittings
    # ------------------------------------------------------

    delete_ids = List[ElementId]()

    for fitting_value in boundary_fitting_values:

        fitting_id = make_element_id(
            fitting_value
        )

        if doc.GetElement(fitting_id) is not None:
            delete_ids.Add(fitting_id)

    if delete_ids.Count > 0:
        doc.Delete(delete_ids)

    doc.Regenerate()

    # ------------------------------------------------------
    # Disconnect direct selected-to-outer connections
    # ------------------------------------------------------

    for data in boundary_data:

        outer_element_id = data[
            "outer_element_id"
        ]

        if not id_is_valid(outer_element_id):
            continue

        selected_element = doc.GetElement(
            data["selected_element_id"]
        )

        outer_element = doc.GetElement(
            outer_element_id
        )

        if selected_element is None:
            continue

        if outer_element is None:
            continue

        selected_connector = nearest_connector(
            selected_element,
            data["selected_origin"]
        )

        outer_connector = nearest_connector(
            outer_element,
            data["outer_origin"]
        )

        disconnect_connectors(
            selected_connector,
            outer_connector
        )

    doc.Regenerate()

    # ------------------------------------------------------
    # Shorten selected boundary curves
    # ------------------------------------------------------

    for data in boundary_data:

        selected_element = doc.GetElement(
            data["selected_element_id"]
        )

        if selected_element is None:

            raise Exception(
                "A selected boundary element no longer exists."
            )

        shortened_point = shorten_boundary_curve(
            selected_element,
            data["selected_origin"],
            horizontal_run
        )

        data["shortened_point"] = shortened_point

    doc.Regenerate()

    # ------------------------------------------------------
    # Move selected curves and internal fittings together
    # ------------------------------------------------------

    move_ids = List[ElementId]()
    added_ids = set()

    for selected_element in selected_elements:

        current_element = doc.GetElement(
            selected_element.Id
        )

        if current_element is None:
            continue

        current_id_value = element_id_value(
            current_element.Id
        )

        if current_id_value in added_ids:
            continue

        move_ids.Add(
            current_element.Id
        )

        added_ids.add(
            current_id_value
        )

    for fitting in internal_fittings:

        current_fitting = doc.GetElement(
            fitting.Id
        )

        if current_fitting is None:
            continue

        fitting_id_value = element_id_value(
            current_fitting.Id
        )

        if fitting_id_value in added_ids:
            continue

        move_ids.Add(
            current_fitting.Id
        )

        added_ids.add(
            fitting_id_value
        )

    if move_ids.Count == 0:

        raise Exception(
            "No valid selected elements were found to move."
        )

    ElementTransformUtils.MoveElements(
        doc,
        move_ids,
        vertical_vector
    )

    doc.Regenerate()

    resulting_ids = []

    for selected_element in selected_elements:

        if doc.GetElement(
            selected_element.Id
        ) is not None:

            resulting_ids.append(
                selected_element.Id
            )

    for fitting in internal_fittings:

        if doc.GetElement(
            fitting.Id
        ) is not None:

            resulting_ids.append(
                fitting.Id
            )

    # ------------------------------------------------------
    # Create transitions at the two external boundaries
    # ------------------------------------------------------

    for data in boundary_data:

        selected_element = doc.GetElement(
            data["selected_element_id"]
        )

        if selected_element is None:

            raise Exception(
                "The selected boundary element no longer exists."
            )

        original_point = data[
            "selected_origin"
        ]

        shortened_point = data[
            "shortened_point"
        ]

        moved_shortened_point = (
            shortened_point
            + vertical_vector
        )

        transition = create_curve_like(
            doc,
            selected_element,
            original_point,
            moved_shortened_point
        )

        doc.Regenerate()

        # Connect transition to the moved selected group.
        transition_inner_connector = (
            nearest_connector(
                transition,
                moved_shortened_point
            )
        )

        selected_inner_connector = (
            nearest_connector(
                selected_element,
                moved_shortened_point
            )
        )

        doc.Create.NewElbowFitting(
            transition_inner_connector,
            selected_inner_connector
        )

        doc.Regenerate()

        # Connect transition to the unchanged outer run.
        outer_element_id = data[
            "outer_element_id"
        ]

        if id_is_valid(outer_element_id):

            outer_element = doc.GetElement(
                outer_element_id
            )

            if outer_element is None:

                raise Exception(
                    "The outer MEP element no longer exists."
                )

            transition_outer_connector = (
                nearest_connector(
                    transition,
                    original_point
                )
            )

            outer_connector = nearest_connector(
                outer_element,
                data["outer_origin"]
            )

            doc.Create.NewElbowFitting(
                outer_connector,
                transition_outer_connector
            )

            doc.Regenerate()

        resulting_ids.append(
            transition.Id
        )

    return resulting_ids


# ==========================================================
# EXTERNAL EVENT HANDLER
# ==========================================================

class ApplyHandler(IExternalEventHandler):

    def __init__(self):

        self.offset_text = ""
        self.angle_text = ""
        self.window = None
        self.is_running = False

    def Execute(self, application):

        if self.is_running:
            return

        self.is_running = True

        transaction = None

        try:
            uidoc = application.ActiveUIDocument

            if uidoc is None:

                self.window.set_status(
                    "No active Revit document."
                )

                return

            doc = uidoc.Document

            offset_value = float(
                self.offset_text.strip()
            )

            angle_value = float(
                self.angle_text.strip()
            )

            if abs(offset_value) <= TOLERANCE:

                self.window.set_status(
                    "Offset must not be zero."
                )

                return

            if (
                angle_value < 1.0
                or angle_value > 90.0
            ):

                self.window.set_status(
                    "Angle must be between 1 and 90 degrees."
                )

                return

            selected_elements = (
                get_selected_mep_curves(
                    uidoc,
                    doc
                )
            )

            if not selected_elements:

                self.window.set_status(
                    "Select one or more split ducts, pipes, "
                    "cable trays or conduits."
                )

                return

            first_element = selected_elements[0]

            for selected_element in selected_elements:

                if not same_mep_class(
                    first_element,
                    selected_element
                ):

                    self.window.set_status(
                        "Select only one MEP category at a time."
                    )

                    return

            internal_offset = to_internal_units(
                doc,
                offset_value
            )

            transaction = Transaction(
                doc,
                "MMB MEP Up/Down"
            )

            transaction.Start()

            failure_options = (
                transaction.GetFailureHandlingOptions()
            )

            failure_options.SetFailuresPreprocessor(
                MEPFailurePreprocessor()
            )

            failure_options.SetClearAfterRollback(
                True
            )

            transaction.SetFailureHandlingOptions(
                failure_options
            )

            resulting_ids = apply_to_selected_group(
                doc,
                selected_elements,
                internal_offset,
                angle_value
            )

            transaction_status = (
                transaction.Commit()
            )

            if (
                transaction_status
                != TransactionStatus.Committed
            ):

                self.window.set_status(
                    "Revit could not commit the offset. "
                    "Check the fitting routing preferences."
                )

                return

            selected_result_ids = (
                List[ElementId]()
            )

            for element_id in resulting_ids:

                if doc.GetElement(element_id) is not None:

                    selected_result_ids.Add(
                        element_id
                    )

            uidoc.Selection.SetElementIds(
                selected_result_ids
            )

            self.window.set_status(
                "Applied successfully to {0} selected "
                "section(s).".format(
                    len(selected_elements)
                )
            )

        except Exception as exception:

            try:
                if (
                    transaction is not None
                    and transaction.HasStarted()
                ):
                    transaction.RollBack()

            except Exception:
                pass

            if self.window is not None:

                error_message = str(exception)

                if not error_message:

                    error_message = (
                        "Unable to create the offset."
                    )

                self.window.set_status(
                    "Failed: {0}".format(
                        error_message
                    )
                )

        finally:
            self.is_running = False

    def GetName(self):

        return "MMB MEP Up/Down Apply"


# ==========================================================
# PREVIEW EXTERNAL EVENT
# ==========================================================

class PreviewHandler(IExternalEventHandler):
    """
    Calculates the proposed geometry without changing the
    selected Revit elements.

    This handler provides a safe calculated preview in the
    UI. An exact translucent 3D representation requires a
    DirectContext3D rendering server.
    """

    def __init__(self):

        self.window = None
        self.offset_value = 0.0
        self.angle_value = 45.0
        self.is_running = False
        self.pending_request = False

    def Execute(self, application):

        if self.is_running:
            self.pending_request = True
            return

        self.is_running = True
        self.pending_request = False

        try:
            uidoc = application.ActiveUIDocument

            if uidoc is None:

                self.window.set_preview(
                    "No active Revit document."
                )

                return

            doc = uidoc.Document

            selected_elements = (
                get_selected_mep_curves(
                    uidoc,
                    doc
                )
            )

            if not selected_elements:

                self.window.set_preview(
                    "Select one or more split ducts, pipes, "
                    "cable trays or conduits."
                )

                return

            offset_value = float(
                self.offset_value
            )

            angle_value = float(
                self.angle_value
            )

            if abs(offset_value) <= TOLERANCE:

                self.window.set_preview(
                    "Offset: 0. Move the slider left or right."
                )

                return

            if (
                angle_value <= 0.0
                or angle_value > 90.0
            ):

                self.window.set_preview(
                    "Enter an angle greater than 0 and "
                    "up to 90 degrees."
                )

                return

            internal_offset = (
                to_internal_units(
                    doc,
                    offset_value
                )
            )

            actual_angle = abs(
                angle_value
            )

            if (
                abs(actual_angle - 90.0)
                <= TOLERANCE
            ):

                horizontal_run_internal = 0.0

            else:

                horizontal_run_internal = (
                    abs(internal_offset)
                    / math.tan(
                        math.radians(
                            actual_angle
                        )
                    )
                )

            # Convert the calculated horizontal run back to
            # the current project display unit.
            horizontal_run_display = (
                UnitUtils.ConvertFromInternalUnits(
                    horizontal_run_internal,
                    get_project_length_unit_id(doc)
                )
            )

            direction_text = (
                "Up"
                if offset_value > 0
                else "Down"
            )

            preview_message = (
                "{0} {1} at {2}°. "
                "Horizontal transition run: {3}. "
                "Selected sections: {4}."
            ).format(
                direction_text,
                self.window.format_numeric_value(
                    abs(offset_value)
                ),
                self.window.format_numeric_value(
                    actual_angle
                ),
                self.window.format_numeric_value(
                    horizontal_run_display
                ),
                len(selected_elements)
            )

            self.window.set_preview(
                preview_message
            )

        except Exception as exception:

            message = str(exception)

            if not message:
                message = "Unable to calculate preview."

            self.window.set_preview(
                "Preview unavailable: {0}".format(
                    message
                )
            )

        finally:
            self.is_running = False

            if self.pending_request:

                try:
                    self.pending_request = False
                    self.window.preview_event.Raise()
                except Exception:
                    pass

    def GetName(self):

        return "MMB MEP Up/Down Preview"


# ==========================================================
# MODELESS WINDOW
# ==========================================================

class UpDownWindow(forms.WPFWindow):

    SLIDER_MINIMUM = -10000.0
    SLIDER_MAXIMUM = 10000.0

    def __init__(self):

        self._updating_offset = True
        self._updating_angle = True

        forms.WPFWindow.__init__(
            self,
            "MEPUpDown.xaml"
        )

        # --------------------------------------------------
        # Apply event
        # --------------------------------------------------

        self.handler = ApplyHandler()
        self.handler.window = self

        self.external_event = ExternalEvent.Create(
            self.handler
        )

        # --------------------------------------------------
        # Preview event
        # --------------------------------------------------

        self.preview_handler = PreviewHandler()
        self.preview_handler.window = self

        self.preview_event = ExternalEvent.Create(
            self.preview_handler
        )

        # --------------------------------------------------
        # Initial slider settings
        # --------------------------------------------------

        self.offset_slider.Minimum = (
            self.SLIDER_MINIMUM
        )

        self.offset_slider.Maximum = (
            self.SLIDER_MAXIMUM
        )

        self.offset_slider.Value = 0.0

        self.negative_offset_box.Text = ""
        self.positive_offset_box.Text = "0"

        # --------------------------------------------------
        # Initial angle
        # --------------------------------------------------

        self.angle_box.Text = "45"

        self._selected_angle = 45.0

        self._updating_offset = False
        self._updating_angle = False

        self.highlight_angle_button(
            45.0
        )

    # ======================================================
    # DISPLAY HELPERS
    # ======================================================

    def set_status(self, text, is_error=False):

        self.status.Text = text

        try:
            if is_error:
                self.status.Foreground = (
                    self.FindResource(
                        "ErrorTextBrush"
                    )
                )
            else:
                self.status.Foreground = (
                    self.FindResource(
                        "NormalTextBrush"
                    )
                )
        except Exception:
            pass

    def set_preview(self, text):

        self.preview_text.Text = text

    def format_numeric_value(self, value):

        value = float(value)

        if (
            abs(value - round(value))
            <= TOLERANCE
        ):

            return str(
                int(round(value))
            )

        return (
            "{0:.3f}".format(value)
            .rstrip("0")
            .rstrip(".")
        )

    # ======================================================
    # OFFSET SYNCHRONISATION
    # ======================================================

    def clamp_to_slider(self, value):

        value = float(value)

        if value < self.offset_slider.Minimum:
            return self.offset_slider.Minimum

        if value > self.offset_slider.Maximum:
            return self.offset_slider.Maximum

        return value

    def get_offset_value(self):

        return float(
            self.offset_slider.Value
        )

    def update_offset_ui(self, value):

        if self._updating_offset:
            return

        self._updating_offset = True

        try:
            value = float(value)
            value = self.clamp_to_slider(value)

            self.offset_slider.Value = value

            formatted = self.format_numeric_value(
                value
            )

            self.current_offset_text.Text = (
                formatted
            )

            if value < 0.0:

                self.negative_offset_box.Text = (
                    self.format_numeric_value(
                        abs(value)
                    )
                )

                self.positive_offset_box.Text = ""

            elif value > 0.0:

                self.negative_offset_box.Text = ""

                self.positive_offset_box.Text = (
                    formatted
                )

            else:

                self.negative_offset_box.Text = ""
                self.positive_offset_box.Text = "0"

        finally:
            self._updating_offset = False

    def negative_offset_text_changed(
        self,
        sender,
        args
    ):

        if self._updating_offset:
            return

        text = sender.Text.strip()

        if text in ("", "-", ".", "-."):
            return

        try:
            value = -abs(float(text))

            self.update_offset_ui(value)

            self.request_preview()

        except Exception:

            self.set_status(
                "Enter a valid downward offset.",
                True
            )

    def positive_offset_text_changed(
        self,
        sender,
        args
    ):

        if self._updating_offset:
            return

        text = sender.Text.strip()

        if text in ("", "+", ".", "+."):
            return

        try:
            value = abs(float(text))

            self.update_offset_ui(value)

            self.request_preview()

        except Exception:

            self.set_status(
                "Enter a valid upward offset.",
                True
            )

    def offset_slider_value_changed(
        self,
        sender,
        args
    ):

        if self._updating_offset:
            return

        self.update_offset_ui(
            self.offset_slider.Value
        )

        # Do not call Revit continuously for every small
        # movement. The UI value updates immediately.
        self.set_preview(
            "Offset preview: {0}. Release the slider "
            "to calculate the transition.".format(
                self.format_numeric_value(
                    self.offset_slider.Value
                )
            )
        )

    def offset_slider_mouse_up(
        self,
        sender,
        args
    ):

        self.request_preview()

    # ======================================================
    # ANGLE CONTROLS
    # ======================================================

    def get_angle_value(self):

        angle = float(
            self.angle_box.Text.strip()
        )

        if angle <= 0.0 or angle > 90.0:

            raise ValueError(
                "Angle must be greater than 0 "
                "and no more than 90 degrees."
            )

        return angle

    def set_angle_value(self, angle):

        angle = float(angle)

        if angle <= 0.0 or angle > 90.0:
            return

        self._updating_angle = True

        try:
            self.angle_box.Text = (
                self.format_numeric_value(angle)
            )

            self._selected_angle = angle

            self.highlight_angle_button(
                angle
            )

        finally:
            self._updating_angle = False

        self.request_preview()

    def angle_preset_click(
        self,
        sender,
        args
    ):

        try:
            angle = float(sender.Tag)

            self.set_angle_value(angle)

        except Exception:

            self.set_status(
                "Unable to read the angle preset.",
                True
            )

    def angle_text_changed(
        self,
        sender,
        args
    ):

        if self._updating_angle:
            return

        text = sender.Text.strip()

        if text in ("", ".", "0."):
            return

        try:
            angle = float(text)

            if angle <= 0.0 or angle > 90.0:

                self.set_status(
                    "Custom angle must be greater than "
                    "0 and up to 90 degrees.",
                    True
                )

                return

            self._selected_angle = angle

            self.highlight_angle_button(
                angle
            )

            self.request_preview()

        except Exception:

            self.set_status(
                "Enter a valid custom angle.",
                True
            )

    def highlight_angle_button(self, angle):

        buttons = [
            (self.angle_30_button, 30.0),
            (self.angle_45_button, 45.0),
            (self.angle_60_button, 60.0),
            (self.angle_90_button, 90.0)
        ]

        for button, button_angle in buttons:

            if (
                abs(angle - button_angle)
                <= TOLERANCE
            ):

                button.Background = (
                    self.FindResource(
                        "SuccessTextBrush"
                    )
                )

                button.Foreground = (
                    self.FindResource(
                        "NormalTextBrush"
                    )
                )

            else:

                try:
                    from System.Windows.Media import (
                        Brushes
                    )

                    button.Background = (
                        Brushes.WhiteSmoke
                    )

                    button.Foreground = (
                        Brushes.Black
                    )

                except Exception:
                    pass

    # ======================================================
    # PREVIEW REQUEST
    # ======================================================

    def request_preview(self):

        try:
            offset = self.get_offset_value()
            angle = self.get_angle_value()

        except Exception as exception:

            self.set_preview(
                str(exception)
            )

            return

        self.preview_handler.offset_value = offset
        self.preview_handler.angle_value = angle

        try:
            self.preview_event.Raise()

        except Exception:
            pass

    # ======================================================
    # APPLY
    # ======================================================

    def apply_click(self, sender, args):

        if self.handler.is_running:
            return

        try:
            offset_value = self.get_offset_value()
            angle_value = self.get_angle_value()

        except Exception as exception:

            self.set_status(
                str(exception),
                True
            )

            return

        if abs(offset_value) <= TOLERANCE:

            self.set_status(
                "Offset must not be zero.",
                True
            )

            return

        self.handler.offset_text = str(
            offset_value
        )

        self.handler.angle_text = str(
            angle_value
        )

        self.status.Text = (
            "Applying to the current Revit selection..."
        )

        self.external_event.Raise()

    # ======================================================
    # CLOSE
    # ======================================================

    def close_click(self, sender, args):

        self.Close()


# ==========================================================
# START MODELESS WINDOW
# ==========================================================

window = UpDownWindow()
window.Show()