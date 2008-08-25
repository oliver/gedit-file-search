#    Gedit file search plugin
#    Copyright (C) 2008  Oliver Gerlich <oliver.gerlich@gmx.de>
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
# - FileSearchWindowHelper (is instantiated by FileSearchPlugin for every window, and holds the search dialog)
# - FileSearcher (is instantiated by FileSearchWindowHelper for every search, and holds the result tab)
# - FileSearchPlugin (the actual plugin, which implements the Gedit plugin interface)
#
# Search functionality classes:
# - SearchProcess (starts the external find/grep commands for searching, and reads the output)
# - GrepParser (accumulates output from grep command and parses it to extract files, line numbers, and lines)
#
# Helper classes:
# - ProcessInfo (gets process tree info, for killing search processes)
# - RecentDirs (holds list of recently-selected search directories, for search dialog)
#


import os
import gedit
import gtk
import gobject
import fcntl
import popen2
import re
import urllib

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


class ProcessInfo:
    """
    Parses the process table in /proc and offers info
    about processes and their parents.
    """
    def __init__ (self):

        self.pids = []

        intRe = re.compile('^\d+$')
        nameRe = re.compile('^Name:\s+(\w+)$')
        ppidRe = re.compile('^PPid:\s+(\d+)$')
        for d in os.listdir('/proc'):
            if intRe.match(d):
                pid = int(d)
                name = ''
                ppid = 0
                fileName = "/proc/%d/status" % pid
                fd = open(fileName, "r")
                for line in fd.readlines():
                    m = nameRe.match(line)
                    if m:
                        name = m.group(1)
                        continue
                    m = ppidRe.match(line)
                    if m:
                        ppid = int(m.group(1))
                        continue
                self.pids.append( (pid, name, ppid) )

    def getName (self, mainPid):
        for pid in self.pids:
            if pid[0] == mainPid:
                return pid[1]
        return None

    def getDirectChildren (self, mainPid):
        res = []
        for pid in self.pids:
            if pid[2] == mainPid:
                res.append(pid[0])
        return res

    def getAllChildren (self, mainPid):
        "Returns a list of all (direct and indirect) child processes"
        res = []
        directChildren = self.getDirectChildren(mainPid)
        res.extend(directChildren)
        for pid in directChildren:
            res.extend( self.getAllChildren(pid) )
        return res


class RecentDirs:
    """
    Encapsulates a gtk.ListStore that stores a list of recent directories
    """
    def __init__ (self, maxEntries = 10):
        self.store = gtk.ListStore(str)
        self.maxEntries = maxEntries

    def add (self, dirname):
        "Add a directory that was just used."

        for row in self.store:
            if row[0] == dirname:
                it = self.store.get_iter(row.path)
                self.store.remove(it)

        self.store.prepend([dirname])

    def isEmpty (self):
        return (len(self.store) == 0)

    def topEntry (self):
        if self.isEmpty():
            return None
        else:
            return self.store[0][0]


class SearchProcess:
    """
    - starts the search command
    - asynchronously waits for output from search command
    - passes output to GrepParser
    - kills search command if requested
    """
    def __init__ (self, queryText, directory, resultHandler):
        self.parser = GrepParser(resultHandler)

        cmd = "find '%s' -print0 2> /dev/null | xargs -0 grep -H -I -n -s -Z -e '%s'" % (directory, queryText)
        #cmd = "sleep 2; echo -n 'abc'; sleep 3; echo 'xyz'; sleep 3"
        #cmd = "sleep 2"
        #cmd = "echo 'abc'"
        #print "executing command: %s" % cmd
        self.popenObj = popen2.Popen3(cmd)
        self.pipe = self.popenObj.fromchild

        # make pipe non-blocking:
        fl = fcntl.fcntl(self.pipe, fcntl.F_GETFL)
        fcntl.fcntl(self.pipe, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        #print "(add watch)"
        gobject.io_add_watch(self.pipe, gobject.IO_IN | gobject.IO_ERR | gobject.IO_HUP,
            self.onPipeReadable)

    def onPipeReadable (self, fd, cond):
        #print "condition: %s" % cond
        if (cond & gobject.IO_IN):
            readText = self.pipe.read(1000)
            #print "(read %d bytes)" % len(readText)
            if self.parser:
                self.parser.parseFragment(readText)
            return True
        else:
            if self.parser:
                self.parser.finish()
            #print "(closing pipe)"
            result = self.pipe.close()
            if result == None:
                #print "(search finished successfully)"
                pass
            else:
                #print "(search finished with exit code %d; exited: %s, exit status: %d)" % (result,
                #str(os.WIFEXITED(result)), os.WEXITSTATUS(result))
                pass
            self.popenObj.wait()
            return False

    def cancel (self):
        print "(cancelling search command)"
        mainPid = self.popenObj.pid
        pi = ProcessInfo()
        allProcs = [mainPid]
        allProcs.extend(pi.getAllChildren(mainPid))
        print "main pid: %d; num procs: %d" % (mainPid, len(allProcs))
        for pid in allProcs:
            print "killing pid %d (name: %s)" % (pid, pi.getName(pid))
            os.kill(pid, 15)

    def destroy (self):
        """
        Force search process to stop as soon as possible, and ignore any further results.
        """
        self.cancel()
        self.parser = None


class GrepParser:
    """
    - buffers output from grep command
    - extracts full (nul-delimited) lines
    - parses lines for file name, line number, and line text
    - passes extracted info to resultHandler
    """
    def __init__ (self, resultHandler):
        self.buf = ""
        self.resultHandler = resultHandler

    def parseFragment (self, text):
        self.buf = self.buf + text

        while '\n' in self.buf:
            pos = self.buf.index('\n')
            line = self.buf[:pos]
            self.buf = self.buf[pos + 1:]
            self.parseLine(line)

    def parseLine (self, line):
        filename = None
        lineno = None
        linetext = ""
        if '\0' in line:
            [filename, end] = line.split('\0', 1)
            if ':' in end:
                [lineno, linetext] = end.split(':', 1)
                lineno = int(lineno)

        if lineno == None:
            #print "(ignoring invalid line)"
            pass
        else:
            # Assume that grep output is in UTF8 encoding, and convert it to
            # a Unicode string. Also, sanitize non-UTF8 characters.
            # TODO: what's the actual encoding of grep's output?
            linetext = unicode(linetext, 'utf8', 'replace')
            #print "file: '%s'; line: %d; text: '%s'" % (filename, lineno, linetext)
            self.resultHandler.handleResult(filename, lineno, linetext)

    def finish (self):
        self.parseFragment("")
        if self.buf != "":
            self.parseLine(self.buf)
        self.resultHandler.handleFinished()


class FileSearchWindowHelper:
    def __init__(self, plugin, window):
        print "Plugin created for", window
        self._window = window
        self._plugin = plugin
        self._dialog = None
        self.searchers = [] # list of existing SearchProcess instances

        self._lastDirs = RecentDirs()

        self._insert_menu()

        self._window.connect_object("destroy", FileSearchWindowHelper.destroy, self)

    def deactivate(self):
        print "Plugin stopped for", self._window
        self.destroy()

    def destroy (self):
        print "have to destroy %d existing searchers" % len(self.searchers)
        for s in self.searchers:
            s.destroy()
        self._window = None
        self._plugin = None

    def update_ui(self):
        # Called whenever the window has been updated (active tab
        # changed, etc.)
        print "Plugin update for", self._window

    def registerSearcher (self, searcher):
        self.searchers.append(searcher)

    def unregisterSearcher (self, searcher):
        self.searchers.remove(searcher)

    def _insert_menu(self):
        # Get the GtkUIManager
        manager = self._window.get_ui_manager()

        # Create a new action group
        self._action_group = gtk.ActionGroup("FileSearchPluginActions")
        self._action_group.add_actions([("FileSearch", "gtk-find", _("Find in files ..."),
                                         "", _("Search in multiple files"),
                                         self.on_search_files_activate)])

        # Insert the action group
        manager.insert_action_group(self._action_group, -1)

        # Merge the UI
        self._ui_id = manager.add_ui_from_string(ui_str)

    def on_cboSearchTextEntry_changed (self, textEntry):
        """
        Is called when the search text entry is modified;
        disables the Search button whenever no search text is entered.
        """
        if textEntry.get_text() == "":
            self.tree.get_widget('btnSearch').set_sensitive(False)
        else:
            self.tree.get_widget('btnSearch').set_sensitive(True)

    def on_search_files_activate(self, action):
        print "(find in files)"

        gladeFile = os.path.join(os.path.dirname(__file__), "file-search.glade")
        self.tree = gtk.glade.XML(gladeFile)
        self.tree.signal_autoconnect(self)

        self._dialog = self.tree.get_widget('searchDialog')
        self._dialog.set_transient_for(self._window)

        #
        # set initial values for search dialog widgets
        #

        # find a nice default value for the search directory:
        searchDir = os.getcwdu()
        if self._window.get_active_tab():
            currFileDir = self._window.get_active_tab().get_document().get_uri()
            if currFileDir != None and currFileDir.startswith("file:///"):
                searchDir = os.path.dirname(currFileDir[7:])

        cboLastDirs = self.tree.get_widget('cboSearchDirectoryList')
        cboLastDirs.set_model(self._lastDirs.store)
        cboLastDirs.set_text_column(0)

        # make sure that the selected default dir is really on top of the list:
        if self._lastDirs.isEmpty() or self._lastDirs.topEntry() != searchDir:
            self._lastDirs.add(searchDir)
        cboLastDirs.set_active(0)
        # TODO: the algorithm to select a good default search dir could probably be improved...

        # display and run the search dialog
        result = self._dialog.run()
        print "result: %s" % result

        if result != 1:
            print "(cancelled)"
            self._dialog.destroy()
            return

        print "(starting search)"
        searchText = self.tree.get_widget('cboSearchTextEntry').get_text()
        searchDir = self.tree.get_widget('cboSearchDirectoryEntry').get_text()
        self._dialog.destroy()

        print "searching for '%s' in '%s'" % (searchText, searchDir)
        if searchText == "":
            print "internal error: search text is empty!"
            return
        searchDir = os.path.expanduser(searchDir)
        if not(os.path.exists(searchDir)):
            print "error: directory '%s' doesn't exist!" % searchDir
            return

        self._lastDirs.add(searchDir)

        searcher = FileSearcher(self._window, self, searchText, searchDir)

class FileSearcher:
    """
    Gets a search query (and related info) and then handles everything related
    to that single file search:
    - creating a result window
    - starting grep (through SearchProcess)
    - displaying matches
    A FileSearcher object lives until its result panel is closed.
    """
    def __init__ (self, window, pluginHelper, searchText, searchDir):
        self._window = window
        self.pluginHelper = pluginHelper
        self.pluginHelper.registerSearcher(self)
        self.files = {}
        self.numMatches = 0
        self.wasCancelled = False

        self._createResultPanel()
        self._updateSummary()
        self.searchProcess = SearchProcess(searchText, searchDir, self)

    def handleResult (self, file, lineno, linetext):
        if not(self.files.has_key(file)):
            it = self._addResultFile(file)
            self.files[file] = it
        else:
            it = self.files[file]
        self._addResultLine(it, lineno, linetext)
        self.numMatches += 1
        self._updateSummary()

    def handleFinished (self):
        print "(finished)"
        self.searchProcess = None
        editBtn = self.tree.get_widget("btnModifyFileSearch")
        editBtn.set_label("gtk-edit")

        if self.wasCancelled:
            line = "<i><span foreground=\"red\">(search was cancelled)</span></i>"
            self.treeStore.append(None, [line, '', 0])
        elif self.numMatches == 0:
            line = "<i>(no matching files found)</i>"
            self.treeStore.append(None, [line, '', 0])

    def _updateSummary (self):
        summary = "<b>%d</b> matches\nin %d files" % (self.numMatches, len(self.files))
        self.tree.get_widget("lblNumMatches").set_label(summary)


    def _createResultPanel (self):
        print "(add result panel)"

        gladeFile = os.path.join(os.path.dirname(__file__), "file-search.glade")
        self.tree = gtk.glade.XML(gladeFile, 'hbxFileSearchResult')
        self.tree.signal_autoconnect(self)
        resultContainer = self.tree.get_widget('hbxFileSearchResult')

        resultContainer.set_data("filesearcher", self)

        panel = self._window.get_bottom_panel()
        panel.add_item(resultContainer, "File Search", "gtk-find")
        panel.activate_item(resultContainer)

        editBtn = self.tree.get_widget("btnModifyFileSearch")
        editBtn.set_label("gtk-cancel")


        self.treeStore = gtk.TreeStore(str, str, int)
        self.treeView = self.tree.get_widget('tvFileSearchResult')
        self.treeView.set_model(self.treeStore)

        tc = gtk.TreeViewColumn("File", gtk.CellRendererText(), markup=0)
        self.treeView.append_column(tc)

    def _addResultFile (self, filename):
        line = "<span foreground=\"#000000\" size=\"smaller\">%s</span>" % filename
        it = self.treeStore.append(None, [line, filename, 0])
        self.treeView.expand_all()
        return it

    def _addResultLine (self, it, lineno, linetext):
        linetext = escapeMarkup(linetext)
        line = "<b>%d:</b> <span foreground=\"blue\">%s</span>" % (lineno, linetext)
        self.treeStore.append(it, [line, None, lineno])
        self.treeView.expand_all()

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

        uri="file://%s" % urllib.quote(file)
        gedit.commands.load_uri(window=self._window, uri=uri, line_pos=lineno)
        if lineno > 0: # this is necessary for Gedit 2.17.4 and older (see gbo #401219)
            currDoc = self._window.get_active_document()
            currDoc.goto_line(lineno - 1) # -1 required to work around gbo #503665
            currView = gedit.tab_get_from_document(currDoc).get_view()
            currView.scroll_to_cursor()

    def on_btnClose_clicked (self, button):
        self.destroy()

    def destroy (self):
        if self.searchProcess:
            self.searchProcess.destroy()
            self.searchProcess = None

        panel = self._window.get_bottom_panel()
        resultContainer = self.tree.get_widget('hbxFileSearchResult')
        resultContainer.set_data("filesearcher", None)
        panel.remove_item(resultContainer)
        self.treeStore = None
        self.treeView = None
        self._window = None
        self.files = {}
        self.tree = None
        self.pluginHelper.unregisterSearcher(self)

    def on_btnModify_clicked (self, button):
        if not(self.searchProcess):
            # edit search params
            pass
        else:
            # cancel search
            self.searchProcess.cancel()
            self.wasCancelled = True


def escapeMarkup (origText):
    "Replaces Pango markup special characters with their escaped replacements"
    text = origText
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


class FileSearchPlugin(gedit.Plugin):
    def __init__(self):
        gedit.Plugin.__init__(self)
        self._instances = {}

    def activate(self, window):
        self._instances[window] = FileSearchWindowHelper(self, window)

    def deactivate(self, window):
        self._instances[window].deactivate()
        del self._instances[window]

    def update_ui(self, window):
        self._instances[window].update_ui()
