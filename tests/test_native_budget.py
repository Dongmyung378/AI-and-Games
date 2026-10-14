"""Actual native protocol checks and guarded historical adapter preservation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from hexai.native import ROOT, resolve_compiler, sha256
from scripts.build_legacy_benchmark import ORIGINAL, build_adapter, generate


def request_line(version="V2", allowance=None, remaining=None, board=None):
    rows = board or ",".join("0" * 11 for _ in range(11))
    text = f"{version};R;11;START;;{rows};1"
    if version == "V3":
        text += f";{allowance};{remaining}"
    return text


class NativeBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = ROOT / ".local/test-temp"
        directory.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=directory)
        cls.work = Path(cls.temporary.name)
        compiler = os.environ.get("HEX_TEST_COMPILER")
        try:
            command = resolve_compiler(compiler)
        except ValueError as error:
            cls.temporary.cleanup()
            raise unittest.SkipTest(str(error))
        cls.native = Path(os.environ["HEX_TEST_NATIVE"]) if "HEX_TEST_NATIVE" in os.environ else cls.work / ("native.exe" if os.name == "nt" else "native")
        if "HEX_TEST_NATIVE" not in os.environ:
            compiled = subprocess.run(command + ["-std=c++17", "-O2", "-pthread", str(ROOT / "native/hex_search.cpp"), "-o", str(cls.native)],
                                      text=True, capture_output=True, timeout=180)
            if compiled.returncode:
                raise RuntimeError(compiled.stderr)
        cls.legacy = Path(os.environ["HEX_TEST_LEGACY"]) if "HEX_TEST_LEGACY" in os.environ else cls.work / ("legacy.exe" if os.name == "nt" else "legacy")
        if "HEX_TEST_LEGACY" not in os.environ:
            build_adapter(cls.legacy, compiler)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_engine(self, engine, message, arguments=None):
        completed = subprocess.run([str(engine), *(arguments or [])], input=message + "\n", capture_output=True,
                                   text=True, timeout=10)
        telemetry = []
        for line in completed.stderr.splitlines():
            try:
                telemetry.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return completed, telemetry

    def test_both_engines_exhausted_external_budget_return_legal_fallback(self):
        for engine in (self.native, self.legacy):
            result, telemetry = self.run_engine(engine, request_line("V3", 0, 0), ["--workers", "2"])
            self.assertEqual(result.returncode, 0, result.stderr)
            move = [int(value) for value in result.stdout.strip().split(",")]
            self.assertTrue(all(0 <= value < 11 for value in move))
            self.assertEqual(telemetry[0]["iterations"], 0)
            self.assertEqual(telemetry[0]["protocol"], "V3")

    def test_external_remaining_caps_search_allocation_and_terminates(self):
        for engine in (self.native, self.legacy):
            result, telemetry = self.run_engine(engine, request_line("V3", .5, .01), ["--workers", "2"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLessEqual(telemetry[0]["effective_search_allowance_seconds"], .01)
            self.assertLess(telemetry[0]["seconds"], 1)

    def test_both_engines_reject_invalid_v3_or_terminal_boards(self):
        terminal = ",".join("R" + "0" * 10 for _ in range(11))
        for engine in (self.native, self.legacy):
            for message in (request_line("V3", "nan", 300), request_line("V3", -1, 300),
                            request_line("V3", 1, 1, terminal), request_line("V3", 1, 1) + ";extra"):
                result, _ = self.run_engine(engine, message)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")

    def test_v2_iteration_mode_and_seeded_legacy_are_exactly_repeatable(self):
        for engine in (self.native, self.legacy):
            arguments = ["--workers", "3", "--iterations", "301", "--seed", "486"]
            first, a = self.run_engine(engine, request_line(), arguments)
            second, b = self.run_engine(engine, request_line(), arguments)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(a[0]["iterations"], 301)
            self.assertEqual(b[0]["iterations"], 301)
            self.assertEqual([w["iterations"] for w in a[0]["workers"]], [101, 100, 100])
            self.assertEqual(a[0]["nodes"], b[0]["nodes"])
            self.assertEqual(a[0]["rave_updates"], b[0]["rave_updates"])
            if engine == self.legacy:
                self.assertEqual(a[0]["rave_updates"], 0)

    def test_legacy_generation_preserves_original_and_guards_source_hash(self):
        before = sha256(ORIGINAL)
        receipt = generate(ORIGINAL, self.work / "generated.cpp")
        self.assertEqual(before, sha256(ORIGINAL))
        self.assertTrue(all(item["unchanged"] for item in receipt["unchanged_algorithm_regions"]))
        changed = self.work / "tampered.cpp"
        changed.write_text(ORIGINAL.read_text(encoding="utf-8") + "// changed\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            generate(changed, self.work / "refused.cpp")
        self.assertFalse((self.work / "refused.cpp").exists())
        with self.assertRaises(ValueError):
            generate(ORIGINAL, ORIGINAL)

    def test_v3_is_deadline_mode_unless_iteration_limit_is_explicit(self):
        result, telemetry = self.run_engine(self.native, request_line("V3", .06, 1), ["--workers", "1"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(telemetry[0]["iterations"], 0)
        self.assertGreater(telemetry[0]["seconds"], .025)
        fixed, telemetry_fixed = self.run_engine(self.native, request_line("V3", 1, 1), ["--iterations", "3"])
        self.assertEqual(fixed.returncode, 0, fixed.stderr)
        self.assertEqual(telemetry_fixed[0]["iterations"], 3)


if __name__ == "__main__":
    unittest.main()
