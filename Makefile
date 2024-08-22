# SPDX-License-Identifier: MIT

.DEFAULT_GOAL := all

SHELL = /bin/sh

## VARIABLES

PACKAGE = nilrt-snac
VERSION := $(shell git describe)

# GNU directories
prefix ?= /usr/local
exec_prefix ?= $(prefix)
bindir ?= $(exec_prefix)/bin

datarootdir ?= $(prefix)/share

datadir ?= $(datarootdir)
docdir ?= $(datarootdir)/doc
libdir ?= $(exec_prefix)/lib
sbindir ?= $(exec_prefix)/sbin
sysconfdir ?= $(prefix)/etc

PYTHON_FILES = \
	$(shell find nilrt_snac -name \*.py -or -name \*.txt)

SRC_FILES = \
	src/nilrt-snac-conflicts/control \
	src/ni-wireguard-labview/ni-wireguard-labview.initd \
	src/ni-wireguard-labview/wglv0.conf \
	src/nilrt-snac \

DIST_FILES = \
	$(SRC_FILES) \
	$(PYTHON_FILES) \
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

.PHONY : all clean dist install uninstall test

all : src/nilrt-snac-conflicts/nilrt-snac-conflicts.ipk


clean :
	rm -f ./$(PACKAGE)-*.tar.gz
	make -C src/nilrt-snac-conflicts clean


dist : $(PACKAGE)-$(VERSION).tar.gz


install : all $(DIST_FILES)
	mkdir -p $(DESTDIR)$(sbindir)
	install -o 0 -g 0 --mode=0755 -t "$(DESTDIR)$(sbindir)" \
		src/nilrt-snac

	mkdir -p $(DESTDIR)$(libdir)/$(PACKAGE)/nilrt_snac
	install --mode=0444 -t "$(DESTDIR)$(libdir)/$(PACKAGE)/nilrt_snac" \
		$(shell find nilrt_snac -name \*.py -or -name \*.txt -maxdepth 1) \

	# install doesn't support recursive copy
	mkdir -p $(DESTDIR)$(libdir)/$(PACKAGE)/nilrt_snac/_configs
	install --mode=0444 -t "$(DESTDIR)$(libdir)/$(PACKAGE)/nilrt_snac/_configs" \
		$(shell find nilrt_snac/_configs -name \*.py -maxdepth 1) \

	mkdir -p $(DESTDIR)$(docdir)/$(PACKAGE)
	install --mode=0444 -t "$(DESTDIR)$(docdir)/$(PACKAGE)" \
		LICENSE \
		README.md

	# install conflicts IPK
	mkdir -p $(DESTDIR)$(datarootdir)/$(PACKAGE)
	install --mode=0644 -t "$(DESTDIR)$(datarootdir)/$(PACKAGE)" \
		src/nilrt-snac-conflicts/nilrt-snac-conflicts.ipk

	# ni-wireguard-labview
	install --mode=0700 -d "$(DESTDIR)$(sysconfdir)/wireguard"
	install --mode=0660 \
		src/ni-wireguard-labview/wglv0.conf \
		$(DESTDIR)$(sysconfdir)/wireguard
	install --mode=0755 -d "$(DESTDIR)$(sysconfdir)/init.d"
	install --mode=0754 \
		src/ni-wireguard-labview/ni-wireguard-labview.initd \
		"$(DESTDIR)$(sysconfdir)/init.d/ni-wireguard-labview"


uninstall :
	rm -vf $(DESTDIR)$(sbindir)/nilrt-snac
	rm -rvf $(DESTDIR)$(libdir)/$(PACKAGE)
	rm -rvf $(DESTDIR)$(docdir)/$(PACKAGE)
	rm -f $(DESTDIR)$(sysconfdir)/wireguard/wglv0.*
	rm -f $(DESTDIR)$(sysconfdir)/init.d/ni-wireguard-labview
