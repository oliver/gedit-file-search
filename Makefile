PLUGIN_SUBFOLDER=file-search
LANG_FOLDER=$(PLUGIN_SUBFOLDER)/locale

DIST_FILES= \
	$(LANG_FOLDER) \
	$(PLUGIN_SUBFOLDER)/file-search.glade \
	$(PLUGIN_SUBFOLDER)/__init__.py \
	$(PLUGIN_SUBFOLDER)/searcher.py \
	$(PLUGIN_SUBFOLDER)/ui.py \
	file-search.gedit-plugin \
	README

TGZ_FOLDER=gedit-file-search

all: po mo

tgz: po mo
	mkdir -p $(TGZ_FOLDER)
	cp --parents -r $(DIST_FILES) $(TGZ_FOLDER)
	rm -f $(TGZ_FOLDER)/$(LANG_FOLDER)/file-search.pot
	find $(TGZ_FOLDER)/$(LANG_FOLDER)/ -iname "*.po" -exec rm -f {} \;
	tar -czf gedit-file-search-`date +"%Y%m%d_%H%M%S"`.tgz $(TGZ_FOLDER)
	rm -rf $(TGZ_FOLDER)

clean-pot:
	rm -f $(LANG_FOLDER)/file-search.pot
	mkdir -p $(LANG_FOLDER)
	# Workaround for `xgettext -j`, that stops if no file exists.
	touch $(LANG_FOLDER)/file-search.pot

mo:
	for po in $(shell find $(LANG_FOLDER)/ -iname "*.po");\
	do\
		msgfmt -o $${po%\.*}.mo $$po;\
	done

po: pot
	for po in $(shell find ./ -iname "*.po");\
	do\
		msgmerge -o tempo $$po $(LANG_FOLDER)/file-search.pot;\
		rm $$po;\
		mv tempo $$po;\
	done

pot: clean-pot
	xgettext -j -o $(LANG_FOLDER)/file-search.pot -L Glade $(PLUGIN_SUBFOLDER)/file-search.glade
	xgettext -j -o $(LANG_FOLDER)/file-search.pot -L Python $(PLUGIN_SUBFOLDER)/ui.py

install:
	cp file-search.plugin ~/.local/share/gedit/plugins
	cp -r file-search ~/.local/share/gedit/plugins
