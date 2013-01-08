PKGNAME=blivet
VERSION=$(shell awk '/Version:/ { print $$2 }' $(PKGNAME).spec)
RELEASE=$(shell awk '/Release:/ { print $$2 }' $(PKGNAME).spec | sed -e 's|%.*$$||g')
TAG=$(PKGNAME)-$(VERSION)-$(RELEASE)

#TX_PULL_ARGS = -a --disable-overwrite
#TX_PUSH_ARGS = -s

all:
	$(MAKE) -C po

po-pull:
#	tx pull $(TX_PULL_ARGS)
	@echo "po-pull not implemented"

check:
	@echo "*** Running pylint to verify source ***"
	#PYTHONPATH=. pylint blivet/*.py blivet/*/*.py --rcfile=/dev/null -i y -r n --disable=C,R --disable=W0141,W0142,W0221,W0401,W0403,W0404,W0603,W0611,W0612,W0613,W0614,W0703

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
	git tag -a -m "Tag as $(TAG)" -f $(TAG)
	@echo "Tagged as $(TAG)"

archive: check tag
	@rm -f ChangeLog
	@make ChangeLog
	git archive --format=tar --prefix=$(PKGNAME)-$(VERSION)/ $(TAG) > $(PKGNAME)-$(VERSION).tar
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
	@git log --pretty="format:- %s (%ae)" $(TAG).. |sed -e 's/@.*)/)/'
	@echo

bumpver: po-pull
	@NEWSUBVER=$$((`echo $(VERSION) |cut -d . -f 3` + 1)) ; \
	NEWVERSION=`echo $(VERSION).$$NEWSUBVER |cut -d . -f 1,2,4` ; \
	DATELINE="* `date "+%a %b %d %Y"` `git config user.name` <`git config user.email`> - $$NEWVERSION-1"  ; \
	cl=`grep -n %changelog blivet.spec |cut -d : -f 1` ; \
	tail --lines=+$$(($$cl + 1)) blivet.spec > speclog ; \
	(head -n $$cl blivet.spec ; echo "$$DATELINE" ; make --quiet rpmlog 2>/dev/null ; echo ""; cat speclog) > blivet.spec.new ; \
	mv blivet.spec.new blivet.spec ; rm -f speclog ; \
	sed -i "s/Version: $(VERSION)/Version: $$NEWVERSION/" blivet.spec ; \
	sed -i "s/version='$(VERSION)'/version='$$NEWVERSION'/" setup.py ; \
	make -C po $(PKGNAME).pot ; \
	tx push $(TX_PUSH_ARGS)

.PHONY: check clean install tag archive local
