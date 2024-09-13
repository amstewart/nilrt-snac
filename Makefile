# SPDX-License-Identifier: MIT

.DEFAULT_GOAL := all


# PROJECT VARIABLES #

export PACKAGE = nilrt-snac
export VERSION := $(shell git describe)

# INSTALL PATHS #

export prefix ?= /usr/local
export exec_prefix ?= $(prefix)
export bindir ?= $(exec_prefix)/bin

export datarootdir ?= $(prefix)/share

export datadir ?= $(datarootdir)
export docdir ?= $(datarootdir)/doc
export libdir ?= $(exec_prefix)/lib
export sbindir ?= $(exec_prefix)/sbin
export sysconfdir ?= $(prefix)/etc

# BINARIES #

export PYTHON ?= python3
export PYTEST ?= $(PYTHON) -m pytest
export SHELL ?= /bin/sh

# FILES #

PYNILRT_SNAC_FILES = \
	$(shell find nilrt_snac -name \*.py -or -name \*.txt)

TEST_FILES = \
	$(shell find tests/ -type f | git check-ignore -vn --stdin | cut -f2)

SRC_FILES = \
	src/nilrt-snac-conflicts/control \
	src/ni-wireguard-labview/ni-wireguard-labview.initd \
	src/ni-wireguard-labview/wglv0.conf \
	src/nilrt-snac \

DIST_FILES = \
	$(SRC_FILES) \
	$(PYNILRT_SNAC_FILES) \
	LICENSE \
	README.md \
	Makefile \



# REAL TARGETS #
################

$(PACKAGE)-$(VERSION).tar.gz : $(DIST_FILES)
	tar -czf $@ $(DIST_FILES)


src/nilrt-snac-conflicts/nilrt-snac-conflicts.ipk :
	make -C src/nilrt-snac-conflicts $(@F)


# PHONY TARGETS #
#################

.PHONY : all clean dist install installcheck mkinstalldirs uninstall

all : src/nilrt-snac-conflicts/nilrt-snac-conflicts.ipk


clean :
	rm -f ./$(PACKAGE)-*.tar.gz
	make -C src/nilrt-snac-conflicts clean


dist : $(PACKAGE)-$(VERSION).tar.gz


install : all mkinstalldirs $(DIST_FILES)
	# binaries
	install --mode=0755 -t "$(DESTDIR)$(sbindir)" src/nilrt-snac

	# license files
	install --mode=0444 -t "$(DESTDIR)$(docdir)/$(PACKAGE)" \
		LICENSE \
		README.md

	# install conflicts IPK
	install --mode=0644 -t "$(DESTDIR)$(datarootdir)/$(PACKAGE)" \
		src/nilrt-snac-conflicts/nilrt-snac-conflicts.ipk

	# ni-wireguard-labview
	install --mode=0660 \
		src/ni-wireguard-labview/wglv0.conf \
		"$(DESTDIR)$(sysconfdir)/wireguard"
	install --mode=0754 \
		src/ni-wireguard-labview/ni-wireguard-labview.initd \
		"$(DESTDIR)$(sysconfdir)/init.d/ni-wireguard-labview"

	# install python library
	for pyfile in $(PYNILRT_SNAC_FILES); do \
		install -D "$${pyfile}" "$(DESTDIR)$(libdir)/$(PACKAGE)/$${pyfile}"; \
	done

	# integration tests
	for file in $(TEST_FILES); do \
		install -D "$${file}" "$(DESTDIR)$(libdir)/$(PACKAGE)/$${file}"; \
	done


installcheck :
	$(PYTEST) -v "$(realpath $(DESTDIR)$(libdir)/$(PACKAGE)/tests/integration)"


mkinstalldirs :
	mkdir -p --mode=0700 "$(DESTDIR)$(sysconfdir)/wireguard"
	mkdir -p --mode=0755 "$(DESTDIR)$(sysconfdir)/init.d"
	mkdir -p "$(DESTDIR)$(datarootdir)/$(PACKAGE)"
	mkdir -p "$(DESTDIR)$(docdir)/$(PACKAGE)"
	mkdir -p "$(DESTDIR)$(libdir)/$(PACKAGE)"
	mkdir -p "$(DESTDIR)$(sbindir)"


uninstall :
	# directories
	rm -rvf "$(DESTDIR)$(datarootdir)/$(PACKAGE)"
	rm -rvf "$(DESTDIR)$(docdir)/$(PACKAGE)"
	rm -rvf "$(DESTDIR)$(libdir)/$(PACKAGE)"

	# files
	rm -vf "$(DESTDIR)$(sysconfdir)/init.d/ni-wireguard-labview"
	rm -vf "$(DESTDIR)$(sysconfdir)/wireguard"/wglv0.*
	rm -vf "$(DESTDIR)$(sbindir)/nilrt-snac"
