# -*- coding: utf-8 -*-

from pyrevit import revit, script, UI
from Autodesk.Revit.DB import (
    XYZ, Transaction, UnitUtils, UnitTypeId,
    BuiltInParameter, MEPCurve
)

from Autodesk.Revit.DB.Mechanical import Duct
from Autodesk.Revit.DB.Plumbing import Pipe

# ------------------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------------------
doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()
output = script.get_output()

logger.info("Starting 45° Downward Elbow Tool")

# ------------------------------------------------------------------------------
# Pick Element
# ------------------------------------------------------------------------------
try:
    ref = uidoc.Selection.PickObject(
        UI.Selection.ObjectType.Element,
        "Select a duct or pipe"
    )
except:
    script.exit()

elem = doc.GetElement(ref.ElementId)

if not isinstance(elem, MEPCurve):
    output.print_md("❌ **Selected element is not a duct or pipe**")
    script.exit()

mep_curve = elem

# ------------------------------------------------------------------------------
# Find Closest Unconnected Connector
# ------------------------------------------------------------------------------
connectors = mep_curve.ConnectorManager.Connectors
location = mep_curve.Location

mid_point = None
if hasattr(location, "Curve"):
    mid_point = location.Curve.Evaluate(0.5, True)
elif hasattr(location, "Point"):
    mid_point = location.Point

closest_conn = None
min_dist = float("inf")

for conn in connectors:
    if conn.IsConnected:
        continue
    dist = conn.Origin.DistanceTo(mid_point)
    if dist < min_dist:
        min_dist = dist
        closest_conn = conn

if not closest_conn:
    output.print_md("❌ **No open connector found**")
    script.exit()

logger.info("Open connector found")

# ------------------------------------------------------------------------------
# Get Diameter / Width
# ------------------------------------------------------------------------------
dimension = 0.0

if isinstance(mep_curve, Duct):
    width_param = mep_curve.LookupParameter("Width")
    if not width_param:
        width_param = doc.GetElement(mep_curve.GetTypeId()).LookupParameter("Width")
    dimension = width_param.AsDouble()

elif isinstance(mep_curve, Pipe):
    dia_param = mep_curve.LookupParameter("Diameter")
    if not dia_param:
        dia_param = doc.GetElement(mep_curve.GetTypeId()).LookupParameter("Diameter")
    dimension = dia_param.AsDouble()

if dimension <= 0:
    output.print_md("❌ **Invalid diameter or width detected**")
    script.exit()

segment_length = dimension * 2.0

# ------------------------------------------------------------------------------
# Direction Logic (45° Down)
# ------------------------------------------------------------------------------
conn_dir = closest_conn.CoordinateSystem.BasisZ
threshold = UnitUtils.ConvertToInternalUnits(0.01, UnitTypeId.Feet)

if abs(conn_dir.Z) < threshold:
    horiz = XYZ(conn_dir.X, conn_dir.Y, 0).Normalize()
    new_dir = (horiz - XYZ.BasisZ).Normalize()
else:
    new_dir = (XYZ.BasisX + conn_dir).Normalize()

start_pt = closest_conn.Origin
end_pt = start_pt + new_dir * segment_length

level = doc.GetElement(mep_curve.ReferenceLevel.Id)

# ------------------------------------------------------------------------------
# Transaction
# ------------------------------------------------------------------------------
t = Transaction(doc, "Create 45° Downward Elbow")
t.Start()

try:
    if isinstance(mep_curve, Duct):
        system_id = mep_curve.get_Parameter(
            BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM
        ).AsElementId()

        new_curve = Duct.Create(
            doc, system_id, mep_curve.GetTypeId(),
            level.Id, start_pt, end_pt
        )

        new_curve.LookupParameter("Width").Set(dimension)
        new_curve.LookupParameter("Height").Set(mep_curve.Height)

    else:  # Pipe
        system_id = mep_curve.get_Parameter(
            BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM
        ).AsElementId()

        new_curve = Pipe.Create(
            doc, system_id, mep_curve.GetTypeId(),
            level.Id, start_pt, end_pt
        )

        new_curve.LookupParameter("Diameter").Set(dimension)

    # --------------------------------------------------------------------------
    # Find matching connector on new segment
    # --------------------------------------------------------------------------
    new_conn = None
    for c in new_curve.ConnectorManager.Connectors:
        if c.Origin.DistanceTo(start_pt) < threshold:
            new_conn = c
            break

    if not new_conn:
        raise Exception("Connector not found on new segment")

    # --------------------------------------------------------------------------
    # Create Elbow Fitting
    # --------------------------------------------------------------------------
    elbow = doc.Create.NewElbowFitting(closest_conn, new_conn)

    if not elbow:
        raise Exception("Failed to create elbow fitting")

    t.Commit()

except Exception as ex:
    t.RollBack()
    output.print_md("❌ **Error:** {}".format(str(ex)))
    script.exit()

# ------------------------------------------------------------------------------
# Done
# ------------------------------------------------------------------------------
output.print_md("✅ **45° downward elbow created successfully**")
logger.info("Elbow created successfully")