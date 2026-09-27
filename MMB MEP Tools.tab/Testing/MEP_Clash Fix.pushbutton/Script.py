# -*- coding: utf-8 -*-

# MMB MEP Tools
# MEP Clash Fix
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
MMB MEP Clash Fix
Modeless pyRevit tool for Revit 2023 and later.

Supported:
    - Pipe
    - Duct
    - Cable Tray
    - Conduit

Workflow:
    1. Open MEP Clash Fix.
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
    Color,
    ConnectorType,
    DirectShape,
    ElementId,
    ElementTransformUtils,
    FailureProcessingResult,
    FailureSeverity,
    FillPatternElement,
    FilteredElementCollector,
    ForgeTypeId,
    GeometryInstance,
    GeometryObject,
    IFailuresPreprocessor,
    Line,
    LocationCurve,
    Options,
    OverrideGraphicSettings,
    Solid,
    SolidUtils,
    Transaction,
    TransactionStatus,
    Transform,
    UnitUtils,
    ViewDetailLevel,
    ViewType,
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


__title__ = "MEP Clash Fix"
__author__ = "Govind Ranjith Kota"


SUPPORTED_CLASSES = (
    Pipe,
    Duct,
    Conduit,
    CableTray
)

TOLERANCE = 0.000001

PREVIEW_APPLICATION_ID = "MMB_MEP_CLASH_FIX_PREVIEW"
PREVIEW_DATA_ID = "MEP_CLASH_FIX_GHOST"
PREVIEW_RED = 60
PREVIEW_GREEN = 220
PREVIEW_BLUE = 235
PREVIEW_TRANSPARENCY = 72


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
# OFFSET MODE HELPERS
# ==========================================================

def get_curve_direction(element):
    """
    Returns the normalised direction of a supported
    straight MEP curve.
    """

    if not is_supported_curve(element):
        return None

    curve = element.Location.Curve

    start_point = curve.GetEndPoint(0)
    end_point = curve.GetEndPoint(1)

    direction = (
        end_point
        - start_point
    )

    if (
        direction.GetLength()
        <= TOLERANCE
    ):
        return None

    return direction.Normalize()


def find_collinear_curve_through_split_fitting(
    seed_element,
    seed_connector,
    original_selected_ids
):
    """
    Detects a union or inline fitting created by Revit's
    standard Split Element command.

    Returns the stationary curve on the opposite side and
    the split fitting that must be removed before changing
    the moving seed curve.
    """

    seed_direction = get_inward_direction(
        seed_element,
        seed_connector.Origin
    )

    for reference in get_physical_references(
        seed_connector
    ):

        fitting = reference.Owner

        if not is_supported_fitting(fitting):
            continue

        stationary_candidates = []

        for fitting_connector in get_connectors(
            fitting
        ):

            for fitting_reference in (
                get_physical_references(
                    fitting_connector
                )
            ):

                owner = fitting_reference.Owner

                if owner is None:
                    continue

                if owner.Id == seed_element.Id:
                    continue

                if not is_supported_curve(owner):
                    continue

                if not same_mep_class(
                    seed_element,
                    owner
                ):
                    continue

                owner_id_value = element_id_value(
                    owner.Id
                )

                if owner_id_value in original_selected_ids:
                    continue

                owner_direction = get_curve_direction(
                    owner
                )

                if owner_direction is None:
                    continue

                alignment = abs(
                    seed_direction.DotProduct(
                        owner_direction
                    )
                )

                # A split union should connect two essentially
                # collinear curve sections.
                if alignment < 0.98:
                    continue

                outer_connector = nearest_connector(
                    owner,
                    fitting_connector.Origin
                )

                stationary_candidates.append({
                    "selected_element_id":
                        seed_element.Id,

                    "selected_origin":
                        copy_xyz(
                            seed_connector.Origin
                        ),

                    "outer_element_id":
                        owner.Id,

                    "outer_origin":
                        copy_xyz(
                            outer_connector.Origin
                        ),

                    "boundary_fitting_id":
                        fitting.Id,

                    "alignment":
                        alignment,

                    "distance":
                        outer_connector.Origin.DistanceTo(
                            seed_connector.Origin
                        )
                })

        if stationary_candidates:

            stationary_candidates.sort(
                key=lambda item: (
                    item["distance"],
                    -item["alignment"]
                )
            )

            return stationary_candidates[0]

    return None


def find_one_point_split_from_seed(
    doc,
    seed_element,
    original_selected_ids
):
    """
    Finds the One Transition boundary from the manually
    selected seed curve.

    Priority:
        1. Direct same-class curve connection at a seed end.
        2. Coincident or nearby aligned curve endpoint.

    The directly connected opposite curve is treated as the
    stationary side. The network is expanded from the seed
    without crossing into that stationary curve.
    """

    if not is_supported_curve(seed_element):

        raise Exception(
            "One Transition requires a supported "
            "MEP curve as the selected seed."
        )

    seed_curve = seed_element.Location.Curve

    seed_direction = (
        seed_curve.GetEndPoint(1)
        - seed_curve.GetEndPoint(0)
    )

    if seed_direction.GetLength() <= TOLERANCE:

        raise Exception(
            "The selected seed curve has no valid direction."
        )

    seed_direction = seed_direction.Normalize()

    seed_connectors = get_connectors(
        seed_element
    )

    direct_candidates = []
    fitting_candidates = []

    # ======================================================
    # METHOD 1:
    # DIRECT CURVE-TO-CURVE CONNECTION
    # ======================================================

    for seed_connector in seed_connectors:

        seed_origin = copy_xyz(
            seed_connector.Origin
        )

        # ==================================================
        # SPLIT ELEMENT WITH UNION / INLINE FITTING
        # ==================================================

        fitting_boundary = (
            find_collinear_curve_through_split_fitting(
                seed_element,
                seed_connector,
                original_selected_ids
            )
        )

        if fitting_boundary is not None:

            fitting_candidates.append(
                fitting_boundary
            )

        for reference in get_physical_references(
            seed_connector
        ):

            owner = reference.Owner

            if not is_supported_curve(owner):
                continue

            if not same_mep_class(
                seed_element,
                owner
            ):
                continue

            owner_value = element_id_value(
                owner.Id
            )

            if owner_value in original_selected_ids:
                continue

            owner_curve = owner.Location.Curve

            owner_direction = (
                owner_curve.GetEndPoint(1)
                - owner_curve.GetEndPoint(0)
            )

            if (
                owner_direction.GetLength()
                <= TOLERANCE
            ):
                continue

            owner_direction = (
                owner_direction.Normalize()
            )

            alignment = abs(
                seed_direction.DotProduct(
                    owner_direction
                )
            )

            # The two split halves must be collinear.
            if alignment < 0.98:
                continue

            owner_connector = nearest_connector(
                owner,
                seed_origin
            )

            direct_candidates.append({
                "selected_element_id":
                    seed_element.Id,

                "selected_origin":
                    seed_origin,

                "outer_element_id":
                    owner.Id,

                "outer_origin":
                    copy_xyz(
                        owner_connector.Origin
                    ),

                "boundary_fitting_id":
                    ElementId.InvalidElementId,

                "alignment":
                    alignment,

                "distance":
                    owner_connector.Origin.DistanceTo(
                        seed_origin
                    )
            })
    # Prefer the fitting-based split created by Revit's
    # standard Split Element command.
    if fitting_candidates:

        fitting_candidates.sort(
            key=lambda item: (
                item["distance"],
                -item["alignment"]
            )
        )

        return fitting_candidates[0]
    if direct_candidates:

        direct_candidates.sort(
            key=lambda item: (
                item["distance"],
                -item["alignment"]
            )
        )

        return direct_candidates[0]

    # ======================================================
    # METHOD 2:
    # GEOMETRIC FALLBACK FOR SPLIT WITH GAP
    # ======================================================

    category_id = seed_element.Category.Id

    maximum_gap = 3.0
    lateral_tolerance = 0.10

    collector = (
        FilteredElementCollector(doc)
        .OfCategoryId(category_id)
        .WhereElementIsNotElementType()
    )

    best_boundary = None
    best_score = None

    for seed_connector in seed_connectors:

        seed_origin = copy_xyz(
            seed_connector.Origin
        )

        for candidate in collector:

            if not is_supported_curve(candidate):
                continue

            if candidate.Id == seed_element.Id:
                continue

            candidate_value = element_id_value(
                candidate.Id
            )

            if candidate_value in original_selected_ids:
                continue

            if not same_mep_class(
                seed_element,
                candidate
            ):
                continue

            candidate_curve = (
                candidate.Location.Curve
            )

            candidate_direction = (
                candidate_curve.GetEndPoint(1)
                - candidate_curve.GetEndPoint(0)
            )

            if (
                candidate_direction.GetLength()
                <= TOLERANCE
            ):
                continue

            candidate_direction = (
                candidate_direction.Normalize()
            )

            alignment = abs(
                seed_direction.DotProduct(
                    candidate_direction
                )
            )

            if alignment < 0.98:
                continue

            candidate_points = [
                candidate_curve.GetEndPoint(0),
                candidate_curve.GetEndPoint(1)
            ]

            for candidate_point in candidate_points:

                gap_vector = (
                    candidate_point
                    - seed_origin
                )

                gap_distance = (
                    gap_vector.GetLength()
                )

                if gap_distance > maximum_gap:
                    continue

                projection = (
                    gap_vector.DotProduct(
                        seed_direction
                    )
                )

                projected_vector = (
                    seed_direction.Multiply(
                        projection
                    )
                )

                lateral_vector = (
                    gap_vector
                    - projected_vector
                )

                lateral_distance = (
                    lateral_vector.GetLength()
                )

                if (
                    lateral_distance
                    > lateral_tolerance
                ):
                    continue

                score = (
                    gap_distance
                    + lateral_distance
                    + ((1.0 - alignment) * 10.0)
                )

                if (
                    best_score is None
                    or score < best_score
                ):

                    best_score = score

                    best_boundary = {
                        "selected_element_id":
                            seed_element.Id,

                        "selected_origin":
                            seed_origin,

                        "outer_element_id":
                            candidate.Id,

                        "outer_origin":
                            copy_xyz(
                                candidate_point
                            ),

                        "boundary_fitting_id":
                            ElementId.InvalidElementId
                    }

    if best_boundary is None:

        raise Exception(
            "One Transition could not identify the split "
            "from the selected seed. Select the first MEP "
            "curve immediately after the split on the side "
            "that must move."
        )

    return best_boundary


def resolve_boundaries_for_mode(
    doc,
    selected_elements,
    selected_ids,
    boundaries,
    offset_mode
):
    """
    Two Transition uses the existing two-boundary analysis.

    One Transition does not use this function. Its boundary
    must be detected from the manually selected seed before
    the downstream network is expanded.
    """

    if offset_mode == "two_point":

        if len(boundaries) != 2:

            raise Exception(
                "Two Transitions mode requires exactly "
                "two external boundaries. "
                "Boundaries found: {0}.".format(
                    len(boundaries)
                )
            )

        return boundaries

    if offset_mode == "one_point":

        raise Exception(
            "Internal error: One Transition boundary was "
            "not prepared from the selected seed curve."
        )

    raise Exception(
        "Unknown offset mode: {0}".format(
            offset_mode
        )
    )


# ==========================================================
# MULTIPLE-SELECTION AND MOVEMENT HELPERS
# ==========================================================
def get_connected_owners(element):
    """
    Returns physically connected external element owners.
    """

    connected_owners = []

    for connector in get_connectors(element):

        for reference in get_physical_references(
            connector
        ):

            owner = reference.Owner

            if owner is None:
                continue

            connected_owners.append(owner)

    return connected_owners

def expand_connected_network_from_seed(
    doc,
    seed_element,
    blocked_element_ids
):
    """
    Traverses the complete physically connected network from
    the manually selected seed.

    The stationary curve on the opposite side of the prepared
    split is blocked. Therefore, traversal cannot cross the
    One Transition boundary.

    Elbows, tees, branches and downstream MEP curves are
    included so the complete downstream branch moves together.
    """

    if not is_supported_curve(
        seed_element
    ):

        return [], []

    visited_ids = set()

    pending_elements = [
        seed_element
    ]

    collected_curves = {}
    collected_fittings = {}

    while pending_elements:

        current_element = (
            pending_elements.pop()
        )

        if current_element is None:
            continue

        current_id_value = element_id_value(
            current_element.Id
        )

        if (
            current_id_value
            in visited_ids
        ):
            continue

        if (
            current_id_value
            in blocked_element_ids
        ):
            continue

        visited_ids.add(
            current_id_value
        )

        if is_supported_curve(
            current_element
        ):

            if not same_mep_class(
                seed_element,
                current_element
            ):
                continue

            collected_curves[
                current_id_value
            ] = current_element

        elif is_supported_fitting(
            current_element
        ):

            collected_fittings[
                current_id_value
            ] = current_element

        else:
            continue

        connected_owners = (
            get_connected_owners(
                current_element
            )
        )

        for owner in connected_owners:

            if owner is None:
                continue

            owner_id_value = (
                element_id_value(
                    owner.Id
                )
            )

            if (
                owner_id_value
                in visited_ids
            ):
                continue

            if (
                owner_id_value
                in blocked_element_ids
            ):
                continue

            if is_supported_curve(owner):

                if same_mep_class(
                    seed_element,
                    owner
                ):

                    pending_elements.append(
                        owner
                    )

            elif is_supported_fitting(
                owner
            ):

                pending_elements.append(
                    owner
                )

    return (
        list(
            collected_curves.values()
        ),
        list(
            collected_fittings.values()
        )
    )

def expand_one_point_selection(
    doc,
    selected_elements
):
    """
    Prepares one complete downstream network for every
    manually selected seed curve.

    Processing order:

        1. Detect the split from the seed.
        2. Store the stationary opposite curve.
        3. Block the stationary curve.
        4. Traverse the complete downstream network.
        5. Return the downstream curves, fittings and the
           prepared One Transition boundary together.
    """

    original_selected_ids = create_id_set(
        selected_elements
    )

    prepared_groups = []

    processed_curve_ids = set()

    for seed_element in selected_elements:

        seed_id_value = element_id_value(
            seed_element.Id
        )

        # If this seed was already collected through another
        # selected seed, do not process the same network twice.
        if (
            seed_id_value
            in processed_curve_ids
        ):
            continue

        split_boundary = (
            find_one_point_split_from_seed(
                doc,
                seed_element,
                original_selected_ids
            )
        )

        stationary_element_id = (
            split_boundary[
                "outer_element_id"
            ]
        )

        if not id_is_valid(
            stationary_element_id
        ):

            raise Exception(
                "The stationary side of the One Transition "
                "split could not be identified."
            )

        blocked_element_ids = set([
            element_id_value(
                stationary_element_id
            )
        ])

        boundary_fitting_id = (
            split_boundary.get(
                "boundary_fitting_id"
            )
        )

        if id_is_valid(
            boundary_fitting_id
        ):

            blocked_element_ids.add(
                element_id_value(
                    boundary_fitting_id
                )
            )

        (
            downstream_curves,
            downstream_fittings
        ) = (
            expand_connected_network_from_seed(
                doc,
                seed_element,
                blocked_element_ids
            )
        )

        if not downstream_curves:

            raise Exception(
                "No downstream MEP network was found "
                "from the selected seed curve."
            )

        downstream_curve_ids = (
            create_id_set(
                downstream_curves
            )
        )

        processed_curve_ids.update(
            downstream_curve_ids
        )

        prepared_groups.append({
            "curves":
                downstream_curves,

            "fittings":
                downstream_fittings,

            "boundary":
                split_boundary
        })

    if not prepared_groups:

        raise Exception(
            "No valid One Transition downstream "
            "networks were prepared."
        )

    return prepared_groups


def split_selected_into_connected_groups(selected_elements):
    """
    Splits a mixed selection into independent connected MEP groups.
    Each group may contain Pipe, Duct, Conduit or CableTray curves, but a
    physical group naturally remains one category because Revit connectors
    do not directly connect unlike MEP curve categories.
    """
    selected_ids = create_id_set(selected_elements)
    by_id = dict(
        (element_id_value(element.Id), element)
        for element in selected_elements
    )
    adjacency = dict((value, set()) for value in by_id.keys())

    for element in selected_elements:
        source_id = element_id_value(element.Id)

        for connector in get_connectors(element):
            for reference in get_physical_references(connector):
                owner = reference.Owner
                owner_id = element_id_value(owner.Id)

                if owner_id in selected_ids:
                    adjacency[source_id].add(owner_id)
                    adjacency[owner_id].add(source_id)
                    continue

                if not is_supported_fitting(owner):
                    continue

                fitting_selected_ids = list(
                    get_selected_curves_connected_to_fitting(
                        owner,
                        selected_ids
                    )
                )

                for first_id in fitting_selected_ids:
                    for second_id in fitting_selected_ids:
                        if first_id != second_id:
                            adjacency[first_id].add(second_id)

    groups = []
    visited = set()

    for start_id in by_id.keys():
        if start_id in visited:
            continue

        stack = [start_id]
        visited.add(start_id)
        group = []

        while stack:
            current_id = stack.pop()
            group.append(by_id[current_id])

            for neighbour_id in adjacency[current_id]:
                if neighbour_id not in visited:
                    visited.add(neighbour_id)
                    stack.append(neighbour_id)

        groups.append(group)

    return groups


def get_group_move_vector(
    selected_elements,
    boundaries,
    offset,
    movement_mode
):
    """
    Up/Down uses global Z. Left/Right uses the horizontal right-hand normal
    of the selected group at its first processed split boundary.

    Positive offset:
        Up in Up/Down mode
        Right in Left/Right mode
    Negative offset:
        Down in Up/Down mode
        Left in Left/Right mode
    """
    if movement_mode == "up_down":
        return XYZ(0.0, 0.0, offset)

    if movement_mode != "left_right":
        raise Exception(
            "Unknown movement mode: {0}".format(movement_mode)
        )

    if not boundaries:
        raise Exception(
            "No valid split boundary was found for Left/Right mode."
        )

    reference_boundary = boundaries[0]
    reference_element = None

    for element in selected_elements:
        if element.Id == reference_boundary["selected_element_id"]:
            reference_element = element
            break

    if reference_element is None:
        raise Exception(
            "Unable to determine the Left/Right reference element."
        )

    inward = get_inward_direction(
        reference_element,
        reference_boundary["selected_origin"]
    )

    plan_direction = XYZ(inward.X, inward.Y, 0.0)

    if plan_direction.GetLength() <= TOLERANCE:
        raise Exception(
            "Left/Right mode is not supported for a vertical MEP section."
        )

    plan_direction = plan_direction.Normalize()

    # Right-hand perpendicular in plan when looking from the split boundary
    # towards the selected group.
    right_direction = XYZ(
        plan_direction.Y,
        -plan_direction.X,
        0.0
    )

    return right_direction.Multiply(offset)


def validate_group_for_movement(
    selected_elements,
    boundaries,
    movement_mode
):
    """Validates that one connected group contains one MEP category."""
    first_element = selected_elements[0]

    for selected_element in selected_elements:
        if not same_mep_class(first_element, selected_element):
            raise Exception(
                "Connected groups cannot mix MEP categories."
            )

    if movement_mode == "left_right" and len(boundaries) == 2:
        first_element = None
        second_element = None

        for element in selected_elements:
            if element.Id == boundaries[0]["selected_element_id"]:
                first_element = element
            if element.Id == boundaries[1]["selected_element_id"]:
                second_element = element

        if first_element is not None and second_element is not None:
            first_direction = get_inward_direction(
                first_element,
                boundaries[0]["selected_origin"]
            )
            second_direction = get_inward_direction(
                second_element,
                boundaries[1]["selected_origin"]
            )

            first_plan = XYZ(
                first_direction.X,
                first_direction.Y,
                0.0
            )
            second_plan = XYZ(
                second_direction.X,
                second_direction.Y,
                0.0
            )

            if (
                first_plan.GetLength() > TOLERANCE
                and second_plan.GetLength() > TOLERANCE
            ):
                alignment = abs(
                    first_plan.Normalize().DotProduct(
                        second_plan.Normalize()
                    )
                )

                if alignment < 0.98:
                    raise Exception(
                        "Left/Right Two Point mode requires the two boundary "
                        "runs to be parallel."
                    )


# ==========================================================
# GROUP OFFSET OPERATION
# ==========================================================

def apply_to_selected_group(
    doc,
    selected_elements,
    offset,
    angle,
    offset_mode,
    movement_mode,
    prepared_boundary=None,
    prepared_fittings=None
):
    """Applies one offset operation to one connected MEP group."""

    selected_ids = create_id_set(
        selected_elements
    )

    # ======================================================
    # ONE TRANSITION
    # ======================================================

    if offset_mode == "one_point":

        if prepared_boundary is None:

            raise Exception(
                "One Transition boundary was not prepared "
                "from the selected seed curve."
            )

        boundaries = [
            dict(
                prepared_boundary
            )
        ]

        if prepared_fittings is not None:

            internal_fittings = list(
                prepared_fittings
            )

        else:

            internal_fittings = (
                find_internal_fittings(
                    selected_elements,
                    selected_ids
                )
            )

    # ======================================================
    # TWO TRANSITIONS
    # ======================================================

    else:

        internal_fittings = (
            find_internal_fittings(
                selected_elements,
                selected_ids
            )
        )

        internal_fitting_ids = (
            create_id_set(
                internal_fittings
            )
        )

        boundaries = find_group_boundaries(
            selected_elements,
            selected_ids,
            internal_fitting_ids
        )

        boundaries = resolve_boundaries_for_mode(
            doc,
            selected_elements,
            selected_ids,
            boundaries,
            offset_mode
        )

    validate_group_for_movement(
        selected_elements,
        boundaries,
        movement_mode
    )

    if abs(angle - 90.0) <= TOLERANCE:
        transition_run = 0.0
    else:
        transition_run = (
            abs(offset)
            / math.tan(math.radians(angle))
        )

    movement_vector = get_group_move_vector(
        selected_elements,
        boundaries,
        offset,
        movement_mode
    )

    boundary_data = []
    boundary_fitting_values = set()

    for boundary in boundaries:
        boundary_data.append({
            "selected_element_id": boundary["selected_element_id"],
            "selected_origin": copy_xyz(boundary["selected_origin"]),
            "outer_element_id": boundary["outer_element_id"],
            "outer_origin": (
                copy_xyz(boundary["outer_origin"])
                if boundary["outer_origin"] is not None
                else None
            ),
            "boundary_fitting_id": boundary["boundary_fitting_id"]
        })

        boundary_fitting_id = boundary["boundary_fitting_id"]

        if id_is_valid(boundary_fitting_id):
            boundary_fitting_values.add(
                element_id_value(boundary_fitting_id)
            )

    delete_ids = List[ElementId]()

    for fitting_value in boundary_fitting_values:
        fitting_id = make_element_id(fitting_value)

        if doc.GetElement(fitting_id) is not None:
            delete_ids.Add(fitting_id)

    if delete_ids.Count > 0:
        doc.Delete(delete_ids)

    doc.Regenerate()

    for data in boundary_data:

        if not id_is_valid(
            data["outer_element_id"]
        ):
            continue

        # If a split union or inline fitting existed, it was
        # deleted above. Deleting it disconnects the two curves.
        if id_is_valid(
            data["boundary_fitting_id"]
        ):
            continue

        selected_element = doc.GetElement(
            data["selected_element_id"]
        )

        outer_element = doc.GetElement(
            data["outer_element_id"]
        )

        if (
            selected_element is None
            or outer_element is None
        ):
            continue

        disconnect_connectors(
            nearest_connector(
                selected_element,
                data["selected_origin"]
            ),
            nearest_connector(
                outer_element,
                data["outer_origin"]
            )
        )

    doc.Regenerate()
    # ======================================================
    # SHORTEN THE MOVING BOUNDARY CURVE
    # ======================================================

    for data in boundary_data:

        selected_element = doc.GetElement(
            data["selected_element_id"]
        )

        if selected_element is None:

            raise Exception(
                "A selected boundary element no longer exists."
            )

        data["shortened_point"] = (
            shorten_boundary_curve(
                selected_element,
                data["selected_origin"],
                transition_run
            )
        )

    doc.Regenerate()
    move_ids = List[ElementId]()
    added_ids = set()

    for element in list(selected_elements) + list(internal_fittings):
        current_element = doc.GetElement(element.Id)

        if current_element is None:
            continue

        current_value = element_id_value(current_element.Id)

        if current_value not in added_ids:
            move_ids.Add(current_element.Id)
            added_ids.add(current_value)

    if move_ids.Count == 0:
        raise Exception(
            "No valid selected elements were found to move."
        )

    ElementTransformUtils.MoveElements(
        doc,
        move_ids,
        movement_vector
    )

    doc.Regenerate()

    resulting_ids = []

    for element_id in move_ids:
        if doc.GetElement(element_id) is not None:
            resulting_ids.append(element_id)

    for data in boundary_data:
        selected_element = doc.GetElement(
            data["selected_element_id"]
        )

        if selected_element is None:
            raise Exception(
                "The moved boundary element no longer exists."
            )

        original_point = data["selected_origin"]
        moved_shortened_point = (
            data["shortened_point"]
            + movement_vector
        )

        transition = create_curve_like(
            doc,
            selected_element,
            original_point,
            moved_shortened_point
        )

        doc.Regenerate()

        doc.Create.NewElbowFitting(
            nearest_connector(
                transition,
                moved_shortened_point
            ),
            nearest_connector(
                selected_element,
                moved_shortened_point
            )
        )

        doc.Regenerate()

        if id_is_valid(data["outer_element_id"]):
            outer_element = doc.GetElement(
                data["outer_element_id"]
            )

            if outer_element is None:
                raise Exception(
                    "The outer MEP element no longer exists."
                )

            doc.Create.NewElbowFitting(
                nearest_connector(
                    outer_element,
                    data["outer_origin"]
                ),
                nearest_connector(
                    transition,
                    original_point
                )
            )

            doc.Regenerate()

        resulting_ids.append(transition.Id)

    return resulting_ids


def apply_to_all_selected_groups(
    doc,
    selected_elements,
    offset,
    angle,
    offset_mode,
    movement_mode
):
    """
    Two Transitions processes the explicit user-selected
    groups.

    One Transition detects a split from every selected seed,
    expands the complete network after that split and passes
    the prepared split boundary directly to Apply.
    """

    resulting_ids = []

    # ======================================================
    # ONE TRANSITION
    # ======================================================

    if offset_mode == "one_point":

        prepared_groups = (
            expand_one_point_selection(
                doc,
                selected_elements
            )
        )

        for (
            group_index,
            prepared_group
        ) in enumerate(
            prepared_groups
        ):

            try:

                group_result_ids = (
                    apply_to_selected_group(
                        doc,
                        prepared_group[
                            "curves"
                        ],
                        offset,
                        angle,
                        offset_mode,
                        movement_mode,
                        prepared_group[
                            "boundary"
                        ],
                        prepared_group[
                            "fittings"
                        ]
                    )
                )

                resulting_ids.extend(
                    group_result_ids
                )

            except Exception as exception:

                raise Exception(
                    "Group {0} failed: {1}".format(
                        group_index + 1,
                        str(exception)
                    )
                )

        return (
            resulting_ids,
            len(prepared_groups)
        )

    # ======================================================
    # TWO TRANSITIONS
    # ======================================================

    groups = (
        split_selected_into_connected_groups(
            selected_elements
        )
    )

    for group_index, group in enumerate(
        groups
    ):

        try:

            group_result_ids = (
                apply_to_selected_group(
                    doc,
                    group,
                    offset,
                    angle,
                    offset_mode,
                    movement_mode
                )
            )

            resulting_ids.extend(
                group_result_ids
            )

        except Exception as exception:

            raise Exception(
                "Group {0} failed: {1}".format(
                    group_index + 1,
                    str(exception)
                )
            )

    return resulting_ids, len(groups)


# ==========================================================
# CYAN DIRECTSHAPE PREVIEW HELPERS
# ==========================================================

def delete_preview_elements(doc):
    """Deletes all cyan ghost elements created by this command."""
    ids = List[ElementId]()

    for element in FilteredElementCollector(doc).OfClass(DirectShape):
        try:
            if element.ApplicationId == PREVIEW_APPLICATION_ID:
                ids.Add(element.Id)
        except Exception:
            pass

    if ids.Count > 0:
        doc.Delete(ids)


def get_element_solids(element):
    """Returns visible solids from MEP curves and family fittings."""
    options = Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False
    options.DetailLevel = ViewDetailLevel.Fine

    geometry = element.get_Geometry(options)
    solids = []

    if geometry is None:
        return solids

    for geometry_object in geometry:
        if isinstance(geometry_object, Solid):
            if geometry_object.Volume > TOLERANCE:
                solids.append(geometry_object)

        elif isinstance(geometry_object, GeometryInstance):
            for nested_object in geometry_object.GetInstanceGeometry():
                if isinstance(nested_object, Solid):
                    if nested_object.Volume > TOLERANCE:
                        solids.append(nested_object)

    return solids


def get_solid_fill_pattern_id(doc):
    for pattern_element in FilteredElementCollector(doc).OfClass(
        FillPatternElement
    ):
        try:
            if pattern_element.GetFillPattern().IsSolidFill:
                return pattern_element.Id
        except Exception:
            pass

    return ElementId.InvalidElementId


def create_preview_directshape(doc, solids):
    if not solids:
        return None

    preview = DirectShape.CreateElement(
        doc,
        ElementId(BuiltInCategory.OST_GenericModel)
    )

    preview.ApplicationId = PREVIEW_APPLICATION_ID
    preview.ApplicationDataId = PREVIEW_DATA_ID

    shape_objects = List[GeometryObject]()

    for solid in solids:
        shape_objects.Add(solid)

    preview.SetShape(shape_objects)
    return preview


def apply_preview_graphics(doc, view, preview):
    if preview is None:
        return

    colour = Color(
        PREVIEW_RED,
        PREVIEW_GREEN,
        PREVIEW_BLUE
    )

    settings = OverrideGraphicSettings()
    settings.SetProjectionLineColor(colour)
    settings.SetSurfaceTransparency(PREVIEW_TRANSPARENCY)

    solid_fill_id = get_solid_fill_pattern_id(doc)

    if id_is_valid(solid_fill_id):
        try:
            settings.SetSurfaceForegroundPatternId(solid_fill_id)
            settings.SetSurfaceForegroundPatternColor(colour)
        except Exception:
            pass

    view.SetElementOverrides(preview.Id, settings)


def create_group_preview(
    doc,
    view,
    selected_curves,
    internal_fittings,
    movement_vector
):
    """Creates one cyan DirectShape for one selected connected group."""
    transform = Transform.CreateTranslation(movement_vector)
    transformed_solids = []

    for element in list(selected_curves) + list(internal_fittings):
        for solid in get_element_solids(element):
            try:
                transformed_solids.append(
                    SolidUtils.CreateTransformed(
                        solid,
                        transform
                    )
                )
            except Exception:
                pass

    preview = create_preview_directshape(
        doc,
        transformed_solids
    )
    apply_preview_graphics(doc, view, preview)
    return preview


def create_all_group_previews(
    doc,
    view,
    selected_elements,
    offset,
    angle,
    offset_mode,
    movement_mode
):
    """
    Creates a cyan preview of the complete moving network.

    One Transition uses the same prepared seed boundary and
    downstream network as Apply.

    Two Transitions retains the explicit-selection preview.
    """

    # ======================================================
    # ONE TRANSITION
    # ======================================================

    if offset_mode == "one_point":

        prepared_groups = (
            expand_one_point_selection(
                doc,
                selected_elements
            )
        )

        for (
            group_index,
            prepared_group
        ) in enumerate(
            prepared_groups
        ):

            group = prepared_group[
                "curves"
            ]

            internal_fittings = (
                prepared_group[
                    "fittings"
                ]
            )

            boundaries = [
                dict(
                    prepared_group[
                        "boundary"
                    ]
                )
            ]

            validate_group_for_movement(
                group,
                boundaries,
                movement_mode
            )

            movement_vector = (
                get_group_move_vector(
                    group,
                    boundaries,
                    offset,
                    movement_mode
                )
            )

            preview = create_group_preview(
                doc,
                view,
                group,
                internal_fittings,
                movement_vector
            )

            if preview is None:

                raise Exception(
                    "No preview geometry was found "
                    "for downstream group {0}.".format(
                        group_index + 1
                    )
                )

        return len(
            prepared_groups
        )

    # ======================================================
    # TWO TRANSITIONS
    # ======================================================

    groups = (
        split_selected_into_connected_groups(
            selected_elements
        )
    )

    created_count = 0

    for group_index, group in enumerate(
        groups
    ):

        selected_ids = create_id_set(
            group
        )

        internal_fittings = (
            find_internal_fittings(
                group,
                selected_ids
            )
        )

        internal_fitting_ids = (
            create_id_set(
                internal_fittings
            )
        )

        boundaries = find_group_boundaries(
            group,
            selected_ids,
            internal_fitting_ids
        )

        boundaries = resolve_boundaries_for_mode(
            doc,
            group,
            selected_ids,
            boundaries,
            offset_mode
        )

        validate_group_for_movement(
            group,
            boundaries,
            movement_mode
        )

        movement_vector = (
            get_group_move_vector(
                group,
                boundaries,
                offset,
                movement_mode
            )
        )

        preview = create_group_preview(
            doc,
            view,
            group,
            internal_fittings,
            movement_vector
        )

        if preview is None:

            raise Exception(
                "No preview geometry was found "
                "for group {0}.".format(
                    group_index + 1
                )
            )

        created_count += 1

    return created_count


# ==========================================================
# EXTERNAL EVENT HANDLER
# ==========================================================

class ApplyHandler(IExternalEventHandler):

    def __init__(self):

        self.offset_text = ""
        self.angle_text = ""
        self.offset_mode = "two_point"
        self.movement_mode = "up_down"
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

            internal_offset = to_internal_units(
                doc,
                offset_value
            )

            transaction = Transaction(
                doc,
                "MMB MEP Clash Fix"
            )

            transaction.Start()

            # Remove cyan preview before creating permanent MEP geometry.
            delete_preview_elements(doc)
            doc.Regenerate()

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

            resulting_ids, group_count = apply_to_all_selected_groups(
                doc,
                selected_elements,
                internal_offset,
                angle_value,
                self.offset_mode,
                self.movement_mode
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
                "Applied successfully to {0} section(s) in "
                "{1} group(s).".format(
                    len(selected_elements),
                    group_count
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

        return "MMB MEP Clash Fix Apply"


# ==========================================================
# PREVIEW EXTERNAL EVENT
# ==========================================================

class PreviewHandler(IExternalEventHandler):
    """
    Creates a cyan translucent DirectShape ghost of selected MEP curves and
    internal fittings at the proposed elevation. The real MEP group is not
    moved during preview.
    """

    def __init__(self):
        self.window = None
        self.offset_value = 0.0
        self.angle_value = 45.0
        self.offset_mode = "two_point"
        self.movement_mode = "up_down"
        self.is_running = False
        self.pending_request = False

    def Execute(self, application):
        if self.is_running:
            self.pending_request = True
            return

        self.is_running = True
        self.pending_request = False
        transaction = None

        try:
            uidoc = application.ActiveUIDocument

            if uidoc is None:
                self.window.set_preview("No active Revit document.")
                return

            doc = uidoc.Document
            view = doc.ActiveView

            if view is None or view.ViewType == ViewType.DrawingSheet:
                self.window.set_preview(
                    "Open a model view to display the cyan preview."
                )
                return

            offset_value = float(self.offset_value)
            angle_value = float(self.angle_value)

            transaction = Transaction(
                doc,
                "MMB MEP Clash Fix Preview"
            )
            transaction.Start()

            # Replace the previous ghost rather than accumulating previews.
            delete_preview_elements(doc)

            if abs(offset_value) <= TOLERANCE:
                transaction.Commit()
                self.window.set_preview(
                    "Offset: 0. Move the slider left or right."
                )
                try:
                    uidoc.RefreshActiveView()
                except Exception:
                    pass
                return

            if angle_value <= 0.0 or angle_value > 90.0:
                transaction.Commit()
                self.window.set_preview(
                    "Enter an angle greater than 0 and up to 90 degrees."
                )
                return

            selected_elements = get_selected_mep_curves(uidoc, doc)

            if not selected_elements:
                transaction.Commit()
                self.window.set_preview(
                    "Select one or more split ducts, pipes, cable trays "
                    "or conduits."
                )
                return

            internal_offset = to_internal_units(doc, offset_value)

            preview_group_count = create_all_group_previews(
                doc,
                view,
                selected_elements,
                internal_offset,
                angle_value,
                self.offset_mode,
                self.movement_mode
            )

            transaction.Commit()

            run = 0.0

            if abs(angle_value - 90.0) > TOLERANCE:
                run = (
                    abs(offset_value)
                    / math.tan(math.radians(angle_value))
                )

            mode_text = (
                "One Point"
                if self.offset_mode == "one_point"
                else "Two Point"
            )

            if self.movement_mode == "left_right":
                direction_text = (
                    "Right" if offset_value > 0.0 else "Left"
                )
                movement_text = "Side Offset"
            else:
                direction_text = (
                    "Up" if offset_value > 0.0 else "Down"
                )
                movement_text = "Up / Down Offset"

            self.window.set_preview(
                "{0}, {1}: cyan {2} preview {3} at {4} deg. "
                "Transition run: {5}. {6} section(s), {7} group(s).".format(
                    movement_text,
                    mode_text,
                    direction_text,
                    self.window.format_offset_value(abs(offset_value)),
                    self.window.format_angle_value(angle_value),
                    self.window.format_offset_value(run),
                    len(selected_elements),
                    preview_group_count
                )
            )

            try:
                uidoc.RefreshActiveView()
            except Exception:
                pass

        except Exception as exception:
            try:
                if transaction is not None and transaction.HasStarted():
                    transaction.RollBack()
            except Exception:
                pass

            message = str(exception)

            if not message:
                message = "Unable to create cyan preview."

            self.window.set_preview(
                "Preview unavailable: {0}".format(message)
            )

        finally:
            self.is_running = False

            if self.pending_request:
                self.pending_request = False

                try:
                    self.window.preview_event.Raise()
                except Exception:
                    pass

    def GetName(self):
        return "MMB MEP Clash Fix Cyan Preview"


class ClearPreviewHandler(IExternalEventHandler):
    def Execute(self, application):
        transaction = None

        try:
            uidoc = application.ActiveUIDocument

            if uidoc is None:
                return

            doc = uidoc.Document

            transaction = Transaction(
                doc,
                "Clear MEP Clash Fix Preview"
            )
            transaction.Start()

            delete_preview_elements(doc)

            transaction.Commit()

            try:
                uidoc.RefreshActiveView()
            except Exception:
                pass

        except Exception:
            try:
                if transaction is not None and transaction.HasStarted():
                    transaction.RollBack()
            except Exception:
                pass

    def GetName(self):
        return "Clear MMB MEP Clash Fix Preview"


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

        self.clear_preview_handler = ClearPreviewHandler()
        self.clear_preview_event = ExternalEvent.Create(
            self.clear_preview_handler
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

        self.update_mode_text()
        self.highlight_movement_button()
        self.update_direction_labels()

    # ======================================================
    # MOVEMENT MODE
    # ======================================================

    def get_movement_mode(self):
        return getattr(self, "_movement_mode", "up_down")

    def movement_up_down_click(self, sender, args):
        self._movement_mode = "up_down"
        self.highlight_movement_button()
        self.update_direction_labels()
        self.request_preview()

    def movement_left_right_click(self, sender, args):
        self._movement_mode = "left_right"
        self.highlight_movement_button()
        self.update_direction_labels()
        self.request_preview()

    def highlight_movement_button(self):
        try:
            from System.Windows.Media import Brushes

            selected_brush = Brushes.LightGreen
            normal_brush = Brushes.WhiteSmoke

            if self.get_movement_mode() == "left_right":
                self.left_right_button.Background = selected_brush
                self.up_down_button.Background = normal_brush
            else:
                self.up_down_button.Background = selected_brush
                self.left_right_button.Background = normal_brush
        except Exception:
            pass

    def update_direction_labels(self):
        try:
            if self.get_movement_mode() == "left_right":
                self.negative_direction_label.Text = "Left"
                self.positive_direction_label.Text = "Right"
            else:
                self.negative_direction_label.Text = "Down"
                self.positive_direction_label.Text = "Up"
        except Exception:
            pass

    # ======================================================
    # OFFSET MODE
    # ======================================================

    def get_offset_mode(self):
        try:
            if self.one_point_mode.IsChecked:
                return "one_point"
        except Exception:
            pass

        return "two_point"

    def update_mode_text(self):
        if self.get_offset_mode() == "one_point":
            self.set_preview(
                "One Point mode: split once and select the side that must move."
            )
        else:
            self.set_preview(
                "Two Point mode: split twice and select the middle group."
            )

    def offset_mode_changed(self, sender, args):
        if not hasattr(self, "preview_handler"):
            return

        self.handler.offset_mode = self.get_offset_mode()
        self.preview_handler.offset_mode = self.get_offset_mode()
        self.handler.movement_mode = self.get_movement_mode()
        self.preview_handler.movement_mode = self.get_movement_mode()
        self.update_mode_text()
        self.request_preview()

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

    def format_offset_value(self, value):
        """Displays offsets and transition runs as whole project units."""

        return str(
            int(round(float(value)))
        )

    def format_angle_value(self, value):
        """Displays angles with up to one decimal place."""

        value = float(value)

        return (
            "{0:.1f}".format(value)
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

            formatted = self.format_offset_value(
                value
            )

            self.current_offset_text.Text = (
                formatted
            )

            if value < 0.0:

                self.negative_offset_box.Text = (
                    self.format_offset_value(
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
                self.format_offset_value(
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
                self.format_angle_value(angle)
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
        self.preview_handler.offset_mode = self.get_offset_mode()
        self.preview_handler.movement_mode = self.get_movement_mode()

        try:
            result = self.preview_event.Raise()

            if str(result) == "Pending":
                self.preview_handler.pending_request = True

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

        self.handler.offset_mode = self.get_offset_mode()
        self.handler.movement_mode = self.get_movement_mode()

        self.status.Text = (
            "Applying to the current Revit selection..."
        )

        self.external_event.Raise()

    # ======================================================
    # CLOSE
    # ======================================================

    def close_click(self, sender, args):

        try:
            self.clear_preview_event.Raise()
        except Exception:
            pass

        self.Close()


# ==========================================================
# START MODELESS WINDOW
# ==========================================================

window = UpDownWindow()
window.Show()