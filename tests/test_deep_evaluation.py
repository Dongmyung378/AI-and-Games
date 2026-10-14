"""External budget accounting, public signatures and multi-position measurements."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hexai.cli import benchmark, benchmark_fixtures, validate_fixtures
from hexai.evaluation import (atomic_json, evaluate, move_budget, participant_command,
                              replay, run_game, summarize, validate_manifest)
from hexai.native import EngineError, hardware_signature
from tests.test_evaluation import fake_factory, manifest


class SharedBudgetTests(unittest.TestCase):
    def test_allocator_retains_late_game_headroom(self):
        budget = {"mode": "game_time", "game_seconds": 300, "expected_actor_moves": 24,
                  "minimum_future_actor_moves": 8, "io_reserve_seconds": .05,
                  "response_margin_seconds": 2}
        first = move_budget(budget, 0, 0)
        self.assertAlmostEqual(first["assigned_search_seconds"], 299.95 / 24)
        spent = 0
        for number in range(50):
            allocation = move_budget(budget, spent, number)
            self.assertLess(allocation["assigned_search_seconds"], allocation["remaining_seconds"])
            spent += allocation["assigned_search_seconds"]
        self.assertGreater(300 - spent, .05)
        self.assertGreater(300 - spent, 0)

    def test_v3_budget_reconstructs_across_pie_role_change(self):
        config = manifest()
        config["budget"] = {"mode": "game_time", "game_seconds": 300, "workers": 1}
        validate_manifest(config)
        result = run_game(config, config["games"][0], process_factory=fake_factory(
            {"a": [(0, 0), (1, 0), (1, 1), (1, 2)], "b": [(-1, -1), (0, 1), (2, 2)]}))
        self.assertEqual(result["winner"], "a")
        self.assertEqual(result["participant_requests"], {"a": 4, "b": 3})
        for event in result["moves"]:
            self.assertTrue(event["message"].startswith("V3;"))
            self.assertEqual(len(event["message"].split(";")), 9)
        self.assertTrue(replay(result)["verified"])
        damaged = copy.deepcopy(result)
        damaged["moves"][2]["budget_allocation"]["assigned_search_seconds"] += 1
        with self.assertRaisesRegex(ValueError, "allocation"):
            replay(damaged)
        damaged = copy.deepcopy(result)
        damaged["participant_seconds"]["a"] += 1
        with self.assertRaisesRegex(ValueError, "accounting"):
            replay(damaged)

    def test_timeout_response_is_accounted_without_fabricated_move(self):
        config = manifest()
        config["budget"] = {"mode": "game_time", "game_seconds": 300}
        class Failure:
            telemetry = []
            def __init__(self, command):
                pass
            def request(self, message, timeout):
                raise EngineError("timeout", "controlled timeout", 1.25)
            def close(self):
                pass
        result = run_game(config, config["games"][0], process_factory=Failure)
        self.assertEqual(result["participant_seconds"]["a"], 1.25)
        self.assertEqual(len(result["moves"]), 0)
        self.assertEqual(len(result["request_failures"]), 1)
        self.assertTrue(replay(result)["verified"])
        comparison = summarize(config, [result])["comparisons"][0]
        self.assertEqual(comparison["left_verified_wins_per_scheduled_game"], 0)
        self.assertEqual(comparison["failure_rate_scheduled"], .5)
        self.assertEqual(comparison["missing_games"], 1)

    def test_controlled_adapter_is_explicit_and_equal_workers_required(self):
        config = manifest()
        config["board_size"] = 11
        config["budget"] = {"mode": "game_time", "game_seconds": 300, "workers": 2}
        config["participants"]["b"] = {"kind": "benchmark_legacy", "executable": "legacy-adapter"}
        validate_manifest(config)
        command = participant_command(config["participants"]["b"], config["budget"], config["games"][0], "B", "new")
        self.assertIn("--workers", command)
        self.assertNotIn("--policy", command)
        self.assertNotIn("--iterations", command)
        config["participants"]["b"]["workers"] = 8
        with self.assertRaisesRegex(ValueError, "identical"):
            validate_manifest(config)
        config["participants"]["b"] = {"kind": "legacy", "executable": "exact-old"}
        with self.assertRaisesRegex(ValueError, "Unmodified"):
            validate_manifest(config)

    def test_cross_host_side_pair_is_rejected(self):
        config = manifest()
        results = [{**game, "status": "completed", "winner": "a", "execution_signature": {"host": index}}
                   for index, game in enumerate(config["games"])]
        with self.assertRaisesRegex(ValueError, "crossed"):
            summarize(config, results)

    def test_hardware_signature_does_not_publish_hostname(self):
        with patch("hexai.native.platform.node", return_value="private-computer-name"):
            signature = hardware_signature({"system": "Linux", "logical_cpus": 4})
        self.assertNotIn("private-computer-name", json.dumps(signature))
        self.assertEqual(len(signature["host_sha256"]), 64)

    def test_checkpoint_guard_creates_resumable_empty_receipt(self):
        root = Path(__file__).resolve().parents[1] / ".local" / "test-temp"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            directory = Path(temporary)
            binary = directory / "fake-engine"
            binary.write_text("same executable")
            source = directory / "config.json"
            atomic_json(source, manifest())
            with patch("hexai.evaluation.run_game") as play:
                result = evaluate(source, directory / "run", binary, max_wall_seconds=1)
                play.assert_not_called()
            self.assertTrue(result["checkpoint_stop"]["resume_required"])
            self.assertEqual(result["recorded_games"], 0)
            self.assertTrue((directory / "run" / "metadata.json").is_file())

    def test_source_change_prevents_claiming_stale_binary_as_current(self):
        from hexai.native import sha256
        root = Path(__file__).resolve().parents[1] / ".local" / "test-temp"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            directory = Path(temporary)
            binary = directory / "fake-engine"
            binary.write_text("same executable")
            native_source = directory / "engine.cpp"
            native_source.write_text("old source")
            atomic_json(binary.with_name(binary.name + ".build.json"), {
                "executable_sha256": sha256(binary), "source": str(native_source), "source_sha256": sha256(native_source)})
            native_source.write_text("changed source")
            config = directory / "config.json"
            atomic_json(config, manifest())
            with self.assertRaisesRegex(ValueError, "Source changed"):
                evaluate(config, directory / "run", binary)


class FixtureTests(unittest.TestCase):
    def test_three_fixtures_are_deterministic_legal_and_nonterminal(self):
        fixtures = benchmark_fixtures(11)
        self.assertEqual(fixtures, benchmark_fixtures(11))
        self.assertEqual([item["id"] for item in fixtures], ["opening", "middle", "late"])
        validate_fixtures(fixtures)
        self.assertEqual([item["turn"] for item in fixtures], [2, 41, 81])
        damaged = copy.deepcopy(fixtures)
        damaged[1]["turn"] += 1
        with self.assertRaisesRegex(ValueError, "trace"):
            validate_fixtures(damaged)


if __name__ == "__main__":
    unittest.main()
