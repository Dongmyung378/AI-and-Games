import random
from agents.Group26.mcts_core import MCTSBase

class Agent_RAVE_TS(MCTSBase):
    def select_child(self, node):
        def rave_ts_score(child):
            mc_wins = child.wins
            mc_losses = child.visits - child.wins
            rave_wins = child.rave_wins
            rave_losses = child.rave_visits - child.rave_wins
            w = 0.5
            alpha = mc_wins + (rave_wins * w) + 1
            beta_val = mc_losses + (rave_losses * w) + 1
            return random.betavariate(alpha, beta_val)
        return max(node.children, key=rave_ts_score)


