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


from pyrevit import revit, script, forms

from Autodesk.Revit.UI.Selection import (
    ObjectType,
    ISelectionFilter
)

from Autodesk.Revit import Exceptions
from Autodesk.Revit.DB import InsulationLiningBase

uidoc = revit.uidoc
doc = revit.doc

logger = script.get_logger()


# -------------------------------------------------
# Connector Helpers
# -------------------------------------------------
class NoConnectorManagerError(Exception):
    pass


def get_connector_manager(elem):

    try:
        return elem.ConnectorManager
    except:
        pass

    try:
        if elem.MEPModel:
            return elem.MEPModel.ConnectorManager
    except:
        pass

    raise NoConnectorManagerError()


# -------------------------------------------------
# Selection Filter
# -------------------------------------------------
class NoInsulation(ISelectionFilter):

    def AllowElement(self, elem):

        if isinstance(elem, InsulationLiningBase):
            return False

        try:
            get_connector_manager(elem)
            return True
        except:
            return False

    def AllowReference(self, reference, position):
        return True


# -------------------------------------------------
# Disconnect Two Elements
# -------------------------------------------------
def disconnect_two_elements(elem1, elem2):

    try:
        cm1 = get_connector_manager(elem1)
        cm2 = get_connector_manager(elem2)

    except NoConnectorManagerError:
        return

    connectors1 = list(cm1.Connectors)
    connectors2 = list(cm2.Connectors)

    disconnected = False

    for c1 in connectors1:

        if not c1.IsConnected:
            continue

        for ref in c1.AllRefs:

            if ref.Owner.Id == elem2.Id:

                try:
                    c1.DisconnectFrom(ref)
                    disconnected = True
                except:
                    pass

    return disconnected


# -------------------------------------------------
# Main Loop
# -------------------------------------------------
def disconnect():

    try:
            ref1 = uidoc.Selection.PickObject(
                ObjectType.Element,
                NoInsulation(),
                "Pick first element"
            )

    except Exceptions.OperationCanceledException:
        return False

    elem1 = doc.GetElement(ref1.ElementId)

    try:
            ref2 = uidoc.Selection.PickObject(
                ObjectType.Element,
                NoInsulation(),
                "Pick second element"
            )

    except Exceptions.OperationCanceledException:
        return True

    elem2 = doc.GetElement(ref2.ElementId)

    if elem1.Id == elem2.Id:
        return True

    with revit.Transaction("Disconnect Elements"):

        disconnect_two_elements(elem1, elem2)

    return True

# -------------------------------------------------
# Main
# -------------------------------------------------
disconnect()