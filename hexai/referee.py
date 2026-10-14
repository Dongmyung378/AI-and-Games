"""Use the preserved coursework Board for connectivity and the same pie rule."""
from pathlib import Path
import sys

_engine = str(Path(__file__).resolve().parents[1] / "engine")
if _engine not in sys.path:
    sys.path.insert(0, _engine)
from src.Board import Board
from src.Colour import Colour


class Referee:
    def __init__(self, size: int, red: str, blue: str):
        self.board = Board(size)
        self.players = {Colour.RED: red, Colour.BLUE: blue}
        self.colour = Colour.RED
        self.turn = 1
        self.previous_move = None
        self.winner = None

    @property
    def actor(self):
        return self.players[self.colour]

    def board_text(self):
        return ",".join("".join(Colour.get_char(tile.colour) for tile in row) for row in self.board.tiles)

    def message(self):
        if self.previous_move is None:
            command, move = "START", ""
        elif self.previous_move == (-1, -1):
            command, move = "SWAP", ""
        else:
            command, move = "CHANGE", f"{self.previous_move[0]},{self.previous_move[1]}"
        return f"V2;{Colour.get_char(self.colour)};{self.board.size};{command};{move};{self.board_text()};{self.turn}"

    def play(self, move):
        if self.winner is not None:
            raise ValueError("Cannot play after a connecting path has won.")
        x, y = move
        if (x, y) == (-1, -1):
            if self.turn != 2:
                raise ValueError("Swap is legal only at turn two.")
            self.players[Colour.RED], self.players[Colour.BLUE] = self.players[Colour.BLUE], self.players[Colour.RED]
            # The original Game flips current_player inside _make_move and again
            # in its outer loop. The next colour is BLUE and the first mover acts.
        else:
            if not (0 <= x < self.board.size and 0 <= y < self.board.size):
                raise ValueError("Move is outside the board.")
            if self.board.tiles[x][y].colour is not None:
                raise ValueError("Move addresses an occupied tile.")
            self.board.set_tile_colour(x, y, self.colour)
            if self.board.has_ended(self.colour):
                self.winner = self.actor
            self.colour = Colour.opposite(self.colour)
        self.previous_move = (x, y)
        self.turn += 1


def parse_board(text: str) -> Board:
    rows = text.split(",")
    size = len(rows)
    if not (3 <= size <= 19) or any(len(row) != size or set(row) - set("RB0") for row in rows):
        raise ValueError("Board must contain 3–19 equally sized comma-separated rows of R, B and 0.")
    board = Board(size)
    for x, row in enumerate(rows):
        for y, value in enumerate(row):
            board.set_tile_colour(x, y, Colour.from_char(value))
    return board
