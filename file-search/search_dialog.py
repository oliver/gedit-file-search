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
# - SearchDialog (holds the search dialog)
#
# Helper classes:
# - RecentList (holds list of recently-selected search directories, for search dialog)
# - SearchQuery (holds all parameters for a search; also, can read and write these from/to GSettings)
#

import os
try:
    from urllib.parse import quote, unquote
except:
    from urllib import quote, unquote
from gi.repository import Gtk, Gdk, Gio, Pango

from .plugin_common import _, ngettext, APP_NAME, resourceDir, gladeFile, isUnicode, gtkToUnicode
from .result_panel import ResultPanel


GSETTINGS_SCHEMA_NAME = "io.github.oliver.gedit-file-search"


class RecentList:
    """
    Encapsulates a gtk.ListStore that stores a generic list of "most recently used entries"
    """
    def __init__ (self, gclient, confKey, maxEntries = 10):
        self.gclient = gclient
        self.confKey = confKey
        self.store = Gtk.ListStore(str, bool, bool) # text, save-to-gsettings, is-separator
        self._maxEntries = maxEntries
        self._haveSeparator = False

        elementList = self.gclient.get_strv(self.confKey)
        elementList.reverse()
        for e in elementList:
            if e and len(e) > 0:
                decodedName = unquote(gtkToUnicode(e))
                self.add(decodedName, False)

        # TODO: also listen for gsettings changes, and reload the list then

    def add (self, entrytext, doStore=True):
        "Add an entry that was just used."
        assert(isUnicode(entrytext))

        for row in self.store:
            if row[0] == entrytext:
                it = self.store.get_iter(row.path)
                self.store.remove(it)

        treeiter = self.store.prepend()
        self.store.set_row(treeiter, [entrytext, True, False])

        # remove excess elements from end of list
        for i in range(len(self.store)-1, self._maxEntries-1, -1):
            if self.store[i][1] and not(self.store[i][2]): # only remove entries which have do-store set and is-separator unset
                it = self.store.get_iter(self.store[i].path)
                self.store.remove(it)

        if doStore:
            entries = []
            for e in self.store:
                if not(e[1]):
                    continue
                assert(type(e[0]) == str)
                encodedName = quote(e[0])
                entries.append(encodedName)
            self.gclient.set_strv(self.confKey, entries)


    def addTemp (self, entrytext):
        if not(self._haveSeparator):
            self.store.append(["(_sep_)", False, True])
            self._haveSeparator = True
        self.store.append([entrytext, False, False])

    def resetTemps (self):
        for row in self.store:
            if not(row[1]):
                it = self.store.get_iter(row.path)
                self.store.remove(it)
        self._haveSeparator = False

    def separatorRowFunc (self, model, it, data):
        return model[it][2]

    def isEmpty (self):
        return (len(self.store) == 0)

    def topEntry (self):
        if self.isEmpty():
            return None
        else:
            return self.store[0][0]


class SearchQuery:
    """
    Contains all parameters for a single search action.
    """
    def __init__ (self, gclient):
        self.text = ''
        self.directory = ''
        self.fileTypeString = ''
        self.caseSensitive     = gclient.get_boolean("case-sensitive")
        self.wholeWord         = gclient.get_boolean("whole-word")
        self.isRegExp          = gclient.get_boolean("is-reg-exp")
        self.includeSubfolders = gclient.get_boolean("include-subfolders")
        self.excludeHidden     = gclient.get_boolean("exclude-hidden")
        self.excludeBackup     = gclient.get_boolean("exclude-backup")
        self.excludeVCS        = gclient.get_boolean("exclude-vcs")
        self.selectFileTypes   = gclient.get_boolean("select-file-types")

    def storeDefaults (self, gclient):
        gclient.set_boolean("case-sensitive", self.caseSensitive)
        gclient.set_boolean("whole-word", self.wholeWord)
        gclient.set_boolean("is-reg-exp", self.isRegExp)
        gclient.set_boolean("include-subfolders", self.includeSubfolders)
        gclient.set_boolean("exclude-hidden", self.excludeHidden)
        gclient.set_boolean("exclude-backup", self.excludeBackup)
        gclient.set_boolean("exclude-vcs", self.excludeVCS)
        gclient.set_boolean("select-file-types", self.selectFileTypes)

    def parseFileTypeString (self):
        "Returns a list with the separate file globs from fileTypeString"
        return self.fileTypeString.split()


class SearchDialog:
    def __init__ (self, pluginHelper, window):
        self._pluginHelper = pluginHelper
        self._window = window
        self._dialog = None
        self.gclient = self.initGSettings()

        self._lastSearchTerms = RecentList(self.gclient, "recent-search-terms")
        self._lastDirs = RecentList(self.gclient, "recent-dirs")
        self._lastTypes = RecentList(self.gclient, "recent-types")

        if self._lastTypes.isEmpty():
            # add some default file types
            self._lastTypes.add('*.C *.cpp *.cxx *.h *.hpp')
            self._lastTypes.add('*.c *.h')
            self._lastTypes.add('*.py')
            self._lastTypes.add('*')

        self._lastDir = None
        self._autoCompleteList = None

    def initGSettings(self):
        schemaSource = Gio.SettingsSchemaSource.new_from_directory(
            resourceDir, Gio.SettingsSchemaSource.get_default(), False)
        schema = schemaSource.lookup(GSETTINGS_SCHEMA_NAME, False)
        return Gio.Settings.new_full(schema, None, None)

    def show(self, searchText=None, searchDirectory=None):
        "Displays the search dialog"

        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(APP_NAME)
        self.builder.add_objects_from_file(gladeFile, ['searchDialog'])
        self.builder.connect_signals(self)

        self._dialog = self.builder.get_object('searchDialog')
        self._dialog.set_transient_for(self._window)

        #
        # set initial values for search dialog widgets
        #

        # get base directory of currently opened file:
        currentDocDir = None
        if self._window.get_active_tab():
            gFilePath = self._window.get_active_tab().get_document().get_location()
            if gFilePath != None:
                currentDocDir = gFilePath.get_parent().get_path()

        if searchDirectory is not None:
            searchDir = searchDirectory
        else:
            # find a nice default value for the search directory:
            if self._lastDir != None:
                # if possible, use same directory as in last search:
                searchDir = self._lastDir
            else:
                # this is the first search since opening this Gedit window;
                # try to use directory of displayed file
                if currentDocDir is not None:
                    searchDir = currentDocDir
                else:
                    searchDir = os.getcwd() # fall back to Gedit's current working dir

        searchDir = os.path.normpath(searchDir) + "/"

        # ... and display that in the text field:
        self.builder.get_object('cboSearchDirectoryEntry').set_text(searchDir)

        # Set up autocompletion for search directory:
        completion = Gtk.EntryCompletion()
        self.builder.get_object('cboSearchDirectoryEntry').set_completion(completion)
        self._autoCompleteList = Gtk.ListStore(str)
        completion.set_model(self._autoCompleteList)
        completion.set_text_column(0)

        # Fill the drop-down part of the text field with recent dirs:
        cboLastDirs = self.builder.get_object('cboSearchDirectoryList')
        cboLastDirs.set_model(self._lastDirs.store)
        cboLastDirs.set_entry_text_column(0)
        cboLastDirs.set_row_separator_func(self._lastDirs.separatorRowFunc, None)

        self._lastDirs.resetTemps()
        if currentDocDir is not None:
            self._lastDirs.addTemp(currentDocDir)

        # TODO: the algorithm to select a good default search dir could probably be improved...

        if searchText == None:
            searchText = ""
            if self._window.get_active_tab():
                currDoc = self._window.get_active_document()
                selectionIters = currDoc.get_selection_bounds()
                if selectionIters and len(selectionIters) == 2:
                    # Only use selected text if it doesn't span multiple lines:
                    if selectionIters[0].get_line() == selectionIters[1].get_line():
                        searchText = selectionIters[0].get_text(selectionIters[1])
        self.builder.get_object('cboSearchTextEntry').set_text(searchText)

        cboLastSearches = self.builder.get_object('cboSearchTextList')
        cboLastSearches.set_model(self._lastSearchTerms.store)
        cboLastSearches.set_entry_text_column(0)

        # Fill list of file types:
        cboLastTypes = self.builder.get_object('cboFileTypeList')
        cboLastTypes.set_model(self._lastTypes.store)
        cboLastTypes.set_entry_text_column(0)

        if not(self._lastTypes.isEmpty()):
            typeListString = self._lastTypes.topEntry()
            self.builder.get_object('cboFileTypeEntry').set_text(typeListString)


        # get default values for other controls from GSettings:
        query = SearchQuery(self.gclient)
        self.builder.get_object('cbCaseSensitive').set_active(query.caseSensitive)
        self.builder.get_object('cbRegExp').set_active(query.isRegExp)
        self.builder.get_object('cbWholeWord').set_active(query.wholeWord)
        self.builder.get_object('cbIncludeSubfolders').set_active(query.includeSubfolders)
        self.builder.get_object('cbExcludeHidden').set_active(query.excludeHidden)
        self.builder.get_object('cbExcludeBackups').set_active(query.excludeBackup)
        self.builder.get_object('cbExcludeVCS').set_active(query.excludeVCS)
        self.builder.get_object('cbSelectFileTypes').set_active(query.selectFileTypes)
        self.builder.get_object('cboFileTypeList').set_sensitive( query.selectFileTypes )

        #
        # actually display search dialog
        #

        inputValid = False
        while not(inputValid):
            # display and run the search dialog (in a loop until all fields are correctly entered)
            result = self._dialog.run()
            if result != 1:
                self._dialog.destroy()
                return

            searchText = gtkToUnicode(self.builder.get_object('cboSearchTextEntry').get_text())
            searchDir = gtkToUnicode(self.builder.get_object('cboSearchDirectoryEntry').get_text())
            typeListString = gtkToUnicode(self.builder.get_object('cboFileTypeEntry').get_text())

            searchDir = os.path.expanduser(searchDir)
            searchDir = os.path.normpath(searchDir) + "/"

            if searchText == "":
                print("internal error: search text is empty!")
            elif not(os.path.exists(searchDir)):
                msgDialog = Gtk.MessageDialog(self._dialog, Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
                    Gtk.MessageType.ERROR, Gtk.ButtonsType.OK, _("Directory does not exist"))
                msgDialog.format_secondary_text(_("The specified directory does not exist."))
                msgDialog.run()
                msgDialog.destroy()
            else:
                inputValid = True

        #
        # handle dialog input
        #

        query.text = searchText
        query.directory = searchDir
        query.caseSensitive = self.builder.get_object('cbCaseSensitive').get_active()
        query.isRegExp = self.builder.get_object('cbRegExp').get_active()
        query.wholeWord = self.builder.get_object('cbWholeWord').get_active()
        query.includeSubfolders = self.builder.get_object('cbIncludeSubfolders').get_active()
        query.excludeHidden = self.builder.get_object('cbExcludeHidden').get_active()
        query.excludeBackup = self.builder.get_object('cbExcludeBackups').get_active()
        query.excludeVCS = self.builder.get_object('cbExcludeVCS').get_active()
        query.selectFileTypes = self.builder.get_object('cbSelectFileTypes').get_active()
        query.fileTypeString = typeListString

        self._dialog.destroy()

        #print "searching for '%s' in '%s'" % (searchText, searchDir)

        self._lastSearchTerms.add(searchText)
        self._lastDirs.add(searchDir)
        self._lastTypes.add(typeListString)
        query.storeDefaults(self.gclient)
        self._lastDir = searchDir

        # the ResultPanel object will also start the actual search:
        ResultPanel(self._window, self._pluginHelper, query)

    def on_cboSearchTextEntry_changed (self, textEntry):
        """
        Is called when the search text entry is modified;
        disables the Search button whenever no search text is entered.
        """
        if textEntry.get_text() == "":
            self.builder.get_object('btnSearch').set_sensitive(False)
        else:
            self.builder.get_object('btnSearch').set_sensitive(True)

    def on_cbSelectFileTypes_toggled (self, checkbox):
        self.builder.get_object('cboFileTypeList').set_sensitive( checkbox.get_active() )

    def on_cboSearchDirectoryEntry_changed (self, entry):
        text = entry.get_text()
        if text and self._autoCompleteList != None:
            path = os.path.dirname(text)
            start = os.path.basename(text)

            self._autoCompleteList.clear()
            try:
                files = os.listdir(path)
            except OSError:
                return
            for f in files:
                if not(os.path.isdir(path + os.sep + f)):
                    continue
                if f.startswith(".") and not(start.startswith(".")):
                    # show hidden dirs only if explicitly requested by user
                    continue
                if f.startswith(start):
                    if path == "/":
                        match = path + f + os.sep
                    else:
                        match = path + os.sep + f + os.sep
                    self._autoCompleteList.append([match])

    def on_btnBrowse_clicked (self, button):
        fileChooser = Gtk.FileChooserDialog(title=_("Select Directory"),
            transient_for=self._dialog,
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        fileChooser.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        fileChooser.add_button(Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        fileChooser.set_default_response(Gtk.ResponseType.OK)
        fileChooser.set_local_only(False)
        fileChooser.set_filename( self.builder.get_object('cboSearchDirectoryEntry').get_text() )

        response = fileChooser.run()
        if response == Gtk.ResponseType.OK:
            selectedDir = os.path.normpath( fileChooser.get_filename() ) + "/"
            self.builder.get_object('cboSearchDirectoryEntry').set_text(selectedDir)
        fileChooser.destroy()

