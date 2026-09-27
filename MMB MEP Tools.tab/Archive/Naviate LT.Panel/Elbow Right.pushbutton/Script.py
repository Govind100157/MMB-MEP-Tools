# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Plumbing import Pipe
from Autodesk.Revit.DB.Mechanical import Duct
from Autodesk.Revit.UI import *

from pyrevit import revit, script

logger = script.get_logger()

doc = revit.doc
uidoc = revit.uidoc

# -------------------------------------------------
# USER INPUT – CONNECTOR XYZ (Internal Units: feet)
# -------------------------------------------------
CONNECTOR_X = 0.0
CONNECTOR_Y = 0.0
CONNECTOR_Z = 0.0

picked_point = XYZ(CONNECTOR_X, CONNECTOR_Y, CONNECTOR_Z)

# -------------------------------------------------
# PRE-SELECTION CHECK
# -------------------------------------------------
selection_ids = list(uidoc.Selection.GetElementIds())

if len(selection_ids) != 1:
    logger.error("Please pre-select exactly ONE duct or pipe.")
    script.exit()

element = doc.GetElement(selection_ids[0])

is_duct = isinstance(element, Duct)
is_pipe = isinstance(element, Pipe)

if not (is_duct or is_pipe):
    logger.error("Selected element is not a duct or pipe.")
    script.exit()

# -------------------------------------------------
# GET SIZE + SEGMENT LENGTH
# -------------------------------------------------
segment_length = 0.0

if is_duct:
    width_param = element.LookupParameter("Width")
    height_param = element.LookupParameter("Height")

    if not width_param or not height_param:
        duct_type = doc.GetElement(element.GetTypeId())
        width_param = duct_type.LookupParameter("Width")
        height_param = duct_type.LookupParameter("Height")

    if not width_param or not height_param:
        logger.error("Could not retrieve duct Width/Height.")
        script.exit()

    width = width_param.AsDouble()
    height = height_param.AsDouble()
    segment_length = 2.0 * width

else:  # PIPE
    diameter_param = element.LookupParameter("Diameter")
    if not diameter_param:
        pipe_type = doc.GetElement(element.GetTypeId())
        diameter_param = pipe_type.LookupParameter("Diameter")

    if not diameter_param:
        logger.error("Could not retrieve pipe Diameter.")
        script.exit()

    diameter = diameter_param.AsDouble()
    segment_length = 2.0 * diameter

# -------------------------------------------------
# GET CONNECTORS
# -------------------------------------------------
connectors = element.ConnectorManager.Connectors

# -------------------------------------------------
# FIND NEAREST OPEN CONNECTOR
# -------------------------------------------------
available_connector = None
min_dist = float("inf")

for conn in connectors:
    if not conn.IsConnected:
        dist = conn.Origin.DistanceTo(picked_point)
        if dist < min_dist:
            min_dist = dist
            available_connector = conn

if not available_connector:
    logger.error("No open connector found.")
    script.exit()

# -------------------------------------------------
# DETERMINE FORWARD DIRECTION
# -------------------------------------------------
if not isinstance(element.Location, LocationCurve):
    logger.error("Element has no LocationCurve.")
    script.exit()

curve = element.Location.Curve
p0 = curve.GetEndPoint(0)
p1 = curve.GetEndPoint(1)

if p0.DistanceTo(available_connector.Origin) < p1.DistanceTo(available_connector.Origin):
    forward = curve.Direction
else:
    forward = curve.Direction.Negate()

horizontal_forward = XYZ(forward.X, forward.Y, 0)

if horizontal_forward.IsZeroLength():
    horizontal_forward = XYZ.BasisX

horizontal_forward = horizontal_forward.Normalize()

# RIGHT TURN VECTOR (Forward × Z)
right_vector = horizontal_forward.CrossProduct(XYZ.BasisZ)

if right_vector.IsZeroLength():
    logger.error("Failed to compute right-hand direction.")
    script.exit()

# -------------------------------------------------
# CREATE NEW SEGMENT + ELBOW
# -------------------------------------------------
start_point = available_connector.Origin
end_point = start_point + right_vector.Multiply(segment_length)

def get_nearest_connectors(set1, set2):
    min_distance = float("inf")
    c1_best = None
    c2_best = None

    for c1 in set1:
        if c1.IsConnected:
            continue
        for c2 in set2:
            if c2.IsConnected:
                continue
            d = c1.Origin.DistanceTo(c2.Origin)
            if d < min_distance:
                min_distance = d
                c1_best = c1
                c2_best = c2
    return c1_best, c2_best

t = Transaction(doc, "Elbow Right Tool")
t.Start()

try:
    if is_duct:
        original = element

        new_elem = Duct.Create(
            doc,
            original.MEPSystem.GetTypeId(),
            original.DuctType.Id,
            original.ReferenceLevel.Id,
            start_point,
            end_point
        )

        new_elem.get_Parameter(
            BuiltInParameter.RBS_CURVE_WIDTH_PARAM
        ).Set(width)

        new_elem.get_Parameter(
            BuiltInParameter.RBS_CURVE_HEIGHT_PARAM
        ).Set(height)

        c1, c2 = get_nearest_connectors(
            original.ConnectorManager.Connectors,
            new_elem.ConnectorManager.Connectors
        )

        doc.Create.NewElbowFitting(c1, c2)
        logger.info("✅ Elbow and new duct created.")

    else:  # PIPE
        original = element

        new_elem = Pipe.Create(
            doc,
            original.MEPSystem.GetTypeId(),
            original.PipeType.Id,
            original.ReferenceLevel.Id,
            start_point,
            end_point
        )

        new_elem.get_Parameter(
            BuiltInParameter.RBS_PIPE_DIAMETER_PARAM
        ).Set(diameter)

        c1, c2 = get_nearest_connectors(
            original.ConnectorManager.Connectors,
            new_elem.ConnectorManager.Connectors
        )

        doc.Create.NewElbowFitting(c1, c2)
        logger.info("✅ Elbow and new pipe created.")

    t.Commit()

except Exception as ex:
    t.RollBack()
    logger.error("❌ Transaction failed: {}".format(ex))
    raise