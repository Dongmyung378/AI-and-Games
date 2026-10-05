import contextlib
import io
import os
from pathlib import Path
import platform
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import Hex
from agents.Group026.RAVE_TS import RAVE_TS
from src.Board import Board
from src.Colour import Colour
from src.Game import Game
from src.Move import Move
from src.Player import Player


def process_fixture(initial):
    return SimpleNamespace(
        stdin=io.StringIO(),
        stdout=io.StringIO("5,5\n0,0\n0,2\n" if initial == "R" else "-1,-1\n0,1\n"),
        wait=lambda timeout=None: 0,
    )


class AdapterTests(unittest.TestCase):
    def test_both_pie_swap_roles_follow_the_actual_referee(self):
        processes = {}
        expected = {"R": [], "B": []}

        def start(arguments, **kwargs):
            processes[arguments[1]] = process_fixture(arguments[1])
            return processes[arguments[1]]

        def move(agent, initial, turn, board, previous):
            expected[initial].append(agent.colour.get_char())
            return agent.make_move(turn, board, previous)

        with patch("agents.Group026.RAVE_TS.Popen", side_effect=start):
            first, second = RAVE_TS(Colour.RED), RAVE_TS(Colour.BLUE)
            game = Game(Player("first", first), Player("second", second), logDest=os.devnull)
            self.addCleanup(game.logDest.close)
            opening = move(first, "R", 1, game.board, None)
            game._make_move(opening)
            game.current_player = Colour.BLUE
            swap = move(second, "B", 2, game.board, opening)
            game._make_move(swap)
            reply = move(first, "R", 3, game.board, swap)
            game.board.set_tile_colour(reply.x, reply.y, Colour.BLUE)
            answer = move(second, "B", 4, game.board, reply)
            game.board.set_tile_colour(answer.x, answer.y, Colour.RED)
            move(first, "R", 5, game.board, answer)

        self.assertEqual(expected, {"R": ["R", "B", "B"], "B": ["B", "R"]})
        for initial, process in processes.items():
            messages = process.stdin.getvalue().splitlines()
            self.assertEqual([line.split(";")[1] for line in messages], expected[initial])
            self.assertTrue(all(line.startswith("V2;") for line in messages))
            protocol_test = os.environ.get("HEX_PROTOCOL_TEST_BINARY")
            if protocol_test:
                result = subprocess.run(
                    [protocol_test, "--trace", initial],
                    input="\n".join(messages) + "\n", text=True, capture_output=True,
                    check=True, timeout=5,
                )
                self.assertEqual(result.stdout.splitlines(), expected[initial])

    def test_direct_non11_board_is_rejected_before_protocol_write(self):
        process = process_fixture("R")
        with patch("agents.Group026.RAVE_TS.Popen", return_value=process):
            agent = RAVE_TS(Colour.RED)
            with self.assertRaisesRegex(ValueError, "11x11"):
                agent.make_move(1, Board(3), None)
        self.assertEqual(process.stdin.getvalue(), "")

    def test_cli_rejects_non11_before_creating_either_process(self):
        with patch("agents.Group026.RAVE_TS.Popen") as start, contextlib.redirect_stderr(io.StringIO()) as error:
            with self.assertRaises(SystemExit) as caught:
                Hex.main(["-b", "7"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("11x11", error.getvalue())
        start.assert_not_called()

    def test_native_binary_location_does_not_depend_on_working_directory(self):
        with patch("agents.Group026.RAVE_TS.Popen", return_value=process_fixture("R")) as start:
            RAVE_TS(Colour.RED)
        self.assertEqual(Path(start.call_args.args[0][0]).resolve(),
                         Path(__file__).resolve().parents[1] / "agents/Group026/RAVE_TS")

    def test_out_of_board_response_is_an_execution_error(self):
        process = process_fixture("R")
        process.stdout = io.StringIO("12,0\n")
        with patch("agents.Group026.RAVE_TS.Popen", return_value=process):
            agent = RAVE_TS(Colour.RED)
            with self.assertRaisesRegex(RuntimeError, "out-of-board"):
                agent.make_move(1, Board(11), None)


@unittest.skipUnless(
    sys.platform.startswith("linux") and platform.machine().lower() in ("x86_64", "amd64"),
    "The shipped binary targets Linux x86_64.",
)
class NativeSmokeTests(unittest.TestCase):
    def test_actual_native_opening_swap_and_next_role_request(self):
        board = Board(11)
        board.set_tile_colour(5, 5, Colour.RED)
        agent = RAVE_TS(Colour.BLUE)
        try:
            swap = agent.make_move(2, board, Move(5, 5))
            self.assertEqual((swap.x, swap.y), (-1, -1))
            agent.colour = Colour.RED
            tactical = Board(11)
            for row in range(10):
                tactical.set_tile_colour(row, 0, Colour.RED)
            answer = agent.make_move(4, tactical, Move(5, 5))
            self.assertEqual((answer.x, answer.y), (10, 0))
            self.assertIsNone(tactical.tiles[answer.x][answer.y].colour)
        finally:
            agent.close()

    def test_native_rejects_old_protocol_without_computing_a_move(self):
        binary = Path(__file__).resolve().parents[1] / "agents/Group026/RAVE_TS"
        result = subprocess.run([str(binary), "R", "11"], input="START;;000;1;\n",
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("protocol V2", result.stderr)


if __name__ == "__main__":
    unittest.main()
