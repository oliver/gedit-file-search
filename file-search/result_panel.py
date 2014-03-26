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
# - ResultPanel (is instantiated by FileSearchWindowHelper for every search, and holds the result tab)
#


import os
try:
    from urllib.parse import quote
except:
    from urllib import quote
from gi.repository import Gedit, GLib, Gtk, Gdk, Gio, Pango, GtkSource

from .plugin_common import _, ngettext, APP_NAME, gladeFile, isUnicode
from .searcher import SearchProcess, buildQueryRE



class ResultPanel:
    """
    Gets a search query (and related info) and then handles everything related
    to that single file search:
    - creating a result window
    - starting grep (through SearchProcess)
    - displaying matches
    A ResultPanel object lives until its result panel is closed.
    """
    def __init__ (self, window, pluginHelper, query):
        self._window = window
        self.pluginHelper = pluginHelper
        self.pluginHelper.registerSearcher(self)
        self.query = query
        self.files = {}
        self.numMatches = 0
        self.numLines = 0
        self.wasCancelled = False
        self.searchProcess = None
        self._collapseAll = False # if true, new nodes will be displayed collapsed

        self._createResultPanel()
        self._updateSummary()

        searchSummary = "<span size=\"smaller\">" + \
            _("searching for <i>%(keywords)s</i> in <i>%(folder)s</i>") % \
                {
                    'keywords': escapeMarkup(query.text),
                    'folder': escapeMarkup(GLib.filename_display_name(query.directory))
                } + \
            "</span>"
        it = self.treeStore.append(None, None)
        self.treeStore.set(it, 0, searchSummary, 1, "", 2, 0)

        self.searchProcess = SearchProcess(query, self)
        self._updateSummary()

    def _createResultPanel (self):
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(APP_NAME)
        self.builder.add_objects_from_file(gladeFile, ['hbxFileSearchResult'])
        self.builder.connect_signals(self)
        resultContainer = self.builder.get_object('hbxFileSearchResult')

        resultContainer.resultpanel = self # keep a reference to avoid destruction of panel

        tabTitle = self.query.text
        if len(tabTitle) > 30:
            tabTitle = tabTitle[:30] + u"\u2026" # ellipsis character 
        panel = self._window.get_bottom_panel()
        if hasattr(panel, "add_titled"):
            panel.add_titled(resultContainer, str(self), tabTitle)
            panel.set_visible_child(resultContainer)
        else:
            panel.add_item_with_stock_icon(resultContainer, str(self), tabTitle, "gtk-find")
            panel.activate_item(resultContainer)

        editBtn = self.builder.get_object("btnModifyFileSearch")
        editBtn.set_label("gtk-stop")

        panel.set_property("visible", True)


        self.treeStore = Gtk.TreeStore(str, object, int) # markup, file name, line number
        self.treeView = self.builder.get_object('tvFileSearchResult')
        self.treeView.set_model(self.treeStore)

        self.treeView.set_search_equal_func(resultSearchCb, None)

        tc = Gtk.TreeViewColumn("File", Gtk.CellRendererText(), markup=0)
        self.treeView.append_column(tc)

    def destroy (self):
        if self.searchProcess:
            self.searchProcess.destroy()
            self.searchProcess = None

        panel = self._window.get_bottom_panel()
        resultContainer = self.builder.get_object('hbxFileSearchResult')
        resultContainer.resultpanel = None
        if not(hasattr(panel, "add_titled")):
            panel.remove_item(resultContainer)
        resultContainer.destroy()
        resultContainer = None
        self.treeStore.clear()
        self.treeStore = None
        self.treeView = None
        self._window = None
        self.files = {}
        self.builder = None
        self.pluginHelper.unregisterSearcher(self)

    def on_btnClose_clicked (self, button):
        self.destroy()

    def on_btnModify_clicked (self, button):
        if not(self.searchProcess):
            # TODO: edit search params
            pass
        else:
            # cancel search
            self.searchProcess.cancel()
            self.wasCancelled = True


    def handleResult (self, file, lineno, linetext):
        assert not(isUnicode(file)) # for opening files, raw file names are needed
        assert isUnicode(linetext)
        expandRow = False
        if not(file in self.files):
            it = self._addResultFile(file)
            self.files[file] = it
            expandRow = True
        else:
            it = self.files[file]
        if self._collapseAll:
            expandRow = False
        self._addResultLine(it, lineno, linetext)
        if expandRow:
            path = self.treeStore.get_path(it)
            self.treeView.expand_row(path, False)
        self._updateSummary()

    def handleFinished (self):
        #print "(finished)"
        if not(self.builder):
            return

        self.searchProcess = None
        editBtn = self.builder.get_object("btnModifyFileSearch")
        editBtn.hide()
        editBtn.set_label("gtk-edit")

        self._updateSummary()

        if self.wasCancelled:
            line = "<i><span foreground=\"red\">" + _("(search was cancelled)") + "</span></i>"
        elif self.numMatches == 0:
            line = "<i>" + _("(no matching files found)") + "</i>"
        else:
            line = "<i>" + ngettext("found %d match", "found %d matches", self.numMatches) % self.numMatches
            line += ngettext(" (%d line)", " (%d lines)", self.numLines) % self.numLines
            line += ngettext(" in %d file", " in %d files", len(self.files)) % len(self.files) + "</i>"
        it = self.treeStore.append(None, None)
        self.treeStore.set(it, 0, line, 1, "", 2, 0)

    def _updateSummary (self):
        summary = ngettext("<b>%d</b> match", "<b>%d</b> matches", self.numMatches) % self.numMatches
        summary += "\n" + ngettext("in %d file", "in %d files", len(self.files)) % len(self.files)
        if self.searchProcess:
            summary += u"\u2026" # ellipsis character
        self.builder.get_object("lblNumMatches").set_label(summary)

    def _addResultFile (self, filename):
        dispFilename = filename

        # remove leading search directory part if present:
        dispFilename = dispFilename.decode("utf-8", "replace")
        if dispFilename.startswith(self.query.directory):
            dispFilename = dispFilename[ len(self.query.directory): ]
            dispFilename.lstrip("/")

        (directory, file) = os.path.split( dispFilename )
        if directory:
            directory = os.path.normpath(directory) + "/"

        line = "%s<b>%s</b>" % (escapeMarkup(directory), escapeMarkup(file))
        it = self.treeStore.append(None, None)
        self.treeStore.set(it, 0, line, 1, filename, 2, 0)
        return it

    def _addResultLine (self, it, lineno, linetext):
        addTruncationMarker = False
        if len(linetext) > 1000:
            linetext = linetext[:1000]
            addTruncationMarker = True

        assert(isUnicode(linetext))
        linetext = linetext.replace('\0', u'\uFFFD') # Pango can't handle NULL bytes in markup

        if not(self.query.isRegExp):
            (linetext, numLineMatches) = escapeAndHighlight(linetext, self.query.text, self.query.caseSensitive, self.query.wholeWord)
            self.numMatches += numLineMatches
        else:
            linetext = escapeMarkup(linetext)
            self.numMatches += 1
        self.numLines += 1

        if addTruncationMarker:
            linetext += "</span><span size=\"smaller\"><i> [...]</i>"
        line = "<b>%d:</b> <span foreground=\"blue\">%s</span>" % (lineno, linetext)
        newIt = self.treeStore.append(it, None)
        self.treeStore.set(newIt, 0, line, 2, lineno)

    def on_row_activated (self, widget, path, col):
        selectedIter = self.treeStore.get_iter(path)
        parentIter = self.treeStore.iter_parent(selectedIter)
        lineno = 0
        if parentIter == None:
            file = self.treeStore.get_value(selectedIter, 1)
        else:
            file = self.treeStore.get_value(parentIter, 1)
            lineno = self.treeStore.get_value(selectedIter, 2)

        if not(file):
            return

        uri="file://%s" % quote(file)
        location=Gio.file_new_for_uri(uri)
        Gedit.commands_load_location(self._window, location, None, lineno, -1)

        # use an Idle handler so the document has time to load:  
        GLib.idle_add(self.onDocumentOpenedCb)

    def onDocumentOpenedCb (self):
        self._window.get_active_view().grab_focus()
        currDoc = self._window.get_active_document()

        # highlight matches in opened document:
        if hasattr(GtkSource, "SearchSettings"):
            # set_search_context() is necessary to integrate with existing Gedit search
            # (but is not universally available - see bgo#726408)
            if hasattr(currDoc, "set_search_context"):
                settings = GtkSource.SearchSettings()
                settings.set_search_text(self.query.text)
                settings.set_case_sensitive(self.query.caseSensitive)
                settings.set_at_word_boundaries(self.query.wholeWord)
                context = GtkSource.SearchContext.new(currDoc, settings)
                currDoc.set_search_context(context)
        else:
            flags = 0
            if self.query.caseSensitive:
                flags |= 4
            if self.query.wholeWord:
                flags |= 2
            currDoc.set_search_text(self.query.text, flags)

        return False

    def on_tvFileSearchResult_button_press_event (self, treeview, event):
        if event.button == 3:
            treeview.grab_focus()

            path = treeview.get_path_at_pos(int(event.x), int(event.y))
            if path is not None:
                treeview.set_cursor(path[0], path[1], False)

            menu = Gtk.Menu()
            self.contextMenu = menu # need to keep a reference to the menu

            mi = Gtk.ImageMenuItem.new_from_stock("gtk-copy", None)
            if path is not None:
                mi.connect_object("activate", ResultPanel.onCopyActivate, self, treeview, path[0])
            else:
                mi.set_sensitive(False)
            mi.show()
            menu.append(mi)

            mi = Gtk.SeparatorMenuItem.new()
            mi.show()
            menu.append(mi)

            mi = Gtk.MenuItem(label=_("Expand All"))
            mi.connect_object("activate", ResultPanel.onExpandAllActivate, self, treeview)
            mi.show()
            menu.append(mi)

            mi = Gtk.MenuItem(label=_("Collapse All"))
            mi.connect_object("activate", ResultPanel.onCollapseAllActivate, self, treeview)
            mi.show()
            menu.append(mi)

            menu.popup(None, None, None, None, event.button, event.time)
            return True
        else:
            return False

    def onCopyActivate (self, treeview, path):
        it = treeview.get_model().get_iter(path)
        markupText = treeview.get_model().get_value(it, 0)
        plainText = Pango.parse_markup(markupText, -1, u'\x00')[2]

        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(plainText, -1)
        clipboard.store()

    def onExpandAllActivate (self, treeview):
        self._collapseAll = False
        treeview.expand_all()

    def onCollapseAllActivate (self, treeview):
        self._collapseAll = True
        treeview.collapse_all()


def resultSearchCb (model, column, key, it, userdata):
    """Callback function for searching in result list"""
    lineText = model.get_value(it, column)
    plainText = Pango.parse_markup(lineText, -1, u'\x00')[2] # remove Pango markup

    # for file names, add a leading slash before matching:
    parentIter = model.iter_parent(it)
    if parentIter == None and not(plainText.startswith("/")):
        plainText = "/" + plainText

    # if search text contains only lower-case characters, do case-insensitive matching:
    if key.islower():
        plainText = plainText.lower()

    # if the line contains the search text, it matches:
    if plainText.find(key) >= 0:
        return False

    # line doesn't match:
    return True


def escapeMarkup (origText):
    "Replaces Pango markup special characters with their escaped replacements"
    text = origText
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text

def escapeAndHighlight (origText, searchText, caseSensitive, wholeWord):
    """
    Replaces Pango markup special characters, and adds highlighting markup
    around text fragments that match searchText.
    """

    # split origText by searchText; the resulting list will contain normal text
    # and matching text interleaved (if two matches are adjacent in origText,
    # they will be separated by an empty string in the resulting list).
    matchLen = len(searchText)
    fragments = []
    startPos = 0
    text = origText[:]
    pattern = buildQueryRE(searchText, caseSensitive, wholeWord)
    while True:
        m = pattern.search(text, startPos)
        if m is None:
            break
        pos = m.start()

        preStr = origText[startPos:pos]
        matchStr = origText[pos:pos+matchLen]
        fragments.append(preStr)
        fragments.append(matchStr)
        startPos = pos+matchLen
    fragments.append(text[startPos:])

    numMatches = (len(fragments) - 1) / 2

    if len(fragments) < 3:
        print("too few fragments (got only %d)" % len(fragments))
        print("text: '%s'" % origText.encode("utf8", "replace"))
        numMatches += 1
    #assert(len(fragments) > 2)

    # join fragments again, adding markup around matches:
    retText = ""
    highLight = False
    for f in fragments:
        f = escapeMarkup(f)
        if highLight:
            retText += "<span background=\"#FFFF00\">%s</span>" % f
        else:
            retText += f
        highLight = not(highLight)
    return (retText, numMatches)
