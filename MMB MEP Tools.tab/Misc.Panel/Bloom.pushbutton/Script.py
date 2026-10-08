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
    FilteredElementCollector,
    Level,
    Domain,
    ConnectorProfileType,
    BuiltInCategory,
    ElementId
)

from Autodesk.Revit.DB.Mechanical import (
    Duct,
    DuctType
)

from Autodesk.Revit.DB.Plumbing import (
    Pipe,
    PipeType
)

from Autodesk.Revit.DB.Electrical import (
    Conduit,
    ConduitType,
    CableTray,
    CableTrayType
)

from Autodesk.Revit.UI.Selection import ObjectType


doc = revit.doc
uidoc = revit.uidoc


# =====================================================
# SETTINGS
# =====================================================

STUB_LENGTH = UnitUtils.ConvertToInternalUnits(
    1000.0,
    UnitTypeId.Millimeters
)


# =====================================================
# BASIC HELPERS
# =====================================================

def first_element(cls):
    elems = list(
        FilteredElementCollector(doc)
        .OfClass(cls)
        .ToElements()
    )

    return elems[0] if elems else None


def get_nearest_level(z):
    levels = list(
        FilteredElementCollector(doc)
        .OfClass(Level)
        .ToElements()
    )

    if not levels:
        return None

    return min(
        levels,
        key=lambda x: abs(x.Elevation - z)
    )


def get_connector_manager(elem):
    try:
        if elem.MEPModel:
            return elem.MEPModel.ConnectorManager
    except:
        pass

    try:
        return elem.ConnectorManager
    except:
        pass

    return None


def get_open_connectors(elem):
    cm = get_connector_manager(elem)

    if not cm:
        return []

    result = []

    for c in cm.Connectors:
        try:
            if not c.IsConnected:
                result.append(c)
        except:
            pass

    return result


def get_all_connectors(elem):
    cm = get_connector_manager(elem)

    if not cm:
        return []

    result = []

    try:
        for c in cm.Connectors:
            result.append(c)
    except:
        pass

    return result


def get_direction(conn):
    try:
        vec = conn.CoordinateSystem.BasisZ

        if vec and vec.GetLength() > 0.0001:
            return vec.Normalize()
    except:
        pass

    return XYZ.BasisX


def get_closest_connector(elem, point):
    cm = get_connector_manager(elem)

    if not cm:
        return None

    conns = list(cm.Connectors)

    if not conns:
        return None

    return min(
        conns,
        key=lambda c: c.Origin.DistanceTo(point)
    )


def is_valid_connector_for_curve(conn):
    try:
        if conn is None:
            return False

        if conn.Origin is None:
            return False

        return True
    except:
        return False


def bic_int(name):
    try:
        value = getattr(BuiltInCategory, name)

        try:
            return value.value__
        except:
            return int(value)

    except:
        return None


def get_category_int(elem):
    try:
        if elem and elem.Category:
            return elem.Category.Id.IntegerValue
    except:
        pass

    return None

def is_category(elem, bic):
    try:
        if not elem:
            return False

        if not elem.Category:
            return False

        return elem.Category.Id == ElementId(bic)

    except:
        return False
        
        
def make_category_set(names):
    result = set()

    for name in names:
        value = bic_int(name)

        if value is not None:
            result.add(value)

    return result


# =====================================================
# CATEGORY SETS
# =====================================================

DUCT_CATEGORIES = make_category_set([
    "OST_DuctCurves",
    "OST_FlexDuctCurves",
    "OST_DuctFitting",
    "OST_DuctAccessory",
    "OST_DuctTerminal",
    "OST_AirTerminals",
    "OST_MechanicalEquipment"
])

PIPE_CATEGORIES = make_category_set([
    "OST_PipeCurves",
    "OST_FlexPipeCurves",
    "OST_PipeFitting",
    "OST_PipeAccessory",
    "OST_PlumbingFixtures",
    "OST_Sprinklers",
    "OST_MechanicalEquipment"
])

CABLETRAY_CATEGORIES = make_category_set([
    "OST_CableTray",
    "OST_CableTrayFitting",
    "OST_CableTrayRun",
    "OST_CableTrayAccessory"
])

CONDUIT_CATEGORIES = make_category_set([
    "OST_Conduit",
    "OST_ConduitFitting",
    "OST_ConduitRun"
])


# =====================================================
# CONNECTED CURVE TYPE HELPERS
# =====================================================

def get_type_from_owner_if_curve(conn, curve_cls):
    try:
        owner = conn.Owner

        if isinstance(owner, curve_cls):
            return doc.GetElement(owner.GetTypeId())

    except:
        pass

    return None


def get_connected_curve_type_from_owner_connectors(conn, curve_cls):
    """
    Useful for fittings, accessories, terminals and equipment.
    If selected connector is on a fitting, check all connectors of the same owner.
    If any connector is connected to a Duct/Pipe/CableTray/Conduit, use that curve type.
    """

    try:
        owner = conn.Owner

        if not owner:
            return None

        owner_id = owner.Id.IntegerValue

        owner_connectors = get_all_connectors(owner)

        for own_conn in owner_connectors:
            try:
                for ref_conn in own_conn.AllRefs:
                    try:
                        ref_owner = ref_conn.Owner

                        if not ref_owner:
                            continue

                        if ref_owner.Id.IntegerValue == owner_id:
                            continue

                        if isinstance(ref_owner, curve_cls):
                            return doc.GetElement(ref_owner.GetTypeId())

                    except:
                        pass

            except:
                pass

    except:
        pass

    return None


# =====================================================
# DUCT TYPE MATCHING
# =====================================================

def duct_type_shape_matches(duct_type, conn):
    try:
        if duct_type.Shape == conn.Shape:
            return True
    except:
        pass

    try:
        shape = conn.Shape
        name = ""

        try:
            name += duct_type.FamilyName.lower()
        except:
            pass

        try:
            name += " " + duct_type.Name.lower()
        except:
            pass

        if shape == ConnectorProfileType.Round:
            if "round" in name:
                return True

        elif shape == ConnectorProfileType.Rectangular:
            if "rect" in name:
                return True

        elif shape == ConnectorProfileType.Oval:
            if "oval" in name:
                return True

    except:
        pass

    return False


def get_duct_type_for_connector(conn):
    """
    Priority:
    1. If owner is duct, use same duct type.
    2. If owner fitting/accessory/equipment is connected to a duct elsewhere, use that duct type.
    3. Match duct type by connector shape.
    4. Fallback to first duct type.
    """

    duct_type = get_type_from_owner_if_curve(
        conn,
        Duct
    )

    if duct_type:
        return duct_type

    duct_type = get_connected_curve_type_from_owner_connectors(
        conn,
        Duct
    )

    if duct_type:
        return duct_type

    duct_types = list(
        FilteredElementCollector(doc)
        .OfClass(DuctType)
        .ToElements()
    )

    if not duct_types:
        return None

    for dt in duct_types:
        if duct_type_shape_matches(dt, conn):
            return dt

    return duct_types[0]


# =====================================================
# PIPE TYPE MATCHING
# =====================================================

def get_pipe_type_for_connector(conn):
    """
    Priority:
    1. If owner is pipe, use same pipe type.
    2. If owner fitting/accessory/equipment is connected to a pipe elsewhere, use that pipe type.
    3. Fallback to first pipe type.
    """

    pipe_type = get_type_from_owner_if_curve(
        conn,
        Pipe
    )

    if pipe_type:
        return pipe_type

    pipe_type = get_connected_curve_type_from_owner_connectors(
        conn,
        Pipe
    )

    if pipe_type:
        return pipe_type

    return first_element(PipeType)


# =====================================================
# CABLE TRAY TYPE MATCHING
# =====================================================

def get_cabletray_type_for_connector(conn):
    """
    Priority:
    1. If owner is cable tray, use same cable tray type.
    2. If owner fitting is connected to cable tray elsewhere, use that cable tray type.
    3. Fallback to first cable tray type.
    """

    cabletray_type = get_type_from_owner_if_curve(
        conn,
        CableTray
    )

    if cabletray_type:
        return cabletray_type

    cabletray_type = get_connected_curve_type_from_owner_connectors(
        conn,
        CableTray
    )

    if cabletray_type:
        return cabletray_type

    return first_element(CableTrayType)


# =====================================================
# CONDUIT TYPE MATCHING
# =====================================================

def get_conduit_type_for_connector(conn):
    """
    Priority:
    1. If owner is conduit, use same conduit type.
    2. If owner fitting is connected to conduit elsewhere, use that conduit type.
    3. Fallback to first conduit type.
    """

    conduit_type = get_type_from_owner_if_curve(
        conn,
        Conduit
    )

    if conduit_type:
        return conduit_type

    conduit_type = get_connected_curve_type_from_owner_connectors(
        conn,
        Conduit
    )

    if conduit_type:
        return conduit_type

    return first_element(ConduitType)


# =====================================================
# SIZE COPY HELPERS
# =====================================================

def copy_duct_size_from_connector(new_elem, conn):
    try:
        if conn.Shape == ConnectorProfileType.Round:
            dia = conn.Radius * 2.0

            param = new_elem.get_Parameter(
                BuiltInParameter.RBS_CURVE_DIAMETER_PARAM
            )

            if param and not param.IsReadOnly:
                param.Set(dia)

        else:
            width = conn.Width
            height = conn.Height

            wp = new_elem.get_Parameter(
                BuiltInParameter.RBS_CURVE_WIDTH_PARAM
            )

            hp = new_elem.get_Parameter(
                BuiltInParameter.RBS_CURVE_HEIGHT_PARAM
            )

            if wp and not wp.IsReadOnly:
                wp.Set(width)

            if hp and not hp.IsReadOnly:
                hp.Set(height)

    except:
        pass


def copy_pipe_size_from_connector(new_elem, conn):
    try:
        dia = conn.Radius * 2.0

        param = new_elem.get_Parameter(
            BuiltInParameter.RBS_PIPE_DIAMETER_PARAM
        )

        if param and not param.IsReadOnly:
            param.Set(dia)

    except:
        pass


def copy_conduit_size_from_connector(new_elem, conn):
    try:
        dia = conn.Radius * 2.0

        param = new_elem.get_Parameter(
            BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM
        )

        if param and not param.IsReadOnly:
            param.Set(dia)

    except:
        pass


def copy_cabletray_size_from_connector(new_elem, conn):
    try:
        width = conn.Width
        height = conn.Height

        wp = new_elem.get_Parameter(
            BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM
        )

        hp = new_elem.get_Parameter(
            BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM
        )

        if wp and not wp.IsReadOnly:
            wp.Set(width)

        if hp and not hp.IsReadOnly:
            hp.Set(height)

    except:
        pass


# =====================================================
# CONNECTION HELPER
# =====================================================

def connect_safely(source, target):
    try:
        if source.IsConnected:
            return True
    except:
        pass

    try:
        source.ConnectTo(target)
        return True
    except:
        pass

    try:
        doc.Create.NewUnionFitting(
            source,
            target
        )
        return True
    except:
        pass

    try:
        doc.Create.NewElbowFitting(
            source,
            target
        )
        return True
    except:
        pass

    return False


# =====================================================
# STUB KIND DETECTION
# =====================================================

def get_stub_kind(conn):
    """
    Determine which MEP curve must be created.

    HVAC:
        Creates Duct

    Piping:
        Creates Pipe

    CableTrayConduit:
        Checks the actual owner/category because
        Cable Tray and Conduit share the same domain.
    """

    try:
        owner = conn.Owner

        if not owner:
            return None

        # =================================================
        # HVAC
        # =================================================

        if conn.Domain == Domain.DomainHvac:
            return "duct"

        # =================================================
        # PIPING
        # =================================================

        if conn.Domain == Domain.DomainPiping:
            return "pipe"

        # =================================================
        # CABLE TRAY / CONDUIT
        # =================================================

        if conn.Domain == Domain.DomainCableTrayConduit:

            # -------------------------------------------------
            # 1. DIRECT CURVE CLASS CHECK
            # -------------------------------------------------

            try:
                if isinstance(owner, CableTray):
                    return "cabletray"
            except:
                pass

            try:
                if isinstance(owner, Conduit):
                    return "conduit"
            except:
                pass

            # -------------------------------------------------
            # 2. CABLE TRAY CATEGORY CHECK
            # -------------------------------------------------

            try:
                if is_category(
                    owner,
                    BuiltInCategory.OST_CableTray
                ):
                    return "cabletray"
            except:
                pass

            try:
                if is_category(
                    owner,
                    BuiltInCategory.OST_CableTrayFitting
                ):
                    return "cabletray"
            except:
                pass

            # -------------------------------------------------
            # 3. CONDUIT CATEGORY CHECK
            # -------------------------------------------------

            try:
                if is_category(
                    owner,
                    BuiltInCategory.OST_Conduit
                ):
                    return "conduit"
            except:
                pass

            try:
                if is_category(
                    owner,
                    BuiltInCategory.OST_ConduitFitting
                ):
                    return "conduit"
            except:
                pass

            # -------------------------------------------------
            # 4. CONNECTED CABLE TRAY CHECK
            # -------------------------------------------------

            try:
                cabletray_type = (
                    get_connected_curve_type_from_owner_connectors(
                        conn,
                        CableTray
                    )
                )

                if cabletray_type:
                    return "cabletray"

            except:
                pass

            # -------------------------------------------------
            # 5. CONNECTED CONDUIT CHECK
            # -------------------------------------------------

            try:
                conduit_type = (
                    get_connected_curve_type_from_owner_connectors(
                        conn,
                        Conduit
                    )
                )

                if conduit_type:
                    return "conduit"

            except:
                pass

            # -------------------------------------------------
            # 6. UNKNOWN
            #
            # IMPORTANT:
            # Never automatically assume Conduit.
            # -------------------------------------------------

            return None

    except:
        pass

    return None


# =====================================================
# PICK ELEMENT
# =====================================================

try:
    ref = uidoc.Selection.PickObject(
        ObjectType.Element,
        "Select MEP Element"
    )

except:
    script.exit()


element = doc.GetElement(
    ref.ElementId
)

open_connectors = get_open_connectors(
    element
)

if not open_connectors:
    script.exit()


# =====================================================
# TRANSACTION
# =====================================================

t = Transaction(
    doc,
    "Bloom Stub Out"
)

t.Start()

try:
    for conn in open_connectors:

        if not is_valid_connector_for_curve(conn):
            continue

        start = conn.Origin

        direction = get_direction(conn)

        end = start + direction.Multiply(
            STUB_LENGTH
        )

        level = get_nearest_level(
            start.Z
        )

        if not level:
            continue

        stub_kind = get_stub_kind(
            conn
        )

        if not stub_kind:
            continue

        new_elem = None

        # =================================================
        # DUCT
        # Connector-based creation retains system type.
        # Shape/type is selected by connector owner and shape.
        # =================================================

        if stub_kind == "duct":

            duct_type = get_duct_type_for_connector(
                conn
            )

            if not duct_type:
                continue

            try:
                new_elem = Duct.Create(
                    doc,
                    duct_type.Id,
                    level.Id,
                    conn,
                    end
                )

                doc.Regenerate()

                copy_duct_size_from_connector(
                    new_elem,
                    conn
                )

            except:
                continue

        # =================================================
        # PIPE
        # Connector-based creation retains system type.
        # Type is inherited from pipe or connected pipe where possible.
        # =================================================

        elif stub_kind == "pipe":

            pipe_type = get_pipe_type_for_connector(
                conn
            )

            if not pipe_type:
                continue

            try:
                new_elem = Pipe.Create(
                    doc,
                    pipe_type.Id,
                    level.Id,
                    conn,
                    end
                )

                doc.Regenerate()

                copy_pipe_size_from_connector(
                    new_elem,
                    conn
                )

            except:
                continue

        # =================================================
        # CABLE TRAY
        # Important:
        # Cable Tray and Conduit share same connector domain.
        # Category check prevents cable tray fittings becoming conduit.
        # =================================================

        elif stub_kind == "cabletray":

            cabletray_type = get_cabletray_type_for_connector(
                conn
            )

            if not cabletray_type:
                continue

            try:
                new_elem = CableTray.Create(
                    doc,
                    cabletray_type.Id,
                    start,
                    end,
                    level.Id
                )

                doc.Regenerate()

                copy_cabletray_size_from_connector(
                    new_elem,
                    conn
                )

                doc.Regenerate()

                target = get_closest_connector(
                    new_elem,
                    start
                )

                if target:
                    connect_safely(
                        conn,
                        target
                    )

            except:
                continue

        # =================================================
        # CONDUIT
        # =================================================

        elif stub_kind == "conduit":

            conduit_type = get_conduit_type_for_connector(
                conn
            )

            if not conduit_type:
                continue

            try:
                new_elem = Conduit.Create(
                    doc,
                    conduit_type.Id,
                    start,
                    end,
                    level.Id
                )

                doc.Regenerate()

                copy_conduit_size_from_connector(
                    new_elem,
                    conn
                )

                doc.Regenerate()

                target = get_closest_connector(
                    new_elem,
                    start
                )

                if target:
                    connect_safely(
                        conn,
                        target
                    )

            except:
                continue

        if not new_elem:
            continue

    t.Commit()

except:
    t.RollBack()
    raise