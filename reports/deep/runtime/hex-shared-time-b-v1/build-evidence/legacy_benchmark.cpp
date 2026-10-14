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
#include <stdexcept>

// ==========================================
// 1. Constants & Enums
// ==========================================

// Benchmark-only runtime adapter. Original selection, expansion, rollout,
// reward and zero-AMAF code below are preserved byte-for-byte (canonical LF).
#include <cstdint>
#include <iomanip>
struct BenchmarkRuntime {
    std::uint64_t seed = 378, iterations = 0, completed = 0, nodes = 0, rave_updates = 0;
    unsigned int workers = 1;
    int request_turn = 1;
    double seconds = 0, game_seconds = 300, allocated = -1, external_remaining = -1;
    bool iteration_mode = false, original_iteration_cap_reached = false;
    std::chrono::steady_clock::time_point deadline;
    std::vector<std::uint64_t> worker_iterations, worker_nodes, worker_amaf;
} benchmark;

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

thread_local std::mt19937 rng(378); // Seeded separately per controlled worker below.

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
        if (benchmark.allocated >= 0) return benchmark.allocated;
        double remaining = MAX_GAME_TIME - total_time_used;
        if (turn <= 12) return 10.0; 
        if (remaining < 10.0) return 0.5; 
        double budget = remaining * 0.04;
        if (budget > 7.0) budget = 7.0; 
        return budget;
    }

    struct ThreadResult {
        int iterations;
        std::uint64_t nodes = 0, rave_updates = 0;
        bool original_cap = false;
        std::map<Point, std::pair<double, double>> child_stats; 
    };

    // ------------------------------------------
    // Worker: PMR + RAVE Update
    // ------------------------------------------
    ThreadResult run_mcts_worker(FastBoard board, Colour turn, Point opp_move, double time_limit, unsigned int worker_id) {
        std::uint64_t position = 1469598103934665603ULL;
        for (int m = 0; m < NUM_TILES; ++m) position = (position ^ (board.tile_colours[m] + 1)) * 1099511628211ULL;
        std::seed_seq seeds{static_cast<unsigned int>(benchmark.seed), static_cast<unsigned int>(benchmark.seed >> 32),
            static_cast<unsigned int>(position), static_cast<unsigned int>(position >> 32),
            static_cast<unsigned int>(benchmark.request_turn), worker_id, static_cast<unsigned int>(turn)};
        rng.seed(seeds);
        (void)time_limit;
        std::uint64_t rave_updates = 0;

        
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
            if (iterations > 1500000) break; // Original algorithm safety limit retained.
            if (benchmark.iteration_mode && static_cast<std::uint64_t>(iterations) >=
                benchmark.iterations / benchmark.workers + (worker_id < benchmark.iterations % benchmark.workers ? 1 : 0)) break;
            if (std::chrono::steady_clock::now() >= benchmark.deadline) break;

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
                        ++rave_updates;
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
        result.nodes = node_pool.size();
        result.rave_updates = rave_updates;
        result.original_cap = iterations > 1500000;
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
        const unsigned int num_threads = benchmark.workers; 

        std::vector<std::future<ThreadResult>> futures;

        for (unsigned int i = 0; i < num_threads; ++i) {
            futures.push_back(std::async(std::launch::async, 
                &Agent::run_mcts_worker, this, root_board, my_colour, opp_move, time_budget, i));
        }

        std::map<Point, double> total_visits;
        std::map<Point, double> total_wins;
        int total_iterations = 0;

        unsigned int worker_id = 0;
        for (auto& f : futures) {
            ThreadResult res = f.get();
            benchmark.completed += res.iterations; benchmark.nodes += res.nodes; benchmark.rave_updates += res.rave_updates;
            benchmark.original_iteration_cap_reached = benchmark.original_iteration_cap_reached || res.original_cap;
            benchmark.worker_iterations[worker_id] = res.iterations; benchmark.worker_nodes[worker_id] = res.nodes;
            benchmark.worker_amaf[worker_id++] = res.rave_updates;
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

struct NativeRequest {
    Colour colour;
    std::string board;
    Point opponent;
    int turn;
};

int protocol_integer(const std::string& value) {
    if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos)
        throw std::invalid_argument("Protocol integers must contain decimal digits.");
    return std::stoi(value);
}

NativeRequest parse_request(const std::string& line) {
    std::string normalized = line;
    if (!normalized.empty() && normalized.back() == '\r') normalized.pop_back();
    std::stringstream stream(normalized);
    std::string field;
    std::vector<std::string> parts;
    while (std::getline(stream, field, ';')) parts.push_back(field);
    if (parts.size() != 7 || parts[0] != "V2")
        throw std::invalid_argument("Expected protocol V2; rebuild both the adapter and native engine.");
    if (parts[1] != "R" && parts[1] != "B")
        throw std::invalid_argument("Current colour must be R or B.");
    if (protocol_integer(parts[2]) != BOARD_SIZE)
        throw std::invalid_argument("Native RAVE-TS supports only 11x11 boards.");
    if (parts[3] != "START" && parts[3] != "CHANGE" && parts[3] != "SWAP")
        throw std::invalid_argument("Unknown native command.");
    Point opponent = {-1, -1};
    if (parts[3] == "CHANGE") {
        size_t comma = parts[4].find(',');
        if (comma == std::string::npos)
            throw std::invalid_argument("CHANGE requires opponent x,y.");
        opponent = {protocol_integer(parts[4].substr(0, comma)),
                    protocol_integer(parts[4].substr(comma + 1))};
        if (!opponent.isValid()) throw std::invalid_argument("Opponent coordinate is outside the board.");
    } else if (!parts[4].empty()) {
        throw std::invalid_argument("START and SWAP require an empty opponent field.");
    }
    std::stringstream rows(parts[5]);
    std::string row;
    int count = 0;
    while (std::getline(rows, row, ',')) {
        if (row.size() != BOARD_SIZE || row.find_first_not_of("0RB") != std::string::npos)
            throw std::invalid_argument("Each board row must contain eleven 0/R/B cells.");
        ++count;
    }
    if (count != BOARD_SIZE || parts[5].back() == ',')
        throw std::invalid_argument("Expected eleven board rows.");
    int turn = protocol_integer(parts[6]);
    if (turn < 1) throw std::invalid_argument("Turn must be positive.");
    return {parts[1] == "R" ? RED : BLUE, parts[5], opponent, turn};
}

void apply_request(Agent& agent, const NativeRequest& request) {
    // The swap initiator next receives CHANGE. Always apply explicit role state.
    agent.my_colour = request.colour;
    agent.root_board.reset();
    int cell = 0;
    for (char value : request.board) {
        if (value == ',') continue;
        if (value == 'R' || value == 'B')
            agent.root_board.make_move(cell / BOARD_SIZE, cell % BOARD_SIZE, value == 'R' ? RED : BLUE);
        ++cell;
    }
}


double benchmark_number(const std::string& value) {
    std::size_t end = 0;
    double number = std::stod(value, &end);
    if (end != value.size() || !std::isfinite(number) || number < 0)
        throw std::invalid_argument("Expected a finite nonnegative number.");
    return number;
}
std::uint64_t benchmark_integer(const std::string& value) {
    if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos)
        throw std::invalid_argument("Expected an unsigned decimal integer.");
    return std::stoull(value);
}
int main(int argc, char* argv[]) {
    try {
        int first = 1;
        if (argc >= 3 && (std::string(argv[1]) == "R" || std::string(argv[1]) == "B")) {
            if (protocol_integer(argv[2]) != BOARD_SIZE) throw std::invalid_argument("Only 11x11 is supported.");
            first = 3;
        }
        for (int i = first; i < argc; ++i) {
            std::string key = argv[i];
            if (key == "--version") { std::cout << "hex-legacy-controlled-benchmark 1.0.0\n"; return 0; }
            if (i + 1 >= argc) throw std::invalid_argument("Missing option value.");
            std::string value = argv[++i];
            if (key == "--seed") benchmark.seed = benchmark_integer(value);
            else if (key == "--workers") {
                auto count = benchmark_integer(value);
                if (count < 1 || count > 64) throw std::invalid_argument("Workers must be 1 through 64.");
                benchmark.workers = static_cast<unsigned int>(count);
            } else if (key == "--iterations") {
                benchmark.iterations = benchmark_integer(value);
                if (benchmark.iterations < 1 || benchmark.iterations > 1000000000ULL)
                    throw std::invalid_argument("Iteration total must be 1 through 1000000000.");
                benchmark.iteration_mode = true;
            } else if (key == "--seconds") benchmark.seconds = benchmark_number(value);
            else if (key == "--game-seconds") benchmark.game_seconds = benchmark_number(value);
            else throw std::invalid_argument("Unknown benchmark option: " + key);
        }
        init_centrality();
        Agent agent(RED);
        double cumulative_used = 0;
        int previous_turn = 0;
        std::string line;
        while (std::getline(std::cin, line)) {
            if (line.empty()) continue;
            const auto started = std::chrono::steady_clock::now();
            if (line.back() == '\r') line.pop_back();
            std::vector<std::string> parts;
            std::stringstream input(line);
            std::string field;
            while (std::getline(input, field, ';')) parts.push_back(field);
            bool v3 = parts.size() == 9 && parts[0] == "V3";
            if (!v3 && !(parts.size() == 7 && parts[0] == "V2"))
                throw std::invalid_argument("Expected seven V2 or nine V3 fields.");
            std::string original_line = "V2";
            for (int i = 1; i < 7; ++i) original_line += ";" + parts[i];
            NativeRequest request = parse_request(original_line);
            if (parts[3] == "START" || request.turn <= previous_turn) cumulative_used = 0;
            benchmark.request_turn = request.turn;
            benchmark.completed = benchmark.nodes = benchmark.rave_updates = 0;
            benchmark.original_iteration_cap_reached = false;
            benchmark.worker_iterations.assign(benchmark.workers, 0);
            benchmark.worker_nodes.assign(benchmark.workers, 0);
            benchmark.worker_amaf.assign(benchmark.workers, 0);
            benchmark.external_remaining = v3 ? benchmark_number(parts[8]) : -1;
            double remaining = std::max(0.0, benchmark.game_seconds - cumulative_used);
            if (v3) remaining = std::min(benchmark.game_seconds, benchmark.external_remaining);
            benchmark.allocated = v3 ? std::min(benchmark_number(parts[7]), remaining) :
                (benchmark.iteration_mode ? remaining : std::min(agent.get_time_budget(request.turn), remaining));
            if (benchmark.seconds > 0) benchmark.allocated = std::min(benchmark.allocated, benchmark.seconds);
            // End the search before the outer response deadline. No selection math changes.
            const double margin = std::min(.010, benchmark.allocated * .05);
            benchmark.deadline = started + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                std::chrono::duration<double>(std::max(0.0, benchmark.allocated - margin)));
            apply_request(agent, request);
            if (agent.root_board.check_win(RED) || agent.root_board.check_win(BLUE))
                throw std::invalid_argument("Terminal board: no move is legal.");
            Point move = agent.get_best_move(request.turn, request.opponent);
            double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
            cumulative_used += seconds;
            previous_turn = request.turn;
            std::cout << move.x << ',' << move.y << std::endl;
            std::cerr << std::setprecision(10) << "{\"kind\":\"hex_search_move\",\"version\":\"controlled-legacy-1.0.0\","
                "\"policy\":\"controlled_historical_rave_ts\",\"protocol\":\"" << (v3 ? "V3" : "V2")
                << "\",\"seed\":" << benchmark.seed << ",\"turn\":" << request.turn
                << ",\"colour\":\"" << (request.colour == RED ? 'R' : 'B') << "\",\"move\":[" << move.x << ',' << move.y
                << "],\"reason\":\"" << (move.x < 0 ? "pie_rule_swap" : (benchmark.completed ? "search" : "tactic_or_budget_fallback"))
                << "\",\"iterations\":" << benchmark.completed << ",\"nodes\":" << benchmark.nodes
                << ",\"rave_updates\":" << benchmark.rave_updates << ",\"seconds\":" << seconds
                << ",\"game_seconds_used\":" << cumulative_used << ",\"effective_search_allowance_seconds\":" << benchmark.allocated
                << ",\"external_remaining_seconds\":" << benchmark.external_remaining
                << ",\"original_iteration_cap_reached\":" << (benchmark.original_iteration_cap_reached ? "true" : "false")
                << ",\"workers\":[";
            for (unsigned int w = 0; w < benchmark.workers; ++w) {
                if (w) std::cerr << ',';
                std::cerr << "{\"id\":" << w << ",\"iterations\":" << benchmark.worker_iterations[w]
                    << ",\"nodes\":" << benchmark.worker_nodes[w] << ",\"rave_updates\":" << benchmark.worker_amaf[w] << '}';
            }
            std::cerr << "]}" << std::endl;
            // Prevent the historical scheduler's synthetic swap charge from affecting fairness.
            agent.total_time_used = cumulative_used;
            benchmark.allocated = -1;
        }
        return 0;
    } catch (const std::exception& error) {
        // Error strings here are fixed source text or option names, never document contents.
        std::cerr << "Controlled legacy Hex error: " << error.what() << std::endl;
        return 2;
    }
}
