# -*- coding: utf-8 -*-

from pyrevit import forms
from pyrevit import revit

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    RevitLinkInstance,
    View,
    ViewType,
    Transaction,
    ElementId
)

from System.Collections.Generic import List

doc = revit.doc


class LinkVisibilityWindow(forms.WPFWindow):

    def __init__(self):

        forms.WPFWindow.__init__(
            self,
            "LinkVisibility.xaml"
        )

        self.links = {}
        self.views = {}

        self.load_data()

        self.btnApply.Click += self.apply_clicked
        self.btnSelectAllLinks.Click += self.select_all_links
        self.btnSelectAllViews.Click += self.select_all_views

        self.ShowDialog()

    def load_data(self):

        # Load Links

        links = (
            FilteredElementCollector(doc)
            .OfClass(RevitLinkInstance)
            .ToElements()
        )

        for link in links:

            try:

                if link.GetLinkDocument():
                    name = link.GetLinkDocument().Title
                else:
                    name = link.Name

                # Avoid duplicates

                if name not in self.links:
                    self.links[name] = link
                    self.lstLinks.Items.Add(name)

            except:
                pass

        # Load Views

        views = (
            FilteredElementCollector(doc)
            .OfClass(View)
            .ToElements()
        )

        for view in views:

            try:

                if view.IsTemplate:
                    continue

                if view.ViewType in [
                    ViewType.ProjectBrowser,
                    ViewType.SystemBrowser
                ]:
                    continue

                self.views[view.Name] = view
                self.lstViews.Items.Add(view.Name)

            except:
                pass

    def select_all_links(self, sender, args):

        self.lstLinks.SelectAll()

    def select_all_views(self, sender, args):

        self.lstViews.SelectAll()

    def apply_clicked(self, sender, args):

        selected_links = list(
            self.lstLinks.SelectedItems
        )

        selected_views = list(
            self.lstViews.SelectedItems
        )

        if not selected_views:

            forms.alert(
                "Please select at least one view."
            )
            return

        t = Transaction(
            doc,
            "Update Link Visibility"
        )

        t.Start()

        try:

            for view_name in selected_views:

                view = self.views[view_name]

                for link_name, link in self.links.items():

                    ids = List
                    ids.Add(link.Id)

                    try:

                        if link_name in selected_links:

                            # Visible

                            if view.IsElementHidden(link.Id):

                                view.UnhideElements(ids)

                        else:

                            # Hidden

                            if not view.IsElementHidden(link.Id):

                                view.HideElements(ids)

                    except Exception as ex:
                        print(
                            "{} | {} | {}".format(
                                view.Name,
                                link_name,
                                ex
                            )
                        )

            t.Commit()

            forms.alert(
                "Completed successfully."
            )

            self.Close()

        except Exception as ex:

            t.RollBack()

            forms.alert(
                str(ex),
                title="Error"
            )


LinkVisibilityWindow()