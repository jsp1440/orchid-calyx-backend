"""Promptfoo custom provider: run one adversarial tool call through the executor guards.

The prompt is a JSON object ``{"tool": ..., "input": {...}}``. The output is
``<VERDICT>: <detail>`` where VERDICT is REFUSED, ALLOWED or EXECUTED.
Offline: no model and no network are involved.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oc_guard_harness import run_case


def call_api(prompt, options, context):
    case = json.loads(prompt)
    verdict, detail = run_case(case)
    return {"output": f"{verdict}: {detail}"}
