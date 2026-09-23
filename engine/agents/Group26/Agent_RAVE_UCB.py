import math
from agents.Group26.mcts_core import MCTSBase

class Agent_RAVE_UCB(MCTSBase):
    def select_child(self, node):
        b = 300
        
        def rave_ucb_score(child):
            if child.visits == 0:
                return float('inf')
            ucb_bias = 1.41 * math.sqrt(math.log(node.visits) / child.visits)
            q_mc = child.wins / child.visits
            if child.rave_visits == 0:
                q_rave = 0.5
            else:
                q_rave = child.rave_wins / child.rave_visits
            beta = math.sqrt(b / (3 * node.visits + b))
            combined_value = (1 - beta) * q_mc + beta * q_rave
            return combined_value + ucb_bias
        return max(node.children, key=rave_ucb_score)


