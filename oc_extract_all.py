import os
import sys

if os.getenv("OC_ALLOW_LEGACY_OC_SCRIPT_RUN") != "YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION":
    print("BLOCKED: This legacy Orchid Continuum/Calyx root-level script is write-capable or schema-stale and is disabled by default.")
    print("This safety guard prevents accidental production database writes.")
    print("To run intentionally, set OC_ALLOW_LEGACY_OC_SCRIPT_RUN=YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION after manual review.")
    sys.exit(2)

import subprocess

for i in range(30):
    print("Running batch", i + 1)
    subprocess.run(["python", "oc_extract_taxonomy.py"])
