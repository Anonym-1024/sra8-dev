# Building programs with the kit (spec Section 7).  Build the tools first
# (make in the parent folder, or make examples there).
#
#   make                 everything below into build/
#   make build/terminal.mem
#
# Copy a build/*.mem over program.mem of the FPGA project to run it from
# the boot ROM.

ROOT    := ..
AS      := $(ROOT)/bin/sra8-as
LD      := $(ROOT)/bin/sra8-ld
SCRIPTS := $(ROOT)/ldscripts
BUILD   := build

# The legacy sample programs, laid out like the legacy assembler.
ASM_PROGRAMS := echo loader terminal user_echo example demo

all: $(ASM_PROGRAMS:%=$(BUILD)/%.mem)

$(BUILD):
	mkdir -p $@

$(BUILD)/%.o: asm/%.s | $(BUILD)
	$(AS) $< -o $@ -l $(BUILD)/$*.lst

$(BUILD)/%.mem: $(BUILD)/%.o
	$(LD) -T $(SCRIPTS)/flat.ld --format mem -o $@ -M $(BUILD)/$*.map $<

clean:
	rm -rf $(BUILD)

.PHONY: all clean
.SECONDARY:
