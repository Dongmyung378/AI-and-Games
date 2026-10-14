// Maintained Hex search engine. The historical submission is intentionally separate.
// Standard-library C++17 only; see README.md for statistic and budget conventions.
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <numeric>
#include <queue>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace hex {
using Clock = std::chrono::steady_clock;
constexpr int MAX_SIZE = 19, MAX_CELLS = MAX_SIZE * MAX_SIZE;
constexpr int DX[6] = {-1, -1, 0, 0, 1, 1};
constexpr int DY[6] = {0, 1, -1, 1, -1, 0};
enum Colour : unsigned char { RED = 0, BLUE = 1, EMPTY = 2 };
Colour opposite(Colour c) { return c == RED ? BLUE : RED; }
double elapsed(Clock::time_point begin) {
    return std::chrono::duration<double>(Clock::now() - begin).count();
}
std::uint64_t mixed(std::uint64_t x) {
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}

struct Board {
    int n, cells, empty_count;
    std::array<int, MAX_CELLS + 4> parent{};
    std::array<unsigned char, MAX_CELLS + 4> rank{};
    std::array<Colour, MAX_CELLS> colour{};
    std::array<int, MAX_CELLS> empty{}, position{};
    explicit Board(int size = 11) : n(size), cells(size * size), empty_count(cells) {
        if (size < 3 || size > MAX_SIZE) throw std::invalid_argument("Board size must be 3 through 19.");
        std::iota(parent.begin(), parent.end(), 0);
        colour.fill(EMPTY);
        std::iota(empty.begin(), empty.end(), 0);
        std::iota(position.begin(), position.end(), 0);
    }
    bool inside(int x, int y) const { return x >= 0 && x < n && y >= 0 && y < n; }
    int find(int a) const { while (a != parent[a]) a = parent[a]; return a; }
    int compressed_find(int a) {
        while (a != parent[a]) { parent[a] = parent[parent[a]]; a = parent[a]; }
        return a;
    }
    void join(int a, int b) {
        a = compressed_find(a); b = compressed_find(b);
        if (a == b) return;
        if (rank[a] < rank[b]) std::swap(a, b);
        parent[b] = a;
        if (rank[a] == rank[b]) ++rank[a];
    }
    void play(int move, Colour player) {
        if (move < 0 || move >= cells || colour[move] != EMPTY || player == EMPTY)
            throw std::logic_error("Illegal simulated move.");
        colour[move] = player;
        const int old_pos = position[move], tail = empty[--empty_count];
        empty[old_pos] = tail; position[tail] = old_pos; position[move] = -1;
        const int x = move / n, y = move % n;
        for (int k = 0; k < 6; ++k) {
            int ax = x + DX[k], ay = y + DY[k];
            if (inside(ax, ay) && colour[ax * n + ay] == player) join(move, ax * n + ay);
        }
        if (player == RED) {
            if (x == 0) join(move, cells);
            if (x == n - 1) join(move, cells + 1);
        } else {
            if (y == 0) join(move, cells + 2);
            if (y == n - 1) join(move, cells + 3);
        }
    }
    bool wins(Colour c) const {
        return c == RED ? find(cells) == find(cells + 1) : find(cells + 2) == find(cells + 3);
    }
    Colour winner() const { return wins(RED) ? RED : (wins(BLUE) ? BLUE : EMPTY); }
};

struct Request {
    Colour player;
    Board board;
    int last_move, turn;
    std::string command;
};
std::vector<std::string> fields(const std::string& input, char separator) {
    std::vector<std::string> result;
    std::size_t first = 0;
    for (;;) {
        const auto next = input.find(separator, first);
        result.push_back(input.substr(first, next == std::string::npos ? next : next - first));
        if (next == std::string::npos) break;
        first = next + 1;
    }
    return result;
}
std::uint64_t unsigned_integer(const std::string& s) {
    if (s.empty() || s.find_first_not_of("0123456789") != std::string::npos)
        throw std::invalid_argument("An unsigned decimal integer was expected.");
    std::size_t end = 0;
    auto value = std::stoull(s, &end);
    if (end != s.size()) throw std::invalid_argument("Invalid integer.");
    return value;
}
int bounded_integer(const std::string& s, int low, int high) {
    auto v = unsigned_integer(s);
    if (v < static_cast<std::uint64_t>(low) || v > static_cast<std::uint64_t>(high))
        throw std::invalid_argument("Integer is outside its allowed range.");
    return static_cast<int>(v);
}
double nonnegative_number(const std::string& s) {
    std::size_t end = 0;
    double value = std::stod(s, &end);
    if (end != s.size() || !std::isfinite(value) || value < 0)
        throw std::invalid_argument("A finite nonnegative number was expected.");
    return value;
}
Request parse_request(std::string line) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    auto parts = fields(line, ';');
    if (parts.size() != 7 || parts[0] != "V2") throw std::invalid_argument("Expected seven V2 protocol fields.");
    if (parts[1] != "R" && parts[1] != "B") throw std::invalid_argument("Current colour must be R or B.");
    const int n = bounded_integer(parts[2], 3, MAX_SIZE);
    if (parts[3] != "START" && parts[3] != "CHANGE" && parts[3] != "SWAP")
        throw std::invalid_argument("Unknown protocol command.");
    int last = -1;
    if (parts[3] == "CHANGE") {
        auto coordinate = fields(parts[4], ',');
        if (coordinate.size() != 2) throw std::invalid_argument("CHANGE requires x,y.");
        last = bounded_integer(coordinate[0], 0, n - 1) * n + bounded_integer(coordinate[1], 0, n - 1);
    } else if (!parts[4].empty()) throw std::invalid_argument("START and SWAP require an empty coordinate field.");
    auto rows = fields(parts[5], ',');
    if (rows.size() != static_cast<std::size_t>(n)) throw std::invalid_argument("Unexpected board row count.");
    Board board(n);
    for (int x = 0; x < n; ++x) {
        if (rows[x].size() != static_cast<std::size_t>(n) || rows[x].find_first_not_of("0RB") != std::string::npos)
            throw std::invalid_argument("Board rows must contain exactly n cells of 0/R/B.");
        for (int y = 0; y < n; ++y)
            if (rows[x][y] != '0') board.play(x * n + y, rows[x][y] == 'R' ? RED : BLUE);
    }
    return {parts[1] == "R" ? RED : BLUE, board, last,
            bounded_integer(parts[6], 1, 1000000), parts[3]};
}

struct Config {
    std::string policy = "rave_ts";
    std::uint64_t seed = 378, iterations = 10000;
    int workers = 1, node_cap = 60000;
    double seconds = 0, game_seconds = 300, memory_mb = 128, rave_k = 300, exploration = std::sqrt(2.0);
    bool bridge = true, ordering = true, swap = true, tactics = true, explicit_iterations = false;
    bool rave() const { return policy == "rave_ucb" || policy == "rave_ts"; }
    bool thompson() const { return policy == "ts" || policy == "rave_ts" || policy == "legacy_ts"; }
};

// A bridge has two friendly endpoints and two common neighbouring carriers.
// If the opponent takes one carrier, defend through the other, unless connected already.
int bridge_save(const Board& board, int last, Colour player) {
    if (last < 0 || board.colour[last] != opposite(player)) return -1;
    static constexpr int patterns[6][6] = {
        {-1, 0, 1, -1, 0, -1}, {-1, 1, 1, 0, 0, 1},
        {0, -1, 1, 0, 1, -1}, {-1, 0, 0, 1, -1, 1},
        {0, -1, -1, 1, -1, 0}, {0, 1, 1, -1, 1, 0}
    };
    auto endpoint = [&](int x, int y) {
        if (board.inside(x, y)) return board.colour[x * board.n + y] == player ? x * board.n + y : -1;
        if (player == RED && y >= 0 && y < board.n) {
            if (x < 0) return board.cells;
            if (x >= board.n) return board.cells + 1;
        }
        if (player == BLUE && x >= 0 && x < board.n) {
            if (y < 0) return board.cells + 2;
            if (y >= board.n) return board.cells + 3;
        }
        return -1;
    };
    const int x = last / board.n, y = last % board.n;
    for (const auto& p : patterns) {
        int sx = x + p[4], sy = y + p[5];
        if (!board.inside(sx, sy) || board.colour[sx * board.n + sy] != EMPTY) continue;
        int a = endpoint(x + p[0], y + p[1]), b = endpoint(x + p[2], y + p[3]);
        if (a >= 0 && b >= 0 && board.find(a) != board.find(b)) return sx * board.n + sy;
    }
    return -1;
}

struct Node {
    int move;
    Colour to_play;
    std::uint64_t visits = 0, wins = 0;  // wins belong to to_play; parent explicitly inverts.
    std::vector<int> children, untried;
    std::vector<std::uint32_t> amaf_visits, amaf_wins; // own-to_play future actions at this node.
    Node(const Board& board, Colour player, int action, const Config& cfg, std::mt19937_64& rng)
        : move(action), to_play(player) {
        if (board.winner() != EMPTY) return;
        children.reserve(board.empty_count);
        untried.assign(board.empty.begin(), board.empty.begin() + board.empty_count);
        if (cfg.rave()) { amaf_visits.assign(board.cells, 0); amaf_wins.assign(board.cells, 0); }
        std::shuffle(untried.begin(), untried.end(), rng);
        if (cfg.ordering) {
            auto priority = [&](int m) {
                const int x = m / board.n, y = m % board.n;
                const double center = (board.n - 1) / 2.0;
                double score = -std::abs(x - center) - std::abs(y - center);
                if (action >= 0) {
                    int dx = x - action / board.n, dy = y - action % board.n;
                    int distance = (std::abs(dx) + std::abs(dy) + std::abs(dx + dy)) / 2;
                    if (distance == 2) score += 4.0;
                }
                for (int k = 0; k < 6; ++k) {
                    int ax = x + DX[k], ay = y + DY[k];
                    if (board.inside(ax, ay) && board.colour[ax * board.n + ay] == player) score += 1.5;
                }
                return score;
            };
            // Stable sorting keeps seed-controlled tie order. The highest priority is popped last.
            std::stable_sort(untried.begin(), untried.end(), [&](int a, int b) { return priority(a) < priority(b); });
        }
    }
};
struct Action { int move; Colour player; };
struct Path { int node; std::size_t start; };

double rave_beta(const Node& node, const Config& cfg) {
    return cfg.rave_k == 0 ? 0 : std::sqrt(cfg.rave_k / (3.0 * node.visits + cfg.rave_k));
}
int select_child(const std::vector<Node>& arena, int parent_id, const Config& cfg, std::mt19937_64& rng) {
    const Node& parent = arena[parent_id];
    int best = -1;
    double best_score = -std::numeric_limits<double>::infinity();
    for (int id : parent.children) {
        const Node& child = arena[id];
        const double successes = static_cast<double>(child.visits - child.wins);
        double score;
        const bool has_amaf = cfg.rave() && parent.amaf_visits[child.move] > 0;
        const double beta = has_amaf ? rave_beta(parent, cfg) : 0;
        if (cfg.thompson()) {
            // The optional same-engine control reproduces only the historical
            // zero-AMAF posterior scaling, not the entire historical executable.
            const double mc_weight = cfg.policy == "legacy_ts" ? child.visits / (1000.0 + child.visits) : 1 - beta;
            const double effective_wins = mc_weight * successes + (has_amaf ? beta * parent.amaf_wins[child.move] : 0);
            const double effective_losses = mc_weight * child.wins +
                (has_amaf ? beta * (parent.amaf_visits[child.move] - parent.amaf_wins[child.move]) : 0);
            std::gamma_distribution<double> a(effective_wins + 1, 1), b(effective_losses + 1, 1);
            double aa = a(rng), bb = b(rng);
            score = aa / (aa + bb);
        } else {
            if (child.visits == 0) score = std::numeric_limits<double>::infinity();
            else {
                double q = successes / child.visits;
                if (has_amaf) q = (1 - beta) * q + beta * parent.amaf_wins[child.move] / parent.amaf_visits[child.move];
                score = q + cfg.exploration * std::sqrt(std::log(static_cast<double>(parent.visits) + 1) / child.visits);
            }
        }
        if (score > best_score) { best_score = score; best = id; }
    }
    if (best < 0) throw std::logic_error("Selection on an empty node.");
    return best;
}
std::uint64_t backpropagate(std::vector<Node>& arena, const std::vector<Path>& path,
                            const std::vector<Action>& history, Colour winner, bool use_amaf) {
    std::uint64_t updates = 0;
    for (const auto& entry : path) {
        Node& node = arena[entry.node];
        ++node.visits;
        if (winner == node.to_play) ++node.wins;
        if (use_amaf) {
            // Hex is placement-only: an action occurs at most once in a continuation.
            // Selected tree actions belong in each ancestor's suffix, not just rollout moves.
            for (std::size_t i = entry.start; i < history.size(); ++i) {
                if (history[i].player != node.to_play) continue;
                const int move = history[i].move;
                ++node.amaf_visits[move];
                if (winner == node.to_play) ++node.amaf_wins[move];
                ++updates;
            }
        }
    }
    return updates;
}

struct WorkerResult {
    int id = 0;
    std::uint64_t seed = 0, iterations = 0, rave_updates = 0;
    int nodes = 0;
    double seconds = 0;
    bool cap_reached = false;
    std::array<std::uint64_t, MAX_CELLS> visits{}, wins{};
};
WorkerResult search_worker(const Request& req, const Config& cfg, int worker, std::uint64_t count,
                           int node_cap, Clock::time_point deadline) {
    const auto begin = Clock::now();
    std::uint64_t position_hash = mixed(static_cast<std::uint64_t>(req.board.n));
    for (int m = 0; m < req.board.cells; ++m)
        position_hash = mixed(position_hash ^ (static_cast<std::uint64_t>(req.board.colour[m] + 1) * (m + 1)));
    WorkerResult result;
    result.id = worker;
    result.seed = mixed(cfg.seed ^ position_hash ^ mixed(static_cast<std::uint64_t>(req.turn)) ^
                        mixed(worker + 1) ^ mixed(static_cast<std::uint64_t>(req.player) + 123));
    std::mt19937_64 rng(result.seed);
    std::vector<Node> arena;
    arena.reserve(node_cap);
    arena.emplace_back(req.board, req.player, req.last_move, cfg, rng);
    std::vector<Action> history;
    std::vector<Path> path;
    history.reserve(req.board.cells); path.reserve(req.board.cells + 1);
    for (std::uint64_t iteration = 0; iteration < count; ++iteration) {
        // Every iteration checks the shared monotonic deadline. Completed simulations only are recorded.
        if (Clock::now() >= deadline) break;
        Board board = req.board;
        history.clear(); path.clear(); path.push_back({0, 0});
        int current = 0;
        Colour winner = board.winner();
        while (winner == EMPTY) {
            Node& node = arena[current];
            if (!node.untried.empty() && arena.size() < static_cast<std::size_t>(node_cap)) {
                const int move = node.untried.back(); node.untried.pop_back();
                const Colour player = node.to_play;
                board.play(move, player); history.push_back({move, player});
                const int child = static_cast<int>(arena.size());
                node.children.push_back(child);
                arena.emplace_back(board, opposite(player), move, cfg, rng);
                current = child; path.push_back({current, history.size()});
                winner = board.winner();
                break;
            }
            if (!node.untried.empty()) result.cap_reached = true;
            if (node.children.empty()) break;
            int child = select_child(arena, current, cfg, rng);
            const Colour player = node.to_play;
            board.play(arena[child].move, player); history.push_back({arena[child].move, player});
            current = child; path.push_back({current, history.size()});
            winner = board.winner();
        }
        Colour player = arena[current].to_play;
        int last_move = history.empty() ? req.last_move : history.back().move;
        while (winner == EMPTY && board.empty_count > 0) {
            int move = cfg.bridge ? bridge_save(board, last_move, player) : -1;
            if (move < 0) move = board.empty[std::uniform_int_distribution<int>(0, board.empty_count - 1)(rng)];
            board.play(move, player); history.push_back({move, player});
            winner = board.winner(); last_move = move; player = opposite(player);
        }
        if (winner == EMPTY) throw std::logic_error("A full Hex board must have a winner.");
        result.rave_updates += backpropagate(arena, path, history, winner, cfg.rave());
        ++result.iterations;
    }
    result.nodes = static_cast<int>(arena.size());
    result.cap_reached = result.cap_reached || result.nodes >= node_cap;
    for (int child : arena[0].children) {
        const Node& node = arena[child];
        result.visits[node.move] = node.visits;
        result.wins[node.move] = node.visits - node.wins;
    }
    result.seconds = elapsed(begin);
    return result;
}

struct Decision {
    int move = -1;
    std::string reason;
    std::uint64_t iterations = 0, rave_updates = 0, chosen_visits = 0, chosen_wins = 0;
    int nodes = 0, effective_node_cap = 0;
    double seconds = 0;
    std::vector<WorkerResult> workers;
};
int tactical(const Board& board, Colour player) {
    for (int move = 0; move < board.cells; ++move) {
        if (board.colour[move] != EMPTY) continue;
        Board next = board; next.play(move, player);
        if (next.wins(player)) return move;
    }
    return -1;
}
Decision decide(const Request& req, const Config& cfg, double already_used) {
    const auto begin = Clock::now();
    if (req.board.winner() != EMPTY) throw std::invalid_argument("Terminal board: no move is legal after the game ends.");
    if (req.board.empty_count == 0) throw std::invalid_argument("Full board: no legal move remains.");
    Decision result;
    if (cfg.swap && req.turn == 2 && req.player == BLUE && req.board.empty_count == req.board.cells - 1 && req.last_move >= 0) {
        int dx = req.last_move / req.board.n - req.board.n / 2;
        int dy = req.last_move % req.board.n - req.board.n / 2;
        if ((std::abs(dx) + std::abs(dy) + std::abs(dx + dy)) / 2 <= 3) {
            result.reason = "pie_rule_swap"; result.seconds = elapsed(begin); return result;
        }
    }
    if (cfg.tactics) {
        result.move = tactical(req.board, req.player);
        if (result.move >= 0) { result.reason = "tactical_win"; result.seconds = elapsed(begin); return result; }
        result.move = tactical(req.board, opposite(req.player));
        if (result.move >= 0) { result.reason = "tactical_block"; result.seconds = elapsed(begin); return result; }
    }
    double remaining = std::max(0.0, cfg.game_seconds - already_used);
    double allowance = cfg.seconds > 0 ? std::min(cfg.seconds, remaining) : remaining;
    // Reserve a small part of a finite wall-clock budget for aggregation and serialization.
    const double margin = std::min(0.010, allowance * 0.05);
    auto deadline = begin + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(std::max(0.0, allowance - margin)));
    const std::size_t per_node_bound = sizeof(Node) + req.board.cells * (2 * sizeof(int) +
        (cfg.rave() ? 2 * sizeof(std::uint32_t) : 0)) + 128;
    int memory_nodes = static_cast<int>(std::min(1000000.0, cfg.memory_mb * 1024 * 1024 / per_node_bound));
    result.effective_node_cap = std::max(cfg.workers, std::min(cfg.node_cap, memory_nodes));
    result.workers.resize(cfg.workers);
    std::vector<std::thread> threads;
    std::vector<std::exception_ptr> failures(cfg.workers);
    threads.reserve(cfg.workers);
    try {
        for (int worker = 0; worker < cfg.workers; ++worker) {
            const std::uint64_t count = cfg.iterations / cfg.workers + (static_cast<std::uint64_t>(worker) < cfg.iterations % cfg.workers ? 1 : 0);
            const int cap = result.effective_node_cap / cfg.workers + (worker < result.effective_node_cap % cfg.workers ? 1 : 0);
            threads.emplace_back([&, worker, count, cap] {
                try { result.workers[worker] = search_worker(req, cfg, worker, count, cap, deadline); }
                catch (...) { failures[worker] = std::current_exception(); }
            });
        }
    } catch (...) { for (auto& t : threads) if (t.joinable()) t.join(); throw; }
    for (auto& t : threads) t.join();
    for (const auto& failure : failures) if (failure) std::rethrow_exception(failure);
    std::array<std::uint64_t, MAX_CELLS> visits{}, wins{};
    for (const auto& worker : result.workers) {
        result.iterations += worker.iterations; result.nodes += worker.nodes; result.rave_updates += worker.rave_updates;
        for (int move = 0; move < req.board.cells; ++move) { visits[move] += worker.visits[move]; wins[move] += worker.wins[move]; }
    }
    result.move = -1;
    for (int move = 0; move < req.board.cells; ++move) {
        if (req.board.colour[move] != EMPTY) continue;
        if (result.move < 0 || visits[move] > visits[result.move] ||
            (visits[move] == visits[result.move] && wins[move] > wins[result.move])) result.move = move;
    }
    if (result.move < 0) throw std::logic_error("Search did not produce a legal action.");
    result.chosen_visits = visits[result.move]; result.chosen_wins = wins[result.move];
    result.reason = result.iterations == 0 ? "budget_exhausted_fallback" :
        (result.chosen_visits == 0 ? "node_cap_fallback" : "search");
    result.seconds = elapsed(begin);
    return result;
}

std::string json_quote(const std::string& value) {
    std::ostringstream out; out << '"';
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(c) << std::dec;
        else out << c;
    }
    out << '"'; return out.str();
}
void diagnostics(const Request& req, const Config& cfg, const Decision& d, double game_used) {
    std::cerr << std::setprecision(10) << "{\"kind\":\"hex_search_move\",\"version\":\"1.0.0\",\"policy\":" << json_quote(cfg.policy)
              << ",\"turn\":" << req.turn << ",\"colour\":\"" << (req.player == RED ? 'R' : 'B')
              << "\",\"seed\":" << cfg.seed << ",\"move\":[" << (d.move < 0 ? -1 : d.move / req.board.n)
              << ',' << (d.move < 0 ? -1 : d.move % req.board.n) << "],\"reason\":" << json_quote(d.reason)
              << ",\"iterations\":" << d.iterations << ",\"nodes\":" << d.nodes << ",\"rave_updates\":" << d.rave_updates
              << ",\"seconds\":" << d.seconds << ",\"game_seconds_used\":" << game_used
              << ",\"node_cap\":" << d.effective_node_cap << ",\"chosen_visits\":" << d.chosen_visits
              << ",\"chosen_wins\":" << d.chosen_wins << ",\"workers\":[";
    bool first = true;
    for (const auto& w : d.workers) {
        if (!first) std::cerr << ',';
        first = false;
        std::cerr << "{\"id\":" << w.id << ",\"seed\":" << w.seed << ",\"iterations\":" << w.iterations
                  << ",\"nodes\":" << w.nodes << ",\"rave_updates\":" << w.rave_updates << ",\"seconds\":" << w.seconds
                  << ",\"node_cap_reached\":" << (w.cap_reached ? "true" : "false") << '}';
    }
    std::cerr << "]}" << std::endl;
}

bool oracle_win(const Board& board, Colour player) {
    std::array<bool, MAX_CELLS> seen{};
    std::queue<int> queue;
    for (int a = 0; a < board.n; ++a) {
        int move = player == RED ? a : a * board.n;
        if (board.colour[move] == player) { queue.push(move); seen[move] = true; }
    }
    while (!queue.empty()) {
        int move = queue.front(); queue.pop();
        int x = move / board.n, y = move % board.n;
        if ((player == RED && x == board.n - 1) || (player == BLUE && y == board.n - 1)) return true;
        for (int k = 0; k < 6; ++k) {
            int ax = x + DX[k], ay = y + DY[k], next = ax * board.n + ay;
            if (board.inside(ax, ay) && !seen[next] && board.colour[next] == player) { seen[next] = true; queue.push(next); }
        }
    }
    return false;
}
void require(bool value, const std::string& message) { if (!value) throw std::logic_error("Self-test: " + message); }
void self_test() {
    int checks = 0;
    // All 3^9 colourings compare union-find against an independent graph traversal.
    for (int encoded = 0; encoded < 19683; ++encoded) {
        Board board(3); int value = encoded;
        for (int move = 0; move < 9; ++move) { int colour = value % 3; value /= 3; if (colour != 2) board.play(move, static_cast<Colour>(colour)); }
        require(board.wins(RED) == oracle_win(board, RED), "red connectivity oracle");
        require(board.wins(BLUE) == oracle_win(board, BLUE), "blue connectivity oracle");
    }
    ++checks;
    Config cfg; cfg.ordering = false; cfg.swap = false;
    std::mt19937_64 rng(42);
    std::vector<Node> arena;
    Board empty(3); arena.emplace_back(empty, RED, -1, cfg, rng);
    Board after = empty; after.play(0, RED); arena.emplace_back(after, BLUE, 0, cfg, rng);
    std::vector<Path> path{{0, 0}, {1, 1}};
    std::vector<Action> history{{0, RED}, {1, BLUE}, {2, RED}, {3, BLUE}};
    require(backpropagate(arena, path, history, BLUE, true) == 4, "AMAF update count");
    require(arena[0].amaf_visits[0] == 1 && arena[0].amaf_visits[2] == 1 && arena[0].amaf_visits[1] == 0, "AMAF same-player suffix");
    require(arena[0].amaf_wins[0] == 0 && arena[1].amaf_wins[1] == 1 && arena[1].amaf_wins[3] == 1, "AMAF winner perspective");
    require(arena[0].wins == 0 && arena[1].wins == 1, "node-to-play reward perspective"); ++checks;
    Config ucb = cfg; ucb.policy = "ucb"; ucb.exploration = 0;
    arena.clear(); arena.reserve(3);
    arena.emplace_back(empty, RED, -1, ucb, rng);
    arena.emplace_back(after, BLUE, 0, ucb, rng);
    Board other = empty; other.play(1, RED); arena.emplace_back(other, BLUE, 1, ucb, rng);
    arena[0].children = {1, 2}; arena[0].visits = 20;
    arena[1].visits = arena[2].visits = 10; arena[1].wins = 10; arena[2].wins = 0;
    require(select_child(arena, 0, ucb, rng) == 2, "parent must invert child's rewards");
    arena[0].to_play = BLUE; arena[1].to_play = arena[2].to_play = RED;
    require(select_child(arena, 0, ucb, rng) == 2, "opponent also maximizes its own reward"); ++checks;
    Board win(3); win.play(0, RED); win.play(3, RED);
    require(tactical(win, RED) == 6, "immediate winning move"); ++checks;
    Request winning{RED, win, -1, 5, "CHANGE"};
    require(decide(winning, cfg, 0).reason == "tactical_win", "root tactical win");
    winning.player = BLUE; require(decide(winning, cfg, 0).move == 6, "root tactical block"); ++checks;
    win.play(6, RED); bool terminal_rejected = false;
    try { decide({BLUE, win, 6, 6, "CHANGE"}, cfg, 0); } catch (const std::invalid_argument&) { terminal_rejected = true; }
    require(terminal_rejected, "terminal board must not expand or return a move"); ++checks;
    Board bridge(5); bridge.play(1 * 5 + 2, RED); bridge.play(3 * 5 + 1, RED); bridge.play(2 * 5 + 2, BLUE);
    require(bridge_save(bridge, 2 * 5 + 2, RED) == 2 * 5 + 1, "interior bridge save"); ++checks;
    Board wall(5); wall.play(1 * 5 + 1, RED); wall.play(0 * 5 + 2, BLUE);
    require(bridge_save(wall, 2, RED) == 1, "goal-edge bridge save"); ++checks;
    for (const std::string policy : {"ucb", "ts", "rave_ucb", "rave_ts"}) {
        cfg.policy = policy; cfg.workers = 3; cfg.iterations = 301; cfg.tactics = false; cfg.node_cap = 2000;
        Request req{RED, Board(5), -1, 1, "START"};
        auto first = decide(req, cfg, 0), second = decide(req, cfg, 0);
        require(first.iterations == 301 && first.workers[0].iterations == 101 && first.workers[1].iterations == 100, "total worker iteration split");
        require(first.move == second.move && first.chosen_visits == second.chosen_visits && first.chosen_wins == second.chosen_wins, "fixed-seed repeatability");
        require((first.rave_updates > 0) == cfg.rave(), "RAVE enabled counters must update");
        for (int i = 0; i < 3; ++i) require(first.workers[i].seed == second.workers[i].seed && first.workers[i].rave_updates == second.workers[i].rave_updates, "worker repeatability");
    }
    ++checks;
    cfg.node_cap = 3; cfg.iterations = 100; cfg.workers = 1;
    auto capped = decide({RED, Board(5), -1, 1, "START"}, cfg, 0);
    require(capped.nodes <= 3 && capped.workers[0].cap_reached && capped.iterations == 100, "node cap bounds allocation without cancelling rollouts"); ++checks;
    cfg.node_cap = 1;
    auto root_only = decide({RED, Board(5), -1, 1, "START"}, cfg, 0);
    require(root_only.nodes == 1 && root_only.reason == "node_cap_fallback", "root-only cap must be labelled as fallback");
    cfg.node_cap = 3;
    cfg.seconds = 0.005; cfg.iterations = 10000000;
    auto timed = decide({RED, Board(11), -1, 1, "START"}, cfg, 0);
    require(timed.seconds < 1 && timed.iterations < cfg.iterations, "monotonic deadline completes promptly"); ++checks;
    auto exhausted = decide({RED, Board(11), -1, 1, "START"}, cfg, cfg.game_seconds);
    require(exhausted.iterations == 0 && exhausted.reason == "budget_exhausted_fallback", "game budget exhaustion"); ++checks;
    auto parsed = parse_request("V2;B;3;SWAP;;000,000,000;3\r");
    require(parsed.player == BLUE && parsed.last_move == -1 && parsed.turn == 3, "explicit swap colour");
    bool malformed_rejected = false;
    try { parse_request("V2;R;3;START;;000,000,000,;1"); } catch (const std::exception&) { malformed_rejected = true; }
    require(malformed_rejected, "malformed board rejection"); ++checks;
    std::cout << "{\"kind\":\"hex_search_self_test\",\"status\":\"passed\",\"checks\":" << checks
              << ",\"exhaustive_connectivity_positions\":19683}" << std::endl;
}

Config arguments(int argc, char** argv) {
    Config cfg;
    int first = 1;
    if (argc >= 3 && (std::string(argv[1]) == "R" || std::string(argv[1]) == "B")) {
        bounded_integer(argv[2], 3, MAX_SIZE); first = 3;
    }
    for (int i = first; i < argc; ++i) {
        std::string key = argv[i];
        if (i + 1 >= argc) throw std::invalid_argument("Option requires a value: " + key);
        std::string value = argv[++i];
        if (key == "--policy") {
            if (value != "ucb" && value != "ts" && value != "rave_ucb" && value != "rave_ts" && value != "legacy_ts")
                throw std::invalid_argument("Unknown search policy.");
            cfg.policy = value;
        } else if (key == "--seed") cfg.seed = unsigned_integer(value);
        else if (key == "--workers") cfg.workers = bounded_integer(value, 1, 64);
        else if (key == "--iterations") { cfg.iterations = unsigned_integer(value); cfg.explicit_iterations = true; }
        else if (key == "--seconds") cfg.seconds = nonnegative_number(value);
        else if (key == "--game-seconds") cfg.game_seconds = nonnegative_number(value);
        else if (key == "--memory-mb") cfg.memory_mb = nonnegative_number(value);
        else if (key == "--node-cap") cfg.node_cap = bounded_integer(value, 1, 1000000);
        else if (key == "--rave-k") cfg.rave_k = nonnegative_number(value);
        else if (key == "--bridge") cfg.bridge = bounded_integer(value, 0, 1) != 0;
        else if (key == "--ordering") cfg.ordering = bounded_integer(value, 0, 1) != 0;
        else if (key == "--swap") cfg.swap = bounded_integer(value, 0, 1) != 0;
        else if (key == "--tactics") cfg.tactics = bounded_integer(value, 0, 1) != 0;
        else throw std::invalid_argument("Unknown option: " + key);
    }
    if (cfg.iterations == 0 || cfg.iterations > 1000000000ULL) throw std::invalid_argument("Iteration limit must be 1 through 1000000000.");
    if (cfg.node_cap < cfg.workers) throw std::invalid_argument("Node cap must allow at least one root per worker.");
    if (cfg.memory_mb < 1 || cfg.memory_mb > 4096) throw std::invalid_argument("Memory allowance must be 1 through 4096 MiB.");
    if (cfg.seconds > 0 && !cfg.explicit_iterations) cfg.iterations = 1000000000ULL;
    return cfg;
}
} // namespace hex

int main(int argc, char** argv) {
    std::locale::global(std::locale::classic());
    try {
        if (argc == 2 && std::string(argv[1]) == "--version") { std::cout << "hex-search 1.0.0 C++17\n"; return 0; }
        if (argc == 2 && std::string(argv[1]) == "--self-test") { hex::self_test(); return 0; }
        if (argc == 2 && std::string(argv[1]) == "--help") {
            std::cout << "Usage: hex-search [R|B BOARD_SIZE] [options]\n"
                "Reads V2;R|B;n;START|CHANGE|SWAP;x,y-or-empty;board-rows;turn from stdin.\n"
                "Options: --policy ucb|ts|rave_ucb|rave_ts|legacy_ts --seed UINT --workers 1..64\n"
                " --iterations TOTAL --seconds SEC --game-seconds SEC --node-cap TOTAL\n"
                " --memory-mb MIB --rave-k NUMBER --bridge 0|1 --ordering 0|1\n"
                " --swap 0|1 --tactics 0|1\n"
                "Default: rave_ts, seed378, 1worker, 10000iterations, game300seconds.\n"
                "--seconds without --iterations selects deadline mode. If both are supplied,\n"
                "the first reached limit stops search. stdout is x,y; stderr is JSON telemetry.\n"
                "Use --self-test for exhaustive connectivity and search invariant checks.\n";
            return 0;
        }
        auto cfg = hex::arguments(argc, argv);
        double game_used = 0;
        int last_turn = 0;
        std::string line;
        while (std::getline(std::cin, line)) {
            if (line.empty()) continue;
            const auto request_start = hex::Clock::now();
            auto request = hex::parse_request(line);
            if (request.command == "START" || request.turn <= last_turn) game_used = 0;
            const double parse_seconds = hex::elapsed(request_start);
            auto result = hex::decide(request, cfg, game_used + parse_seconds);
            result.seconds = hex::elapsed(request_start);
            game_used += result.seconds; last_turn = request.turn;
            std::cout << (result.move < 0 ? -1 : result.move / request.board.n) << ','
                      << (result.move < 0 ? -1 : result.move % request.board.n) << std::endl;
            hex::diagnostics(request, cfg, result, game_used);
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "{\"kind\":\"hex_search_error\",\"error\":" << hex::json_quote(error.what()) << '}' << std::endl;
        return 2;
    }
}
