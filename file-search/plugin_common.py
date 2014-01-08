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


import sys, os
from gettext import gettext, translation
import locale

resourceDir = os.path.dirname(__file__)
gladeFile = os.path.join(resourceDir, "file-search.ui")


def isUnicode(s):
    if sys.version_info[0] < 3:
        return (type(s) == unicode)
    else:
        return (type(s) == str)

def gtkToUnicode(s):
    "convert string returned by GTK to unicode string"
    if sys.version_info[0] < 3:
        return s.decode("utf-8")
    else:
        return s


# translation
APP_NAME = 'file-search'
LOCALE_PATH = os.path.join(resourceDir, 'locale')
t = translation(APP_NAME, LOCALE_PATH, fallback=True)

if hasattr(t, "ugettext"):
    _ = t.ugettext
    ngettext = t.ungettext
else:
    _ = t.gettext
    ngettext = t.ngettext

# set gettext domain for GtkBuilder
locale.bindtextdomain(APP_NAME, LOCALE_PATH)

