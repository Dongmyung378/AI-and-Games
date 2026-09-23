import time
import random
import copy
from src.AgentBase import AgentBase
from src.Move import Move
from src.Colour import Colour
from src.Board import Board

class MCTSNode:
    def __init__(self, move=None, parent=None, state=None):
        self.move = move
        self.parent = parent
        self.children = []
        
        self.visits = 0
        self.wins = 0
        
        self.rave_visits = 0
        self.rave_wins = 0
        
        self.untried_moves = self.get_legal_moves(state) if state else []

    def get_legal_moves(self, board: Board):
        moves = []
        for i in range(board.size):
            for j in range(board.size):
                if board.tiles[i][j].colour is None:
                    moves.append(Move(i, j))
        return moves

    def add_child(self, move, state):
        child = MCTSNode(move=move, parent=self, state=state)
        self.children.append(child)
        return child

class MCTSBase(AgentBase):
    def __init__(self, colour: Colour):
        super().__init__(colour)
        self.root = None
        self.remaining_time = 300.0

    def make_move(self, turn: int, board: Board, opp_move: Move | None) -> Move:
        self.root = MCTSNode(state=board)
        start_time = time.time()
        
        time_budget = self.remaining_time * 0.035
        
        while time.time() - start_time < time_budget - 0.05:
            self.run_iteration(board)
        
        elapsed = time.time() - start_time
        self.remaining_time -= elapsed
        
        if turn == 2 and self.colour == Colour.BLUE:
            best_child = max(self.root.children, key=lambda c: c.visits)
            win_rate = best_child.wins / best_child.visits
            
            if win_rate < 0.45: 
                return Move(-1, -1)
        
        if not self.root.children:
            return self.get_random_move(board)
        best_child = max(self.root.children, key=lambda c: c.visits)
        return best_child.move

    def run_iteration(self, board: Board):
        node = self.root
        sim_board = copy.deepcopy(board)

        current_colour = self.colour 

        while not node.untried_moves and node.children:
            node = self.select_child(node)
            sim_board.set_tile_colour(node.move.x, node.move.y, current_colour)
            current_colour = Colour.opposite(current_colour)

        if node.untried_moves:
            move = node.untried_moves.pop()
            sim_board.set_tile_colour(move.x, move.y, current_colour)
            current_colour = Colour.opposite(current_colour)
            node = node.add_child(move, sim_board)

        winner, red_moves, blue_moves = self.simulate(sim_board, current_colour)

        self.backpropagate(node, winner, red_moves, blue_moves)

    def simulate(self, board: Board, current_colour: Colour):
        legal_moves = [
            Move(i, j) 
            for i in range(board.size) 
            for j in range(board.size) 
            if board.tiles[i][j].colour is None
        ]
        random.shuffle(legal_moves)
        
        red_moves = set()
        blue_moves = set()
        
        player = current_colour
        while legal_moves:
            if board.has_ended(Colour.RED):
                return Colour.RED, red_moves, blue_moves
            if board.has_ended(Colour.BLUE):
                return Colour.BLUE, red_moves, blue_moves

            move = legal_moves.pop() 
            board.set_tile_colour(move.x, move.y, player)
            
            if player == Colour.RED:
                red_moves.add((move.x, move.y))
            else:
                blue_moves.add((move.x, move.y))

            player = Colour.opposite(player)
            
        if board.has_ended(Colour.RED): return Colour.RED, red_moves, blue_moves
        return Colour.BLUE, red_moves, blue_moves

    def backpropagate(self, node: MCTSNode, winner: Colour, red_moves: set, blue_moves: set):
        while node is not None:
            node.visits += 1
            if winner == self.colour:
                node.wins += 1
            if node.move:
                move_tuple = (node.move.x, node.move.y)
                
                if winner == Colour.RED:
                    if move_tuple in red_moves:
                        node.rave_visits += 1
                        node.rave_wins += 1
                    elif move_tuple in blue_moves:
                        node.rave_visits += 1
                        
                else:
                    if move_tuple in blue_moves:
                        node.rave_visits += 1
                        node.rave_wins += 1
                    elif move_tuple in red_moves:
                        node.rave_visits += 1
            node = node.parent

    def select_child(self, node):
        raise NotImplementedError("select_child must be implemented by subclass")

    def get_random_move(self, board):
        for i in range(board.size):
            for j in range(board.size):
                if board.tiles[i][j].colour is None:
                    return Move(i, j)
        return Move(-1, -1)


