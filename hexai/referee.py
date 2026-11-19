"""Self-contained Hex board, connectivity verifier, and pie-rule referee (swap-pieces & swap-sides)."""
from __future__ import annotations

from collections import deque
from enum import Enum


class Colour(Enum):
    """Hex player colours: RED connects Top<->Bottom, BLUE connects Left<->Right."""

    RED = 0
    BLUE = 1

    @staticmethod
    def get_char(colour: Colour | None) -> str:
        if colour == Colour.RED:
            return "R"
        if colour == Colour.BLUE:
            return "B"
        return "0"

    @staticmethod
    def from_char(c: str) -> Colour | None:
        if c == "R":
            return Colour.RED
        if c == "B":
            return Colour.BLUE
        return None

    @staticmethod
    def opposite(colour: Colour | None) -> Colour | None:
        if colour == Colour.RED:
            return Colour.BLUE
        if colour == Colour.BLUE:
            return Colour.RED
        return None


NEIGHBORS = ((-1, 0), (-1, 1), (0, 1), (1, 0), (1, -1), (0, -1))


class Tile:
    __slots__ = ("x", "y", "colour")

    def __init__(self, x: int, y: int, colour: Colour | None = None):
        self.x = x
        self.y = y
        self.colour = colour


class Board:
    """N x N Hex board with exact iterative BFS winning-path verification."""

    def __init__(self, board_size: int = 11):
        self._size = board_size
        self._tiles = [[Tile(i, j) for j in range(board_size)] for i in range(board_size)]
        self._winner: Colour | None = None

    @property
    def size(self) -> int:
        return self._size

    @property
    def tiles(self) -> list[list[Tile]]:
        return self._tiles

    def set_tile_colour(self, x: int, y: int, colour: Colour | None) -> None:
        self._tiles[x][y].colour = colour

    def get_winner(self) -> Colour | None:
        return self._winner

    def has_ended(self, colour: Colour) -> bool:
        if colour not in (Colour.RED, Colour.BLUE):
            raise ValueError("Invalid colour.")
        n = self._size
        visited = [[False] * n for _ in range(n)]
        queue: deque[tuple[int, int]] = deque()
        if colour == Colour.RED:
            for c in range(n):
                if self._tiles[0][c].colour == Colour.RED:
                    visited[0][c] = True
                    queue.append((0, c))
        else:
            for r in range(n):
                if self._tiles[r][0].colour == Colour.BLUE:
                    visited[r][0] = True
                    queue.append((r, 0))
        while queue:
            x, y = queue.popleft()
            if (colour == Colour.RED and x == n - 1) or (colour == Colour.BLUE and y == n - 1):
                self._winner = colour
                return True
            for dx, dy in NEIGHBORS:
                nx, ny = x + dx, y + dy
                if 0 <= nx < n and 0 <= ny < n and not visited[nx][ny] and self._tiles[nx][ny].colour == colour:
                    visited[nx][ny] = True
                    queue.append((nx, ny))
        return False

    def winning_path(self, colour: Colour) -> list[tuple[int, int]]:
        """Return one shortest winning chain of (row, col) coordinates if `colour` has won, else []."""
        n = self._size
        parent: dict[tuple[int, int], tuple[int, int] | None] = {}
        queue: deque[tuple[int, int]] = deque()
        if colour == Colour.RED:
            for c in range(n):
                if self._tiles[0][c].colour == Colour.RED:
                    parent[(0, c)] = None
                    queue.append((0, c))
        else:
            for r in range(n):
                if self._tiles[r][0].colour == Colour.BLUE:
                    parent[(r, 0)] = None
                    queue.append((r, 0))
        while queue:
            x, y = queue.popleft()
            if (colour == Colour.RED and x == n - 1) or (colour == Colour.BLUE and y == n - 1):
                path = []
                cur: tuple[int, int] | None = (x, y)
                while cur is not None:
                    path.append(cur)
                    cur = parent[cur]
                path.reverse()
                return path
            for dx, dy in NEIGHBORS:
                nx, ny = x + dx, y + dy
                if 0 <= nx < n and 0 <= ny < n and (nx, ny) not in parent and self._tiles[nx][ny].colour == colour:
                    parent[(nx, ny)] = (x, y)
                    queue.append((nx, ny))
        return []


class Referee:
    """Independent Hex referee enforcing connectivity and the pie rule."""

    def __init__(self, size: int, red: str, blue: str):
        self.board = Board(size)
        self.players = {Colour.RED: red, Colour.BLUE: blue}
        self.colour = Colour.RED
        self.turn = 1
        self.previous_move: tuple[int, int] | None = None
        self.winner: str | None = None

    @property
    def actor(self) -> str:
        return self.players[self.colour]

    def board_text(self) -> str:
        return ",".join("".join(Colour.get_char(tile.colour) for tile in row) for row in self.board.tiles)

    def message(self) -> str:
        if self.previous_move is None:
            command, move = "START", ""
        elif self.previous_move == (-1, -1):
            command, move = "SWAP", ""
        else:
            command, move = "CHANGE", f"{self.previous_move[0]},{self.previous_move[1]}"
        return f"V2;{Colour.get_char(self.colour)};{self.board.size};{command};{move};{self.board_text()};{self.turn}"

    def play(self, move: tuple[int, int]) -> None:
        if self.winner is not None:
            raise ValueError("Cannot play after a connecting path has won.")
        x, y = move
        if (x, y) == (-1, -1):
            if self.turn != 2:
                raise ValueError("Swap is legal only at turn two.")
            self.players[Colour.RED], self.players[Colour.BLUE] = self.players[Colour.BLUE], self.players[Colour.RED]
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
        raise ValueError("Board must contain 3-19 equally sized comma-separated rows of R, B and 0.")
    board = Board(size)
    for x, row in enumerate(rows):
        for y, value in enumerate(row):
            board.set_tile_colour(x, y, Colour.from_char(value))
    return board
