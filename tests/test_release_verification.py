"""Saved-evidence validation across source versions and checkout line endings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from hexai.evaluation import manifest_hash, run_game, summarize
from scripts.verify_release import ROOT, file_check, safe_path, verify, verify_suite
from tests.test_public_package import small_manifest


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class SavedReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = ROOT / ".local/test-temp"
        temporary.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_file_checksum_normalizes_only_declared_text(self):
        text = b"line one\nline two\n"
        (self.root / "text.py").write_bytes(text.replace(b"\n", b"\r\n"))
        spec = {"canonical_lf": True, "sha256": hashlib.sha256(text).hexdigest(), "bytes": len(text)}
        self.assertTrue(file_check(self.root, "text.py", spec)["canonical_lf"])
        binary = b"\x00\xff\r\n\x00"
        (self.root / "binary").write_bytes(binary)
        binary_spec = {"sha256": hashlib.sha256(binary).hexdigest(), "bytes": len(binary)}
        self.assertFalse(file_check(self.root, "binary", binary_spec)["canonical_lf"])
        (self.root / "text.py").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            file_check(self.root, "text.py", spec)

    def test_default_prefers_new_inventory_without_rewriting_historical_inventory(self):
        payload = b"unchanged\n"
        (self.root / "historical.py").write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        dump(self.root / "reports/original.json", {"original_commit": "old",
             "files": {"historical.py": {"canonical_sha256": digest, "bytes": len(payload)}}})
        dump(self.root / "reports/release-manifest-v2.json", {"schema_version": 2,
             "original_inventory": "reports/original.json",
             "files": {"historical.py": {"sha256": digest, "bytes": len(payload)}}})
        old = b'{"historical":"inventory retained verbatim"}\n'
        (self.root / "reports/release-manifest.json").write_bytes(old)
        result = verify(self.root)
        self.assertEqual(result["release_manifest"], "reports/release-manifest-v2.json")
        self.assertEqual(result["original_files_unchanged"], 1)
        self.assertEqual((self.root / "reports/release-manifest.json").read_bytes(), old)

    def test_repository_escape_paths_are_rejected_on_every_platform(self):
        for relative in ("../outside", "/tmp/outside", r"..\outside", "C:/outside"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                safe_path(self.root, relative)

    def saved_suite(self):
        config = small_manifest()
        config["games"] += [{**game, "game_id": "second-" + game["game_id"], "pair_id": "second-pair",
                             "seed": game["seed"] + 1, "opening_seed": game["opening_seed"] + 1}
                            for game in list(config["games"])]
        dump(self.root / "configs/suite.json", config)
        runner = b"historical runner version\n"
        native = b"historical native version\n"
        archive_path = self.root / "reports/historical/source.zip"
        archive_path.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive_path, "w") as archive:
            for name in ("native.py", "referee.py", "evaluation.py", "cli.py"):
                archive.writestr("hexai/" + name, runner)
            archive.writestr("native/hex_search.cpp", native)
        # The release currently contains newer code. Historical validation must
        # use the pinned snapshot instead of claiming these matches used it.
        (self.root / "hexai").mkdir()
        (self.root / "native").mkdir()
        (self.root / "hexai/evaluation.py").write_bytes(b"new runner version\n")
        (self.root / "native/hex_search.cpp").write_bytes(b"new native version\n")
        results, directories = [], []
        for index, game in enumerate(config["games"]):
            directory = "reports/runs/" + str(index // 2)
            if directory not in directories:
                directories.append(directory)
            dump(self.root / directory / "manifest.json", config)
            runner_bytes = runner if index < 2 else runner.replace(b"\n", b"\r\n")
            native_bytes = native if index < 2 else native.replace(b"\n", b"\r\n")
            binaries = {label: {"sha256": "binary-" + label, "build_receipt": {
                "source_sha256": hashlib.sha256(native_bytes).hexdigest(),
                "executable_sha256": "binary-" + label}} for label in config["participants"]}
            dump(self.root / directory / "metadata.json", {
                "manifest_sha256": manifest_hash(config), "binaries": binaries,
                "runner_sha256": {name: hashlib.sha256(runner_bytes).hexdigest()
                                  for name in ("native.py", "referee.py", "evaluation.py", "cli.py")},
                "environment": {"system": "test"}})
            class Fake:
                telemetry = []
                peak_rss_bytes = None
                def __init__(self, command):
                    pass
                def request(self, message, timeout):
                    fields = message.split(";")
                    colour, board = fields[1], fields[5].split(",")
                    x, y = (next(row for row in range(3) if board[row][0] == "0"), 0) if colour == "R" else (
                        next(row for row in range(3) if board[row][1] == "0"), 1)
                    return (x, y), .001
                def close(self):
                    pass
            result = run_game(config, game, process_factory=Fake)
            self.assertEqual(result["status"], "completed")
            dump(self.root / directory / "games" / (game["game_id"] + ".json"), result)
            results.append(result)
        dump(self.root / "reports/aggregate.json", summarize(config, results))
        return {"manifest": "configs/suite.json", "aggregate": "reports/aggregate.json",
                "run_dirs": directories, "expected_games": 4, "expected_completed": 4,
                "source_archive": "reports/historical/source.zip"}

    def test_historical_source_archive_validates_lf_and_crlf_hosts_without_live_code_equality(self):
        suite = self.saved_suite()
        result = verify_suite(self.root, suite)
        self.assertEqual(result["games"], 4)
        self.assertEqual(result["replayed_moves"], 20)
        self.assertEqual(len(result["recorded_native_source_hashes"]["a"]), 2)
        self.assertEqual(result["source_archive"], suite["source_archive"])

    def test_runner_source_change_is_rejected_within_historical_suite(self):
        suite = self.saved_suite()
        path = self.root / suite["run_dirs"][1] / "metadata.json"
        metadata = json.loads(path.read_text())
        metadata["runner_sha256"]["evaluation.py"] = hashlib.sha256(b"unrelated source\n").hexdigest()
        dump(path, metadata)
        with self.assertRaisesRegex(ValueError, "Pinned runner source differs"):
            verify_suite(self.root, suite)

    def test_saved_executable_and_build_receipt_must_agree(self):
        suite = self.saved_suite()
        path = self.root / suite["run_dirs"][1] / "metadata.json"
        metadata = json.loads(path.read_text())
        metadata["binaries"]["a"]["sha256"] = "changed-binary"
        dump(path, metadata)
        with self.assertRaisesRegex(ValueError, "executable hash differs"):
            verify_suite(self.root, suite)

    def test_modern_game_signature_tampering_is_rejected_before_aggregation(self):
        suite = self.saved_suite()
        for relative in suite["run_dirs"]:
            path = self.root / relative / "metadata.json"
            metadata = json.loads(path.read_text())
            metadata["schema_version"] = 2
            metadata["execution_signature"] = {"hardware": {"hardware_sha256": "recorded-host"},
                                               "participants": {"a": {"workers": 1}, "b": {"workers": 1}}}
            dump(path, metadata)
            for game_path in (self.root / relative / "games").glob("*.json"):
                game = json.loads(game_path.read_text())
                game["execution_signature"] = metadata["execution_signature"]
                dump(game_path, game)
        damaged_path = next((self.root / suite["run_dirs"][1] / "games").glob("*.json"))
        damaged = json.loads(damaged_path.read_text())
        damaged["execution_signature"]["hardware"]["hardware_sha256"] = "different-host"
        dump(damaged_path, damaged)
        with self.assertRaisesRegex(ValueError, "execution signature differs"):
            verify_suite(self.root, suite)

    def test_identical_signatures_do_not_allow_pair_legs_in_different_runs(self):
        suite = self.saved_suite()
        # The two metadata records intentionally describe the same allocation
        # class and binaries. Provenance still requires both legs in one run.
        first = self.root / suite["run_dirs"][0]
        second = self.root / suite["run_dirs"][1]
        first_metadata = json.loads((first / "metadata.json").read_text())
        first_metadata["schema_version"] = 2
        first_metadata["execution_signature"] = {"hardware": {"hardware_sha256": "same-allocation-class"},
                                                   "participants": {"a": {"workers": 1}, "b": {"workers": 1}}}
        dump(first / "metadata.json", first_metadata)
        dump(second / "metadata.json", first_metadata)
        games = []
        for run in (first, second):
            for game_path in (run / "games").glob("*.json"):
                game = json.loads(game_path.read_text())
                game["execution_signature"] = first_metadata["execution_signature"]
                dump(game_path, game)
                games.append(game)
        config = json.loads((self.root / suite["manifest"]).read_text())
        dump(self.root / suite["aggregate"], summarize(config, games))
        self.assertEqual(verify_suite(self.root, suite)["games"], 4)
        # Move only one side of the first pair into the other recorded run.
        leg = first / "games/pair-b.json"
        leg.replace(second / "games/pair-b.json")
        with self.assertRaisesRegex(ValueError, "pair spans different recorded run"):
            verify_suite(self.root, suite)


if __name__ == "__main__":
    unittest.main()
