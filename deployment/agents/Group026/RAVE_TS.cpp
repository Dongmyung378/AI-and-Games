#include <iostream>
#include <vector>
#include <string>
#include <sstream>
#include <cmath>
#include <algorithm>
#include <random>
#include <chrono>
#include <memory>
#include <limits>
#include <thread>  
#include <future>  
#include <mutex>   
#include <map>     
#include <deque>
#include <memory_resource>

// ==========================================
// 1. Constants & Enums
// ==========================================
const int BOARD_SIZE = 11;
const int NUM_TILES = BOARD_SIZE * BOARD_SIZE;
const double MAX_GAME_TIME = 300.0;
const double RAVE_EQUIV = 1000.0;

enum Colour { RED = 0, BLUE = 1, EMPTY = 2 };

struct Point {
    int x, y;
    bool operator==(const Point& other) const { return x == other.x && y == other.y; }
    bool operator<(const Point& other) const { 
        if (x != other.x) return x < other.x;
        return y < other.y;
    }
    bool isValid() const { return x >= 0 && x < BOARD_SIZE && y >= 0 && y < BOARD_SIZE; }
};

Colour opposite(Colour c) {
    if (c == RED) return BLUE;
    if (c == BLUE) return RED;
    return EMPTY;
}

thread_local std::mt19937 rng(std::random_device{}());

// ==========================================
// 2. FastBoard (Union-Find Optimization)
// ==========================================
class FastBoard {
public:
    int parent[NUM_TILES + 4];
    Colour tile_colours[NUM_TILES];
    
    int empty_tiles[NUM_TILES]; 
    int empty_pos[NUM_TILES];
    int empty_count;

    const int RED_TOP = NUM_TILES;
    const int RED_BOTTOM = NUM_TILES + 1;
    const int BLUE_LEFT = NUM_TILES + 2;
    const int BLUE_RIGHT = NUM_TILES + 3;

    FastBoard() { reset(); }

    FastBoard(const FastBoard& other) {
        std::copy(std::begin(other.parent), std::end(other.parent), std::begin(parent));
        std::copy(std::begin(other.tile_colours), std::end(other.tile_colours), std::begin(tile_colours));
        std::copy(std::begin(other.empty_tiles), std::end(other.empty_tiles), std::begin(empty_tiles));
        std::copy(std::begin(other.empty_pos), std::end(other.empty_pos), std::begin(empty_pos));
        empty_count = other.empty_count;
    }

    void reset() {
        for (int i = 0; i < NUM_TILES + 4; ++i) parent[i] = i;
        for (int i = 0; i < NUM_TILES; ++i) {
            tile_colours[i] = EMPTY;
            empty_tiles[i] = i;
            empty_pos[i] = i;
        }
        empty_count = NUM_TILES;
    }

    int find(int i) {
        int root = i;
        while (root != parent[root]) root = parent[root];
        int curr = i;
        while (curr != root) {
            int next = parent[curr];
            parent[curr] = root;
            curr = next;
        }
        return root;
    }

    void join(int i, int j) {
        int root_i = find(i);
        int root_j = find(j);
        if (root_i != root_j) parent[root_i] = root_j;
    }

    void make_move(int x, int y, Colour c) {
        int idx = x * BOARD_SIZE + y;
        if (tile_colours[idx] != EMPTY) return;

        tile_colours[idx] = c;
        
        int pos = empty_pos[idx];
        int last_tile = empty_tiles[empty_count - 1];
        
        empty_tiles[pos] = last_tile;
        empty_pos[last_tile] = pos;
        empty_count--;

        int dx[] = {-1, -1, 0, 0, 1, 1};
        int dy[] = {0, 1, -1, 1, -1, 0};

        for (int k = 0; k < 6; ++k) {
            int nx = x + dx[k];
            int ny = y + dy[k];
            if (nx >= 0 && nx < BOARD_SIZE && ny >= 0 && ny < BOARD_SIZE) {
                int n_idx = nx * BOARD_SIZE + ny;
                if (tile_colours[n_idx] == c) {
                    join(idx, n_idx);
                }
            }
        }

        if (c == RED) {
            if (x == 0) join(idx, RED_TOP);
            if (x == BOARD_SIZE - 1) join(idx, RED_BOTTOM);
        } else if (c == BLUE) {
            if (y == 0) join(idx, BLUE_LEFT);
            if (y == BOARD_SIZE - 1) join(idx, BLUE_RIGHT);
        }
    }

    bool check_win(Colour c) {
        if (c == RED) return find(RED_TOP) == find(RED_BOTTOM);
        if (c == BLUE) return find(BLUE_LEFT) == find(BLUE_RIGHT);
        return false;
    }
};

double STATIC_CENTRALITY[BOARD_SIZE][BOARD_SIZE];

void init_centrality() {
    double cx = BOARD_SIZE / 2.0;
    double cy = BOARD_SIZE / 2.0;
    for(int i=0; i<BOARD_SIZE; ++i) {
        for(int j=0; j<BOARD_SIZE; ++j) {
            double dist = std::abs(i - cx) + std::abs(j - cy);
            STATIC_CENTRALITY[i][j] = 10.0 - dist;
        }
    }
}

// ==========================================
// 3. MCTS Node (Thompson Sampling + Heuristic)
// ==========================================
struct Node {
    Point move;
    Node* parent;

    std::pmr::vector<Node*> children;
    std::pmr::vector<Point> untried_moves;
    
    double visits = 0;
    double wins = 0;
    double rave_visits = 0; 
    double rave_wins = 0;

    Colour turn; 

    Node(Point m, Node* p, Colour t, const FastBoard& board, Point last_opp_move, std::pmr::memory_resource* mem) 
        : move(m), parent(p), turn(t), children(mem), untried_moves(mem) {
        
        std::vector<std::pair<double, Point>> scored_moves;
        scored_moves.reserve(board.empty_count); 

        bool is_radius1[BOARD_SIZE][BOARD_SIZE] = {false};
        bool is_radius2[BOARD_SIZE][BOARD_SIZE] = {false};

        if (last_opp_move.isValid()) {
            int pat_dx[] = { -1, -1, 0, 0, 1, 1,   -1, -2, -1, 1, 2, 1 };
            int pat_dy[] = { 0, 1, -1, 1, -1, 0,    2, 1, -1, -2, -1, 1 };

            for (int k = 0; k < 12; ++k) {
                int nx = last_opp_move.x + pat_dx[k];
                int ny = last_opp_move.y + pat_dy[k];
                if (nx >= 0 && nx < BOARD_SIZE && ny >= 0 && ny < BOARD_SIZE) {
                    if (k < 6) is_radius1[nx][ny] = true;
                    else       is_radius2[nx][ny] = true;
                }
            }
        }

        for (int k = 0; k < board.empty_count; ++k) {
            int idx = board.empty_tiles[k];
            int i = idx / BOARD_SIZE;
            int j = idx % BOARD_SIZE;

            double score = 0.0;
            score += STATIC_CENTRALITY[i][j];

            if (is_radius2[i][j]) score += 12.0; 
            else if (is_radius1[i][j]) score -= 2.0; 

            std::uniform_real_distribution<double> dist_noise(0.0, 3.0);
            score += dist_noise(rng);

            scored_moves.push_back({score, {i, j}});
        }

        std::sort(scored_moves.begin(), scored_moves.end(), 
            [](const std::pair<double, Point>& a, const std::pair<double, Point>& b) {
                return a.first < b.first; 
            });
        for (const auto& item : scored_moves) {
            untried_moves.push_back(item.second);
        }
    }
    ~Node() {}
};

// ==========================================
// 4. Agent Class (Main Logic)
// ==========================================
class Agent {
public:
    Colour my_colour;
    FastBoard root_board;
    double total_time_used;

    Agent(Colour c) : my_colour(c), total_time_used(0.0) {}

    Agent(const Agent& other) 
        : my_colour(other.my_colour), 
        root_board(other.root_board), 
        total_time_used(other.total_time_used) {}

    Agent* clone() const {
        return new Agent(*this); 
    }

    // ------------------------------------------
    // Logic: Select Child (Modified for RAVE)
    // ------------------------------------------
    Node* select_child(Node* node) {
        Node* best_child = nullptr;
        double best_score = -1.0;

        for (Node* child : node->children) {
            double beta = RAVE_EQUIV / (RAVE_EQUIV + child->visits + 1e-5);
            
            double combined_wins = (1.0 - beta) * child->wins + beta * child->rave_wins;
            double combined_losses = (1.0 - beta) * (child->visits - child->wins) + beta * (child->rave_visits - child->rave_wins);
            
            std::gamma_distribution<double> dist_alpha(combined_wins + 1.0, 1.0);
            std::gamma_distribution<double> dist_beta(combined_losses + 1.0, 1.0);
            
            double x = dist_alpha(rng);
            double y = dist_beta(rng);
            double score = x / (x + y);

            if (score > best_score) {
                best_score = score;
                best_child = child;
            }
        }
        return best_child;
    }

    // ------------------------------------------
    // Logic: Simulation (RAVE)
    // ------------------------------------------
    Colour simulate(Node* leaf, FastBoard& board, std::vector<int>& red_moves, std::vector<int>& blue_moves) {
        Colour current_c = leaf->turn;

        red_moves.clear();
        blue_moves.clear();
        
        int last_pos = -1;
        if (leaf->move.isValid()) {
            last_pos = leaf->move.x * BOARD_SIZE + leaf->move.y;
        }
        
        int moves_left = board.empty_count;
        
        while (!board.check_win(RED) && !board.check_win(BLUE) && moves_left > 0) {
            int r, c, pos;
            Point smart_move = {-1, -1};

            if (last_pos != -1) {
                smart_move = find_bridge_save(board, last_pos, current_c);
            }

            if (smart_move.x != -1) {
                r = smart_move.x;
                c = smart_move.y;
                pos = r * BOARD_SIZE + c;
            } else {
                int rand_idx = std::uniform_int_distribution<int>(0, moves_left - 1)(rng);
                pos = board.empty_tiles[rand_idx];
                
                r = pos / BOARD_SIZE;
                c = pos % BOARD_SIZE;
            }

            board.make_move(r, c, current_c);
            if (current_c == RED) red_moves.push_back(pos);
            else blue_moves.push_back(pos);

            moves_left = board.empty_count; 
            last_pos = pos;
            current_c = opposite(current_c);
        }
        
        if (board.check_win(my_colour)) return my_colour;
        if (board.check_win(opposite(my_colour))) return opposite(my_colour);
        return EMPTY;
    }

    // Logic: Bridge Saving (Wall Aware)
    Point find_bridge_save(FastBoard& board, int last_idx, Colour defend_col) {
        if (last_idx == -1) return {-1, -1};

        int ox = last_idx / BOARD_SIZE;
        int oy = last_idx % BOARD_SIZE;

        static const int pats[6][6] = {
            {-1, 0,  1, -1,  0, -1}, {-1, 1,  1, 0,   0, 1},
            {0, -1,  1, 0,   1, -1}, {-1, 0,  0, 1,  -1, 1},
            {0, -1, -1, 1,  -1, 0},  {0, 1,   1, -1,  1, 0}
        };

        for (int k = 0; k < 6; ++k) {
            int x1 = ox + pats[k][0]; int y1 = oy + pats[k][1];
            int x2 = ox + pats[k][2]; int y2 = oy + pats[k][3];
            int sx = ox + pats[k][4]; int sy = oy + pats[k][5];

            if (sx < 0 || sx >= BOARD_SIZE || sy < 0 || sy >= BOARD_SIZE) continue;
            int idxS = sx * BOARD_SIZE + sy;
            if (board.tile_colours[idxS] != EMPTY) continue;

            int idx1 = -1;
            int idx2 = -1;

            bool p1_ok = false;
            bool p2_ok = false;

            if (x1 >= 0 && x1 < BOARD_SIZE && y1 >= 0 && y1 < BOARD_SIZE) {
                int tmp = x1 * BOARD_SIZE + y1;
                if (board.tile_colours[x1 * BOARD_SIZE + y1] == defend_col) {
                    p1_ok = true;
                    idx1 = tmp;
                }
            } else {
                if (defend_col == RED) {
                    if (x1 < 0) { p1_ok = true; idx1 = board.RED_TOP; }
                    else if (x1 >= BOARD_SIZE) { p1_ok = true; idx1 = board.RED_BOTTOM; }
                } else {
                    if (y1 < 0) { p1_ok = true; idx1 = board.BLUE_LEFT; }
                    else if (y1 >= BOARD_SIZE) { p1_ok = true; idx1 = board.BLUE_RIGHT; }
                }
            }

            if (x2 >= 0 && x2 < BOARD_SIZE && y2 >= 0 && y2 < BOARD_SIZE) {
                int tmp = x2 * BOARD_SIZE + y2;
                if (board.tile_colours[tmp] == defend_col) {
                    p2_ok = true;
                    idx2 = tmp;
                }
            } else {
                if (defend_col == RED) {
                    if (x2 < 0) { p2_ok = true; idx2 = board.RED_TOP; }
                    else if (x2 >= BOARD_SIZE) { p2_ok = true; idx2 = board.RED_BOTTOM; }
                } else {
                    if (y2 < 0) { p2_ok = true; idx2 = board.BLUE_LEFT; }
                    else if (y2 >= BOARD_SIZE) { p2_ok = true; idx2 = board.BLUE_RIGHT; }
                }
            }

            if (p1_ok && p2_ok) {
                if (idx1 != -1 && idx2 != -1) {
                    if (board.find(idx1) == board.find(idx2)) {
                        continue;
                    }
                }
                return {sx, sy};
            }
        }
        return {-1, -1};
    }

    Point check_immediate_threat(const FastBoard& board, Colour me) {
        for (int k = 0; k < board.empty_count; ++k) {
            int idx = board.empty_tiles[k];
            int r = idx / BOARD_SIZE;
            int c = idx % BOARD_SIZE;
            
            FastBoard copy = board; 
            copy.make_move(r, c, me);
            if (copy.check_win(me)) return {r, c};
        }

        Colour opp = opposite(me);
        for (int k = 0; k < board.empty_count; ++k) {
            int idx = board.empty_tiles[k];
            int r = idx / BOARD_SIZE;
            int c = idx % BOARD_SIZE;
            
            FastBoard copy = board;
            copy.make_move(r, c, opp);
            if (copy.check_win(opp)) return {r, c};
        }
        
        return {-1, -1};
    }

    double get_time_budget(int turn) {
        double remaining = MAX_GAME_TIME - total_time_used;
        if (turn <= 12) return 10.0; 
        if (remaining < 10.0) return 0.5; 
        double budget = remaining * 0.04;
        if (budget > 7.0) budget = 7.0; 
        return budget;
    }

    struct ThreadResult {
        int iterations;
        std::map<Point, std::pair<double, double>> child_stats; 
    };

    // ------------------------------------------
    // Worker: PMR + RAVE Update
    // ------------------------------------------
    ThreadResult run_mcts_worker(FastBoard board, Colour turn, Point opp_move, double time_limit) {
        auto start_time = std::chrono::high_resolution_clock::now();
        
        std::pmr::monotonic_buffer_resource pool_resource(256 * 1024 * 1024);
        std::deque<Node> node_pool;

        node_pool.emplace_back(Point{-1, -1}, nullptr, turn, board, opp_move, &pool_resource);
        Node* root = &node_pool.back();

        int iterations = 0;
        
        std::vector<int> red_moves, blue_moves;
        red_moves.reserve(NUM_TILES);
        blue_moves.reserve(NUM_TILES);
        
        bool winner_moves_map[NUM_TILES];

        while (true) {
            if (iterations > 1500000) break;

            if (iterations % 1000 == 0) {
                auto now = std::chrono::high_resolution_clock::now();
                std::chrono::duration<double> elapsed = now - start_time;
                if (elapsed.count() > time_limit - 0.1) break;
            }

            Node* node = root;
            FastBoard sim_board = board;

            while (node->untried_moves.empty() && !node->children.empty()) {
                node = select_child(node);
                sim_board.make_move(node->move.x, node->move.y, node->parent->turn);
            }
            
            if (!node->untried_moves.empty()) {
                Point m = node->untried_moves.back();
                node->untried_moves.pop_back();
                
                Colour next_turn = opposite(node->turn);
                sim_board.make_move(m.x, m.y, node->turn);
                
                node_pool.emplace_back(m, node, next_turn, sim_board, m, &pool_resource);
                Node* child = &node_pool.back();
                
                node->children.push_back(child);
                node = child;
            }
            
            Colour winner = simulate(node, sim_board, red_moves, blue_moves);

            std::fill(std::begin(winner_moves_map), std::end(winner_moves_map), false);
            const std::vector<int>& winner_history = (winner == RED) ? red_moves : blue_moves;
            for (int pos : winner_history) { winner_moves_map[pos] = true; }

            while (node != nullptr) {
                node->visits++;
                if (node->parent && node->parent->turn == winner) {
                    node->wins++;
                }
                if (node->parent) {
                    int move_idx = node->move.x * BOARD_SIZE + node->move.y;
                    if (winner_moves_map[move_idx]) {
                        node->rave_visits++;
                        if (node->parent->turn == winner) {
                            node->rave_wins++;
                        }
                    }
                }
                node = node->parent;
            }
            iterations++;
        }

        ThreadResult result;
        result.iterations = iterations;
        for (Node* child : root->children) {
            result.child_stats[child->move] = {child->visits, child->wins};
        }
        
        return result;
    }

    // ------------------------------------------
    // Main Decision Function (Parallelized & Fixed 8-Core)
    // ------------------------------------------
    Point get_best_move(int turn, Point opp_move) {
        if (turn == 2 && my_colour == BLUE && opp_move.isValid()) {
            int center = BOARD_SIZE / 2;
            int dx = opp_move.x - center;
            int dy = opp_move.y - center;
            int hex_dist = (std::abs(dx) + std::abs(dy) + std::abs(dx + dy)) / 2;
            if (hex_dist <= 3) {
                total_time_used += 0.1;
                return {-1, -1};
            }
            else {
                total_time_used += 0.1;
                return {center, center};
            }
        }

        auto move_start = std::chrono::high_resolution_clock::now();

        Point crit = check_immediate_threat(root_board, my_colour);
        if (crit.x != -1) return crit;

        double time_budget = get_time_budget(turn);
        const unsigned int num_threads = 8; 

        std::vector<std::future<ThreadResult>> futures;

        for (unsigned int i = 0; i < num_threads; ++i) {
            futures.push_back(std::async(std::launch::async, 
                &Agent::run_mcts_worker, this, root_board, my_colour, opp_move, time_budget));
        }

        std::map<Point, double> total_visits;
        std::map<Point, double> total_wins;
        int total_iterations = 0;

        for (auto& f : futures) {
            ThreadResult res = f.get();
            total_iterations += res.iterations;
            for (auto const& [move, stats] : res.child_stats) {
                total_visits[move] += stats.first;
                total_wins[move] += stats.second;
            }
        }

        Point best_move = {-1, -1};
        double max_visits = -1.0;

        for (auto const& [move, visits] : total_visits) {
            if (visits > max_visits) {
                max_visits = visits;
                best_move = move;
            }
        }
        
        if (best_move.x == -1) {
            for(int i=0; i<NUM_TILES; ++i) {
                if(root_board.tile_colours[i] == EMPTY) {
                    best_move = {i/BOARD_SIZE, i%BOARD_SIZE};
                    break;
                }
            }
        }

        // Final Safety Check
        if (root_board.tile_colours[best_move.x * BOARD_SIZE + best_move.y] != EMPTY) {
            for(int i=0; i<NUM_TILES; ++i) {
                if(root_board.tile_colours[i] == EMPTY) return {i/BOARD_SIZE, i%BOARD_SIZE};
            }
        }

        auto move_end = std::chrono::high_resolution_clock::now();
        std::chrono::duration<double> move_duration = move_end - move_start;
        total_time_used += move_duration.count();

        double speed = (move_duration.count() > 0) ? (total_iterations / move_duration.count()) : 0;

        return best_move;
    }
};

int main(int argc, char* argv[]) {
    init_centrality();
    if (argc < 2) return 1;
    char col_char = argv[1][0];
    Colour my_col = (col_char == 'R') ? RED : BLUE;
    
    Agent agent(my_col);

    std::string line;
    while (std::getline(std::cin, line)) {
        std::stringstream ss(line);
        std::string segment;
        std::vector<std::string> parts;
        while(std::getline(ss, segment, ';')) parts.push_back(segment);

        if (parts.empty()) continue;
        
        Point opp_move = {-1, -1};
        std::string command = parts[0];
        if (command == "CHANGE") {
            size_t comma = parts[1].find(',');
            if (comma != std::string::npos) {
                opp_move.x = std::stoi(parts[1].substr(0, comma));
                opp_move.y = std::stoi(parts[1].substr(comma + 1));
            }
        }

        std::string board_str = parts[2];
        int row = 0, col = 0;
        agent.root_board.reset();
        for (char c : board_str) {
            if (c == ',') continue;
            if (c == 'R') agent.root_board.make_move(row, col, RED);
            else if (c == 'B') agent.root_board.make_move(row, col, BLUE);
            col++;
            if (col >= BOARD_SIZE) { col = 0; row++; }
        }
        
        int turn_num = std::stoi(parts[3]);
        Point move = agent.get_best_move(turn_num, opp_move);
        
        if (move.x == -1 && move.y == -1) std::cout << "-1,-1" << std::endl;
        else std::cout << move.x << "," << move.y << std::endl;
    }
    return 0;
}


