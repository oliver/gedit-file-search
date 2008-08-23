
import os
import gedit
import gtk
import gobject
import fcntl
import popen2
import re

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


class SearchProcess:
    def __init__ (self, queryText, directory, resultHandler):
        self.parser = GrepParser(resultHandler)

        cmd = "find '%s' -print 2> /dev/null | xargs grep -H -I -n -s -Z -e '%s'" % (directory, queryText)
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
            self.parser.parseFragment(readText)
            return True
        else:
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


class GrepParser:
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


class RecentDirs:
    "Encapsulates a gtk.ListStore that stores a list of recent directories"
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


class FileSearchWindowHelper:
    def __init__(self, plugin, window):
        print "Plugin created for", window
        self._window = window
        self._plugin = plugin
        self._dialog = None

        self._lastDirs = RecentDirs()

        self._insert_menu()

    def deactivate(self):
        print "Plugin stopped for", self._window
        self._window = None
        self._plugin = None

    def update_ui(self):
        # Called whenever the window has been updated (active tab
        # changed, etc.)
        print "Plugin update for", self._window

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

        gladeFile = os.path.join(os.path.dirname(__file__), "gedit-file-search.glade")
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
        if not(os.path.exists(searchDir)):
            print "error: directory '%s' doesn't exist!" % searchDir
            return

        self._lastDirs.add(searchDir)

        searcher = FileSearcher(self._window, searchText, searchDir)

class FileSearcher:
    """
    Gets a search query (and related info) and then handles everything related
    to that single file search:
    - creating a result window
    - starting grep (through SearchProcess)
    - displaying matches
    A FileSearcher object lives until its result panel is closed.
    """
    def __init__ (self, window, searchText, searchDir):
        self._window = window
        self.files = {}
        self.numMatches = 0
        self.hasFinished = False

        self.encoding = gedit.encoding_get_current()

        self._add_result_panel()
        self.updateSummary()
        sp = SearchProcess(searchText, searchDir, self)

    def handleResult (self, file, lineno, linetext):
        if not(self.files.has_key(file)):
            it = self._add_result_file(file)
            self.files[file] = it
        else:
            it = self.files[file]
        self._add_result_line(it, lineno, linetext)
        self.numMatches += 1
        self.updateSummary()

    def handleFinished (self):
        print "(finished)"
        self.hasFinished = True
        editBtn = self.tree.get_widget("btnModifyFileSearch")
        editBtn.set_label("gtk-edit")

    def updateSummary (self):
        summary = "<b>%d</b> matches\nin %d files" % (self.numMatches, len(self.files))
        self.tree.get_widget("lblNumMatches").set_label(summary)


    def _add_result_panel (self):
        print "(add result panel)"

        gladeFile = os.path.join(os.path.dirname(__file__), "gedit-file-search.glade")
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

    def _add_result_file (self, filename):
        line = "<span foreground=\"#000000\" size=\"smaller\">%s</span>" % filename
        it = self.treeStore.append(None, [line, filename, 0])
        self.treeView.expand_all()
        return it

    def _add_result_line (self, it, lineno, linetext):
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

        uri="file://%s" % file

        # jump to document if already open, or open new tab:
        allDocs = self._window.get_documents()
        found = False
        for doc in allDocs:
            if doc.get_uri() == uri:
                tab = gedit.tab_get_from_document(doc)
                self._window.set_active_tab(tab)
                if lineno > 0:
                    doc.goto_line(lineno - 1)
                    tab.get_view().scroll_to_cursor()
                found = True
                break

        if not(found):
            self._window.create_tab_from_uri(uri=uri, encoding=self.encoding,
                line_pos=lineno, create=False, jump_to=True)

    def on_btnClose_clicked (self, button):
        panel = self._window.get_bottom_panel()
        resultContainer = self.tree.get_widget('hbxFileSearchResult')
        resultContainer.set_data("filesearcher", None)
        panel.remove_item(resultContainer)
        self.treeStore = None
        self.treeView = None
        self._window = None
        self.files = {}
        self.tree = None

    def on_btnModify_clicked (self, button):
        if self.hasFinished:
            # edit search params
            pass
        else:
            # cancel search
            pass


def escapeMarkup (origText):
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
