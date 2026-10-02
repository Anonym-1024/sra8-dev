# Building programs with the kit (spec Section 9).  Build the tools first
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
LIB     := $(ROOT)/lib
BUILD   := build

# The legacy sample programs: no crt0, laid out like the legacy assembler.
ASM_PROGRAMS := echo loader terminal user_echo example demo

all: $(ASM_PROGRAMS:%=$(BUILD)/%.mem) $(BUILD)/hello.mem

$(BUILD) $(BUILD)/lib:
	mkdir -p $@

$(BUILD)/%.o: asm/%.s | $(BUILD)
	$(AS) $< -o $@ -l $(BUILD)/$*.lst

$(BUILD)/%.mem: $(BUILD)/%.o
	$(LD) -T $(SCRIPTS)/flat.ld --format mem -o $@ -M $(BUILD)/$*.map $<

# A program that uses crt0 and the runtime, linked with boot.ld.
# crt0.o must come first: its unnamed code section follows the vector.
$(BUILD)/lib/%.o: $(LIB)/%.s | $(BUILD)/lib
	$(AS) -Werror $< -o $@

$(BUILD)/hello.o: rt/hello.s | $(BUILD)
	$(AS) $< -o $@

$(BUILD)/hello.mem: $(BUILD)/lib/crt0.o $(BUILD)/hello.o $(BUILD)/lib/uart.o $(BUILD)/lib/isr_default.o
	$(LD) -T $(SCRIPTS)/boot.ld --format mem -o $@ -M $(BUILD)/hello.map $^

clean:
	rm -rf $(BUILD)

.PHONY: all clean
.SECONDARY:
