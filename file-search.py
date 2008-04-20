
import os
import gedit
import gtk

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

class FileSearchWindowHelper:
    def __init__(self, plugin, window):
        print "Plugin created for", window
        self._window = window
        self._plugin = plugin
        self._dialog = None

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

    def on_search_files_activate(self, action):
        print "(find in files)"

        gladeFile = os.path.join(os.path.dirname(__file__), "gedit-file-search.glade")
        self.tree = gtk.glade.XML(gladeFile)

        self.tree.signal_autoconnect(self)
        self._dialog = self.tree.get_widget('searchDialog')
        self._dialog.set_transient_for(self._window)
        result = self._dialog.run()
        print "result: %s" % result
        if result == 1:
            print "(starting search)"
        else:
            print "(cancelled)"
        self._dialog.destroy()

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
