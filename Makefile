# SRA-8 development kit: assembler, linker and disassembler in Python 3,
# standard library only.  The C23 port lives in c/ (make c).
#
#   make test           run the test suite
#   make install        make sra8-as, sra8-ld, sra8-objdump callable from anywhere
#   make uninstall      remove them again
#   make docs vscode    regenerate docs/isa.md and the VS Code assembly grammar
#   make examples       build the example programs into examples/build
#   make golden         regenerate tests/golden with the legacy assembler of the RTL
#   make c              build and test the C port

PYTHON ?= python3
PREFIX ?= $(HOME)/.local
TOOLS  := sra8-as sra8-ld sra8-objdump

.PHONY: all test install uninstall docs vscode examples golden c clean

all: test

test:
	$(PYTHON) -m unittest discover -s tests

# Symbolic links to the launchers in bin/.  The launchers find this folder
# through the link, so the tools keep using this checkout and its
# ldscripts/; a git pull or an edit takes effect immediately.
install:
	mkdir -p $(PREFIX)/bin
	for t in $(TOOLS); do ln -sf $(CURDIR)/bin/$$t $(PREFIX)/bin/$$t; done
	@case ":$$PATH:" in *":$(PREFIX)/bin:"*) ;; \
	    *) echo "note: $(PREFIX)/bin is not on PATH; add it, e.g. to ~/.zshrc:"; \
	       echo '    export PATH="$(PREFIX)/bin:$$PATH"';; esac

uninstall:
	for t in $(TOOLS); do if [ -L $(PREFIX)/bin/$$t ]; then rm $(PREFIX)/bin/$$t; fi; done

docs:
	$(PYTHON) -m sra8.isa > docs/isa.md

vscode:
	$(PYTHON) vscode/sra8-lang/gen_grammars.py

examples:
	$(MAKE) -C examples

golden:
	$(PYTHON) tests/make_golden.py

c:
	$(MAKE) -C c test

clean:
	$(MAKE) -C examples clean
	$(MAKE) -C c clean
	find . -name __pycache__ -prune -exec rm -rf {} +
