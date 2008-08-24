DIST_FILES= \
	file-search.gedit-plugin \
	file-search.py \
	file-search.glade \
	README

tgz:
	tar czf gedit-file-search-`date +"%Y%m%d_%H%M%S"`.tgz $(DIST_FILES)
