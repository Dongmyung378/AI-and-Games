"""Python referee adapter for the fixed-size Linux C++ agent."""

from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired

from src.AgentBase import AgentBase
from src.Board import Board
from src.Colour import Colour
from src.Move import Move


class RAVE_TS(AgentBase):
    """Keep the native process's role synchronized with the referee's pie rule."""

    fixed_board_size = 11

    def __deepcopy__(self, memo):
        return self

    def __init__(self, colour: Colour):
        super().__init__(colour)
        executable = Path(__file__).with_name("RAVE_TS")
        self.agent_process = Popen(
            [str(executable), colour.get_char(), str(self.fixed_board_size)],
            stdout=PIPE,
            stdin=PIPE,
            text=True,
        )

    def make_move(self, turn: int, board: Board, opp_move: Move | None) -> Move:
        if board.size != self.fixed_board_size:
            raise ValueError("The native RAVE-TS agent supports only 11x11 boards.")
        rows = ",".join(
            "".join("0" if tile.colour is None else tile.colour.get_char() for tile in row)
            for row in board.tiles
        )
        if opp_move is None:
            command, opponent = "START", ""
        elif opp_move.x == -1 and opp_move.y == -1:
            command, opponent = "SWAP", ""
        else:
            command, opponent = "CHANGE", f"{opp_move.x},{opp_move.y}"

        # Both participants change colour after a swap. The initiator next receives
        # CHANGE, not SWAP, so every request must carry the current referee colour.
        message = f"V2;{self.colour.get_char()};{board.size};{command};{opponent};{rows};{turn}\n"
        try:
            self.agent_process.stdin.write(message)
            self.agent_process.stdin.flush()
            response = self.agent_process.stdout.readline().strip()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError("The native Hex process stopped; rebuild it for protocol V2.") from exc
        try:
            x, y = map(int, response.split(","))
        except ValueError as exc:
            raise RuntimeError("The native Hex process returned no valid move; check its error output.") from exc
        if (x, y) != (-1, -1) and not (0 <= x < board.size and 0 <= y < board.size):
            raise RuntimeError(f"The native Hex process returned an out-of-board move: {x},{y}.")
        return Move(x, y)

    def close(self):
        if self.agent_process.stdin and not self.agent_process.stdin.closed:
            try:
                self.agent_process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        try:
            self.agent_process.wait(timeout=1)
        except TimeoutExpired:
            self.agent_process.kill()
            self.agent_process.wait(timeout=1)
        finally:
            if self.agent_process.stdout:
                self.agent_process.stdout.close()
