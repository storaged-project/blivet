PYTHON?=python3
PKG_INSTALL?=dnf

PKGNAME=blivet
SPECFILE=python-blivet.spec
VERSION=$(shell $(PYTHON) setup.py --version)
RPMVERSION=$(shell rpmspec -q --queryformat "%{version}\n" $(SPECFILE) | head -1)
RPMRELEASE=$(shell rpmspec --undefine '%dist' -q --queryformat "%{release}\n" $(SPECFILE) | head -1)
RC_RELEASE ?= $(shell date -u +0.1.%Y%m%d%H%M%S)
RELEASE_TAG=$(PKGNAME)-$(RPMVERSION)-$(RPMRELEASE)
VERSION_TAG=$(PKGNAME)-$(VERSION)

ifeq ($(PYTHON),python3)
  COVERAGE=coverage3
else
  COVERAGE=coverage
endif

ZANATA_PULL_ARGS = --transdir ./po/
ZANATA_PUSH_ARGS = --srcdir ./po/ --push-type source --force

MOCKCHROOT ?= fedora-rawhide-$(shell uname -m)

all:
	$(MAKE) -C po

po-pull:
	@which zanata >/dev/null 2>&1 || ( echo "You need to install Zanata client to download translation files"; exit 1 )
	zanata pull $(ZANATA_PULL_ARGS)

po-empty:
	for lingua in $$(gawk 'match($$0, /locale>(.*)<\/locale/, ary) {print ary[1]}' ./zanata.xml) ; do \
		[ -f ./po/$$lingua.po ] || \
		msginit -i ./po/$(PKGNAME).pot -o ./po/$$lingua.po --no-translator || \
		exit 1 ; \
	done

# Try to fetch the real .po files, but if that fails use the empty ones
po-fallback:
	$(MAKE) po-pull || $(MAKE) po-empty

install-requires:
	@echo "*** Installing the dependencies required for testing and analysis ***"
	@which ansible-playbook &>/dev/null || ( echo "Please install Ansible to install testing dependencies"; exit 1 )
	@ansible-playbook -K -i "localhost," -c local install-test-dependencies.yml --extra-vars "python=$(PYTHON)"

test:
	@echo "*** Running unittests with $(PYTHON) ***"
	PYTHONPATH=.:$(PYTHONPATH) $(PYTHON) -m unittest discover -v -s tests/ -p '*_test.py'

coverage:
	@echo "*** Running unittests with $(COVERAGE) for $(PYTHON) ***"
	PYTHONPATH=.:tests/ $(COVERAGE) run --branch -m unittest discover -v -s tests/ -p '*_test.py'
	$(COVERAGE) report --include="blivet/*" --show-missing
	$(COVERAGE) report --include="blivet/*" > coverage-report.log

pylint:
	@echo "*** Running pylint ***"
	PYTHONPATH=.:tests/:$(PYTHONPATH) $(PYTHON) tests/pylint/runpylint.py

pep8:
	@echo "*** Running pep8 compliance check ***"
	@if test `which pycodestyle-3` ; then \
		pep8='pycodestyle-3' ; \
	elif test `which pycodestyle` ; then \
		pep8='pycodestyle' ; \
	elif test `which pep8` ; then \
		pep8='pep8' ; \
	else \
		echo "You need to install pycodestyle/pep8 to run this check."; exit 1; \
	fi ; \
	$$pep8 --ignore=E501,E402,E731,W504 blivet/ tests/ examples/

canary: po-fallback
	@echo "*** Running translation-canary tests ***"
	PYTHONPATH=translation-canary:$(PYTHONPATH) $(PYTHON) -m translation_canary.translatable po/blivet.pot

check:
	@status=0; \
	$(MAKE) pylint || status=1; \
	$(MAKE) pep8 || status=1; \
	$(MAKE) canary || status=1; \
	exit $$status

clean:
	-rm *.tar.gz blivet/*.pyc blivet/*/*.pyc ChangeLog
	$(MAKE) -C po clean
	$(PYTHON) setup.py -q clean --all

install:
	$(PYTHON) setup.py install --root=$(DESTDIR)
	$(MAKE) -C po install

ChangeLog:
	(GIT_DIR=.git git log > .changelog.tmp && mv .changelog.tmp ChangeLog; rm -f .changelog.tmp) || (touch ChangeLog; echo 'git directory not found: installing possibly empty changelog.' >&2)

tag:
	@if test $(VERSION) != $(RPMVERSION) ; then \
	  tags='$(VERSION_TAG) $(RELEASE_TAG)' ; \
	elif test $(RPMRELEASE) = "1" ; then \
	  tags='$(VERSION_TAG) $(RELEASE_TAG)' ; \
	else \
	  tags='$(RELEASE_TAG)' ; \
	fi ; \
	for tag in $$tags ; do \
	  git tag -a -s -m "Tag as $$tag" -f $$tag ; \
	  echo "Tagged as $$tag" ; \
	done

release: tag archive

archive: po-pull
	@make -B ChangeLog
	mkdir $(PKGNAME)-$(VERSION)
	git archive --format=tar --prefix=$(PKGNAME)-$(VERSION)/ $(VERSION_TAG) | tar -xf -
	cp -r po $(PKGNAME)-$(VERSION)
	cp ChangeLog $(PKGNAME)-$(VERSION)/
	( cd $(PKGNAME)-$(VERSION) && $(PYTHON) setup.py -q sdist --dist-dir .. )
	rm -rf $(PKGNAME)-$(VERSION)
	git checkout -- po/$(PKGNAME).pot
	@echo "The archive is in $(PKGNAME)-$(VERSION).tar.gz"

local: po-pull
	@make -B ChangeLog
	$(PYTHON) setup.py -q sdist --dist-dir .
	@echo "The archive is in $(PKGNAME)-$(VERSION).tar.gz"

rpmlog:
	@git log --pretty="format:- %s (%ae)" $(RELEASE_TAG).. |sed -e 's/@.*)/)/'
	@echo

bumpver: po-pull
	@opts="-n $(PKGNAME) -v $(VERSION) -r $(RPMRELEASE)" ; \
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
	zanata push $(ZANATA_PUSH_ARGS)

scratch-bumpver: po-empty
	@opts="-n $(PKGNAME) -v $(RPMVERSION) -r $(RPMRELEASE) --newrelease $(RC_RELEASE)" ; \
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
	make -C po $(PKGNAME).pot

scratch: po-empty
	@rm -f ChangeLog
	@make ChangeLog
	@rm -rf $(PKGNAME)-$(VERSION).tar.gz
	@rm -rf /tmp/$(PKGNAME)-$(VERSION) /tmp/$(PKGNAME)
	@dir=$$PWD; cp -a $$dir /tmp/$(PKGNAME)-$(VERSION)
	@cd /tmp/$(PKGNAME)-$(VERSION) ; $(PYTHON) setup.py -q sdist
	@cp /tmp/$(PKGNAME)-$(VERSION)/dist/$(PKGNAME)-$(VERSION).tar.gz .
	@rm -rf /tmp/$(PKGNAME)-$(VERSION)
	@echo "The archive is in $(PKGNAME)-$(VERSION).tar.gz"

rc-release: scratch-bumpver scratch
	mock -r $(MOCKCHROOT) --scrub all || exit 1
	mock -r $(MOCKCHROOT) --buildsrpm  --spec ./$(SPECFILE) --sources . --resultdir $(PWD) || exit 1
	mock -r $(MOCKCHROOT) --rebuild *src.rpm --resultdir $(PWD)  || exit 1

srpm: local
	rpmbuild -bs --nodeps $(SPECFILE) --define "_sourcedir `pwd`"
	rm -f $(PKGNAME)-$(VERSION).tar.gz

rpm: local
	rpmbuild -bb --nodeps $(SPECFILE) --define "_sourcedir `pwd`"
	rm -f $(PKGNAME)-$(VERSION).tar.gz

ci: check coverage

.PHONY: check clean pylint pep8 install tag archive local
