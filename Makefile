PKGNAME=blivet
SPECFILE=python-blivet.spec
VERSION=$(shell python3 setup.py --version)
RPMVERSION=$(shell rpmspec -q --queryformat "%{version}\n" $(SPECFILE) | head -1)
RPMRELEASE=$(shell rpmspec --undefine '%dist' -q --queryformat "%{release}\n" $(SPECFILE) | head -1)
RC_RELEASE ?= $(shell date -u +0.1.%Y%m%d%H%M%S)
RELEASE_TAG=$(PKGNAME)-$(RPMVERSION)-$(RPMRELEASE)
VERSION_TAG=$(PKGNAME)-$(VERSION)

PYTHON=python3
COVERAGE=coverage
PEP8=$(PYTHON)-pep8
ifeq ($(PYTHON),python3)
  COVERAGE=coverage3
endif

ZANATA_PULL_ARGS = --transdir ./po/
ZANATA_PUSH_ARGS = --srcdir ./po/ --push-type source --force

MOCKCHROOT ?= fedora-rawhide-$(shell uname -m)

TEST_DEPENDENCIES = $(shell rpm --specfile python-blivet.spec --requires | cut -d' ' -f1 | grep -v ^blivet)
TEST_DEPENDENCIES += anaconda-core
TEST_DEPENDENCIES += python3-mock
TEST_DEPENDENCIES += python3-coverage
TEST_DEPENDENCIES += dosfstools e2fsprogs xfsprogs hfsplus-tools
TEST_DEPENDENCIES += python3-pocketlint python3-bugzilla
TEST_DEPENDENCIES += python3-pep8 zanata-python-client
TEST_DEPENDENCIES += python3-paramiko libvirt-python3
TEST_DEPENDENCIES := $(shell echo $(sort $(TEST_DEPENDENCIES)) | uniq)

all:
	$(MAKE) -C po

po-pull:
	rpm -q zanata-python-client &>/dev/null || ( echo "need to run: yum install zanata-python-client"; exit 1 )
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

check-requires:
	@echo "*** Checking if the dependencies required for testing and analysis are available ***"
	@status=0 ; \
	for pkg in $(TEST_DEPENDENCIES) ; do \
		test_output="$$(rpm -q --whatprovides "$$pkg")" ; \
		if [ $$? != 0 ]; then \
			echo "$$test_output" ; \
			status=1 ; \
		fi ; \
	done ; \
	exit $$status

install-requires:
	@echo "*** Installing the dependencies required for testing and analysis ***"
	dnf install -y $(TEST_DEPENDENCIES)

test: check-requires
	@echo "*** Running unittests with $(PYTHON) ***"
	PYTHONPATH=. $(PYTHON) -m unittest discover -v -s tests/ -p '*_test.py'

coverage: check-requires
	@echo "*** Running unittests with $(COVERAGE) for $(PYTHON) ***"
	PYTHONPATH=.:tests/ $(COVERAGE) run --branch -m unittest discover -v -s tests/ -p '*_test.py'
	$(COVERAGE) report --include="blivet/*" --show-missing
	$(COVERAGE) report --include="blivet/*" > coverage-report.log

pylint: check-requires
	@echo "*** Running pylint ***"
	PYTHONPATH=.:tests/:$(PYTHONPATH) tests/pylint/runpylint.py

pep8: check-requires
	@echo "*** Running pep8 compliance check ***"
	$(PEP8) --ignore=E501,E402,E731 blivet/ tests/ examples/

canary: check-requires po-fallback
	@echo "*** Running translation-canary tests ***"
	PYTHONPATH=translation-canary:$(PYTHONPATH) python3 -m translation_canary.translatable po/blivet.pot

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

ci: check coverage

.PHONY: check clean pylint pep8 install tag archive local
