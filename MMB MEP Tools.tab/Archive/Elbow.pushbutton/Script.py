# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Plumbing import Pipe
from Autodesk.Revit.DB.Mechanical import Duct
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

from pyrevit import revit, script, forms

doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()

# -------------------------------------------------
# CONSTANT PICK POINT (used only for closest connector)
# -------------------------------------------------
picked_point = XYZ(0, 0, 0)

# -------------------------------------------------
# SELECTION FILTER
# -------------------------------------------------
class DuctPipeSelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, Duct) or isinstance(elem, Pipe)

    def AllowReference(self, reference, position):
        return False

# -------------------------------------------------
# PICK ELEMENT (NO PRESELECTION, SILENT ESC)
# -------------------------------------------------
try:
    ref = uidoc.Selection.PickObject(
        ObjectType.Element,
        DuctPipeSelectionFilter(),
        "Select a duct or pipe"
    )
except:
    script.exit()

element = doc.GetElement(ref.ElementId)

is_duct = isinstance(element, Duct)
is_pipe = isinstance(element, Pipe)

# -------------------------------------------------
# DIRECTION SELECTION UI
# -------------------------------------------------
direction = forms.CommandSwitchWindow.show(
    ["Left", "Right", "Up", "Down"],
    message="Select elbow direction"
)

if not direction:
    script.exit()

# -------------------------------------------------
# GET SIZE & SEGMENT LENGTH
# -------------------------------------------------
if is_duct:
    width = element.LookupParameter("Width").AsDouble()
    height = element.LookupParameter("Height").AsDouble()
    segment_length = 2.0 * width
else:
    diameter = element.LookupParameter("Diameter").AsDouble()
    segment_length = 2.0 * diameter

# -------------------------------------------------
# FIND NEAREST OPEN CONNECTOR
# -------------------------------------------------
available_connector = None
min_dist = float("inf")

for conn in element.ConnectorManager.Connectors:
    if conn.IsConnected:
        continue
    d = conn.Origin.DistanceTo(picked_point)
    if d < min_dist:
        min_dist = d
        available_connector = conn

if not available_connector:
    script.exit()

# -------------------------------------------------
# DETERMINE BASE FORWARD DIRECTION (FOR LEFT / RIGHT)
# -------------------------------------------------
direction_vector = None

if direction in ["Left", "Right"]:
    if not isinstance(element.Location, LocationCurve):
        script.exit()

    curve = element.Location.Curve
    p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)

    forward = curve.Direction
    if p1.DistanceTo(available_connector.Origin) < p0.DistanceTo(available_connector.Origin):
        forward = forward.Negate()

    horizontal_forward = XYZ(forward.X, forward.Y, 0)
    if horizontal_forward.IsZeroLength():
        horizontal_forward = XYZ.BasisX

    horizontal_forward = horizontal_forward.Normalize()

# -------------------------------------------------
# COMPUTE ELBOW VECTOR
# -------------------------------------------------
if direction == "Right":
    direction_vector = horizontal_forward.CrossProduct(XYZ.BasisZ)

elif direction == "Left":
    direction_vector = XYZ.BasisZ.CrossProduct(horizontal_forward)

elif direction == "Up":
    direction_vector = XYZ.BasisZ

elif direction == "Down":
    direction_vector = XYZ.BasisZ.Negate()

if direction_vector.IsZeroLength():
    script.exit()

# -------------------------------------------------
# CREATE NEW SEGMENT + ELBOW
# -------------------------------------------------
start = available_connector.Origin
end = start + direction_vector.Multiply(segment_length)

def nearest_connectors(set1, set2):
    min_d = float("inf")
    pair = (None, None)
    for c1 in set1:
        if c1.IsConnected: continue
        for c2 in set2:
            if c2.IsConnected: continue
            d = c1.Origin.DistanceTo(c2.Origin)
            if d < min_d:
                min_d = d
                pair = (c1, c2)
    return pair

t = Transaction(doc, "Smart Elbow Tool")
t.Start()

try:
    if is_duct:
        new_elem = Duct.Create(
            doc,
            element.MEPSystem.GetTypeId(),
            element.DuctType.Id,
            element.ReferenceLevel.Id,
            start,
            end
        )

        new_elem.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM).Set(width)
        new_elem.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM).Set(height)

    else:
        new_elem = Pipe.Create(
            doc,
            element.MEPSystem.GetTypeId(),
            element.PipeType.Id,
            element.ReferenceLevel.Id,
            start,
            end
        )

        new_elem.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(diameter)

    c1, c2 = nearest_connectors(
        element.ConnectorManager.Connectors,
        new_elem.ConnectorManager.Connectors
    )

    doc.Create.NewElbowFitting(c1, c2)

    t.Commit()

except:
    t.RollBack()
    raise
