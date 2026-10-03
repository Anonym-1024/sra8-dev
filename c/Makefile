# The C23 port of sra8-as, sra8-ld and sra8-objdump: standard library only.
#
#   make                build bin/sra8-as, bin/sra8-ld, bin/sra8-objdump, bin/isagen
#   make test           build, then run tests/run.sh
#   make check-rtl      compare the instruction table with the RTL
#   make SANITIZE=address,undefined clean test     run the tests under sanitizers
#
# Examples, linker scripts and goldens are shared with the Python
# implementation in the parent folder.

CC       ?= cc
CSTD     ?= -std=c23
CFLAGS   ?= -O2 -g -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wno-sign-conversion
LDFLAGS  ?=
RTL      ?= ../../sra-8-fpga/sra-8-fpga

ifdef SANITIZE
CFLAGS  += -fsanitize=$(SANITIZE) -fno-omit-frame-pointer
LDFLAGS += -fsanitize=$(SANITIZE)
endif

BIN      := bin
OBJ      := build/obj
COMMON   := $(wildcard src/common/*.c)
TOOLS    := $(BIN)/sra8-as $(BIN)/sra8-ld $(BIN)/sra8-objdump $(BIN)/isagen

objs = $(patsubst src/%.c,$(OBJ)/%.o,$(1))

.PHONY: all test check-rtl clean

all: $(TOOLS)

$(BIN)/sra8-as: $(call objs,$(wildcard src/as/*.c) $(COMMON))
$(BIN)/sra8-ld: $(call objs,$(wildcard src/ld/*.c) $(COMMON))
$(BIN)/sra8-objdump: $(call objs,$(wildcard src/objdump/*.c) $(COMMON))
$(BIN)/isagen: $(call objs,$(wildcard src/isagen/*.c) $(COMMON))

$(TOOLS):
	@mkdir -p $(BIN)
	$(CC) $(LDFLAGS) -o $@ $^

$(OBJ)/%.o: src/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CSTD) $(CFLAGS) $(CPPFLAGS) -MMD -MP -c -o $@ $<

# the linker's default script: the shared one in the parent folder
$(OBJ)/ld/main.o: CPPFLAGS += -DSRA8_DEFAULT_SCRIPT='"$(abspath ../ldscripts/boot.ld)"'
# the grammar template is one long string
$(OBJ)/isagen/main.o: CFLAGS += -Wno-overlength-strings

-include $(wildcard $(OBJ)/*/*.d)

test: all
	sh tests/run.sh

check-rtl: $(BIN)/isagen
	$(BIN)/isagen check-rtl $(RTL)

clean:
	rm -rf build $(BIN)
