#!/usr/bin/env python3
"""Regenerate tests/golden from the legacy assembler in the RTL folder.

Run once when the sample programs change:  python3 tests/make_golden.py
The legacy assembler assembles the *original* files (with .org), the tests
then check that the ported copies in examples/asm assemble and link to the
same bytes.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RTL = os.environ.get("SRA8_RTL", os.path.join(REPO, "..", "sra-8-fpga", "sra-8-fpga"))
SAMPLES = {"echo": "echo.s", "loader": "loader.s", "terminal": "terminal.s",
           "user_echo": "user_echo.s", "example": "asm/example.s", "demo": "asm/demo.s"}


def main() -> int:
    legacy = os.path.join(RTL, "asm", "sra8asm.py")
    if not os.path.exists(legacy):
        print("legacy assembler not found at %s (set SRA8_RTL)" % legacy, file=sys.stderr)
        return 1
    out = os.path.join(REPO, "tests", "golden")
    os.makedirs(out, exist_ok=True)
    for name, rel in SAMPLES.items():
        src = os.path.join(RTL, rel)
        base = os.path.join(out, name)
        for args in (["-o", base + ".mem"], ["-f", "bin", "-o", base + ".bin"]):
            subprocess.run([sys.executable, legacy, src] + args, check=True, stderr=subprocess.DEVNULL)
        print("golden: %s" % name)
    shutil.copy(os.path.join(RTL, "f.l"), os.path.join(out, "loader_f.l"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
