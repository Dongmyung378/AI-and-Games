"""Meaningful protocol, referee, failure and frozen-evaluation contracts."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hexai.evaluation import (aggregate, atomic_json, evaluate, manifest_hash,
                             run_game, replay, summarize, validate_manifest)
from hexai.native import EngineError, NativeProcess
from hexai.referee import Colour, Referee
from src.Game import Game


def manifest():
    return {"schema_version": 1, "suite_id": "contract-test", "split": "development", "board_size": 3,
            "budget": {"mode": "iterations", "iterations": 25, "workers": 1},
            "participants": {"a": {"kind": "native", "policy": "ucb"}, "b": {"kind": "native", "policy": "ts"}},
            "games": [{"game_id": "pair0-a", "pair_id": "pair0", "red": "a", "blue": "b", "seed": 378,
                       "opening_seed": 12, "opening_moves": []},
                      {"game_id": "pair0-b", "pair_id": "pair0", "red": "b", "blue": "a", "seed": 378,
                       "opening_seed": 12, "opening_moves": []}]}


def fake_factory(choices, failure=None):
    class Fake:
        def __init__(self, command):
            policy = command[command.index("--policy") + 1]
            self.label = "a" if policy == "ucb" else "b"
            self.moves = iter(choices.get(self.label, []))
            self.telemetry = []
        def request(self, message, timeout):
            if failure:
                raise EngineError(failure, "test failure")
            return next(self.moves), .001
        def close(self):
            pass
    return Fake


class RefereeTests(unittest.TestCase):
    def test_swap_trace_matches_preserved_game(self):
        state = Referee(3, "a", "b")
        original = Game.__new__(Game)
        original._board = type(state.board)(3)
        original.players = {colour: SimpleNamespace(name=name, agent=SimpleNamespace(colour=colour), move_time=0)
                            for colour, name in ((Colour.RED, "a"), (Colour.BLUE, "b"))}
        original.current_player, original.has_swapped, original._turn = Colour.RED, False, 1
        original.logDest = io.StringIO()
        from src.Move import Move
        for xy in ((0, 0), (-1, -1), (1, 0), (0, 1), (1, 1), (2, 2), (1, 2)):
            self.assertEqual(state.actor, original.players[original.current_player].name)
            self.assertEqual(state.colour, original.current_player)
            self.assertTrue(original.is_valid_move(Move(*xy), original.turn, original.board))
            original._make_move(Move(*xy))
            state.play(xy)
            self.assertEqual(state.board, original.board)
            if not state.winner:
                original.current_player = Colour.opposite(original.current_player)
                original._turn += 1
        self.assertEqual(state.winner, "a")
        self.assertEqual(state.board.get_winner(), Colour.BLUE)

    def test_connectivity_and_illegal_moves(self):
        state = Referee(3, "a", "b")
        for move in ((0, 0), (0, 1), (1, 0), (1, 1)):
            state.play(move)
        self.assertIsNone(state.winner)
        with self.assertRaises(ValueError):
            state.play((0, 0))
        with self.assertRaises(ValueError):
            state.play((-1, -1))
        state.play((2, 0))
        self.assertEqual(state.winner, "a")

    def test_protocol_explicit_colour_after_swap(self):
        state = Referee(3, "a", "b")
        state.play((1, 1))
        state.play((-1, -1))
        self.assertEqual(state.actor, "a")
        self.assertTrue(state.message().startswith("V2;B;3;SWAP;;"))
        state.play((0, 0))
        self.assertEqual(state.actor, "b")
        self.assertTrue(state.message().startswith("V2;R;3;CHANGE;0,0;"))


class ManifestTests(unittest.TestCase):
    def test_duplicate_game_and_mismatched_pair_rejected(self):
        config = manifest()
        validate_manifest(config)
        config["games"][1]["game_id"] = config["games"][0]["game_id"]
        with self.assertRaises(ValueError):
            validate_manifest(config)
        config = manifest()
        config["games"][1]["seed"] += 1
        with self.assertRaises(ValueError):
            validate_manifest(config)

    def test_config_hash_covers_budget_and_opening(self):
        config = manifest()
        other = copy.deepcopy(config)
        other["budget"]["iterations"] += 1
        self.assertNotEqual(manifest_hash(config), manifest_hash(other))
        other = copy.deepcopy(config)
        other["games"][0]["opening_moves"] = [[1, 1]]
        self.assertNotEqual(manifest_hash(config), manifest_hash(other))

    def test_nonfinite_and_legacy_mutation_rejected(self):
        config = manifest()
        config["budget"] = {"mode": "time", "seconds": float("nan")}
        with self.assertRaises(ValueError):
            validate_manifest(config)
        config = manifest()
        config["board_size"] = 11
        config["participants"]["b"] = {"kind": "legacy", "workers": 2}
        with self.assertRaises(ValueError):
            validate_manifest(config)


class EvaluationTests(unittest.TestCase):
    def test_completed_and_swap_replay_prove_identity(self):
        config = manifest()
        factory = fake_factory({"a": [(0, 0), (1, 0), (1, 1), (1, 2)], "b": [(-1, -1), (0, 1), (2, 2)]})
        result = run_game(config, config["games"][0], process_factory=factory)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["winner"], "a")
        self.assertEqual(result["winning_colour"], "B")
        self.assertTrue(replay(result)["verified"])
        result["winner"] = "b"
        with self.assertRaises(ValueError):
            replay(result)

    def test_failures_cannot_be_counted_as_wins(self):
        config = manifest()
        for status in ("timeout", "protocol_error", "process_error"):
            result = run_game(config, config["games"][0], process_factory=fake_factory({}, status))
            self.assertEqual(result["status"], status)
            self.assertIsNone(result["winner"])
            self.assertTrue(replay(result)["verified"])
            stats = summarize(config, [result])["comparisons"][0]
            self.assertEqual(stats["completed_games"], 0)
            self.assertIsNone(stats["left_win_rate_completed_games"])
            self.assertEqual(stats["failure_rate_recorded"], 1)

    def test_illegal_move_recorded_and_replay_checked(self):
        config = manifest()
        result = run_game(config, config["games"][0], process_factory=fake_factory({"a": [(0, 0)], "b": [(0, 0)]}))
        self.assertEqual(result["status"], "illegal_move")
        self.assertIsNone(result["winner"])
        self.assertEqual(result["failure_actor"], "b")
        self.assertTrue(replay(result)["verified"])

    def test_pair_clusters_and_missing_games(self):
        config = manifest()
        results = [{**game, "status": "completed", "winner": "a"} for game in config["games"]]
        summary = summarize(config, results)
        comparison = summary["comparisons"][0]
        self.assertEqual(comparison["complete_side_pairs"], 1)
        self.assertIsNone(comparison["paired_cluster_bootstrap_95"])
        self.assertEqual(comparison["left_win_rate_completed_games"], 1)
        with self.assertRaises(ValueError):
            summarize(config, results + results[:1])

    def test_resume_changed_manifest_and_pair_sharding(self):
        config = manifest()
        config["games"] += [{**game, "game_id": game["game_id"].replace("pair0", "pair1"), "pair_id": "pair1", "seed": 379, "opening_seed": 13}
                            for game in list(config["games"])]
        temp_root = Path(__file__).resolve().parents[1] / ".local" / "test-temp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            directory = Path(temporary)
            binary = directory / "fake-engine"
            binary.write_text("test executable bytes")
            source = directory / "config.json"
            atomic_json(source, config)
            def simulated(manifest, game, executable):
                choices = {game["red"]: [(0, 0), (1, 0), (2, 0)], game["blue"]: [(0, 1), (1, 1)]}
                return run_game(manifest, game, process_factory=fake_factory(choices))
            with patch("hexai.evaluation.run_game", simulated):
                result = evaluate(source, directory / "run", binary, 0, 2)
            self.assertEqual(result["recorded_games"], 2)
            self.assertEqual(result["comparisons"][0]["complete_side_pairs"], 1)
            config["budget"]["iterations"] += 1
            atomic_json(source, config)
            with self.assertRaises(ValueError):
                evaluate(source, directory / "run", binary, 0, 2, resume=True)


class ProcessTests(unittest.TestCase):
    def test_bounded_timeout_cleans_up_live_process(self):
        engine = NativeProcess([sys.executable, "-c", "import sys,time;sys.stdin.readline();time.sleep(30)"])
        try:
            with self.assertRaises(EngineError) as caught:
                engine.request("test", .05)
            self.assertEqual(caught.exception.status, "timeout")
        finally:
            engine.close()
        self.assertIsNotNone(engine.process.poll())

    def test_stderr_does_not_deadlock_or_disappear(self):
        script = "import sys,json;sys.stdin.readline();print('1,2',flush=True);print(json.dumps({'kind':'test','value':3}),file=sys.stderr,flush=True)"
        with NativeProcess([sys.executable, "-c", script]) as engine:
            move, _ = engine.request("test", 5)
            self.assertEqual(move, (1, 2))
        self.assertIn({"kind": "test", "value": 3}, engine.telemetry)


if __name__ == "__main__":
    unittest.main()
