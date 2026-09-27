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
    MEPCurve
)

from Autodesk.Revit.DB.Mechanical import Duct
from Autodesk.Revit.DB.Plumbing import Pipe
from Autodesk.Revit.DB.Electrical import Conduit, CableTray
from Autodesk.Revit.UI import Selection
from Autodesk.Revit.DB import FilteredElementCollector
from Autodesk.Revit.DB.Mechanical import MechanicalSystemType
from Autodesk.Revit.DB.Plumbing import PipingSystemType

doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()

# ------------------------------------------------------------------------------
# Pick element + click point
# ------------------------------------------------------------------------------
try:
    ref = uidoc.Selection.PickObject(
        Selection.ObjectType.Element,
        "Select a duct, pipe, conduit or cable tray"
    )
    click_pt = ref.GlobalPoint
except:
    script.exit()

elem = doc.GetElement(ref.ElementId)

if not isinstance(elem, (MEPCurve, CableTray)):
    script.exit()

mep_curve = elem

# ------------------------------------------------------------------------------
# Find nearest open connector to click
# ------------------------------------------------------------------------------
try:
    connectors = mep_curve.ConnectorManager.Connectors
except:
    script.exit()

closest_conn = None
min_dist = float("inf")

for conn in connectors:
    if conn.IsConnected:
        continue

    d = conn.Origin.DistanceTo(click_pt)

    if d < min_dist:
        min_dist = d
        closest_conn = conn

if not closest_conn:
    script.exit()

# ------------------------------------------------------------------------------
# Stub length rules
# ------------------------------------------------------------------------------
def compute_stub_length(elem):

    if isinstance(elem, (Conduit, CableTray)):
        return UnitUtils.ConvertToInternalUnits(
            1.0,
            UnitTypeId.Meters
        )

    size_mm = 0.0

    if isinstance(elem, Duct):

        dia = elem.get_Parameter(
            BuiltInParameter.RBS_CURVE_DIAMETER_PARAM
        )

        width = elem.get_Parameter(
            BuiltInParameter.RBS_CURVE_WIDTH_PARAM
        )

        if dia and dia.HasValue:
            size_mm = UnitUtils.ConvertFromInternalUnits(
                dia.AsDouble(),
                UnitTypeId.Millimeters
            )

        elif width and width.HasValue:
            size_mm = UnitUtils.ConvertFromInternalUnits(
                width.AsDouble(),
                UnitTypeId.Millimeters
            )

    elif isinstance(elem, Pipe):

        dia = elem.get_Parameter(
            BuiltInParameter.RBS_PIPE_DIAMETER_PARAM
        )

        if dia and dia.HasValue:
            size_mm = UnitUtils.ConvertFromInternalUnits(
                dia.AsDouble(),
                UnitTypeId.Millimeters
            )

    if size_mm <= 500:
        meters = 2.0
    elif size_mm <= 1000:
        meters = 4.0
    elif size_mm <= 1500:
        meters = 6.0
    elif size_mm <= 2000:
        meters = 8.0
    elif size_mm <= 2500:
        meters = 10.0
    elif size_mm <= 3000:
        meters = 12.0
    elif size_mm <= 3500:
        meters = 14.0
    elif size_mm <= 4000:
        meters = 16.0
    elif size_mm <= 4500:
        meters = 18.0
    elif size_mm <= 5000:
        meters = 20.0
    else:
        meters = 25.0

    return UnitUtils.ConvertToInternalUnits(
        meters,
        UnitTypeId.Meters
    )

segment_length = compute_stub_length(mep_curve)

# ------------------------------------------------------------------------------
# Create DOWN 45° vector
# ------------------------------------------------------------------------------
cs = closest_conn.CoordinateSystem

hvec = XYZ(
    cs.BasisZ.X,
    cs.BasisZ.Y,
    0
)

if hvec.IsZeroLength():
    hvec = XYZ.BasisX

hvec = hvec.Normalize()

# Force downward 45°
down_45 = (
    hvec + XYZ(0, 0, -1)
).Normalize()

start_pt = closest_conn.Origin
end_pt = start_pt + down_45.Multiply(segment_length)

# ------------------------------------------------------------------------------
# Get level
# ------------------------------------------------------------------------------
try:
    level = doc.GetElement(mep_curve.ReferenceLevel.Id)
except:
    try:
        level = doc.GetElement(mep_curve.LevelId)
    except:
        script.exit()

# ------------------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------------------
def get_nearest_connectors(set1, set2):

    min_d = float("inf")
    pair = (None, None)

    for c1 in set1:

        if c1.IsConnected:
            continue

        for c2 in set2:

            if c2.IsConnected:
                continue

            d = c1.Origin.DistanceTo(c2.Origin)

            if d < min_d:
                min_d = d
                pair = (c1, c2)

    return pair

# ------------------------------------------------------------------------------
# Get default system type for undefined ducts/pipes
# ------------------------------------------------------------------------------
def get_default_system_type(elem):

    if isinstance(elem, Duct):

        systems = list(
            FilteredElementCollector(doc)
            .OfClass(MechanicalSystemType)
        )

        if systems:
            return systems[0].Id

    elif isinstance(elem, Pipe):

        systems = list(
            FilteredElementCollector(doc)
            .OfClass(PipingSystemType)
        )

        if systems:
            return systems[0].Id

    return None


# ------------------------------------------------------------------------------
# Transaction
# ------------------------------------------------------------------------------
t = Transaction(doc, "Elbow Down 45°")
t.Start()

try:

    # --------------------------------------------------------------------------
    # DUCT
    # --------------------------------------------------------------------------
    if isinstance(mep_curve, Duct):

        if mep_curve.MEPSystem:
            system_type_id = mep_curve.MEPSystem.GetTypeId()
        else:
            system_type_id = get_default_system_type(mep_curve)

        if not system_type_id:
            raise Exception("No duct system type found in project.")

        new_curve = Duct.Create(
            doc,
            system_type_id,
            mep_curve.DuctType.Id,
            level.Id,
            start_pt,
            end_pt
        )

        for bip in [
            BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
            BuiltInParameter.RBS_CURVE_HEIGHT_PARAM,
            BuiltInParameter.RBS_CURVE_DIAMETER_PARAM
        ]:

            p = mep_curve.get_Parameter(bip)

            if p and p.HasValue:
                np = new_curve.get_Parameter(bip)

                if np:
                    np.Set(p.AsDouble())

    # --------------------------------------------------------------------------
    # PIPE
    # --------------------------------------------------------------------------
    elif isinstance(mep_curve, Pipe):

        if mep_curve.MEPSystem:
            system_type_id = mep_curve.MEPSystem.GetTypeId()
        else:
            system_type_id = get_default_system_type(mep_curve)

        if not system_type_id:
            raise Exception("No pipe system type found in project.")

        new_curve = Pipe.Create(
            doc,
            system_type_id,
            mep_curve.PipeType.Id,
            level.Id,
            start_pt,
            end_pt
        )

        dia_param = mep_curve.get_Parameter(
            BuiltInParameter.RBS_PIPE_DIAMETER_PARAM
        )

        if dia_param and dia_param.HasValue:

            new_curve.get_Parameter(
                BuiltInParameter.RBS_PIPE_DIAMETER_PARAM
            ).Set(
                dia_param.AsDouble()
            )

    # --------------------------------------------------------------------------
    # CONDUIT
    # --------------------------------------------------------------------------
    elif isinstance(mep_curve, Conduit):

        new_curve = Conduit.Create(
            doc,
            mep_curve.GetTypeId(),
            start_pt,
            end_pt,
            level.Id
        )

        dia_param = mep_curve.get_Parameter(
            BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM
        )

        if dia_param and dia_param.HasValue:

            new_curve.get_Parameter(
                BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM
            ).Set(
                dia_param.AsDouble()
            )

    # --------------------------------------------------------------------------
    # CABLE TRAY
    # --------------------------------------------------------------------------
    elif isinstance(mep_curve, CableTray):

        new_curve = CableTray.Create(
            doc,
            mep_curve.GetTypeId(),
            start_pt,
            end_pt,
            level.Id
        )

        width_param = mep_curve.get_Parameter(
            BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM
        )

        height_param = mep_curve.get_Parameter(
            BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM
        )

        if width_param and width_param.HasValue:

            new_curve.get_Parameter(
                BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM
            ).Set(
                width_param.AsDouble()
            )

        if height_param and height_param.HasValue:

            new_curve.get_Parameter(
                BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM
            ).Set(
                height_param.AsDouble()
            )

    else:
        raise Exception("Unsupported element type")

    # --------------------------------------------------------------------------
    # Create elbow fitting
    # --------------------------------------------------------------------------
    c1, c2 = get_nearest_connectors(
        mep_curve.ConnectorManager.Connectors,
        new_curve.ConnectorManager.Connectors
    )

    if c1 and c2:

        try:
            doc.Create.NewElbowFitting(c1, c2)

        except Exception as fit_ex:

            logger.warning(
                "Fitting not created automatically: {}".format(
                    fit_ex
                )
            )

    t.Commit()

    logger.info(
        "✅ Elbow Down 45° created at connector nearest to mouse click."
    )

except:
    try:
        if transaction and transaction.HasStarted():
            transaction.RollBack()
    except:
        pass