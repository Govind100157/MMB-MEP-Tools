# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Plumbing import Pipe, PipingSystemType
from Autodesk.Revit.DB.Mechanical import Duct, MechanicalSystemType
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

from pyrevit import revit, script

logger = script.get_logger()

doc = revit.doc
uidoc = revit.uidoc

class MEPSelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, (Duct, Pipe, Conduit))
    def AllowReference(self, reference, position):
        return False

try:
    picked_ref = uidoc.Selection.PickObject(
        ObjectType.Element,
        MEPSelectionFilter(),
        "Select a duct, pipe, or conduit"
    )
    picked_point = picked_ref.GlobalPoint
except:
    script.exit()

element = doc.GetElement(picked_ref.ElementId)

# Find an available (unconnected) connector nearest to the picked point
connectors = element.ConnectorManager.Connectors
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

# Ensure element has a curve location
if not isinstance(element.Location, LocationCurve):
    logger.error("Element has no LocationCurve.")
    script.exit()

curve = element.Location.Curve
p0 = curve.GetEndPoint(0)
p1 = curve.GetEndPoint(1)
# Determine forward direction along the element (towards the nearest end)
if p0.DistanceTo(available_connector.Origin) < p1.DistanceTo(available_connector.Origin):
    forward = curve.Direction
else:
    forward = curve.Direction.Negate()

horizontal_forward = XYZ(forward.X, forward.Y, 0).Normalize()
if horizontal_forward.IsZeroLength():
    horizontal_forward = XYZ.BasisX

# Naviate LT convention for "right" vector (used previously for Elbow Right)
if abs(forward.Z) > 0.99:  # vertical element
    right_vector = XYZ(-1, 0, 0)  # opposite of global X for Naviate LT
else:
    right_vector = XYZ.BasisZ.CrossProduct(horizontal_forward).Normalize()

# For Elbow Left we invert the right_vector
left_vector = right_vector.Negate()

# -------------------------------------------------
# SEGMENT LENGTH (Govind's strict thresholds)
# -------------------------------------------------
segment_length = 0.0

if isinstance(element, Duct):
    width_param = element.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
    diameter_param = element.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)

    size_mm = 0.0
    if diameter_param and diameter_param.HasValue:
        size_mm = UnitUtils.ConvertFromInternalUnits(diameter_param.AsDouble(), UnitTypeId.Millimeters)
    elif width_param and width_param.HasValue:
        size_mm = UnitUtils.ConvertFromInternalUnits(width_param.AsDouble(), UnitTypeId.Millimeters)

    if size_mm <= 500:
        segment_length = UnitUtils.ConvertToInternalUnits(2.0, UnitTypeId.Meters)
    elif size_mm <= 1000:
        segment_length = UnitUtils.ConvertToInternalUnits(4.0, UnitTypeId.Meters)
    elif size_mm <= 1500:
        segment_length = UnitUtils.ConvertToInternalUnits(6.0, UnitTypeId.Meters)
    elif size_mm <= 2000:
        segment_length = UnitUtils.ConvertToInternalUnits(8.0, UnitTypeId.Meters)
    elif size_mm <= 2500:
        segment_length = UnitUtils.ConvertToInternalUnits(10.0, UnitTypeId.Meters)
    elif size_mm <= 3000:
        segment_length = UnitUtils.ConvertToInternalUnits(12.0, UnitTypeId.Meters)
    elif size_mm <= 3500:
        segment_length = UnitUtils.ConvertToInternalUnits(14.0, UnitTypeId.Meters)
    elif size_mm <= 4000:
        segment_length = UnitUtils.ConvertToInternalUnits(16.0, UnitTypeId.Meters)
    elif size_mm <= 4500:
        segment_length = UnitUtils.ConvertToInternalUnits(18.0, UnitTypeId.Meters)
    elif size_mm <= 5000:
        segment_length = UnitUtils.ConvertToInternalUnits(20.0, UnitTypeId.Meters)
    else:
        segment_length = UnitUtils.ConvertToInternalUnits(25.0, UnitTypeId.Meters)

elif isinstance(element, Pipe):
    diameter_param = element.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
    size_mm = UnitUtils.ConvertFromInternalUnits(diameter_param.AsDouble(), UnitTypeId.Millimeters) if diameter_param and diameter_param.HasValue else 0.0

    if size_mm <= 500:
        segment_length = UnitUtils.ConvertToInternalUnits(2.0, UnitTypeId.Meters)
    elif size_mm <= 1000:
        segment_length = UnitUtils.ConvertToInternalUnits(4.0, UnitTypeId.Meters)
    elif size_mm <= 1500:
        segment_length = UnitUtils.ConvertToInternalUnits(6.0, UnitTypeId.Meters)
    elif size_mm <= 2000:
        segment_length = UnitUtils.ConvertToInternalUnits(8.0, UnitTypeId.Meters)
    elif size_mm <= 2500:
        segment_length = UnitUtils.ConvertToInternalUnits(10.0, UnitTypeId.Meters)
    elif size_mm <= 3000:
        segment_length = UnitUtils.ConvertToInternalUnits(12.0, UnitTypeId.Meters)
    elif size_mm <= 3500:
        segment_length = UnitUtils.ConvertToInternalUnits(14.0, UnitTypeId.Meters)
    elif size_mm <= 4000:
        segment_length = UnitUtils.ConvertToInternalUnits(16.0, UnitTypeId.Meters)
    elif size_mm <= 4500:
        segment_length = UnitUtils.ConvertToInternalUnits(18.0, UnitTypeId.Meters)
    elif size_mm <= 5000:
        segment_length = UnitUtils.ConvertToInternalUnits(20.0, UnitTypeId.Meters)
    else:
        segment_length = UnitUtils.ConvertToInternalUnits(25.0, UnitTypeId.Meters)

elif isinstance(element, Conduit):
    segment_length = UnitUtils.ConvertToInternalUnits(1.0, UnitTypeId.Meters)

# Fallback: if for some reason segment_length is still zero, use 1 meter
if segment_length <= 0.0:
    segment_length = UnitUtils.ConvertToInternalUnits(1.0, UnitTypeId.Meters)

start_point = available_connector.Origin
end_point = start_point + left_vector.Multiply(segment_length)

# -------------------------------------------------
# Helper functions
# -------------------------------------------------
def get_nearest_connectors(set1, set2):
    min_distance = float("inf")
    c1_best = None
    c2_best = None
    for c1 in set1:
        if c1.IsConnected: continue
        for c2 in set2:
            if c2.IsConnected: continue
            d = c1.Origin.DistanceTo(c2.Origin)
            if d < min_distance:
                min_distance = d
                c1_best = c1
                c2_best = c2
    return c1_best, c2_best

def get_default_system_type(is_duct=False, is_pipe=False):
    if is_duct:
        sys_types = FilteredElementCollector(doc).OfClass(MechanicalSystemType).ToElements()
    elif is_pipe:
        sys_types = FilteredElementCollector(doc).OfClass(PipingSystemType).ToElements()
    else:
        return ElementId.InvalidElementId
    return sys_types[0].Id if sys_types else ElementId.InvalidElementId

# -------------------------------------------------
# Transaction: create the left stub and elbow
# -------------------------------------------------
t = Transaction(doc, "Elbow Left Tool")
t.Start()

try:
    if isinstance(element, Duct):
        system_type_id = element.MEPSystem.GetTypeId() if element.MEPSystem else get_default_system_type(is_duct=True)
        new_elem = Duct.Create(doc, system_type_id, element.DuctType.Id, element.ReferenceLevel.Id, start_point, end_point)
        width_param = element.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
        height_param = element.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
        diameter_param = element.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
        if width_param and height_param:
            new_elem.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM).Set(width_param.AsDouble())
            new_elem.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM).Set(height_param.AsDouble())
        elif diameter_param:
            new_elem.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM).Set(diameter_param.AsDouble())
        c1, c2 = get_nearest_connectors(element.ConnectorManager.Connectors, new_elem.ConnectorManager.Connectors)
        if c1 and c2:
            doc.Create.NewElbowFitting(c1, c2)
        else:
            logger.warning("Could not find matching connectors to create elbow for duct.")

    elif isinstance(element, Pipe):
        system_type_id = element.MEPSystem.GetTypeId() if element.MEPSystem else get_default_system_type(is_pipe=True)
        new_elem = Pipe.Create(doc, system_type_id, element.PipeType.Id, element.ReferenceLevel.Id, start_point, end_point)
        diameter_param = element.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
        if diameter_param:
            new_elem.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(diameter_param.AsDouble())
        c1, c2 = get_nearest_connectors(element.ConnectorManager.Connectors, new_elem.ConnectorManager.Connectors)
        if c1 and c2:
            doc.Create.NewElbowFitting(c1, c2)
        else:
            logger.warning("Could not find matching connectors to create elbow for pipe.")

    elif isinstance(element, Conduit):
        new_elem = Conduit.Create(doc, element.GetTypeId(), start_point, end_point, element.ReferenceLevel.Id)
        diameter_param = element.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)
        if diameter_param:
            new_elem.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM).Set(diameter_param.AsDouble())
        logger.info("✅ Conduit segment created with matching size (left bend).")

    t.Commit()
    logger.info("✅ Elbow Left created with Naviate-style direction and strict stub length rules.")

except Exception as ex:
    t.RollBack()
    logger.error("❌ Transaction failed: {}".format(ex))
    raise
