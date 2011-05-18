DIST_FILES= \
	file-search.gedit-plugin \
	file-search/__init__.py \
	file-search/searcher.py \
	file-search/ui.py \
	file-search/file-search.glade \
	README

tgz:
	tar czf gedit-file-search-`date +"%Y%m%d_%H%M%S"`.tgz $(DIST_FILES)
