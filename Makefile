PKGNAME=blivet
SPECFILE=python-blivet.spec
VERSION=$(shell awk '/Version:/ { print $$2 }' $(SPECFILE))
RELEASE=$(shell awk '/Release:/ { print $$2 }' $(SPECFILE) | sed -e 's|%.*$$||g')
RELEASE_TAG=$(PKGNAME)-$(VERSION)-$(RELEASE)
VERSION_TAG=$(PKGNAME)-$(VERSION)

TX_PULL_ARGS = -a --disable-overwrite
TX_PUSH_ARGS = -s

all:
	$(MAKE) -C po

po-pull:
	tx pull $(TX_PULL_ARGS)

check:
	@echo "*** Running pylint to verify source ***"
	#PYTHONPATH=. pylint blivet/*.py blivet/*/*.py --rcfile=/dev/null -i y -r n --disable=C,R --disable=W0141,W0142,W0221,W0401,W0403,W0404,W0603,W0611,W0612,W0613,W0614,W0703

test:
	@echo "*** Running unittests ***"
	PYTHONPATH=.:tests/ python -m unittest discover -v -s tests/ -p '*_test.py'

coverage:
	@which coverage || (echo "*** Please install python-coverage ***"; exit 2)
	@echo "*** Running unittests with coverage ***"
	PYTHONPATH=.:tests/ coverage run --branch -m unittest discover -v -s tests/ -p '*_test.py'
	coverage report --include="blivet/*"

clean:
	-rm *.tar.gz blivet/*.pyc blivet/*/*.pyc ChangeLog
	$(MAKE) -C po clean
	python setup.py -q clean --all

install:
	python setup.py install --root=$(DESTDIR)
	$(MAKE) -C po install

ChangeLog:
	(GIT_DIR=.git git log > .changelog.tmp && mv .changelog.tmp ChangeLog; rm -f .changelog.tmp) || (touch ChangeLog; echo 'git directory not found: installing possibly empty changelog.' >&2)

tag:
	@if test $(RELEASE) = "1" ; then \
	  tags='$(VERSION_TAG) $(RELEASE_TAG)' ; \
	else \
	  tags='$(RELEASE_TAG)' ; \
	fi ; \
	for tag in $$tags ; do \
	  git tag -a -s -m "Tag as $$tag" -f $$tag ; \
	  echo "Tagged as $$tag" ; \
	done

archive: check tag
	@rm -f ChangeLog
	@make ChangeLog
	git archive --format=tar --prefix=$(PKGNAME)-$(VERSION)/ $(VERSION_TAG) > $(PKGNAME)-$(VERSION).tar
	mkdir $(PKGNAME)-$(VERSION)
	cp -r po $(PKGNAME)-$(VERSION)
	cp ChangeLog $(PKGNAME)-$(VERSION)/
	tar -rf $(PKGNAME)-$(VERSION).tar $(PKGNAME)-$(VERSION)
	gzip -9 $(PKGNAME)-$(VERSION).tar
	rm -rf $(PKGNAME)-$(VERSION)
	git checkout -- po/$(PKGNAME).pot
	@echo "The archive is in $(PKGNAME)-$(VERSION).tar.gz"

local: po-pull
	@rm -f ChangeLog
	@make ChangeLog
	@rm -rf $(PKGNAME)-$(VERSION).tar.gz
	@rm -rf /tmp/$(PKGNAME)-$(VERSION) /tmp/$(PKGNAME)
	@dir=$$PWD; cp -a $$dir /tmp/$(PKGNAME)-$(VERSION)
	@cd /tmp/$(PKGNAME)-$(VERSION) ; python setup.py -q sdist
	@cp /tmp/$(PKGNAME)-$(VERSION)/dist/$(PKGNAME)-$(VERSION).tar.gz .
	@rm -rf /tmp/$(PKGNAME)-$(VERSION)
	@echo "The archive is in $(PKGNAME)-$(VERSION).tar.gz"

rpmlog:
	@git log --pretty="format:- %s (%ae)" $(RELEASE_TAG).. |sed -e 's/@.*)/)/'
	@echo

bumpver: po-pull
	@opts="-n $(PKGNAME) -v $(VERSION) -r $(RELEASE)" ; \
	if [ ! -z "$(IGNORE)" ]; then \
		opts="$${opts} -i $(IGNORE)" ; \
	fi ; \
	if [ ! -z "$(MAP)" ]; then \
		opts="$${opts} -m $(MAP)" ; \
	fi ; \
	if [ ! -z "$(SKIP_ACKS)" ]; then \
		opts="$${opts} -s" ; \
	fi ; \
	if [ ! -z "$(BZDEBUG)" ]; then \
		opts="$${opts} -d" ; \
	fi ; \
	( scripts/makebumpver $${opts} ) || exit 1 ; \
	make -C po $(PKGNAME).pot ; \
	tx push $(TX_PUSH_ARGS)

.PHONY: check clean install tag archive local
