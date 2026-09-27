# -*- coding: utf-8 -*-

from pyrevit import forms
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB import Transaction

doc = __revit__.ActiveUIDocument.Document


# =====================================================
# SELECT SHEETS
# =====================================================

all_sheets = sorted(
    FilteredElementCollector(doc)
    .OfClass(ViewSheet)
    .ToElements(),
    key=lambda x: x.SheetNumber
)

sheet_dict = {
    "{} - {}".format(s.SheetNumber, s.Name): s
    for s in all_sheets
}

selected_sheet_names = forms.SelectFromList.show(
    sorted(sheet_dict.keys()),
    title="Select Sheets",
    multiselect=True,
    button_name="Select Sheets"
)

if not selected_sheet_names:
    forms.alert("No sheets selected.", exitscript=True)

selected_sheets = [sheet_dict[name] for name in selected_sheet_names]


# =====================================================
# COLLECT VIEWS
# =====================================================

floor_plans = []
sections = []
callouts = []

for sheet in selected_sheets:

    for view_id in sheet.GetAllPlacedViews():

        view = doc.GetElement(view_id)

        if not view:
            continue

        if view.IsTemplate:
            continue

        # Floor Plans
        if view.ViewType == ViewType.FloorPlan:
            floor_plans.append(view)

        # Sections / Callouts
        elif view.ViewType == ViewType.Section:

            try:
                if view.ParentViewId != ElementId.InvalidElementId:
                    callouts.append(view)
                else:
                    sections.append(view)

            except:
                sections.append(view)


# =====================================================
# REMOVE DUPLICATES
# =====================================================

floor_plans = list({v.Id.IntegerValue: v for v in floor_plans}.values())
sections = list({v.Id.IntegerValue: v for v in sections}.values())
callouts = list({v.Id.IntegerValue: v for v in callouts}.values())


# =====================================================
# GROUPED VIEW SELECTION
# =====================================================

grouped_views = {}

if floor_plans:
    grouped_views["Floor Plans"] = sorted(
        floor_plans,
        key=lambda x: x.Name
    )

if sections:
    grouped_views["Sections"] = sorted(
        sections,
        key=lambda x: x.Name
    )

if callouts:
    grouped_views["Callouts"] = sorted(
        callouts,
        key=lambda x: x.Name
    )

selected_views = forms.SelectFromList.show(
    grouped_views,
    title="Select Views",
    multiselect=True,
    group_selector=True,
    name_attr="Name",
    button_name="Select Views"
)

if not selected_views:
    forms.alert("No views selected.", exitscript=True)


# =====================================================
# SELECT VIEW TEMPLATE
# =====================================================

view_templates = [
    v for v in
    FilteredElementCollector(doc)
    .OfClass(View)
    .ToElements()
    if v.IsTemplate
]

template_dict = {
    "{}".format(v.Name): v
    for v in sorted(view_templates, key=lambda x: x.Name)
}

selected_template_name = forms.SelectFromList.show(
    sorted(template_dict.keys()),
    title="Select View Template",
    multiselect=False,
    button_name="Apply Template"
)

if not selected_template_name:
    forms.alert("No template selected.", exitscript=True)

selected_template = template_dict[selected_template_name]


# =====================================================
# APPLY VIEW TEMPLATE
# =====================================================

updated_views = []

t = Transaction(doc, "Apply View Template")
t.Start()

for view in selected_views:

    try:
        view.ViewTemplateId = selected_template.Id
        updated_views.append(view.Name)

    except:
        pass

t.Commit()


# =====================================================
# RESULT
# =====================================================

forms.alert(
    "View Template '{}'\n\nApplied to {} views.".format(
        selected_template.Name,
        len(updated_views)
    ),
    title="Completed"
)

print("=" * 80)
print("VIEW TEMPLATE APPLIED")
print("=" * 80)

for vname in updated_views:
    print(vname)