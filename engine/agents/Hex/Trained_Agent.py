import time
import math
import copy
import numpy as np
import torch
import torch.nn.functional as F
import os
import random

from src.AgentBase import AgentBase
from src.Board import Board
from src.Colour import Colour
from src.Move import Move

# ★ 모델 파일명
MODEL_FILE_NAME = "hex_best_python.pt"

# =============================================================================
# 0. Deep Learning Model (HexAlphaZeroNet)
# =============================================================================
class ResBlock(torch.nn.Module):
    def __init__(self, num_filters):
        super(ResBlock, self).__init__()
        self.conv1 = torch.nn.Conv2d(num_filters, num_filters, kernel_size=3, padding=1)
        self.bn1 = torch.nn.BatchNorm2d(num_filters)
        self.conv2 = torch.nn.Conv2d(num_filters, num_filters, kernel_size=3, padding=1)
        self.bn2 = torch.nn.BatchNorm2d(num_filters)

    def forward(self, x):
        residual = x
        x = F.relu(self.bn1(self.conv1(x)))
        x = self.bn2(self.conv2(x))
        x += residual
        x = F.relu(x)
        return x

class HexAlphaZeroNet(torch.nn.Module):
    def __init__(self, board_size=11, num_res_blocks=5, num_filters=128):
        super(HexAlphaZeroNet, self).__init__()
        self.conv_input = torch.nn.Sequential(
            torch.nn.Conv2d(3, num_filters, kernel_size=3, padding=1),
            torch.nn.BatchNorm2d(num_filters),
            torch.nn.ReLU()
        )
        self.res_blocks = torch.nn.ModuleList([ResBlock(num_filters) for _ in range(num_res_blocks)])
        self.policy_head = torch.nn.Sequential(
            torch.nn.Conv2d(num_filters, 2, kernel_size=1),
            torch.nn.BatchNorm2d(2),
            torch.nn.ReLU(),
            torch.nn.Flatten(),
            torch.nn.Linear(2 * board_size * board_size, board_size * board_size)
        )
        self.value_head = torch.nn.Sequential(
            torch.nn.Conv2d(num_filters, 1, kernel_size=1),
            torch.nn.BatchNorm2d(1),
            torch.nn.ReLU(),
            torch.nn.Flatten(),
            torch.nn.Linear(board_size * board_size, 64),
            torch.nn.ReLU(),
            torch.nn.Linear(64, 1),
            torch.nn.Tanh()
        )

    def forward(self, x):
        x = self.conv_input(x)
        for block in self.res_blocks:
            x = block(x)
        return self.policy_head(x), self.value_head(x)

# =============================================================================
# 1. FastBoard (Based on your provided code)
# =============================================================================
class FastBoard:
    def __init__(self, size=11):
        self.size = size
        # Union-Find Parent Array (+4 for virtual nodes)
        self.parent = list(range(size * size + 4))
        # 1D Array for board state (None, Red, Blue)
        self.colour_state = [None] * (size * size)
        self.empty_moves = set(range(size * size))
        
        # Virtual Nodes
        self.RED_TOP = size * size
        self.RED_BOTTOM = size * size + 1
        self.BLUE_LEFT = size * size + 2
        self.BLUE_RIGHT = size * size + 3
        
        self.winner = None

    def find(self, i):
        path = []
        while self.parent[i] != i:
            path.append(i)
            i = self.parent[i]
        for node in path:
            self.parent[node] = i
        return i

    def union(self, i, j):
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            self.parent[root_i] = root_j
            return True
        return False

    def from_game_board(self, board: Board):
        """기존 Board 객체로부터 상태 복사"""
        for r in range(self.size):
            for c in range(self.size):
                tile = board.tiles[r][c]
                if tile.colour is not None:
                    self.make_move(r, c, tile.colour)
        return self

    def make_move(self, x, y, colour):
        idx = x * self.size + y
        if idx not in self.empty_moves: return False
        
        self.colour_state[idx] = colour
        self.empty_moves.discard(idx)
        
        # 6방향 이웃 연결
        neighbors = [
            (x-1, y), (x-1, y+1), (x, y-1), 
            (x, y+1), (x+1, y-1), (x+1, y)
        ]
        
        for nx, ny in neighbors:
            if 0 <= nx < self.size and 0 <= ny < self.size:
                n_idx = nx * self.size + ny
                if self.colour_state[n_idx] == colour:
                    self.union(idx, n_idx)
        
        # 가상 노드 연결
        if colour == Colour.RED:
            if x == 0: self.union(idx, self.RED_TOP)
            if x == self.size - 1: self.union(idx, self.RED_BOTTOM)
            if self.find(self.RED_TOP) == self.find(self.RED_BOTTOM): self.winner = Colour.RED
        elif colour == Colour.BLUE:
            if y == 0: self.union(idx, self.BLUE_LEFT)
            if y == self.size - 1: self.union(idx, self.BLUE_RIGHT)
            if self.find(self.BLUE_LEFT) == self.find(self.BLUE_RIGHT): self.winner = Colour.BLUE
            
        return True

    def get_tensor(self, device):
        """신경망 입력을 위한 Tensor 변환 (3채널)"""
        # 1D list -> 2D numpy array 변환
        board_2d = np.array(self.colour_state).reshape(self.size, self.size)
        
        # One-hot encoding
        p_red = (board_2d == Colour.RED).astype(np.float32)
        p_blue = (board_2d == Colour.BLUE).astype(np.float32)
        p_empty = (board_2d == None).astype(np.float32)
        
        return torch.tensor(np.stack([p_red, p_blue, p_empty]), dtype=torch.float32).unsqueeze(0).to(device)

# =============================================================================
# 2. AlphaZero Node (Simplified: No RAVE, No Untried Moves)
# =============================================================================
class Node:
    def __init__(self, prior=0.0):
        self.visits = 0
        self.value_sum = 0.0
        self.prior = prior  # 신경망이 준 확률 (P)
        self.children = {}  # {move_idx: Node}

    @property
    def value(self):
        # Q = W / N
        return self.value_sum / self.visits if self.visits > 0 else 0

# =============================================================================
# 3. Trained Agent (AlphaZero Logic)
# =============================================================================
class Trained_Agent(AgentBase):
    def __init__(self, colour: Colour):
        super().__init__(colour)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"🤖 AlphaZero Agent Loading... Device: {self.device}")
        
        # 모델 로드
        current_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(current_dir, MODEL_FILE_NAME)
        self.model = HexAlphaZeroNet().to(self.device)
        
        if os.path.exists(model_path):
            try:
                self.model.load_state_dict(torch.load(model_path, map_location=self.device))
                print("✅ Model Loaded Successfully!")
            except:
                print("⚠️ Model Load Failed!")
        else:
            print(f"⚠️ Model File Not Found: {model_path}")
            
        self.model.eval()
        self.c_puct = 3.0 # 탐색 상수
        self.remaining_time = 300.0

    def make_move(self, turn: int, board: Board, opp_move: Move | None) -> Move:
        if turn == 2 and self.colour == Colour.BLUE:
            if opp_move and opp_move.x != -1:
                # 중앙과의 거리 계산 (맨해튼 거리 등)
                center = board.size // 2
                dist = abs(opp_move.x - center) + abs(opp_move.y - center)
                
                if dist <= 4:
                    print("⚡ Hard-coded Swap Decision: SWAP!")
                    return Move(-1, -1)
        
        
        start_time = time.time()
        
        # 1. FastBoard 생성 및 상태 동기화
        root_board = FastBoard().from_game_board(board)
        
        # ★ [중요] 상대방 마지막 수 강제 적용 (Illegal Move 방지)
        if opp_move is not None and opp_move.x != -1:
            opp_colour = Colour.BLUE if self.colour == Colour.RED else Colour.RED
            # 보드에 아직 반영 안 됐다면 강제 적용
            root_board.make_move(opp_move.x, opp_move.y, opp_colour)

        # 2. 루트 노드 생성 및 첫 평가
        root = Node(prior=1.0)
        self.expand_and_evaluate(root, root_board)

        # 3. 시간 배분 (남은 시간의 5% 사용, 최대 7초)
        if turn <= 12:
            time_budget = 10.0
        else:
            time_budget = min(self.remaining_time * 0.05, 7.0)
        
        # 4. MCTS 루프
        while True:
            if time.time() - start_time > time_budget - 0.1: break
            
            node = root
            search_board = copy.deepcopy(root_board) # FastBoard는 가벼워서 deepcopy 괜찮음
            path = [node]
            
            # (A) Selection (PUCT)
            while node.children:
                move_idx, node = self.select_child(node)
                path.append(node)
                
                # 가상 보드에 수 두기
                r, c = divmod(move_idx, 11)
                # path 길이가 1(루트) -> 내 차례, 2 -> 상대 차례 ...
                turn_colour = self.colour if len(path) % 2 == 0 else Colour.opposite(self.colour)
                search_board.make_move(r, c, turn_colour)
                
                if search_board.winner is not None: break
            
            # (B) Expansion & Evaluation (Neural Network)
            if search_board.winner is not None:
                # 승부가 났으면 가치 반환 (내가 이겼으면 1, 졌으면 -1)
                value = 1.0 if search_board.winner == self.colour else -1.0
            else:
                # 안 났으면 신경망에게 물어보기
                value = self.expand_and_evaluate(node, search_board)
            
            # (C) Backpropagation
            self.backpropagate(path, value)

        self.remaining_time -= (time.time() - start_time)

        # 5. 최종 선택
        if not root.children:
            best_move_idx = self.get_random_valid(root_board)
        else:
            best_move_idx = max(root.children, key=lambda k: root.children[k].visits)
        
        # [최종 안전장치] 혹시라도 찬 곳을 골랐다면 랜덤으로 변경
        if root_board.colour_state[best_move_idx] is not None:
            print(f"⚠️ Occupied move selected. Fallback to random.")
            best_move_idx = self.get_random_valid(root_board)

        r, c = divmod(best_move_idx, 11)
        return Move(r, c)

    def select_child(self, node):
        """RAVE 대신 PUCT 공식 사용"""
        best_score = -float('inf')
        best_move = -1
        best_child = None
        
        sqrt_n = math.sqrt(node.visits)
        
        for move_idx, child in node.children.items():
            # Q값 (승률)
            q = child.value
            # U값 (탐색 보너스: 확률 * 방문비율)
            u = self.c_puct * child.prior * sqrt_n / (1 + child.visits)
            
            score = q + u
            
            if score > best_score:
                best_score = score
                best_move = move_idx
                best_child = child
        
        return best_move, best_child

    def expand_and_evaluate(self, node, board):
        """롤아웃 대신 신경망 추론"""
        # 1. 텐서 변환
        x = board.get_tensor(self.device)
        
        # 2. 추론
        with torch.no_grad():
            pi, v = self.model(x)
        
        # 3. 결과 파싱
        probs = F.softmax(pi, dim=1).cpu().numpy()[0]
        value = v.item()
        
        # 4. 유효한 수(Legal Moves)만 자식으로 확장
        legal_moves = list(board.empty_moves)
        prob_sum = sum(probs[m] for m in legal_moves)
        
        for m in legal_moves:
            # 확률 재정규화 (Renormalize)
            prior = probs[m] / prob_sum if prob_sum > 0 else 0
            node.children[m] = Node(prior=prior)
            
        return value

    def backpropagate(self, path, leaf_value):
        current_value = leaf_value
        # 리프 노드부터 루트까지 역순으로
        for node in reversed(path):
            node.visits += 1
            node.value_sum += current_value
            current_value = -current_value # 턴 교대 (Minimax 원리)

    def get_random_valid(self, board):
        moves = list(board.empty_moves)
        if not moves: return 0
        return random.choice(moves)







