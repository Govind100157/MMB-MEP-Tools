# -*- coding: utf-8 -*-
from pyrevit import revit, forms
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
import os

doc = revit.doc
uidoc = revit.uidoc

# -------------------------------------------------------
# Collect Section Views
# -------------------------------------------------------

views = [
    v for v in FilteredElementCollector(doc).OfClass(View)
    if not v.IsTemplate and v.ViewType == ViewType.Section
]

if not views:
    forms.alert("No section views found.", exitscript=True)

view_map = {v.Name: v for v in views}

selected = forms.SelectFromList.show(
    sorted(view_map.keys()),
    multiselect=True,
    title="Select Section Views to Export as BCF"
)

if not selected:
    forms.alert("No views selected.", exitscript=True)

export_views = [view_map[n] for n in selected]

# -------------------------------------------------------
# Export BCF
# -------------------------------------------------------

folder = forms.pick_folder(title="Select BCF Export Folder")
if not folder:
    forms.alert("No folder selected.", exitscript=True)

opts = BCFExportOptions()

exported = 0
for v in export_views:
    uidoc.ActiveView = v
    try:
        doc.Export(folder, v.Name, opts)
        exported += 1
    except:
        pass

forms.alert(
    "BCF viewpoints exported: {}\n\nImport these into BIMcollab to create issues."
    .format(exported),
    title="BCF Export Complete"
)
