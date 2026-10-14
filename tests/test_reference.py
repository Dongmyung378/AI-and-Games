"""Correctness checks for the maintained reference and preserved defect probe."""

import copy
import random
import unittest

from hexai.reference import (
    ActionStats, Board, Colour, Node, POLICIES, SearchConfig,
    backpropagate, board_from_rows, search, select_child, tactical_action, winner,
)


def snapshot(node):
    return (
        node.move, node.to_play, node.visits, node.wins,
        tuple((action, stats.visits, stats.wins) for action, stats in sorted(node.amaf.items())),
        tuple((action, snapshot(child)) for action, child in sorted(node.children.items())),
    )


class ReferenceSearchTests(unittest.TestCase):
    def test_reference_rng_does_not_change_global_random_state(self):
        before = random.getstate()
        search(Board(board_size=3), Colour.RED, SearchConfig(policy="rave_ts", iterations=30))
        self.assertEqual(random.getstate(), before)

    def test_all_policies_are_seeded_legal_and_do_not_mutate_the_board(self):
        board = board_from_rows(["R..", ".B.", "..."])
        before = copy.deepcopy(board)
        for policy in POLICIES:
            for colour in (Colour.RED, Colour.BLUE):
                with self.subTest(policy=policy, colour=colour):
                    config = SearchConfig(policy=policy, iterations=120, seed=378)
                    first = search(board, colour, config)
                    second = search(board, colour, config)
                    self.assertIsNone(board.tiles[first.move[0]][first.move[1]].colour)
                    self.assertEqual(first.iterations, 120)
                    self.assertEqual(first.root.visits, 120)
                    self.assertEqual(sum(child.visits for child in first.root.children.values()), 120)
                    self.assertGreater(first.amaf_updates, 0)
                    self.assertEqual(snapshot(first.root), snapshot(second.root))
                    self.assertEqual(first.move, second.move)
                    self.assertEqual(first.amaf_updates, second.amaf_updates)
                    self.assertEqual(board, before)
                    self.assertIsNone(board.get_winner())

    def test_opponent_nodes_choose_their_own_winning_action(self):
        # At a Blue node, child values belong to Red and must be inverted.
        node = Node(Colour.BLUE, visits=200)
        bad_for_blue = Node(Colour.RED, move=(0, 0), visits=100, wins=95)
        good_for_blue = Node(Colour.RED, move=(0, 1), visits=100, wins=5)
        node.children = {(0, 0): bad_for_blue, (0, 1): good_for_blue}
        node.amaf = {(0, 0): ActionStats(100, 5), (0, 1): ActionStats(100, 95)}
        for policy in POLICIES:
            with self.subTest(policy=policy):
                config = SearchConfig(policy=policy, exploration=0)
                picks = [select_child(node, random.Random(seed), config) for seed in range(100)]
                self.assertEqual(sum(child is good_for_blue for child in picks), 100)

    def test_amaf_uses_same_colour_and_only_future_legal_actions(self):
        root = Node(Colour.RED, legal_actions=frozenset({(0, 0), (0, 1), (1, 0)}))
        child = Node(Colour.BLUE, move=(0, 0), legal_actions=frozenset({(0, 1), (1, 0)}))
        history = [((0, 0), Colour.RED), ((0, 1), Colour.BLUE), ((1, 0), Colour.RED)]
        count = backpropagate([(root, 0), (child, 1)], Colour.RED, history)
        self.assertEqual(count, 3)
        self.assertEqual((root.visits, root.wins), (1, 1))
        self.assertEqual((child.visits, child.wins), (1, 0))
        self.assertEqual(set(root.amaf), {(0, 0), (1, 0)})
        self.assertEqual(set(child.amaf), {(0, 1)})
        self.assertEqual(child.amaf[(0, 1)].wins, 0)

    def test_amaf_deduplicates_an_action_in_one_continuation(self):
        node = Node(Colour.RED, legal_actions=frozenset({(0, 0)}))
        count = backpropagate([(node, 0)], Colour.RED, [((0, 0), Colour.RED)] * 2)
        self.assertEqual(count, 1)
        self.assertEqual(node.amaf[(0, 0)].visits, 1)

    def test_amaf_values_can_change_rave_selection(self):
        node = Node(Colour.RED, visits=20)
        first = Node(Colour.BLUE, move=(0, 0), visits=10, wins=5)
        second = Node(Colour.BLUE, move=(0, 1), visits=10, wins=5)
        node.children = {(0, 0): first, (0, 1): second}
        node.amaf = {(0, 0): ActionStats(100, 0), (0, 1): ActionStats(100, 100)}
        self.assertIs(select_child(node, random.Random(0), SearchConfig(policy="ucb", exploration=0)), first)
        self.assertIs(select_child(node, random.Random(0), SearchConfig(policy="rave_ucb", exploration=0)), second)
        picks = [select_child(node, random.Random(seed), SearchConfig(policy="rave_ts")) for seed in range(100)]
        self.assertEqual(sum(child is second for child in picks), 100)

    def test_rave_zero_equivalence_matches_plain_policy(self):
        board = board_from_rows(["R..", ".B.", "..."])
        for plain, rave in (("ucb", "rave_ucb"), ("ts", "rave_ts")):
            first = search(board, Colour.RED, SearchConfig(policy=plain, iterations=120))
            second = search(board, Colour.RED, SearchConfig(policy=rave, iterations=120, rave_equivalence=0))
            self.assertEqual(snapshot(first.root), snapshot(second.root))

    def test_terminal_red_and_blue_positions_return_no_move(self):
        for rows, colour in ((["R..", "R..", "R.."], Colour.RED), (["BBB", "...", "..."], Colour.BLUE)):
            board = board_from_rows(rows)
            for player in (Colour.RED, Colour.BLUE):
                result = search(board, player)
                self.assertIsNone(result.move)
                self.assertEqual(result.iterations, 0)
                self.assertEqual(result.reason, "already_terminal")
                self.assertEqual(result.root.terminal, colour)
            self.assertEqual(tactical_action(board, Colour.RED), (None, None))
            self.assertIsNone(board.get_winner())

    def test_one_cell_board_stops_after_the_winning_move(self):
        for colour in (Colour.RED, Colour.BLUE):
            result = search(Board(board_size=1), colour, SearchConfig(iterations=20))
            child = result.root.children[(0, 0)]
            self.assertEqual(result.move, (0, 0))
            self.assertEqual(child.terminal, colour)
            self.assertEqual(child.children, {})
            self.assertEqual((result.root.visits, result.root.wins), (20, 20))
            self.assertEqual((child.visits, child.wins), (20, 0))
            self.assertEqual(result.root.amaf[(0, 0)].visits, 20)

    def test_tactical_win_and_single_threat_block_for_both_colours(self):
        cases = [
            (["RBB", "RBB", ".BB"], Colour.RED, (2, 0), "tactical_win"),
            (["BR.", "BBR", "RRB"], Colour.BLUE, (0, 2), "tactical_win"),
            (["BB.", "...", ".R."], Colour.RED, (0, 2), "tactical_block"),
            (["R..", "R.B", "..."], Colour.BLUE, (2, 0), "tactical_block"),
        ]
        for rows, colour, action, reason in cases:
            with self.subTest(rows=rows, colour=colour):
                board = board_from_rows(rows)
                self.assertEqual(tactical_action(board, colour), (action, reason))
                result = search(board, colour, SearchConfig(tactical=True))
                self.assertEqual((result.move, result.reason, result.iterations), (action, reason, 0))

    def test_validation_rejects_invalid_configuration(self):
        for config in (
            SearchConfig(policy="unknown"), SearchConfig(iterations=0),
            SearchConfig(iterations=1.5), SearchConfig(seed=None),
            SearchConfig(exploration=-1), SearchConfig(exploration=float("nan")),
            SearchConfig(rave_equivalence=-1),
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                search(Board(board_size=3), Colour.RED, config)
        with self.assertRaises(ValueError):
            search(Board(board_size=3), None)
        for rows in ([], ["..", "."], ["XX", ".."]):
            with self.assertRaises(ValueError):
                board_from_rows(rows)

    def test_original_reference_has_zero_rave_updates_after_1000_iterations(self):
        # A regression probe, not a modification of the archived implementation.
        from agents.Group26.Agent_RAVE_UCB import Agent_RAVE_UCB
        from agents.Group26.mcts_core import MCTSNode

        state = random.getstate()
        try:
            random.seed(378)
            board = Board(board_size=3)
            old = Agent_RAVE_UCB(Colour.RED)
            old.root = MCTSNode(state=board)
            for _ in range(1000):
                old.run_iteration(board)
            stack = [old.root]
            old_rave_updates = 0
            while stack:
                node = stack.pop()
                old_rave_updates += node.rave_visits
                stack.extend(node.children)
            self.assertEqual(old.root.visits, 1000)
            self.assertEqual(old_rave_updates, 0)
        finally:
            random.setstate(state)
        new = search(board, Colour.RED, SearchConfig(policy="rave_ucb", iterations=1000, seed=378))
        self.assertGreater(new.amaf_updates, 0)
        self.assertGreater(sum(stats.visits for stats in new.root.amaf.values()), 0)

    def test_original_referee_matches_independent_connectivity_check(self):
        # An independent graph check detects orientation or neighbour mistakes.
        offsets = ((-1, 0), (-1, 1), (0, 1), (1, 0), (1, -1), (0, -1))

        def connected(board, colour):
            size = board.size
            stack = [(0, i) if colour == Colour.RED else (i, 0) for i in range(size)]
            seen = set()
            while stack:
                x, y = stack.pop()
                if (x, y) in seen or board.tiles[x][y].colour != colour:
                    continue
                seen.add((x, y))
                if (x if colour == Colour.RED else y) == size - 1:
                    return True
                stack.extend((x + dx, y + dy) for dx, dy in offsets if 0 <= x + dx < size and 0 <= y + dy < size)
            return False

        rng = random.Random(378)
        for size in (3, 4, 5, 7):
            for _ in range(80):
                board = Board(board_size=size)
                for x in range(size):
                    for y in range(size):
                        board.set_tile_colour(x, y, rng.choice((None, Colour.RED, Colour.BLUE)))
                red = connected(board, Colour.RED)
                blue = connected(board, Colour.BLUE)
                self.assertFalse(red and blue)
                expected = Colour.RED if red else Colour.BLUE if blue else None
                self.assertEqual(winner(board), expected)


if __name__ == "__main__":
    unittest.main()
