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


from pyrevit import revit, DB
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

doc = revit.doc
uidoc = revit.uidoc

# ==================================================
# SETTINGS
# ==================================================

END_OFFSET_MM = 300
TOP_BOTTOM_OFFSET_MM = 300
DEPTH_MM = 600

MM_TO_FT = 1.0 / 304.8

END_OFFSET = END_OFFSET_MM * MM_TO_FT
TOP_BOTTOM_OFFSET = TOP_BOTTOM_OFFSET_MM * MM_TO_FT
DEPTH = DEPTH_MM * MM_TO_FT

# ==================================================
# SECTION VIEW TYPE
# ==================================================

def get_section_type():

    collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)

    for vft in collector:
        try:
            if vft.ViewFamily == DB.ViewFamily.Section:
                return vft
        except:
            pass

    return None


# ==================================================
# VALIDATE PICKED ELEMENT
# ==================================================

def is_supported_element(elem):

    try:
        if elem is None:
            return False

        if elem.Category is None:
            return False

        if not isinstance(elem.Location, DB.LocationCurve):
            return False

        cname = elem.Category.Name.lower()

        return (
            "duct" in cname
            or "pipe" in cname
            or "conduit" in cname
            or "cable tray" in cname
        )

    except:
        return False


# ==================================================
# CREATE SECTION
# ==================================================

def create_section(elem):

    curve = elem.Location.Curve

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)

    direction = (p1 - p0).Normalize()

    up = DB.XYZ.BasisZ

    viewdir = direction.CrossProduct(up)

    if viewdir.GetLength() < 0.001:
        return

    viewdir = viewdir.Normalize()

    midpoint = (p0 + p1) * 0.5

    bbox = elem.get_BoundingBox(None)

    if bbox:
        height = bbox.Max.Z - bbox.Min.Z
    else:
        height = 1.0

    if height < (300 * MM_TO_FT):
        height = (300 * MM_TO_FT)

    length = curve.Length

    transform = DB.Transform.Identity

    transform.Origin = midpoint
    transform.BasisX = direction
    transform.BasisY = up
    transform.BasisZ = viewdir

    section_box = DB.BoundingBoxXYZ()
    section_box.Transform = transform

    section_box.Min = DB.XYZ(
        -(length / 2.0) - END_OFFSET,
        -(height / 2.0) - TOP_BOTTOM_OFFSET,
        -DEPTH / 2.0
    )

    section_box.Max = DB.XYZ(
        (length / 2.0) + END_OFFSET,
        (height / 2.0) + TOP_BOTTOM_OFFSET,
        DEPTH / 2.0
    )

    section_type = get_section_type()

    if section_type is None:
        return

    t = DB.Transaction(doc, "Section LT")

    try:

        t.Start()

        section = DB.ViewSection.CreateSection(
            doc,
            section_type.Id,
            section_box
        )

        try:
            section.Name = "SECTION LT - {}".format(
                elem.Id.IntegerValue
            )
        except:
            pass

        try:
            section.CropBoxActive = True
        except:
            pass

        try:
            section.CropBoxVisible = True
        except:
            pass

        t.Commit()

    except:

        try:
            t.RollBack()
        except:
            pass


# ==================================================
# MAIN
# ==================================================

try:

    ref = uidoc.Selection.PickObject(
        ObjectType.Element,
        "Select duct, pipe, conduit or cable tray"
    )

except OperationCanceledException:
    raise SystemExit

except:
    raise SystemExit


elem = doc.GetElement(ref.ElementId)

if not is_supported_element(elem):
    raise SystemExit

create_section(elem)