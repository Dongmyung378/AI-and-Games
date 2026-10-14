"""Linux AddressSanitizer/UBSan checks for both maintained and controlled legacy engines."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hexai.native import environment, resolve_compiler, sha256
from scripts.build_legacy_benchmark import build_adapter


def check(output: Path, compiler: str | None = None) -> dict:
    if os.name == "nt":
        raise ValueError("Run sanitizer verification in Linux, WSL or Kaggle CPU.")
    output = Path(output).resolve()
    if any(output.is_relative_to((ROOT / part).resolve()) for part in ("engine", "deployment")):
        raise ValueError("Sanitizer output must not overwrite historical directories.")
    output.mkdir(parents=True, exist_ok=True)
    command = resolve_compiler(compiler)
    native = output / "native-sanitized"
    source = ROOT / "native/hex_search.cpp"
    invocation = command + ["-std=c++17", "-O1", "-g", "-fno-omit-frame-pointer",
                            "-fsanitize=address,undefined", "-pthread", str(source), "-o", str(native)]
    compiled = subprocess.run(invocation, capture_output=True, text=True, timeout=240)
    if compiled.returncode:
        raise RuntimeError("Maintained sanitizer build failed:\n" + compiled.stderr[-12000:])
    legacy = output / "legacy-sanitized"
    legacy_receipt = build_adapter(legacy, compiler, sanitizer=True)
    env = os.environ.copy()
    # Fail instead of continuing after a detected memory or undefined-behaviour error.
    env.update(ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
               HEX_TEST_NATIVE=str(native), HEX_TEST_LEGACY=str(legacy))
    started = time.perf_counter()
    self_test = subprocess.run([str(native), "--self-test"], capture_output=True, text=True, timeout=90, env=env)
    if self_test.returncode:
        raise RuntimeError("Maintained sanitizer self-test failed:\n" + self_test.stderr[-12000:])
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_native_budget.py", "-v"],
                           capture_output=True, text=True, timeout=120, env=env, cwd=ROOT)
    report = {"schema_version": 1, "kind": "linux_address_undefined_sanitizer_validation",
              "status": "passed" if tests.returncode == 0 else "failed", "environment": environment(),
              "native_source_sha256": sha256(source), "native_command": invocation,
              "native_executable_sha256": sha256(native), "legacy_build": legacy_receipt,
              "self_test": {"returncode": self_test.returncode, "stdout": self_test.stdout, "stderr": self_test.stderr},
              "protocol_tests": {"returncode": tests.returncode, "stdout": tests.stdout, "stderr": tests.stderr},
              "test_seconds": time.perf_counter() - started,
              "scope": "Connectivity, AMAF, perspective, cap, seeded worker and actual V2/V3 protocol contracts under ASan/UBSan. Short native searches, not a proof for every input or match workload."}
    (output / "sanitizer-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    if tests.returncode:
        raise RuntimeError("Sanitizer protocol tests failed:\n" + tests.stderr[-12000:])
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/sanitizers")
    parser.add_argument("--compiler")
    args = parser.parse_args()
    print(json.dumps(check(args.output, args.compiler), indent=2))
