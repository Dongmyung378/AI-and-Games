import random
from agents.Group26.mcts_core import MCTSBase

class Agent_TS(MCTSBase):
    def select_child(self, node):
        def ts_score(child):
            wins = child.wins
            losses = child.visits - child.wins
            return random.betavariate(wins + 1, losses + 1)
        return max(node.children, key=ts_score)


