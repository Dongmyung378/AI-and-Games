import math
from agents.Group26.mcts_core import MCTSBase

class Agent_UCB(MCTSBase):
    def select_child(self, node):
        C = 1.41
        def ucb_score(child):
            if child.visits == 0:
                return float('inf')
            exploitation = child.wins / child.visits
            exploration = C * math.sqrt(math.log(node.visits) / child.visits)
            return exploitation + exploration
        return max(node.children, key=ucb_score)


