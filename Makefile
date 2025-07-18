PYTHON=python3

L10N_REPOSITORY=git@github.com:storaged-project/blivet-weblate.git
L10N_BRANCH=master

PKGNAME=blivet
SPECFILE=python-blivet.spec
VERSION=$(shell $(PYTHON) setup.py --version)
RPMVERSION=$(shell rpmspec -q --queryformat "%{version}\n" $(SPECFILE) | head -1)
RPMRELEASE=$(shell rpmspec --undefine '%dist' -q --queryformat "%{release}\n" $(SPECFILE) | head -1)
RELEASE_TAG=$(PKGNAME)-$(RPMVERSION)-$(RPMRELEASE)
VERSION_TAG=$(PKGNAME)-$(VERSION)

COVERAGE=$(PYTHON) -m coverage

all:
	$(MAKE) -C po

po-pull:
	git submodule update --init po
	git submodule update --remote --merge po

potfile:
	make -C po $(PKGNAME).pot
	# This algorithm will make these steps:
	# - clone localization repository
	# - copy pot file to this repository
	# - check if pot file is changed (ignore the POT-Creation-Date otherwise it's always changed)
	# - if not changed:
	#   - remove cloned repository
	# - if changed:
	#   - add pot file
	#   - commit pot file
	#   - tell user to verify this file and push to the remote from the temp dir
	TEMP_DIR=$$(mktemp --tmpdir -d $(PKGNAME)-localization-XXXXXXXXXX) || exit 1 ; \
	git clone --depth 1 -b $(L10N_BRANCH) -- $(L10N_REPOSITORY) $$TEMP_DIR || exit 2 ; \
	cp po/$(PKGNAME).pot $$TEMP_DIR/ || exit 3 ; \
	pushd $$TEMP_DIR ; \
	git difftool --trust-exit-code -y -x "diff -u -I '^\"POT-Creation-Date: .*$$'" HEAD ./$(PKGNAME).pot &>/dev/null ; \
	if [ $$? -eq 0  ] ; then \
		popd ; \
		echo "Pot file is up to date" ; \
		rm -rf $$TEMP_DIR ; \
		git submodule foreach git checkout -- blivet.pot ; \
	else \
		git add ./$(PKGNAME).pot && \
		git commit -m "Update $(PKGNAME).pot" && \
		popd && \
		git submodule foreach git checkout -- blivet.pot ; \
		echo "Pot file updated for the localization repository $(L10N_REPOSITORY) branch $(L10N_BRANCH)" && \
		echo "Please confirm and push:" && \
		echo "$$TEMP_DIR" ; \
	fi ;

install-requires:
	@echo "*** Installing the dependencies required for testing and analysis ***"
	@which ansible-playbook &>/dev/null || ( echo "Please install Ansible to install testing dependencies"; exit 1 )
	@ansible-playbook -K -i "localhost," -c local misc/install-test-dependencies.yml --extra-vars "python=$(PYTHON)"

unit-test:
	@echo "*** Running unit tests with $(PYTHON) ***"
	PYTHONPATH=.:$(PYTHONPATH) $(PYTHON) tests/run_tests.py unit_tests

storage-test:
	@echo "*** Running storage tests with $(PYTHON) ***"
	PYTHONPATH=.:$(PYTHONPATH) $(PYTHON) tests/run_tests.py storage_tests

test:
	@echo "*** Running tests with $(PYTHON) ***"
	PYTHONPATH=.:$(PYTHONPATH) $(PYTHON) tests/run_tests.py

coverage:
	@echo "*** Running unittests with $(COVERAGE) for $(PYTHON) ***"
	PYTHONPATH=.:tests/ $(COVERAGE) run --branch tests/run_tests.py
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
	$$pep8 --ignore=E501,E402,E731,W504,E741 blivet/ tests/ examples/

canary:
	@echo "*** Running translation-canary tests ***"
	@if [ ! -e po/$(PKGNAME).pot ]; then \
		echo "Translation files not present. Skipping" ; \
	else \
		PYTHONPATH=translation-canary:$(PYTHONPATH) $(PYTHON) -m translation_canary.translatable po/$(PKGNAME).pot; \
	fi ; \

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

install-dbus:
	install -d $(DESTDIR)/etc/dbus-1/system.d/
	install -m 644 dbus/blivet.conf $(DESTDIR)/etc/dbus-1/system.d/blivet.conf
	install -d $(DESTDIR)/usr/share/dbus-1/system-services/
	install -m 644 dbus/com.redhat.Blivet0.service $(DESTDIR)/usr/share/dbus-1/system-services/com.redhat.Blivet0.service
	install -d $(DESTDIR)/usr/libexec/
	install -m 755 dbus/blivetd $(DESTDIR)/usr/libexec/blivetd
	install -d $(DESTDIR)/usr/lib/systemd/system
	install -m 644 dbus/blivet.service $(DESTDIR)/usr/lib/systemd/system

install:
	$(PYTHON) -m pip install . --root=$(DESTDIR) --verbose --no-deps --no-build-isolation
	$(MAKE) -C po install
	$(MAKE) install-dbus

ChangeLog:
	(GIT_DIR=.git git log > .changelog.tmp && mv .changelog.tmp ChangeLog; rm -f .changelog.tmp) || (touch ChangeLog; echo 'git directory not found: installing possibly empty changelog.' >&2)

tag:
	git tag -a -s -m "Tag as $(VERSION_TAG)" -f "$(VERSION_TAG)" && \
	echo "Tagged as $(VERSION_TAG)"

release: tag archive

archive: po-pull
	@make -B ChangeLog
	mkdir $(PKGNAME)-$(VERSION)
	git archive --format=tar --prefix=$(PKGNAME)-$(VERSION)/ $(VERSION_TAG) | tar -xf -
	cp -r po $(PKGNAME)-$(VERSION)
	cp ChangeLog $(PKGNAME)-$(VERSION)/
	( cd $(PKGNAME)-$(VERSION) && $(PYTHON) -m build --sdist --outdir .. --no-isolation )
	rm -rf $(PKGNAME)-$(VERSION)
	@echo "The archive is in $(PKGNAME)-$(VERSION).tar.gz"
	@make tests-archive

tests-archive:
	git archive --format=tar --prefix=$(PKGNAME)-$(VERSION)/ $(VERSION_TAG) tests/ | gzip -9 > $(PKGNAME)-$(VERSION)-tests.tar.gz
	@echo "The test archive is in $(PKGNAME)-$(VERSION)-tests.tar.gz"

local: po-pull
	@make -B ChangeLog
	$(PYTHON) -m build --sdist --outdir . --no-isolation
	@echo "The archive is in $(PKGNAME)-$(VERSION).tar.gz"
	git archive --format=tar --prefix=$(PKGNAME)-$(VERSION)/ HEAD tests/ | gzip -9 > $(PKGNAME)-$(VERSION)-tests.tar.gz
	@echo "The test archive is in $(PKGNAME)-$(VERSION)-tests.tar.gz"

rpmlog:
	@git log --pretty="format:- %s (%ae)" $(RELEASE_TAG).. |sed -e 's/@.*)/)/'
	@echo

bumpver: po-pull
	( scripts/makebumpver -n $(PKGNAME) -v $(VERSION) -r $(RPMRELEASE) ) || exit 1 ;

srpm: local
	rpmbuild -bs --nodeps $(SPECFILE) --define "_sourcedir `pwd`"
	rm -f $(PKGNAME)-$(VERSION).tar.gz $(PKGNAME)-$(VERSION)-tests.tar.gz

rpm: local
	rpmbuild -bb --nodeps $(SPECFILE) --define "_sourcedir `pwd`"
	rm -f $(PKGNAME)-$(VERSION).tar.gz $(PKGNAME)-$(VERSION)-tests.tar.gz

release-pypi:
	if ! $(PYTHON) -m build --sdist --wheel; then \
		echo ""; \
		echo Distribution package build failed! Please verify that you have \'python3-build\' and \'python3-setuptools\' installed. >&2; \
		exit 1; \
	fi
	if ! $(PYTHON) -m twine upload dist/*; then \
		echo ""; \
		echo Package upload failed! Make sure the \'twine tool\' is installed and you are registered >&2; \
		exit 1; \
	fi

ci: check coverage

.PHONY: check clean pylint pep8 install tag archive local
