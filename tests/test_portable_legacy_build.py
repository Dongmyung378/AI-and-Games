"""Actual compiler and CreateProcess checks for portable historical-adapter paths."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from hexai.native import ROOT, resolve_compiler, sha256
from scripts.build_legacy_benchmark import build_adapter, compiler_output_path, default_output_path

EXPECTED_GENERATED_SHA256 = "f42ab37e1893ba2bf0ac1eb212381803c95132b68d7e2a18a085d46ab240291e"


class OutputPathContracts(unittest.TestCase):
    def test_default_participant_path_is_platform_independent(self):
        self.assertEqual(default_output_path(ROOT), ROOT / ".local/bin/legacy_benchmark")

    def test_windows_extensionless_target_has_explicit_temporary_exe_path(self):
        target = ROOT / ".local/test-temp/adapter"
        self.assertEqual(compiler_output_path(target, windows=True),
                         target.with_name("adapter.compiler-output.exe"))
        self.assertEqual(compiler_output_path(target, windows=False), target)
        explicit_exe = target.with_suffix(".exe")
        self.assertEqual(compiler_output_path(explicit_exe, windows=True), explicit_exe)


class ActualPortableBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            resolve_compiler(os.environ.get("HEX_TEST_COMPILER"))
        except ValueError as error:
            raise unittest.SkipTest(str(error))
        directory = ROOT / ".local/test-temp"
        directory.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=directory)
        cls.work = Path(cls.temporary.name)
        cls.extensionless = cls.work / "portable-legacy"
        cls.explicit_exe = cls.work / "portable-legacy.exe"
        cls.receipt = build_adapter(cls.extensionless, os.environ.get("HEX_TEST_COMPILER"))
        cls.explicit_receipt = build_adapter(cls.explicit_exe, os.environ.get("HEX_TEST_COMPILER"))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_compiler_installs_exact_extensionless_and_explicit_exe_names(self):
        for target, receipt in ((self.extensionless, self.receipt), (self.explicit_exe, self.explicit_receipt)):
            self.assertTrue(target.is_file())
            self.assertEqual(receipt["executable"], str(target))
            self.assertEqual(receipt["executable_sha256"], sha256(target))
            self.assertTrue(receipt["installed_exact_requested_path"])
            generated = target.with_name(target.name + ".cpp")
            self.assertEqual(sha256(generated), EXPECTED_GENERATED_SHA256)
            self.assertEqual(receipt["generated_source_sha256"], EXPECTED_GENERATED_SHA256)
            patch_path = target.parent / receipt["patch_receipt"]
            self.assertEqual(sha256(patch_path), receipt["patch_receipt_sha256"])
            self.assertEqual(json.loads(target.with_name(target.name + ".build.json").read_text()),
                             receipt)
        if os.name == "nt":
            self.assertFalse(self.extensionless.with_name(self.extensionless.name + ".compiler-output.exe").exists())
            self.assertNotEqual(self.receipt["compiler_output"], self.receipt["executable"])

    def test_actual_extensionless_and_explicit_exe_processes_launch(self):
        for binary in (self.extensionless, self.explicit_exe):
            completed = subprocess.run([str(binary), "--version"], capture_output=True,
                                       text=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("hex-legacy-controlled-benchmark", completed.stdout)

    def test_filename_fix_preserves_seeded_algorithm_stream(self):
        rows = ["R" + "0" * 10] + ["0" * 11] * 10
        rows[5] = "00000B00000"
        message = "V2;R;11;CHANGE;5,5;" + ",".join(rows) + ";3\n"
        trials = []
        for binary in (self.extensionless, self.explicit_exe, self.extensionless):
            result = subprocess.run([str(binary), "--seed", "378", "--workers", "1",
                                     "--iterations", "100", "--game-seconds", "5"],
                                    input=message, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            telemetry = json.loads(result.stderr.strip())
            self.assertEqual(telemetry["iterations"], 100)
            self.assertEqual(telemetry["rave_updates"], 0)
            trials.append((result.stdout, telemetry["nodes"], telemetry["workers"]))
        self.assertEqual(trials[0], trials[1])
        self.assertEqual(trials[1], trials[2])


if __name__ == "__main__":
    unittest.main()
