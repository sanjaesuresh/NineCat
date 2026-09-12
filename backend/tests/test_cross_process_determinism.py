"""The REAL cross-process determinism guard: runs each fixed scenario in
cross_process_scenarios.py in a brand-new subprocess, once per explicit
PYTHONHASHSEED, and asserts byte-identical JSON output.

Unlike an in-process double-call (e.g. test_streaming.py::
test_identical_inputs_produce_identical_plans), a fresh subprocess actually
gets a fresh hash seed, so this is the only place in the suite that can catch
a set/dict-iteration-order bug leaking into an engine's output ordering.
Pure engine code, no DB -- each subprocess is a plain `python -m` call and
stays fast.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# yahoo_fantasy_api ships its own top-level "tests" package in site-packages,
# which shadows `import tests.*` in this venv (its own import chain is
# broken, see its ImportError) -- both the in-process import below and the
# subprocess invocation therefore go by direct file path, never through the
# "tests." dotted package name, to dodge that collision entirely
from cross_process_scenarios import SCENARIOS

# two arbitrary, different, explicit seeds -- "0" disables hash randomization
# entirely, "4242" is just some other fixed value, so a bug that only shows
# up under randomization has two independent chances to surface
SEED_A = "0"
SEED_B = "4242"

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SCENARIOS_SCRIPT = Path(__file__).resolve().with_name("cross_process_scenarios.py")


def _run_scenario(name: str, seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    result = subprocess.run(
        [sys.executable, str(_SCENARIOS_SCRIPT), name],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_output_identical_across_hash_seeds(name):
    first = _run_scenario(name, SEED_A)
    second = _run_scenario(name, SEED_B)

    # compare parsed JSON (not raw stdout) so a trailing-newline/whitespace
    # difference between runs can never masquerade as a real determinism bug
    assert json.loads(first) == json.loads(second)
    # byte-identical too: json.dumps is itself deterministic for these
    # scenarios (no unordered container reaches it unconverted, see
    # cross_process_scenarios._to_jsonable), so the raw strings should match
    assert first == second
