"""Small, auditable MCTS reference using the preserved referee's Hex rules.

Node values and AMAF values belong to the player who is about to move at that
node. A parent therefore inverts a child's Monte Carlo value. AMAF records only
actions played by that node's player later in the same simulation, including
the tree path. This implementation prioritises clarity over tournament speed.
The native engine is the appropriate implementation for large experiments.
"""

from __future__ import annotations

import copy
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# The archived referee uses absolute imports from "src". Resolve that package
# from this repository rather than copying its rules into another implementation.
_ENGINE = Path(__file__).resolve().parents[1] / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))
from src.Board import Board  # noqa: E402
from src.Colour import Colour  # noqa: E402

Action = tuple[int, int]
POLICIES = ("ucb", "ts", "rave_ucb", "rave_ts")


@dataclass(frozen=True)
class SearchConfig:
    policy: str = "rave_ts"
    iterations: int = 200
    seed: int = 378
    exploration: float = 1.41
    rave_equivalence: float = 300.0
    tactical: bool = False

    def validate(self) -> None:
        if self.policy not in POLICIES:
            raise ValueError(f"policy must be one of {POLICIES}")
        if not isinstance(self.iterations, int) or self.iterations < 1:
            raise ValueError("iterations must be a positive integer")
        if not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if not math.isfinite(self.exploration) or self.exploration < 0:
            raise ValueError("exploration must be finite and non-negative")
        if not math.isfinite(self.rave_equivalence) or self.rave_equivalence < 0:
            raise ValueError("rave_equivalence must be finite and non-negative")


@dataclass
class ActionStats:
    visits: int = 0
    wins: int = 0


@dataclass
class Node:
    to_play: Colour
    move: Action | None = None
    visits: int = 0
    wins: int = 0
    children: dict[Action, Node] = field(default_factory=dict)
    untried_moves: list[Action] = field(default_factory=list)
    legal_actions: frozenset[Action] = field(default_factory=frozenset)
    amaf: dict[Action, ActionStats] = field(default_factory=dict)
    terminal: Colour | None = None

    @classmethod
    def from_board(cls, board: Board, to_play: Colour, move: Action | None = None) -> Node:
        terminal = winner(board)
        legal = legal_moves(board) if terminal is None else []
        return cls(
            to_play=to_play,
            move=move,
            untried_moves=legal,
            legal_actions=frozenset(legal),
            terminal=terminal,
        )


@dataclass
class SearchResult:
    move: Action | None
    iterations: int
    root: Node
    amaf_updates: int
    reason: str = "search"


def board_from_rows(rows: Sequence[str]) -> Board:
    """Construct a referee board from square rows of R, B and . or 0."""
    if not rows or any(len(row) != len(rows) for row in rows):
        raise ValueError("rows must describe a non-empty square board")
    board = Board(board_size=len(rows))
    mapping = {"R": Colour.RED, "B": Colour.BLUE, ".": None, "0": None}
    for x, row in enumerate(rows):
        for y, char in enumerate(row):
            if char not in mapping:
                raise ValueError("board characters must be R, B, . or 0")
            board.set_tile_colour(x, y, mapping[char])
    return board


def legal_moves(board: Board) -> list[Action]:
    return [
        (x, y)
        for x in range(board.size)
        for y in range(board.size)
        if board.tiles[x][y].colour is None
    ]


def winner(board: Board) -> Colour | None:
    """Ask the preserved referee for the winner, checking both orientations."""
    if board.get_winner() is not None:
        return board.get_winner()
    board.has_ended(Colour.RED)
    if board.get_winner() is None:
        board.has_ended(Colour.BLUE)
    return board.get_winner()


def winning_moves(board: Board, colour: Colour) -> list[Action]:
    result = []
    for action in legal_moves(board):
        candidate = copy.deepcopy(board)
        candidate.set_tile_colour(*action, colour)
        if winner(candidate) == colour:
            result.append(action)
    return result


def tactical_action(board: Board, colour: Colour) -> tuple[Action | None, str | None]:
    """Take an immediate win or cover the opponent's single winning cell.

    Two distinct immediate opponent wins cannot both be covered by one move.
    In that case this helper defers to search instead of labelling a move as a
    forced defence. This optional helper is not a complete Hex solver.
    """
    if winner(copy.deepcopy(board)) is not None:
        return None, None
    wins = winning_moves(board, colour)
    if wins:
        return wins[0], "tactical_win"
    threats = winning_moves(board, Colour.opposite(colour))
    if len(threats) == 1:
        return threats[0], "tactical_block"
    return None, None


def _rave_beta(node: Node, stats: ActionStats | None, config: SearchConfig) -> float:
    if stats is None or stats.visits == 0 or config.rave_equivalence == 0:
        return 0.0
    k = config.rave_equivalence
    return math.sqrt(k / (3 * node.visits + k))


def select_child(node: Node, rng: random.Random, config: SearchConfig) -> Node:
    """Select an action from the current player's perspective at every depth."""
    if not node.children:
        raise ValueError("cannot select from a node without children")

    def score(item: tuple[Action, Node]) -> float:
        action, child = item
        if child.visits == 0:
            return math.inf
        mc_wins = child.visits - child.wins
        mc_losses = child.wins
        stats = node.amaf.get(action)
        beta = _rave_beta(node, stats, config) if config.policy.startswith("rave_") else 0.0
        if config.policy.endswith("ts"):
            amaf_wins = stats.wins if stats else 0
            amaf_losses = stats.visits - stats.wins if stats else 0
            effective_wins = (1 - beta) * mc_wins + beta * amaf_wins
            effective_losses = (1 - beta) * mc_losses + beta * amaf_losses
            return rng.betavariate(effective_wins + 1, effective_losses + 1)
        mc_value = mc_wins / child.visits
        amaf_value = stats.wins / stats.visits if stats and stats.visits else mc_value
        value = (1 - beta) * mc_value + beta * amaf_value
        exploration = config.exploration * math.sqrt(math.log(node.visits + 1) / child.visits)
        return value + exploration

    return max(sorted(node.children.items()), key=score)[1]


def backpropagate(
    path: Sequence[tuple[Node, int]],
    winning_colour: Colour,
    history: Sequence[tuple[Action, Colour]],
) -> int:
    """Update values and each ancestor's legal same-player continuation actions.

    Each path entry records the simulation-history length at that node's state.
    Earlier actions are excluded, so an ancestor's move cannot contaminate a
    descendant's AMAF statistics. An action gets at most one update per node.
    """
    updates = 0
    for node, start in path:
        node.visits += 1
        node.wins += int(winning_colour == node.to_play)
        actions = {
            action for action, colour in history[start:]
            if colour == node.to_play and action in node.legal_actions
        }
        for action in sorted(actions):
            stats = node.amaf.setdefault(action, ActionStats())
            stats.visits += 1
            stats.wins += int(winning_colour == node.to_play)
            updates += 1
    return updates


def _rollout(
    board: Board, to_play: Colour, rng: random.Random, history: list[tuple[Action, Colour]]
) -> Colour:
    actions = legal_moves(board)
    rng.shuffle(actions)
    winning_colour = winner(board)
    while winning_colour is None and actions:
        action = actions.pop()
        board.set_tile_colour(*action, to_play)
        history.append((action, to_play))
        winning_colour = winner(board)
        to_play = Colour.opposite(to_play)
    if winning_colour is None:
        raise RuntimeError("a full Hex board must have a winner")
    return winning_colour


def search(board: Board, colour: Colour, config: SearchConfig | None = None) -> SearchResult:
    """Run seeded, fixed-iteration search without modifying the supplied board.

    Swap decisions belong to the game harness and are deliberately not included
    in this coordinate-only reference. Legal post-swap positions can be searched.
    Identical input and configuration reproduce the complete statistics within
    the same Python runtime; cross-language RNG equality is not promised.
    """
    config = config or SearchConfig()
    config.validate()
    if colour not in (Colour.RED, Colour.BLUE):
        raise ValueError("colour must be RED or BLUE")
    if board.size < 1:
        raise ValueError("board size must be positive")
    root_board = copy.deepcopy(board)
    root = Node.from_board(root_board, colour)
    if root.terminal is not None:
        return SearchResult(None, 0, root, 0, "already_terminal")
    if config.tactical:
        action, reason = tactical_action(root_board, colour)
        if action is not None:
            return SearchResult(action, 0, root, 0, reason or "tactical")

    rng = random.Random(config.seed)
    amaf_updates = 0
    for _ in range(config.iterations):
        sim_board = copy.deepcopy(root_board)
        node = root
        history: list[tuple[Action, Colour]] = []
        path = [(root, 0)]
        while node.terminal is None and not node.untried_moves and node.children:
            child = select_child(node, rng, config)
            sim_board.set_tile_colour(*child.move, node.to_play)
            history.append((child.move, node.to_play))
            node = child
            path.append((node, len(history)))
        if node.terminal is None and node.untried_moves:
            action = node.untried_moves.pop(rng.randrange(len(node.untried_moves)))
            sim_board.set_tile_colour(*action, node.to_play)
            history.append((action, node.to_play))
            child = Node.from_board(sim_board, Colour.opposite(node.to_play), action)
            node.children[action] = child
            node = child
            path.append((node, len(history)))
        winning_colour = node.terminal or _rollout(sim_board, node.to_play, rng, history)
        amaf_updates += backpropagate(path, winning_colour, history)

    action, _ = max(
        sorted(root.children.items()),
        key=lambda item: (
            item[1].visits,
            1 - item[1].wins / item[1].visits,
        ),
    )
    return SearchResult(action, config.iterations, root, amaf_updates)
