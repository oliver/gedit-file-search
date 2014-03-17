#    Copyright (C) 2008-2011  Oliver Gerlich <oliver.gerlich@gmx.de>
#    Copyright (C) 2011  Jean-Philippe Fleury <contact@jpfleury.net>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.


#
# Main classes:
# - FileSearchWindowHelper (is instantiated by FileSearchPlugin for every window, and handles integration with main UI)
#
# Helper classes:
# - RecentList (holds list of recently-selected search directories, for search dialog)
# - SearchQuery (holds all parameters for a search; also, can read and write these from/to GSettings)
#

import os
from gi.repository import Gedit, GLib, GObject, Gtk, Gio

from .plugin_common import _, ngettext, gtkToUnicode
from .search_dialog import SearchDialog


ui_str = """<ui>
  <menubar name="MenuBar">
    <menu name="SearchMenu" action="Search">
      <placeholder name="SearchOps_2">
        <menuitem name="FileSearch" action="FileSearch"/>
      </placeholder>
    </menu>
  </menubar>
</ui>
"""



class FileSearchWindowHelper(GObject.Object, Gedit.WindowActivatable):
    __gtype_name__ = "FileSearchWindowHelper"
    window = GObject.property(type=Gedit.Window)

    def __init__(self):
        GObject.Object.__init__(self)

    def do_activate(self):
        #print "file-search: plugin created for", window
        self._window = self.window
        self._bus = self._window.get_message_bus()
        self._filebrowserMenuExt = None
        self._filebrowserItemId = None
        self.searchers = [] # list of existing SearchProcess instances

        self._lastClickIter = None # TextIter at position of last right-click or last popup menu

        self._insert_menu()

        self.handlerIds = []
        self.handlerIds.append( self._window.connect_object("destroy", FileSearchWindowHelper.destroy, self) )
        self.handlerIds.append( self._window.connect_object("tab-added", FileSearchWindowHelper.onTabAdded, self) )
        self.handlerIds.append( self._window.connect_object("tab-removed", FileSearchWindowHelper.onTabRemoved, self) )

        self._searchDialog = None

        self._busHandlerId = self._bus.connect_object("registered", FileSearchWindowHelper.onMessageBusRegister, self)
        self._addFileBrowserMenuItem() # try adding menu items right away

    def onMessageBusRegister (self, obj, method):
        if obj == "/plugins/filebrowser" and (
            method == "extend_context_menu" or method == "add_context_item"):
            GLib.idle_add(lambda: self._addFileBrowserMenuItem())

    def do_deactivate(self):
        #print "file-search: plugin stopped for", self._window

        for h in self.handlerIds:
            self._window.handler_disconnect(h)
        self.handlerIds = None

        self._removeFileBrowserMenuItem()
        self._remove_menu()
        self.destroy()

    def do_update_state(self):
        # Called whenever the window has been updated (active tab
        # changed, etc.)
        #print "file-search: plugin update for", self._window
        pass

    def registerSearcher (self, searcher):
        self.searchers.append(searcher)

    def unregisterSearcher (self, searcher):
        self.searchers.remove(searcher)

    def destroy (self):
        #print "have to destroy %d existing searchers" % len(self.searchers)
        for s in self.searchers[:]:
            s.destroy()
        self._window = None

    def _insert_menu(self):
        if hasattr(self._window, "get_ui_manager"):
            # Get the GtkUIManager
            manager = self._window.get_ui_manager()

            # Create a new action group
            self._action_group = Gtk.ActionGroup(name="FileSearchPluginActions")
            self._action_group.add_actions([("FileSearch", "gtk-find", _("Search files..."),
                                             "<control><shift>F", _("Search in all files in a directory"),
                                             self.on_search_files_activate)])

            # Insert the action group
            manager.insert_action_group(self._action_group, -1)

            # Merge the UI
            self._ui_id = manager.add_ui_from_string(ui_str)
        else:
            action = Gio.SimpleAction(name="gedit-file-search-plugin")
            action.connect("activate", self.on_search_files_activate)
            self._window.add_action(action)

    def _remove_menu (self):
        if hasattr(self._window, "get_ui_manager"):
            manager = self._window.get_ui_manager()
            manager.remove_ui(self._ui_id)
            manager.remove_action_group(self._action_group)
        else:
            self._window.remove_action("gedit-file-search-plugin")

    def on_search_files_activate(self, action, parameter=None):
        self._openSearchDialog()

    def _openSearchDialog (self, searchText = None, searchDirectory = None):
        if not(self._searchDialog):
            self._searchDialog = SearchDialog(self, self._window)
        self._searchDialog.show(searchText, searchDirectory)

    def onTabAdded (self, tab):
        handlerIds = []
        handlerIds.append( tab.get_view().connect_object("button-press-event", FileSearchWindowHelper.onButtonPress, self, tab) )
        handlerIds.append( tab.get_view().connect_object("popup-menu", FileSearchWindowHelper.onPopupMenu, self, tab) )
        handlerIds.append( tab.get_view().connect_object("populate-popup", FileSearchWindowHelper.onPopulatePopup, self, tab) )
        tab.fileSearchPluginHandlers = handlerIds # store list of handler IDs so we can later remove the handlers again

    def onTabRemoved (self, tab):
        if hasattr(tab, "fileSearchPluginHandlers") and tab.fileSearchPluginHandlers:
            for h in tab.fileSearchPluginHandlers:
                tab.get_view().handler_disconnect(h)
            tab.fileSearchPluginHandlers = None

    def onButtonPress (self, event, tab):
        if event.button == 3:
            (bufX, bufY) = tab.get_view().window_to_buffer_coords(Gtk.TextWindowType.TEXT, int(event.x), int(event.y))
            self._lastClickIter = tab.get_view().get_iter_at_location(bufX, bufY)

    def onPopupMenu (self, tab):
        insertMark = tab.get_document().get_insert()
        self._lastClickIter = tab.get_document().get_iter_at_mark(insertMark)

    def onPopulatePopup (self, menu, tab):
        # add separator:
        sepMi = Gtk.SeparatorMenuItem.new()
        sepMi.show()
        menu.prepend(sepMi)

        # first check if user has selected some text:
        selText = ""
        currDoc = tab.get_document()
        selectionIters = currDoc.get_selection_bounds()
        if selectionIters and len(selectionIters) == 2:
            # Only use selected text if it doesn't span multiple lines:
            if selectionIters[0].get_line() == selectionIters[1].get_line():
                selText = selectionIters[0].get_text(selectionIters[1])

        # if no text is selected, use current word under cursor:
        if not(selText) and self._lastClickIter:
            startIter = self._lastClickIter.copy()
            if not(startIter.starts_word()):
                startIter.backward_word_start()
            endIter = startIter.copy()
            if endIter.inside_word():
                endIter.forward_word_end()
            selText = startIter.get_text(endIter)

        # add actual menu item:
        if selText:
            menuSelText = gtkToUnicode(selText)
            if len(menuSelText) > 30:
                menuSelText = menuSelText[:30] + u"\u2026" # ellipsis character
            menuText = _('Search files for "%s"') % menuSelText
        else:
            menuText = _('Search files...')
        mi = Gtk.MenuItem.new_with_label(menuText)
        mi.connect_object("activate", FileSearchWindowHelper.onMenuItemActivate, self, selText)
        mi.show()
        menu.prepend(mi)

    def onMenuItemActivate (self, searchText):
        self._openSearchDialog(searchText)

    def _addFileBrowserMenuItem (self):
        if self._bus.is_registered("/plugins/filebrowser", "extend_context_menu"):
            # use new-style filebrowser context menu API
            action = Gio.SimpleAction(name="gedit-file-search-filebrowser")
            action.connect("activate", lambda action, parameter: self.onFbMenuItemActivate(action))
            self.window.add_action(action)

            msg = self._bus.send_sync("/plugins/filebrowser", "extend_context_menu")
            self._filebrowserMenuExt = msg.props.extension
            item = Gio.MenuItem.new(_("Search files..."), "win.gedit-file-search-filebrowser")
            self._filebrowserMenuExt.append_menu_item(item)

        elif self._bus.is_registered("/plugins/filebrowser", "add_context_item"):
            # use old-style filebrowser context menu API
            fbAction = Gtk.Action(name="search-files-plugin", label=_("Search files..."),
                tooltip=_("Search in all files in a directory"), stock_id=None)
            replyMsg = self._bus.send_sync("/plugins/filebrowser", "add_context_item",
                action=fbAction, path="/FilePopup/FilePopup_Opt3")
            self._filebrowserItemId = replyMsg.id
            fbAction.connect('activate', self.onFbMenuItemActivate)

    def _removeFileBrowserMenuItem (self):
        if self._filebrowserMenuExt:
            self.window.remove_action("gedit-file-search-filebrowser")
            self.menu_ext = None
        elif self._filebrowserItemId:
            try:
                self._bus.send_sync("/plugins/filebrowser", "remove_context_item",
                    id=self._filebrowserItemId)
            except:
                pass

    def onFbMenuItemActivate (self, action):
        responseMsg = self._bus.send_sync('/plugins/filebrowser', 'get_view')
        fbView = responseMsg.view
        (model, rowPathes) = fbView.get_selection().get_selected_rows()

        selectedFileObj = None
        for rowPath in rowPathes:
            fileFlags = model[rowPath][3]
            isDirectory = bool(fileFlags & 1)
            if isDirectory:
                selectedFileObj = model[rowPath][2]
                break

        if selectedFileObj is None:
            msg = self._bus.send_sync('/plugins/filebrowser', 'get_root')
            selectedFileObj = msg.location
        selectedDir = selectedFileObj.get_path()

        self._openSearchDialog(searchDirectory=selectedDir)


class FileSearchAppHelper(GObject.Object, Gedit.AppActivatable):
    __gtype_name__ = "FileSearchAppHelper"
    app = GObject.property(type=Gedit.App)

    def __init__(self):
        GObject.Object.__init__(self)

    def do_activate(self):
        if hasattr(self, "extend_menu"):
            self.app.add_accelerator("<control><shift>F", "win.gedit-file-search-plugin", None)

            self.menu_ext = self.extend_menu("search-section")
            item = Gio.MenuItem.new(_("Search files..."), "win.gedit-file-search-plugin")
            self.menu_ext.append_menu_item(item)

    def do_deactivate(self):
        if hasattr(self, "extend_menu"):
            self.app.remove_accelerator("win.gedit-file-search-plugin", None)
            self.menu_ext = None

