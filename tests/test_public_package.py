"""Portable public package contracts, without submitting any remote job."""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.package_kaggle_cpu import (ROOT, assigned_game_ids, completion_record,
                                       package, selected_files, write_flat_outputs)
from hexai.evaluation import evaluate, manifest_hash


def small_manifest():
    return {"schema_version": 1, "suite_id": "portable-package-contract",
            "split": "development", "board_size": 3,
            "budget": {"mode": "iterations", "iterations": 20, "workers": 1},
            "participants": {"a": {"kind": "native", "policy": "ucb"},
                             "b": {"kind": "native", "policy": "ts"}},
            "games": [{"game_id": "pair-a", "pair_id": "pair", "red": "a", "blue": "b",
                       "seed": 378, "opening_seed": 12, "opening_moves": []},
                      {"game_id": "pair-b", "pair_id": "pair", "red": "b", "blue": "a",
                       "seed": 378, "opening_seed": 12, "opening_moves": []}]}


def embedded_payload(script):
    for statement in ast.parse(script).body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "ARCHIVE_B85"
                for target in statement.targets):
            return base64.b85decode(ast.literal_eval(statement.value))
    raise AssertionError("Embedded source archive missing.")


class PublicPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = ROOT / ".local/test-temp"
        temporary.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.config = self.directory / "manifest.json"
        self.config.write_text(json.dumps(small_manifest()), encoding="utf-8")

    def test_embedded_source_is_complete_canonical_and_contains_no_prebuilt_binary(self):
        output = self.directory / "package"
        receipt = package("example", "hex-cpu-check", self.config, output)
        payload = embedded_payload((output / "kernel.py").read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(payload).hexdigest(), receipt["archive_sha256"])
        inventory = json.loads((output / "source-inventory.json").read_text())
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertEqual(set(archive.namelist()), set(inventory))
            self.assertEqual(set(selected_files(ROOT)) | {"configs/frozen.json"}, set(inventory))
            self.assertNotIn("deployment/agents/Group026/RAVE_TS", inventory)
            self.assertNotIn(".local/bin/hex_search", inventory)
            for name, spec in inventory.items():
                content = archive.read(name)
                self.assertEqual(hashlib.sha256(content).hexdigest(), spec["sha256"])
                self.assertEqual(len(content), spec["bytes"])
                self.assertNotIn(b"\r\n", content)
                if name.endswith(".py"):
                    compile(content.decode("utf-8"), name, "exec")
            historical = json.loads(archive.read("deployment/agents/Group026/build-info.json"))
            source = archive.read("deployment/agents/Group026/RAVE_TS.cpp")
            self.assertEqual(hashlib.sha256(source.replace(b"\r", b"\n")).hexdigest(),
                             historical["source_sha256"])

    def test_job_is_private_cpu_only_and_has_explicit_flat_outputs(self):
        output = self.directory / "package"
        package("example", "hex-cpu-check", self.config, output)
        metadata = json.loads((output / "kernel-metadata.json").read_text())
        self.assertTrue(metadata["is_private"])
        for key in ("enable_gpu", "enable_tpu", "enable_internet"):
            self.assertFalse(metadata[key])
        script = (output / "kernel.py").read_text()
        self.assertTrue("write_flat_outputs(work, result, completion)" in script,
                        "Kernel must save downloadable outputs through the tested helper.")
        self.assertIn("historical_source_checksum_matches", script)
        self.assertIn("original_shipped_binary_embedded", script)

    def test_package_archive_is_deterministic_and_refuses_nonempty_output(self):
        first = package("example", "hex-cpu-check", self.config, self.directory / "first")
        second = package("example", "hex-cpu-check", self.config, self.directory / "second")
        self.assertEqual(first["archive_sha256"], second["archive_sha256"])
        self.assertEqual(first["kernel_script_sha256"], second["kernel_script_sha256"])
        with self.assertRaisesRegex(ValueError, "not empty"):
            package("example", "hex-cpu-check", self.config, self.directory / "first")

    def test_nonportable_or_source_overwriting_executable_is_rejected(self):
        for destination in ("../../outside", "C:/local/native.exe", "/tmp/native",
                            r"relative\native", "native/hex_search.cpp", "configs/frozen.json",
                            ".local/bin/native.build.json"):
            config = small_manifest()
            config["participants"]["a"]["executable"] = destination
            self.config.write_text(json.dumps(config))
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                package("example", "hex-cpu-check", self.config, self.directory / "bad")

    def test_portable_custom_destinations_and_shards_are_recorded(self):
        config = small_manifest()
        config["games"] += [{**game, "game_id": "second-" + game["game_id"],
                             "pair_id": "second", "seed": game["seed"] + 1,
                             "opening_seed": game["opening_seed"] + 1}
                            for game in list(config["games"])]
        config["participants"]["a"]["executable"] = "/kaggle/working/hex-source/.local/bin/custom"
        self.config.write_text(json.dumps(config))
        receipt = package("example", "hex-cpu-check", self.config, self.directory / "good",
                          shard_index=1, shard_count=2)
        self.assertEqual((receipt["shard_index"], receipt["shard_count"]), (1, 2))
        self.assertEqual(receipt["assigned_games"], 2)
        with self.assertRaises(ValueError):
            package("example", "hex-cpu-check", self.config, self.directory / "bad",
                    shard_index=2, shard_count=2)

    def test_opt_in_sanitizers_include_actual_native_protocol_checker(self):
        receipt = package("example", "hex-cpu-check", self.config, self.directory / "sanitizers",
                          sanitizers=True)
        self.assertTrue(receipt["sanitizers_requested"])
        inventory = json.loads((self.directory / "sanitizers/source-inventory.json").read_text())
        for name in ("scripts/check_native_sanitizers.py", "scripts/build_legacy_benchmark.py",
                     "tests/test_native_budget.py", "tests/__init__.py"):
            self.assertIn(name, inventory)

    def test_ten_shards_keep_all_400_games_and_each_side_pair_together(self):
        config = small_manifest()
        originals = list(config["games"])
        config["games"] = [{**game, "game_id": str(index) + "-" + game["game_id"],
                            "pair_id": str(index) + "-pair", "seed": game["seed"] + index,
                            "opening_seed": game["opening_seed"] + index}
                           for index in range(200) for game in originals]
        assignments = [set(assigned_game_ids(config, index, 10)) for index in range(10)]
        self.assertTrue(all(len(games) == 40 for games in assignments))
        self.assertEqual(len(set.union(*assignments)), 400)
        self.assertEqual(sum(map(len, assignments)), 400)
        for index in range(200):
            ids = {str(index) + "-" + game["game_id"] for game in originals}
            self.assertEqual(sum(ids <= games for games in assignments), 1)

    def test_assigned_shard_completion_does_not_claim_global_completion(self):
        config = small_manifest()
        config["games"] += [{**game, "game_id": "second-" + game["game_id"],
                             "pair_id": "second", "seed": game["seed"] + 1,
                             "opening_seed": game["opening_seed"] + 1}
                            for game in list(config["games"])]
        records = [{"game_id": game["game_id"], "status": "completed"}
                   for game in config["games"][:2]]
        summary = {"manifest_sha256": manifest_hash(config), "recorded_games": 2}
        receipt = completion_record(config, records, summary, shard_index=0, shard_count=2)
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["scope"], "assigned_shard")
        self.assertEqual(receipt["completed_assigned_games"], 2)
        self.assertEqual(receipt["global_manifest_games"], 4)
        self.assertFalse(receipt["global_manifest_records_complete_from_this_run"])
        checkpoint_summary = {**summary, "recorded_games": 1,
                              "checkpoint_stop": {"reason": "wall_time_guard"}}
        partial = completion_record(config, records[:1], checkpoint_summary, shard_index=0, shard_count=2)
        self.assertEqual(partial["status"], "checkpointed")
        self.assertEqual(partial["partial_recorded_pair_ids"], ["pair"])
        self.assertEqual(partial["completed_assigned_pairs"], 0)
        records[1]["status"] = "timeout"
        receipt = completion_record(config, records, summary, shard_index=0, shard_count=2)
        self.assertEqual(receipt["status"], "completed_with_failures")
        self.assertEqual(receipt["failed_assigned_game_ids"], ["pair-b"])

    def test_real_wall_guard_checkpoints_and_saves_downloadable_flat_zip(self):
        # Exercise the existing evaluator's real between-game wall guard. No
        # participant process can launch because the declared cap will not fit.
        binary = self.directory / "unused-engine"
        binary.write_bytes(b"not executed")
        output = self.directory / "results/evaluation"
        summary = evaluate(self.config, output, binary, max_wall_seconds=.001,
                           checkpoint_margin_seconds=0)
        self.assertEqual(summary["recorded_games"], 0)
        self.assertEqual(summary["checkpoint_stop"]["reason"], "wall_time_guard")
        receipt = completion_record(small_manifest(), [], summary)
        self.assertEqual(receipt["status"], "checkpointed")
        self.assertEqual(receipt["missing_assigned_game_ids"], ["pair-a", "pair-b"])
        published = write_flat_outputs(self.directory, output.parent, receipt)
        archive_path = self.directory / published["result_archive"]
        self.assertEqual(hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                         published["result_archive_sha256"])
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn("evaluation/summary.json", archive.namelist())
            archived = json.loads(archive.read("completion.json"))
            self.assertEqual(archived["status"], "checkpointed")
        flat = json.loads((self.directory / "hex-public-cpu-completion.json").read_text())
        self.assertEqual(flat["status"], "checkpointed")

    def test_wall_limits_are_explicit_and_empty_shards_are_rejected(self):
        receipt = package("example", "hex-cpu-check", self.config, self.directory / "bounded")
        self.assertEqual(receipt["max_wall_seconds"], 33000)
        self.assertEqual(receipt["checkpoint_margin_seconds"], 120)
        script = (self.directory / "bounded/kernel.py").read_text()
        self.assertIn("--max-wall-seconds", script)
        self.assertIn("--checkpoint-margin-seconds", script)
        for wall, margin in ((float("nan"), 120), (33000, float("inf")), (120, 120)):
            with self.subTest(wall=wall, margin=margin), self.assertRaises(ValueError):
                package("example", "hex-cpu-check", self.config, self.directory / "bad",
                        max_wall_seconds=wall, checkpoint_margin_seconds=margin)
        with self.assertRaisesRegex(ValueError, "no assigned games"):
            package("example", "hex-cpu-check", self.config, self.directory / "empty",
                    shard_index=1, shard_count=2)


if __name__ == "__main__":
    unittest.main()
