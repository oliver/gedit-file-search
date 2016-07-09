File Search Plugin for Gedit
=============================
This is a search plugin for Gedit to search for a text inside a directory.

The plugin was tested with Gedit 3.4.1 under Ubuntu 12.04, and with Gedit 3.8.3 under Fedora 19. It should also work under other versions of Gedit 3.

Note that Gedit 2 and older are not supported by this plugin any more (there is an old version of this plugin available, though, which supports Gedit 2).


Installation (from TGZ file)
----------------------------
* download the plugin from https://github.com/oliver/gedit-file-search/releases
* unpack the tgz file
* copy the contents of the gedit-file-search folder to ~/.local/share/gedit/plugins/ (create that folder if necessary)
* start Gedit, go to Edit -> Preferences -> Plugins, and enable "File Search"


Use Search -> Find in files, or right-click in a document and select Search files... to open the search dialog.

Note: if the plugin cannot be enabled, you might need to install support for Python-based plugins. For Ubuntu-like systems, run "sudo apt-get install gir1.2-gtksource-3.0" in terminal. For other systems, look for a software package like "gedit-plugins" - installing it should fix the problem.


Building from source
--------------------
Prerequisites: install GNU Make, GNU Gettext, glib-compile-schemas, and Git. On Ubuntu, run "sudo apt-get install make gettext libglib2.0-bin git" to install these.

Then run:
```
git clone https://github.com/oliver/gedit-file-search.git
cd gedit-file-search
make tgz
```

This will compile translation files and gschema files, and will create a TGZ file containing the entire plugin ready for installation.
