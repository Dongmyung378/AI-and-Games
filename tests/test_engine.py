"""Comprehensive unit & integration tests for Hex-Search v1.2.0 (Pure-CPU C++17 Engine)."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
import unittest

from hexai.battle import BattleReferee, export_sgf, format_algebraic, parse_user_move
from hexai.battle_gui import compute_board_layout, hex_center, hex_vertices, hit_test_hex
from hexai.evaluation import move_budget, participant_command, validate_manifest
from hexai.native import NativeProcess, executable_default
from hexai.referee import Board, Colour, Referee, parse_board

ROOT = Path(__file__).resolve().parents[1]


class RefereeAndGeometryTests(unittest.TestCase):
    def test_board_connectivity_and_winning_path(self):
        b = Board(4)
        for r in range(4):
            b.set_tile_colour(r, 1, Colour.RED)
        self.assertTrue(b.has_ended(Colour.RED))
        self.assertEqual(b.get_winner(), Colour.RED)
        path = b.winning_path(Colour.RED)
        self.assertEqual(len(path), 4)
        self.assertEqual(path[0][0], 0)
        self.assertEqual(path[-1][0], 3)

    def test_parse_board_validation(self):
        b = parse_board("R00,0B0,00R")
        self.assertEqual(b.size, 3)
        self.assertEqual(b.tiles[0][0].colour, Colour.RED)
        self.assertEqual(b.tiles[1][1].colour, Colour.BLUE)
        with self.assertRaises(ValueError):
            parse_board("R0,0B")

    def test_battle_referee_swap_pieces_and_swap_sides(self):
        # Off-diagonal swap-pieces: Red (2,0) -> Blue (0,2), Red moves next, players unchanged
        ref = BattleReferee(11, "AI", "MoHex 3", swap_rule="swap_pieces")
        ref.play((2, 0))
        ref.play((-1, -1))
        self.assertIsNone(ref.board.tiles[2][0].colour)
        self.assertEqual(ref.board.tiles[0][2].colour, Colour.BLUE)
        self.assertEqual(ref.colour, Colour.RED)
        self.assertEqual(ref.actor, "AI")
        self.assertTrue(ref.message().startswith("V2;R;11;SWAP;;"))

        # Diagonal swap-pieces: Red (5,5) -> Blue (5,5)
        ref_diag = BattleReferee(11, "MoHex 3", "AI", swap_rule="swap_pieces")
        ref_diag.play((5, 5))
        ref_diag.play((-1, -1))
        self.assertEqual(ref_diag.board.tiles[5][5].colour, Colour.BLUE)
        self.assertEqual(ref_diag.actor, "MoHex 3")

        # Classic swap-sides: players swap colours, stone stays Red at (2,0)
        ref_sides = Referee(11, "AI", "Opp")
        ref_sides.play((2, 0))
        ref_sides.play((-1, -1))
        self.assertEqual(ref_sides.board.tiles[2][0].colour, Colour.RED)
        self.assertEqual(ref_sides.players[Colour.RED], "Opp")
        self.assertEqual(ref_sides.actor, "AI")

    def test_algebraic_sgf_and_gui_hit_testing(self):
        self.assertEqual(parse_user_move("f6", 11), (5, 5))
        self.assertEqual(parse_user_move("k11", 11), (10, 10))
        self.assertEqual(parse_user_move("5,5", 11), (5, 5))
        self.assertEqual(parse_user_move("swap", 11), (-1, -1))
        self.assertEqual(format_algebraic((5, 5)), "f6")
        sgf = export_sgf(11, "hex-search-v1.2", "MoHex 3", [
            {"colour": "R", "move": [8, 5]},
            {"colour": "B", "move": [-1, -1]},
        ], "hex-search-v1.2", swap_rule="swap_pieces")
        self.assertIn("GM[11]SZ[11]", sgf)
        self.assertIn(";B[f9];W[swap-pieces]", sgf)

        radius, ox, oy = compute_board_layout(900.0, 700.0, 11)
        self.assertGreater(radius, 15.0)
        for tr in (False, True):
            for r in (0, 5, 10):
                for c in (0, 3, 10):
                    cx, cy = hex_center(r, c, radius, ox, oy, transpose=tr)
                    self.assertEqual(len(hex_vertices(cx, cy, radius)), 12)
                    self.assertEqual(hit_test_hex(cx + 1.5, cy - 1.5, 11, radius, ox, oy, transpose=tr), (r, c))
        self.assertIsNone(hit_test_hex(-500.0, -500.0, 11, radius, ox, oy))

    def test_adaptive_v3_clock_allocator_retains_late_game_headroom(self):
        cfg = {"mode": "game_time", "game_seconds": 300.0, "expected_actor_moves": 24, "minimum_future_actor_moves": 8}
        alloc1 = move_budget(cfg, 0.0, 0)
        self.assertAlmostEqual(alloc1["assigned_search_seconds"], (300.0 - 0.05) / 24.0, places=3)
        alloc_late = move_budget(cfg, 250.0, 30)
        self.assertGreater(alloc_late["assigned_search_seconds"], 5.0)
        self.assertLessEqual(alloc_late["assigned_search_seconds"], 50.0)


class NativeEngineV12Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = executable_default()
        if not cls.native.is_file():
            raise unittest.SkipTest("Build native/hex_search.cpp first with: python -m hexai build")

    def test_cpp_self_test_exhaustive_verifications(self):
        completed = subprocess.run([str(self.native), "--self-test"], capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout.strip())
        self.assertEqual(payload["status"], "passed")
        self.assertGreaterEqual(payload["checks"], 26)
        self.assertEqual(payload["exhaustive_connectivity_positions"], 19683)
        self.assertEqual(payload["dead_cell_verifications"], 8784)

    def test_tree_reuse_and_version_telemetry(self):
        cmd = [
            str(self.native), "--policy", "grave_ts", "--seed", "77", "--workers", "1",
            "--iterations", "2000", "--tactics", "0", "--swap", "0", "--tree-reuse", "1",
        ]
        board = [["0"] * 5 for _ in range(5)]
        encode = lambda g: ",".join("".join(row) for row in g)
        with NativeProcess(cmd) as engine:
            m1, _ = engine.request(f"V2;R;5;START;;{encode(board)};1", 10)
            board[m1[0]][m1[1]] = "R"
            opp = (2, 2) if board[2][2] == "0" else (2, 1)
            board[opp[0]][opp[1]] = "B"
            m2, _ = engine.request(f"V2;R;5;CHANGE;{opp[0]},{opp[1]};{encode(board)};3", 10)
            self.assertEqual(board[m2[0]][m2[1]], "0")
            empty_board = ",".join("0" * 5 for _ in range(5))
            engine.request(f"V2;R;5;START;;{empty_board};1", 10)

        moves = [t for t in engine.telemetry if t.get("kind") == "hex_search_move"]
        self.assertEqual(len(moves), 3)
        self.assertEqual(moves[0]["version"], "1.2.0")
        self.assertEqual(moves[0]["reused_nodes"], 0)
        self.assertGreater(moves[1]["reused_nodes"], 0)
        self.assertGreater(moves[1]["reused_visits"], 0)
        self.assertEqual(moves[2]["reused_nodes"], 0)

    def test_gtp_protocol_session(self):
        script = (
            "1 protocol_version\n2 name\n3 version\n4 boardsize 5\n5 clear_board\n"
            "6 play black c3\n7 genmove white\n8 showboard\n9 final_score\n10 quit\n"
        )
        completed = subprocess.run(
            [str(self.native), "--gtp", "--workers", "2", "--seconds", "0.05", "--seed", "42"],
            input=script, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        out = completed.stdout
        self.assertIn("=1 2\n", out)
        self.assertIn("=2 hex-search\n", out)
        self.assertIn("=3 1.2.0\n", out)
        self.assertIn("=9 ?\n", out)

    def test_ponder_protocol_and_opening_book(self):
        cmd = [
            str(self.native), "--policy", "grave_ts", "--seed", "378", "--workers", "4",
            "--seconds", "0.08", "--node-cap", "200000", "--memory-mb", "128",
            "--shared-tree", "1", "--opening-book", "1", "--swap", "1",
        ]
        st = BattleReferee(11, "AI", "Opp", swap_rule="swap_pieces")
        with NativeProcess(cmd) as engine:
            m1, elapsed1 = engine.request(st.message(), 10)
            self.assertLess(elapsed1, 0.5)
            st.play(m1)
            engine.process.stdin.write("PONDER" + st.message()[2:] + "\n")
            engine.process.stdin.flush()
            time.sleep(0.15)
            opp_mv = (5, 5) if m1 != (5, 5) else (5, 4)
            st.play(opp_mv)
            m3, _ = engine.request(st.message(), 10)
            self.assertIsNone(st.board.tiles[m3[0]][m3[1]].colour)
            engine.process.stdin.write("STOP_PONDER\n")
            engine.process.stdin.flush()

        mv_tels = [t for t in engine.telemetry if t.get("kind") == "hex_search_move"]
        self.assertEqual(len(mv_tels), 2)
        self.assertEqual(mv_tels[0]["reason"], "pie_rule_opening_book")
        self.assertGreater(mv_tels[1]["reused_visits"], 0)
        ponder_stops = [t for t in engine.telemetry if t.get("kind") == "hex_search_ponder_stopped"]
        self.assertTrue(any(p.get("iterations", 0) > 0 for p in ponder_stops))

    def test_dead_cell_pruning_triggers_and_preserves_legality(self):
        board = "0R000,00000,00000,00000,00000"
        cmd = [
            str(self.native), "--policy", "grave_ts", "--seed", "99", "--workers", "1",
            "--iterations", "200", "--tactics", "0", "--swap", "0", "--prune-dead", "1",
        ]
        with NativeProcess(cmd) as engine:
            move, _ = engine.request(f"V2;B;5;CHANGE;0,1;{board};2", 10)
        self.assertNotEqual(move, (0, 0))
        self.assertGreater(engine.telemetry[0]["dead_cells_pruned"], 0)

    def test_manifest_validation_and_command_generation(self):
        manifest = {
            "schema_version": 1, "suite_id": "v32-test", "split": "final", "board_size": 11,
            "budget": {"mode": "game_time", "game_seconds": 60, "workers": 4, "node_cap": 500000, "memory_mb": 256},
            "participants": {
                "a": {"kind": "native", "policy": "grave_ts", "workers": 4, "solver": True, "two_dist": True, "shared_tree": True},
                "b": {"kind": "native", "policy": "rave_ts", "workers": 4},
            },
            "games": [
                {"game_id": "p0-a", "pair_id": 0, "red": "a", "blue": "b", "seed": 11, "opening_seed": 22},
                {"game_id": "p0-b", "pair_id": 0, "red": "b", "blue": "a", "seed": 11, "opening_seed": 22},
            ],
        }
        validate_manifest(manifest)
        cmd = participant_command(manifest["participants"]["a"], manifest["budget"], manifest["games"][0], "R", self.native)
        self.assertIn("--shared-tree", cmd)
        self.assertIn("--solver", cmd)


class SavedOnlineBattleReplayTests(unittest.TestCase):
    def test_all_saved_online_battle_records_replay_cleanly(self):
        battle_dir = ROOT / "reports" / "online_battles"
        records = sorted(battle_dir.glob("*.json"))
        self.assertGreaterEqual(len(records), 6)
        for path in records:
            data = json.loads(path.read_text(encoding="utf-8"))
            st = BattleReferee(data["board_size"], data["red"], data["blue"], swap_rule="swap_pieces")
            for ev in data["moves"]:
                st.play(tuple(ev["move"]))
            self.assertEqual(st.winner, data["winner"], f"Replay winner mismatch in {path.name}")
            self.assertEqual(st.board_text(), data["final_board"], f"Final board mismatch in {path.name}")
            sgf_path = path.with_suffix(".sgf")
            self.assertTrue(sgf_path.is_file(), f"Missing matching SGF for {path.name}")
            self.assertIn("GM[11]SZ[11]", sgf_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
