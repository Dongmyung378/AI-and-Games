// Hex-Search v1.2.0: Zero-Dependency Pure-CPU C++17 Hex AI Engine.
// Standard-library C++17 only; compact flat arena, lazy expansion, GRAVE, LGRF-2,
// proven dead-cell pruning, fast inline Beta/Gamma sampling, and subtree reuse.
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <memory>
#include <numeric>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace hex {
using Clock = std::chrono::steady_clock;
constexpr int MAX_SIZE = 19, MAX_CELLS = MAX_SIZE * MAX_SIZE;
// Clockwise cyclic 6-neighbour offsets on the Hex grid.
constexpr int RING_DX[6] = {-1, -1, 0, 1, 1, 0};
constexpr int RING_DY[6] = {0, 1, 1, 0, -1, -1};
constexpr int16_t RING_RED_EDGE = -1;
constexpr int16_t RING_BLUE_EDGE = -2;
constexpr int16_t RING_CORNER = -3;
constexpr int16_t BRIDGE_EDGE_START = -1;
constexpr int16_t BRIDGE_EDGE_END = -2;

enum Colour : std::uint8_t { RED = 0, BLUE = 1, EMPTY = 2 };
inline Colour opposite(Colour c) { return c == RED ? BLUE : RED; }

inline double elapsed(Clock::time_point begin) {
    return std::chrono::duration<double>(Clock::now() - begin).count();
}
inline std::uint64_t mixed(std::uint64_t x) {
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}

// Fast, high-quality deterministic PRNG (xoshiro256**) with cached normal and exact
// inline Marsaglia-Tsang Gamma / Beta sampling.
struct FastRng {
    std::uint64_t s[4]{};
    bool has_spare = false;
    double spare = 0.0;

    explicit FastRng(std::uint64_t seed = 378) { reseed(seed); }
    void reseed(std::uint64_t seed) {
        for (int i = 0; i < 4; ++i) {
            seed = mixed(seed);
            s[i] = seed;
        }
        has_spare = false;
        spare = 0.0;
    }
    static inline std::uint64_t rotl(const std::uint64_t x, int k) {
        return (x << k) | (x >> (64 - k));
    }
    inline std::uint64_t next_u64() {
        const std::uint64_t result = rotl(s[1] * 5, 7) * 9;
        const std::uint64_t t = s[1] << 17;
        s[2] ^= s[0];
        s[3] ^= s[1];
        s[1] ^= s[2];
        s[0] ^= s[3];
        s[2] ^= t;
        s[3] = rotl(s[3], 45);
        return result;
    }
    // Uniform double in (0, 1).
    inline double next_uniform() {
        return (static_cast<double>(next_u64() >> 11) + 0.5) * (1.0 / 9007199254740992.0);
    }
    // Division-free fast bounded integer in [0, range).
    inline int next_bounded(int range) {
        const std::uint64_t r = static_cast<std::uint64_t>(static_cast<std::uint32_t>(next_u64()));
        return static_cast<int>((r * static_cast<std::uint64_t>(range)) >> 32);
    }
    inline double next_normal() {
        if (has_spare) {
            has_spare = false;
            return spare;
        }
        double u, v, s2;
        do {
            u = 2.0 * next_uniform() - 1.0;
            v = 2.0 * next_uniform() - 1.0;
            s2 = u * u + v * v;
        } while (s2 >= 1.0 || s2 == 0.0);
        const double factor = std::sqrt(-2.0 * std::log(s2) / s2);
        spare = v * factor;
        has_spare = true;
        return u * factor;
    }
    // Exact Marsaglia-Tsang Gamma(shape, 1) sampler for shape > 0.
    inline double sample_gamma(double shape) {
        if (shape < 1.0) {
            const double u = next_uniform();
            return sample_gamma(shape + 1.0) * std::pow(u, 1.0 / shape);
        }
        const double d = shape - 1.0 / 3.0;
        const double c = 1.0 / std::sqrt(9.0 * d);
        for (;;) {
            double x, v;
            do {
                x = next_normal();
                v = 1.0 + c * x;
            } while (v <= 0.0);
            v = v * v * v;
            const double u = next_uniform();
            const double x2 = x * x;
            if (u < 1.0 - 0.0331 * x2 * x2) return d * v;
            if (std::log(u) < 0.5 * x2 + d * (1.0 - v + std::log(v))) return d * v;
        }
    }
    inline double sample_beta(double alpha, double beta_p) {
        // For high-concentration posteriors (alpha >= 16 and beta >= 16), moment-matched
        // Gaussian sampling uses 1/2 a Box-Muller draw with exact normal tails and <2e-3 skew error.
        if (alpha >= 16.0 && beta_p >= 16.0) {
            const double total = alpha + beta_p;
            const double mean = alpha / total;
            const double sd = std::sqrt((alpha * beta_p) / (total * total * (total + 1.0)));
            const double x = mean + sd * next_normal();
            return x <= 0.0 ? 1e-9 : (x >= 1.0 ? 1.0 - 1e-9 : x);
        }
        const double ga = sample_gamma(alpha);
        const double gb = sample_gamma(beta_p);
        const double denom = ga + gb;
        return denom > 0.0 ? ga / denom : 0.5;
    }
};

struct BridgeCheck {
    std::int16_t ep1;
    std::int16_t ep2;
    std::int16_t save;
};

struct BoardTopology {
    int n = 0, cells = 0;
    std::array<std::uint8_t, MAX_CELLS> deg{};
    std::array<std::array<std::int16_t, 6>, MAX_CELLS> neighbors{};
    std::array<std::array<std::int16_t, 6>, MAX_CELLS> ring6{};
    std::array<std::array<std::uint8_t, MAX_CELLS>, 2> edge_mask{};
    std::array<std::array<std::uint8_t, MAX_CELLS>, 2> bridge_count{};
    std::array<std::array<std::array<BridgeCheck, 6>, MAX_CELLS>, 2> bridges{};
    std::array<double, MAX_CELLS> center_score{};

    static const BoardTopology& get(int size) {
        static std::array<BoardTopology, MAX_SIZE + 1> cache;
        static std::array<bool, MAX_SIZE + 1> ready{};
        if (!ready[size]) {
            BoardTopology t;
            t.init(size);
            cache[size] = t;
            ready[size] = true;
        }
        return cache[size];
    }

    void init(int size) {
        n = size;
        cells = size * size;
        const double center = (n - 1) / 2.0;
        for (int x = 0; x < n; ++x) {
            for (int y = 0; y < n; ++y) {
                const int m = x * n + y;
                deg[m] = 0;
                edge_mask[RED][m] = static_cast<std::uint8_t>((x == 0 ? 1 : 0) | (x == n - 1 ? 2 : 0));
                edge_mask[BLUE][m] = static_cast<std::uint8_t>((y == 0 ? 1 : 0) | (y == n - 1 ? 2 : 0));
                center_score[m] = -std::abs(x - center) - std::abs(y - center);
                for (int d = 0; d < 6; ++d) {
                    const int ax = x + RING_DX[d], ay = y + RING_DY[d];
                    if (ax >= 0 && ax < n && ay >= 0 && ay < n) {
                        const auto nb = static_cast<std::int16_t>(ax * n + ay);
                        neighbors[m][deg[m]++] = nb;
                        ring6[m][d] = nb;
                    } else if (ax < 0 && ay >= 0 && ay < n) {
                        ring6[m][d] = RING_RED_EDGE;
                    } else if (ax >= n && ay >= 0 && ay < n) {
                        ring6[m][d] = RING_RED_EDGE;
                    } else if (ay < 0 && ax >= 0 && ax < n) {
                        ring6[m][d] = RING_BLUE_EDGE;
                    } else if (ay >= n && ax >= 0 && ax < n) {
                        ring6[m][d] = RING_BLUE_EDGE;
                    } else {
                        ring6[m][d] = RING_CORNER;
                    }
                }
                // Precompute exact bridge-save checks for both defenders when opponent plays m.
                for (int p = 0; p < 2; ++p) {
                    bridge_count[p][m] = 0;
                    const Colour player = static_cast<Colour>(p);
                    auto endpoint_code = [&](int ex, int ey) -> std::int16_t {
                        if (ex >= 0 && ex < n && ey >= 0 && ey < n) return static_cast<std::int16_t>(ex * n + ey);
                        if (player == RED && ey >= 0 && ey < n) {
                            if (ex < 0) return BRIDGE_EDGE_START;
                            if (ex >= n) return BRIDGE_EDGE_END;
                        }
                        if (player == BLUE && ex >= 0 && ex < n) {
                            if (ey < 0) return BRIDGE_EDGE_START;
                            if (ey >= n) return BRIDGE_EDGE_END;
                        }
                        return RING_CORNER;
                    };
                    for (int d = 0; d < 6; ++d) {
                        const int sx = x + RING_DX[d], sy = y + RING_DY[d];
                        if (sx < 0 || sx >= n || sy < 0 || sy >= n) continue;
                        const int d1 = (d + 5) % 6, d2 = (d + 1) % 6;
                        const std::int16_t ep1 = endpoint_code(x + RING_DX[d1], y + RING_DY[d1]);
                        const std::int16_t ep2 = endpoint_code(x + RING_DX[d2], y + RING_DY[d2]);
                        if (ep1 != RING_CORNER && ep2 != RING_CORNER) {
                            bridges[p][m][bridge_count[p][m]++] = {ep1, ep2, static_cast<std::int16_t>(sx * n + sy)};
                        }
                    }
                }
            }
        }
    }
};

// Compact, L1-cache-friendly Hex board using edge-reach bitmask Union-Find.
struct Board {
    int n = 11, cells = 121, empty_count = 121;
    std::uint8_t won_mask = 0; // bit0: RED connected, bit1: BLUE connected
    const BoardTopology* topo = nullptr;
    std::array<std::int16_t, MAX_CELLS> parent{};
    std::array<std::uint8_t, MAX_CELLS> rank{};
    std::array<std::uint8_t, MAX_CELLS> edge_flags{};
    std::array<Colour, MAX_CELLS> colour{};
    std::array<std::int16_t, MAX_CELLS> empty{};
    std::array<std::int16_t, MAX_CELLS> position{};

    explicit Board(int size = 11) : n(size), cells(size * size), empty_count(cells), won_mask(0) {
        if (size < 3 || size > MAX_SIZE) throw std::invalid_argument("Board size must be 3 through 19.");
        topo = &BoardTopology::get(size);
        for (int i = 0; i < cells; ++i) {
            parent[i] = static_cast<std::int16_t>(i);
            rank[i] = 0;
            edge_flags[i] = 0;
            colour[i] = EMPTY;
            empty[i] = static_cast<std::int16_t>(i);
            position[i] = static_cast<std::int16_t>(i);
        }
    }
    // Fast copy of only the active n*n prefix (avoids touching unused MAX_CELLS tail).
    inline void copy_from(const Board& src) {
        n = src.n;
        cells = src.cells;
        empty_count = src.empty_count;
        won_mask = src.won_mask;
        topo = src.topo;
        const std::size_t c = static_cast<std::size_t>(cells);
        std::memcpy(parent.data(), src.parent.data(), c * sizeof(std::int16_t));
        std::memcpy(rank.data(), src.rank.data(), c * sizeof(std::uint8_t));
        std::memcpy(edge_flags.data(), src.edge_flags.data(), c * sizeof(std::uint8_t));
        std::memcpy(colour.data(), src.colour.data(), c * sizeof(Colour));
        std::memcpy(empty.data(), src.empty.data(), static_cast<std::size_t>(empty_count) * sizeof(std::int16_t));
        std::memcpy(position.data(), src.position.data(), c * sizeof(std::int16_t));
    }
    inline bool inside(int x, int y) const { return x >= 0 && x < n && y >= 0 && y < n; }
    inline int find(int a) const {
        while (a != parent[a]) a = parent[a];
        return a;
    }
    inline int compressed_find(int a) {
        while (a != parent[a]) {
            parent[a] = parent[parent[a]];
            a = parent[a];
        }
        return a;
    }
    inline int join(int a, int b) {
        a = compressed_find(a);
        b = compressed_find(b);
        if (a == b) return a;
        if (rank[a] < rank[b]) std::swap(a, b);
        parent[b] = static_cast<std::int16_t>(a);
        edge_flags[a] |= edge_flags[b];
        if (rank[a] == rank[b]) ++rank[a];
        return a;
    }
    inline void play(int move, Colour player) {
        if (move < 0 || move >= cells || colour[move] != EMPTY || player == EMPTY)
            throw std::logic_error("Illegal simulated move.");
        play_unchecked(move, player);
    }
    inline void play_unchecked(int move, Colour player) {
        colour[move] = player;
        const int old_pos = position[move];
        const std::int16_t tail = empty[--empty_count];
        empty[old_pos] = tail;
        position[tail] = static_cast<std::int16_t>(old_pos);
        position[move] = -1;
        edge_flags[move] = topo->edge_mask[player][move];
        int root = move;
        const auto deg = topo->deg[move];
        const auto& nbs = topo->neighbors[move];
        for (int k = 0; k < deg; ++k) {
            const int nb = nbs[k];
            if (colour[nb] == player) root = join(root, nb);
        }
        if (edge_flags[root] == 3) won_mask |= static_cast<std::uint8_t>(1U << player);
    }
    inline bool wins(Colour c) const { return (won_mask & (1U << c)) != 0; }
    inline Colour winner() const {
        return (won_mask & 1U) ? RED : ((won_mask & 2U) ? BLUE : EMPTY);
    }
    bool same_stones(const Board& other) const {
        return n == other.n && std::memcmp(colour.data(), other.colour.data(), static_cast<std::size_t>(cells)) == 0;
    }
};

// Proven 1-cell local dead-cell detector (Bjornsson et al. / MoHex inferior cell analysis).
// A cell is dead if its colour can never alter the winner of any continuation:
//   (1) 4 consecutive neighbours of the same colour on the cyclic 6-ring, or
//   (2) 3 consecutive neighbours of colour C adjacent to 2 consecutive neighbours of opposite colour O.
// Acute-corner exterior gaps (RING_CORNER) are conservatively treated as EMPTY (zero false positives).
inline bool is_dead_cell(const Board& board, int cell) {
    if (board.colour[cell] != EMPTY) return false;
    const auto& ring = board.topo->ring6[cell];
    std::uint8_t r[12];
    for (int i = 0; i < 6; ++i) {
        const std::int16_t nb = ring[i];
        std::uint8_t col;
        if (nb >= 0) col = static_cast<std::uint8_t>(board.colour[nb]);
        else if (nb == RING_RED_EDGE) col = RED;
        else if (nb == RING_BLUE_EDGE) col = BLUE;
        else col = EMPTY;
        r[i] = col;
        r[i + 6] = col;
    }
    for (int i = 0; i < 6; ++i) {
        const std::uint8_t c = r[i];
        if (c == EMPTY) continue;
        if (r[i + 1] == c && r[i + 2] == c) {
            if (r[i + 3] == c) return true; // 4 consecutive same colour
            const std::uint8_t o = static_cast<std::uint8_t>(c ^ 1U);
            if (r[i + 3] == o && r[i + 4] == o) return true; // C,C,C,O,O,*
            if (r[i + 4] == o && r[i + 5] == o) return true; // C,C,C,*,O,O
        }
    }
    return false;
}

// Fast O(1)-table bridge-save check in rollouts.
inline int bridge_save(const Board& board, int last, Colour player) {
    if (last < 0 || board.colour[last] != opposite(player)) return -1;
    const auto count = board.topo->bridge_count[player][last];
    const auto& checks = board.topo->bridges[player][last];
    for (int i = 0; i < count; ++i) {
        const auto& b = checks[i];
        if (board.colour[b.save] != EMPTY) continue;
        // Check endpoint 1 and endpoint 2 belong to player and are not already connected.
        if (b.ep1 >= 0 && b.ep2 >= 0) {
            if (board.colour[b.ep1] == player && board.colour[b.ep2] == player &&
                board.find(b.ep1) != board.find(b.ep2))
                return b.save;
        } else if (b.ep1 < 0 && b.ep2 >= 0) {
            if (board.colour[b.ep2] == player) {
                const std::uint8_t bit = (b.ep1 == BRIDGE_EDGE_START) ? 1U : 2U;
                if ((board.edge_flags[board.find(b.ep2)] & bit) == 0) return b.save;
            }
        } else if (b.ep1 >= 0 && b.ep2 < 0) {
            if (board.colour[b.ep1] == player) {
                const std::uint8_t bit = (b.ep2 == BRIDGE_EDGE_START) ? 1U : 2U;
                if ((board.edge_flags[board.find(b.ep1)] & bit) == 0) return b.save;
            }
        }
    }
    return -1;
}

// Zero-copy 1-ply immediate win / single-threat block detector using edge_flags.
inline int tactical(const Board& board, Colour player) {
    const auto& topo = *board.topo;
    for (int i = 0; i < board.empty_count; ++i) {
        const int move = board.empty[i];
        std::uint8_t mask = topo.edge_mask[player][move];
        const auto deg = topo.deg[move];
        const auto& nbs = topo.neighbors[move];
        for (int k = 0; k < deg; ++k) {
            const int nb = nbs[k];
            if (board.colour[nb] == player) mask |= board.edge_flags[board.find(nb)];
        }
        if (mask == 3) return move;
    }
    return -1;
}

// Count immediate 1-ply winning threats for `player` (capped at 2); outputs first threat move.
inline int count_threats(const Board& board, Colour player, int& first_threat) {
    first_threat = -1;
    int count = 0;
    const auto& topo = *board.topo;
    for (int i = 0; i < board.empty_count; ++i) {
        const int move = board.empty[i];
        std::uint8_t mask = topo.edge_mask[player][move];
        const auto deg = topo.deg[move];
        const auto& nbs = topo.neighbors[move];
        for (int k = 0; k < deg; ++k) {
            const int nb = nbs[k];
            if (board.colour[nb] == player) mask |= board.edge_flags[board.find(nb)];
        }
        if (mask == 3) {
            if (count == 0) first_threat = move;
            if (++count >= 2) return 2;
        }
    }
    return count;
}

// ============================================================================
// Step 7: Exact Disjoint-Carrier Virtual Connection (VC) Solver & Mustplay
// Theorem (Shannon Pairing Strategy / Benzene H-Search Base):
//   If player P has a chain of 2-bridge hyperedges (u_i, v_i; {a_i, b_i}) from
//   Start Edge to End Edge whose carrier cells {a_1, b_1, ..., a_k, b_k} are
//   pairwise disjoint, then P has a 100% mathematically proven forced win even
//   when it is the opponent's turn to move.
// ============================================================================
struct CellBitSet {
    std::array<std::uint64_t, 6> w{}; // 384 bits covers up to 19x19 = 361 cells
    void clear() { w.fill(0ULL); }
    void set(int idx) { w[idx >> 6] |= (1ULL << (idx & 63)); }
    void reset(int idx) { w[idx >> 6] &= ~(1ULL << (idx & 63)); }
    bool test(int idx) const { return (w[idx >> 6] & (1ULL << (idx & 63))) != 0ULL; }
    bool any() const { return (w[0] | w[1] | w[2] | w[3] | w[4] | w[5]) != 0ULL; }
    int count() const {
        int c = 0;
        for (auto v : w) c += __builtin_popcountll(v);
        return c;
    }
    void intersect_with(const CellBitSet& other) {
        for (int i = 0; i < 6; ++i) w[i] &= other.w[i];
    }
};

inline bool has_disjoint_vc_win(const Board& board, Colour player, CellBitSet* carrier_out = nullptr) {
    const Colour w = board.winner();
    if (w == player) {
        if (carrier_out) carrier_out->clear();
        return true;
    }
    if (w != EMPTY) return false;

    const int n = board.n;
    const int cells = board.cells;
    constexpr int MAX_VC_G = 40;
    constexpr int GID_START = 0;
    constexpr int GID_END = 1;

    std::array<std::int8_t, MAX_CELLS> root_gid{};
    root_gid.fill(-1);
    int num_groups = 2;
    int player_stones = 0;
    for (int i = 0; i < cells; ++i) {
        if (board.colour[i] == player) {
            ++player_stones;
            const int r = board.find(i);
            if (root_gid[r] < 0) {
                const std::uint8_t ef = board.edge_flags[r];
                if ((ef & 1U) != 0) root_gid[r] = GID_START;
                else if ((ef & 2U) != 0) root_gid[r] = GID_END;
                else {
                    if (num_groups >= MAX_VC_G) return false;
                    root_gid[r] = static_cast<std::int8_t>(num_groups++);
                }
            }
        }
    }
    // Minimum stones for a 2-bridge VC chain across n rows/cols is (n - 1) / 2.
    if (player_stones < (n - 1) / 2) return false;

    const auto& topo = *board.topo;
    // common_cnt[u][v] and common_cells[u][v][0..5] for u < v (symmetric).
    std::array<std::array<std::uint8_t, MAX_VC_G>, MAX_VC_G> ccnt{};
    std::array<std::array<std::array<std::int16_t, 6>, MAX_VC_G>, MAX_VC_G> ccells{};
    std::array<std::uint64_t, MAX_VC_G> adj_mask{};

    for (int ei = 0; ei < board.empty_count; ++ei) {
        const int e = board.empty[ei];
        int adj[8];
        int acnt = 0;
        const std::uint8_t em = topo.edge_mask[player][e];
        if ((em & 1U) != 0) adj[acnt++] = GID_START;
        if ((em & 2U) != 0) adj[acnt++] = GID_END;
        const auto deg = topo.deg[e];
        const auto& nbs = topo.neighbors[e];
        for (int k = 0; k < deg; ++k) {
            const int nb = nbs[k];
            if (board.colour[nb] == player) {
                const int g = root_gid[board.find(nb)];
                bool dup = false;
                for (int j = 0; j < acnt; ++j) if (adj[j] == g) { dup = true; break; }
                if (!dup) adj[acnt++] = g;
            }
        }
        for (int i = 0; i < acnt; ++i) {
            for (int j = i + 1; j < acnt; ++j) {
                int u = adj[i], v = adj[j];
                if (u > v) std::swap(u, v);
                auto& cnt = ccnt[u][v];
                if (cnt < 6) {
                    ccells[u][v][cnt++] = static_cast<std::int16_t>(e);
                    if (cnt == 2) {
                        adj_mask[u] |= (1ULL << v);
                        adj_mask[v] |= (1ULL << u);
                    }
                }
            }
        }
    }

    // Fast reachability pre-check on the 2-bridge graph (ignore carrier disjointness first).
    std::uint64_t reach = 1ULL << GID_START;
    std::uint64_t frontier = reach;
    while (frontier != 0ULL) {
        std::uint64_t next_f = 0ULL;
        while (frontier != 0ULL) {
            const int u = __builtin_ctzll(frontier);
            frontier &= frontier - 1ULL;
            next_f |= adj_mask[u] & ~reach;
        }
        reach |= next_f;
        frontier = next_f;
        if ((reach & (1ULL << GID_END)) != 0ULL) break;
    }
    if ((reach & (1ULL << GID_END)) == 0ULL) return false;

    // Bounded exact DFS searching for a simple START->END path with pairwise disjoint carrier pairs.
    CellBitSet used;
    used.clear();
    int steps = 0;
    constexpr int MAX_STEPS = 256;

    auto dfs = [&](auto&& self, int u, std::uint64_t vis) -> bool {
        if (u == GID_END) return true;
        if (++steps > MAX_STEPS) return false;

        // Check direct 2-bridge to GID_END first for fastest termination.
        std::uint64_t cand = adj_mask[u] & ~vis;
        auto try_neighbor = [&](int v) -> bool {
            const int lo = u < v ? u : v;
            const int hi = u < v ? v : u;
            const int cnt = ccnt[lo][hi];
            int free_c[6];
            int fc = 0;
            for (int i = 0; i < cnt; ++i) {
                const int cell = ccells[lo][hi][i];
                if (!used.test(cell)) free_c[fc++] = cell;
            }
            if (fc < 2) return false;
            // Try up to 3 distinct carrier pairs (sufficient for all practical Hex bridge conflicts).
            const int max_pairs = (fc == 2) ? 1 : 3;
            int tried = 0;
            for (int i = 0; i < fc && tried < max_pairs; ++i) {
                for (int j = i + 1; j < fc && tried < max_pairs; ++j) {
                    ++tried;
                    used.set(free_c[i]);
                    used.set(free_c[j]);
                    if (self(self, v, vis | (1ULL << v))) return true;
                    used.reset(free_c[i]);
                    used.reset(free_c[j]);
                    if (steps > MAX_STEPS) return false;
                }
            }
            return false;
        };

        if ((cand & (1ULL << GID_END)) != 0ULL) {
            if (try_neighbor(GID_END)) return true;
            cand &= ~(1ULL << GID_END);
        }
        while (cand != 0ULL) {
            const int v = __builtin_ctzll(cand);
            cand &= cand - 1ULL;
            if (try_neighbor(v)) return true;
            if (steps > MAX_STEPS) return false;
        }
        return false;
    };

    if (dfs(dfs, GID_START, 1ULL << GID_START)) {
        if (carrier_out) *carrier_out = used;
        return true;
    }
    return false;
}

// Find a move for `player` that immediately establishes a proven disjoint-carrier VC win,
// choosing the move with the fewest carriers (strict monotonic convergence to physical win).
inline int find_vc_win_move(const Board& board, Colour player) {
    if (board.cells - board.empty_count < std::max(1, (board.n - 1) / 2 - 1)) return -1;
    Board trial(board.n);
    int best_move = -1;
    int best_carriers = 999;
    for (int i = 0; i < board.empty_count; ++i) {
        const int m = board.empty[i];
        trial.copy_from(board);
        trial.play_unchecked(m, player);
        CellBitSet carriers;
        if (has_disjoint_vc_win(trial, player, &carriers)) {
            const int cc = carriers.count();
            if (cc < best_carriers) {
                best_carriers = cc;
                best_move = m;
                if (cc == 0) return m;
            }
        }
    }
    return best_move;
}

// Compute exact VC-Mustplay set at root against opponent's 1-move disjoint-carrier VC threats.
// Returns:
//   -1 if opponent already has a proven win or two disjoint 1-move VC threats (proven loss!),
//    0 if opponent has no 1-move VC threats (no pruning),
//   >0 = number of moves in `mustplay_out` (all moves outside `mustplay_out` provably lose).
inline int compute_vc_mustplay(const Board& board, Colour opp, CellBitSet& mustplay_out) {
    mustplay_out.clear();
    if (board.cells - board.empty_count < std::max(1, (board.n - 1) / 2 - 1)) return 0;
    if (has_disjoint_vc_win(board, opp, nullptr)) return -1;
    Board trial(board.n);
    bool has_threat = false;
    for (int i = 0; i < board.empty_count; ++i) {
        const int m = board.empty[i];
        trial.copy_from(board);
        trial.play_unchecked(m, opp);
        CellBitSet carriers;
        if (has_disjoint_vc_win(trial, opp, &carriers)) {
            carriers.set(m);
            if (!has_threat) {
                mustplay_out = carriers;
                has_threat = true;
            } else {
                mustplay_out.intersect_with(carriers);
                if (!mustplay_out.any()) return -1; // disjoint VC threats -> proven loss!
            }
        }
    }
    return has_threat ? mustplay_out.count() : 0;
}

// Empirically calibrated 11x11 pie-rule swap boundary (v1.0 self-play 50.0% contour):
// avoids swapping weak edge / obtuse-side cells (a2..h2, a3..d3, j3, a4..d4, j4) while
// swapping genuinely >50% interior and acute-side cells (i2, j2, e3..i3, e4..i4, center).
inline bool should_swap(const Board& board, int last_move) {
    const int n = board.n;
    const int x = last_move / n, y = last_move % n;
    if (n == 11) {
        // Canonicalize by 180-degree rotational symmetry (x, y) <-> (10-x, 10-y).
        int cx = x, cy = y;
        if (cx > 5 || (cx == 5 && cy > 5)) {
            cx = 10 - cx;
            cy = 10 - cy;
        }
        if (cx == 0) return false;
        if (cx == 1) return cy >= 8 && cy <= 9;
        if (cx == 2) return cy >= 4 && cy <= 8;
        if (cx == 3) return cy >= 4 && cy <= 8;
        if (cx == 4) return cy >= 3 && cy <= 8;
        return cy >= 2 && cy <= 8;
    }
    const int dx = x - n / 2, dy = y - n / 2;
    return (std::abs(dx) + std::abs(dy) + std::abs(dx + dy)) / 2 <= std::max(1, n / 3);
}

// Empirically measured 11x11 Nash-equilibrium pie-rule first moves (49.4%..50.6% contour):
// denies opponents a free center swap and preserves Turn 1 clock budget for the midgame.
inline int pie_rule_opening_11x11(std::uint64_t seed) {
    static constexpr std::array<int, 10> BOOK = {
        1 * 11 + 7, // h2 (49.5% / 50.5%)
        9 * 11 + 3, // d10
        1 * 11 + 8, // i2 (50.6% / 49.4%)
        9 * 11 + 2, // c10
        2 * 11 + 4, // e3 (50.1% / 49.9%)
        8 * 11 + 6, // g9
        2 * 11 + 5, // f3 (49.8% / 50.2%)
        8 * 11 + 5, // f9
        3 * 11 + 9, // j4 (50.0% / 50.0%)
        7 * 11 + 1, // b8
    };
    return BOOK[mixed(seed ^ 0x51A9B00FULL) % BOOK.size()];
}

struct Request {
    Colour player;
    Board board;
    int last_move, turn;
    std::string command;
    // V3 budgets come from the independent referee, including earlier pipe latency.
    double move_allowance = -1, external_remaining = -1;
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
    const bool external_budget = parts[0] == "V3";
    if ((!external_budget && (parts.size() != 7 || parts[0] != "V2")) ||
        (external_budget && parts.size() != 9))
        throw std::invalid_argument("Expected seven V2 or nine V3 protocol fields.");
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
            bounded_integer(parts[6], 1, 1000000), parts[3],
            external_budget ? nonnegative_number(parts[7]) : -1,
            external_budget ? nonnegative_number(parts[8]) : -1};
}

struct Config {
    std::string policy = "grave_ts";
    std::uint64_t seed = 378, iterations = 10000;
    int workers = 1, node_cap = 200000;
    int expand_threshold = 8;
    int grave_ref = 50;
    double seconds = 0, game_seconds = 300, memory_mb = 128;
    double rave_k = 1000, rave_bias = 0.0005, exploration = std::sqrt(2.0), prior_weight = 8.0, pat_temp = 0.35;
    bool bridge = true, ordering = true, swap = true, tactics = true;
    bool win_check = true, block_check = true;
    bool lgr = false, prune_dead = true, tree_reuse = true, solver = true, two_dist = true;
    bool pat_prior = true, pat_rollout = true;
    bool opening_book = false;
    bool gtp_mode = false;
    int shared_tree_mode = -1; // -1: auto (shared in timed mode when workers>1), 0: root-parallel, 1: shared-tree
    bool explicit_iterations = false;
    bool explicit_grave_ref = false, explicit_rave_bias = false, explicit_exploration = false;
    bool explicit_expand_threshold = false, explicit_prior_weight = false;

    bool use_shared_tree(const Request& req) const {
        if (workers <= 1) return false;
        if (shared_tree_mode >= 0) return shared_tree_mode != 0;
        return (seconds > 0.0 || req.move_allowance >= 0.0) && !explicit_iterations;
    }

    bool rave() const {
        return policy == "rave_ucb" || policy == "rave_ts" || policy == "grave_ucb" || policy == "grave_ts";
    }
    bool grave() const {
        return (policy == "grave_ucb" || policy == "grave_ts") ? (grave_ref > 0) : (rave() && grave_ref > 0);
    }
    bool thompson() const {
        return policy == "ts" || policy == "rave_ts" || policy == "grave_ts" || policy == "legacy_ts";
    }
    void finalize_defaults() {
        const bool is_grave_policy = (policy == "grave_ucb" || policy == "grave_ts");
        if (!explicit_grave_ref) grave_ref = is_grave_policy ? 50 : 0;
        if (!explicit_rave_bias) rave_bias = is_grave_policy ? 0.0005 : 0.0;
        if (!explicit_exploration) exploration = (policy == "grave_ucb") ? 0.35 : std::sqrt(2.0);
        if (!explicit_prior_weight) prior_weight = (is_grave_policy && ordering) ? 8.0 : 0.0;
        if (!explicit_expand_threshold) expand_threshold = is_grave_policy ? 8 : 4;
    }
};

constexpr std::uint8_t NODE_EXPANDED    = 1U;
constexpr std::uint8_t NODE_TERMINAL    = 2U;
constexpr std::uint8_t NODE_PROVEN_WIN  = 4U;  // to_play has a mathematically proven win
constexpr std::uint8_t NODE_PROVEN_LOSS = 8U;  // to_play has a mathematically proven loss
constexpr std::uint8_t NODE_TRUNCATED   = 16U; // expansion was truncated by node_cap
constexpr std::uint8_t NODE_EXPANDING   = 32U; // lock-free expansion claim bit (shared tree)

// Compact 24-byte MCTS node (zero heap allocations per leaf).
struct Node {
    std::int16_t move = -1;
    Colour to_play = RED;
    std::uint8_t state = 0;
    std::uint32_t visits = 0;
    std::uint32_t wins = 0;       // wins for to_play; parent explicitly inverts.
    std::int32_t first_child = -1;
    std::uint16_t child_count = 0;
    std::uint16_t prior_bonus = 500; // quantized prior in [0, 1000]
    std::int32_t amaf_offset = -1;   // offset into flat amaf_visits/amaf_wins pool

    inline bool expanded() const { return (state & NODE_EXPANDED) != 0; }
    inline bool terminal() const { return (state & NODE_TERMINAL) != 0; }
    inline bool proven_win() const { return (state & NODE_PROVEN_WIN) != 0; }
    inline bool proven_loss() const { return (state & NODE_PROVEN_LOSS) != 0; }
    inline bool proven() const { return (state & (NODE_PROVEN_WIN | NODE_PROVEN_LOSS)) != 0; }
    inline bool truncated() const { return (state & NODE_TRUNCATED) != 0; }
};
static_assert(sizeof(Node) <= 32, "Node should stay compact for cache efficiency.");

struct Action { int move; Colour player; };
struct Path { int node; std::size_t start; };

struct SearchTree {
    int board_cells = 0;
    std::vector<Node> arena;
    std::vector<std::uint32_t> amaf_visits;
    std::vector<std::uint32_t> amaf_wins;
    std::array<std::array<std::int16_t, MAX_CELLS>, 2> lgr{};
    std::uint64_t dead_pruned = 0;
    bool valid = false;
    Board root_board;
    Colour root_player = RED;
    int last_decision_move = -1;

    void clear_lgr() {
        lgr[0].fill(-1);
        lgr[1].fill(-1);
    }
    void reset(int cells) {
        board_cells = cells;
        arena.clear();
        amaf_visits.clear();
        amaf_wins.clear();
        clear_lgr();
        dead_pruned = 0;
        valid = false;
        last_decision_move = -1;
    }
    inline int amaf_tables() const {
        return board_cells > 0 ? static_cast<int>(amaf_visits.size() / static_cast<std::size_t>(board_cells)) : 0;
    }
    inline std::int32_t allocate_amaf(int max_amaf_tables) {
        if (amaf_tables() >= max_amaf_tables) return -1;
        const auto offset = static_cast<std::int32_t>(amaf_visits.size());
        amaf_visits.resize(amaf_visits.size() + static_cast<std::size_t>(board_cells), 0);
        amaf_wins.resize(amaf_wins.size() + static_cast<std::size_t>(board_cells), 0);
        return offset;
    }
    // Compact only the subtree rooted at sub_root into a fresh arena (frees dead branches).
    bool rebase_subtree(int sub_root, const Board& new_board, Colour new_player, int node_cap, int max_amaf_tables) {
        if (sub_root < 0 || sub_root >= static_cast<int>(arena.size())) return false;
        std::vector<Node> new_arena;
        std::vector<std::uint32_t> new_av, new_aw;
        new_arena.reserve(std::min<std::size_t>(arena.size(), static_cast<std::size_t>(node_cap)));
        std::vector<int> old_queue;
        old_queue.reserve(1024);
        new_arena.push_back(arena[sub_root]);
        new_arena[0].move = -1;
        new_arena[0].first_child = -1;
        new_arena[0].child_count = 0;
        new_arena[0].amaf_offset = -1;
        if (!new_arena[0].terminal()) {
            new_arena[0].state &= static_cast<std::uint8_t>(~(NODE_EXPANDED | NODE_PROVEN_WIN | NODE_PROVEN_LOSS | NODE_TRUNCATED));
        } else {
            new_arena[0].state &= static_cast<std::uint8_t>(~NODE_EXPANDED);
        }
        old_queue.push_back(sub_root);
        int amaf_count = 0;
        for (std::size_t qi = 0; qi < old_queue.size(); ++qi) {
            const int old_id = old_queue[qi];
            const Node& old_node = arena[old_id];
            if (old_node.amaf_offset >= 0 && amaf_count < max_amaf_tables) {
                const auto off = static_cast<std::int32_t>(new_av.size());
                new_av.insert(new_av.end(), amaf_visits.begin() + old_node.amaf_offset,
                              amaf_visits.begin() + old_node.amaf_offset + board_cells);
                new_aw.insert(new_aw.end(), amaf_wins.begin() + old_node.amaf_offset,
                              amaf_wins.begin() + old_node.amaf_offset + board_cells);
                new_arena[qi].amaf_offset = off;
                ++amaf_count;
            }
            if (old_node.expanded() && old_node.child_count > 0 &&
                static_cast<int>(new_arena.size()) + old_node.child_count <= node_cap) {
                const auto first = static_cast<std::int32_t>(new_arena.size());
                new_arena[qi].first_child = first;
                new_arena[qi].child_count = old_node.child_count;
                new_arena[qi].state |= NODE_EXPANDED;
                if (old_node.truncated()) new_arena[qi].state |= NODE_TRUNCATED;
                for (int c = 0; c < old_node.child_count; ++c) {
                    const int old_child = old_node.first_child + c;
                    Node copy = arena[old_child];
                    copy.first_child = -1;
                    copy.child_count = 0;
                    copy.amaf_offset = -1;
                    // Preserve proven flags only on true terminal/leaf-proven (unexpanded) nodes;
                    // internal nodes will have proven flags cleanly recomputed bottom-up below.
                    if (copy.expanded()) {
                        copy.state &= static_cast<std::uint8_t>(~(NODE_EXPANDED | NODE_PROVEN_WIN | NODE_PROVEN_LOSS | NODE_TRUNCATED));
                    }
                    new_arena.push_back(copy);
                    old_queue.push_back(old_child);
                }
            } else if (!old_node.expanded() && old_node.proven()) {
                // Preserve leaf-level proven state (e.g. terminal or double-threat loss).
                new_arena[qi].state = old_node.state;
            }
        }
        // Bottom-up recomputation of proven flags guarantees 100% parent-child consistency.
        for (std::size_t idx = new_arena.size(); idx-- > 0;) {
            Node& node = new_arena[idx];
            if (!node.expanded() || node.child_count == 0) continue;
            bool any_child_loss = false;
            bool all_children_win = !node.truncated();
            for (int c = 0; c < node.child_count; ++c) {
                const Node& ch = new_arena[node.first_child + c];
                if (ch.proven_loss()) { any_child_loss = true; break; }
                if (!ch.proven_win()) all_children_win = false;
            }
            if (any_child_loss) node.state |= NODE_PROVEN_WIN;
            else if (all_children_win) node.state |= NODE_PROVEN_LOSS;
        }
        arena.swap(new_arena);
        amaf_visits.swap(new_av);
        amaf_wins.swap(new_aw);
        root_board.copy_from(new_board);
        root_player = new_player;
        valid = true;
        return true;
    }
    int find_child(int parent_id, int move) const {
        if (parent_id < 0 || parent_id >= static_cast<int>(arena.size())) return -1;
        const Node& p = arena[parent_id];
        if (!p.expanded() || p.first_child < 0) return -1;
        for (int i = 0; i < p.child_count; ++i) {
            if (arena[p.first_child + i].move == move) return p.first_child + i;
        }
        return -1;
    }
};

// Trained MoHex 2.0-style 6-ring Hex pattern logits (729 raw codes, 216 canonical symmetries,
// learned via convex L-BFGS-B Plackett-Luce from 10,547 pure-CPU self-play positions).
constexpr std::array<float, 729> PAT_LOGIT = {
    +0.0000f, -1.3601f, -1.3263f, -1.3601f, -2.2923f, +1.3173f, -1.3263f, +1.3173f, -2.2059f,
    -1.2949f, -0.4885f, -1.1631f, -1.8932f, -0.7811f, -0.6757f, +1.8366f, +2.5438f, -0.7812f,
    +0.6898f, -0.8849f, +0.6050f, +2.7027f, -2.0163f, +2.7299f, -0.4682f, -0.8360f, -1.6496f,
    -1.3601f, +0.0641f, -0.8379f, -0.6294f, -0.2561f, -0.4996f, -1.8390f, +0.1799f, -0.3891f,
    -1.8932f, +0.0275f, -0.2779f, -0.5408f, +1.0234f, +0.0179f, -0.8552f, +1.2231f, -0.0488f,
    +2.7027f, +0.5643f, +1.6447f, +3.3622f, +2.5232f, +2.4465f, -1.1689f, -0.2414f, -0.0451f,
    -1.3263f, -0.8379f, +0.3577f, -1.8390f, -2.1747f, +2.8516f, +0.8921f, +1.2065f, +0.5822f,
    +1.8366f, -0.2193f, +2.2866f, -0.8552f, -0.2627f, +1.9009f, +3.2616f, +2.6891f, +2.8292f,
    -0.4682f, -1.3574f, +0.4614f, -1.1689f, -1.9356f, +2.7166f, -0.4281f, -0.2967f, +0.2594f,
    -1.3601f, -0.6294f, -1.8390f, +0.0641f, -0.2561f, +0.1799f, -0.8379f, -0.4996f, -0.3891f,
    -0.4885f, +0.5648f, -0.4142f, +0.0275f, +0.4843f, +0.3634f, -0.2193f, +0.4068f, -0.3666f,
    -0.8849f, +0.0598f, +0.0320f, +0.5643f, +0.6863f, +1.2939f, -1.3574f, -0.5209f, -0.3372f,
    -2.2923f, -0.2561f, -2.1747f, -0.2561f, +0.4212f, -0.3947f, -2.1747f, -0.3947f, -1.8872f,
    -0.7811f, +0.4843f, -0.0026f, +1.0234f, +0.5805f, +0.8561f, -0.2627f, +0.3745f, +1.1805f,
    -2.0163f, +0.6863f, +0.1050f, +2.5232f, +1.3760f, +2.9514f, -1.9356f, -0.5108f, +0.6471f,
    +1.3173f, -0.4996f, +2.8516f, +0.1799f, -0.3947f, +1.5323f, +1.2065f, +1.0961f, +0.2120f,
    +2.5438f, +0.4068f, +3.0155f, +1.2231f, +0.3745f, +2.3514f, +2.6891f, +1.2363f, +2.0476f,
    -0.8360f, -0.5209f, +0.3869f, -0.2414f, -0.5108f, +1.1228f, -0.2967f, +0.0526f, +0.1132f,
    -1.3263f, -1.8390f, +0.8921f, -0.8379f, -2.1747f, +1.2065f, +0.3577f, +2.8516f, +0.5822f,
    -1.1631f, -0.4142f, +0.5579f, -0.2779f, -0.0026f, +0.6507f, +2.2866f, +3.0155f, +0.7925f,
    +0.6050f, +0.0320f, +1.0838f, +1.6447f, +0.1050f, +2.1001f, +0.4614f, +0.3869f, +0.4526f,
    +1.3173f, +0.1799f, +1.2065f, -0.4996f, -0.3947f, +1.0961f, +2.8516f, +1.5323f, +0.2120f,
    -0.6757f, +0.3634f, +0.6507f, +0.0179f, +0.8561f, +0.4926f, +1.9009f, +2.3514f, +0.7122f,
    +2.7299f, +1.2939f, +2.1001f, +2.4465f, +2.9514f, +1.0611f, +2.7166f, +1.1228f, +0.5302f,
    -2.2059f, -0.3891f, +0.5822f, -0.3891f, -1.8872f, +0.2120f, +0.5822f, +0.2120f, +0.5866f,
    -0.7812f, -0.3666f, +0.7925f, -0.0488f, +1.1805f, +0.7122f, +2.8292f, +2.0476f, +0.6547f,
    -1.6496f, -0.3372f, +0.4526f, -0.0451f, +0.6471f, +0.5302f, +0.2594f, +0.1132f, +0.5439f,
    -1.2949f, -1.8932f, +1.8366f, -0.4885f, -0.7811f, +2.5438f, -1.1631f, -0.6757f, -0.7812f,
    +0.5020f, +0.3701f, +0.3447f, +0.3701f, +0.5736f, +0.7450f, +0.3447f, +0.7450f, +0.0915f,
    +0.0268f, -0.2395f, +1.0268f, +0.1175f, +0.3695f, +1.9482f, -1.5438f, -1.0318f, -0.6380f,
    -0.4885f, +0.0275f, -0.2193f, +0.5648f, +0.4843f, +0.4068f, -0.4142f, +0.3634f, -0.3666f,
    +0.3701f, +0.5015f, +0.5250f, +0.5817f, +0.5861f, +0.5553f, -0.0745f, +0.0231f, -0.1899f,
    +0.1175f, +0.5761f, +1.0985f, +0.6674f, +1.3121f, +1.4312f, +0.0380f, -0.2966f, -0.3173f,
    -1.1631f, -0.2779f, +2.2866f, -0.4142f, -0.0026f, +3.0155f, +0.5579f, +0.6507f, +0.7925f,
    +0.3447f, +0.5250f, +2.3233f, -0.0745f, +0.4540f, +1.8420f, +2.2311f, +1.9426f, +2.0839f,
    -1.5438f, -1.3629f, +0.1117f, +0.0380f, +1.1844f, +2.5973f, -0.1749f, +0.2033f, +0.2971f,
    -1.8932f, -0.5408f, -0.8552f, +0.0275f, +1.0234f, +1.2231f, -0.2779f, +0.0179f, -0.0488f,
    +0.3701f, +0.5817f, -0.0745f, +0.5015f, +0.5861f, +0.0231f, +0.5250f, +0.5553f, -0.1899f,
    -0.2395f, +0.3412f, +0.6101f, +0.5761f, +0.8392f, +1.0596f, -1.3629f, +0.9590f, -0.0795f,
    -0.7811f, +1.0234f, -0.2627f, +0.4843f, +0.5805f, +0.3745f, -0.0026f, +0.8561f, +1.1805f,
    +0.5736f, +0.5861f, +0.4540f, +0.5861f, +0.5866f, +0.5376f, +0.4540f, +0.5376f, +0.5002f,
    +0.3695f, +0.8392f, +0.6477f, +1.3121f, +0.5685f, +1.7864f, +1.1844f, +0.3001f, +0.2006f,
    -0.6757f, +0.0179f, +1.9009f, +0.3634f, +0.8561f, +2.3514f, +0.6507f, +0.4926f, +0.7122f,
    +0.7450f, +0.5553f, +1.8420f, +0.0231f, +0.5376f, +1.4930f, +1.9426f, +1.3234f, +1.4885f,
    -1.0318f, +0.9590f, +0.6363f, -0.2966f, +0.3001f, +1.7720f, +0.2033f, +0.5531f, -0.0193f,
    +1.8366f, -0.8552f, +3.2616f, -0.2193f, -0.2627f, +2.6891f, +2.2866f, +1.9009f, +2.8292f,
    +0.3447f, -0.0745f, +2.2311f, +0.5250f, +0.4540f, +1.9426f, +2.3233f, +1.8420f, +2.0839f,
    +1.0268f, +0.6101f, +2.0318f, +1.0985f, +0.6477f, +2.2407f, +0.1117f, +0.6363f, +0.4635f,
    +2.5438f, +1.2231f, +2.6891f, +0.4068f, +0.3745f, +1.2363f, +3.0155f, +2.3514f, +2.0476f,
    +0.7450f, +0.0231f, +1.9426f, +0.5553f, +0.5376f, +1.3234f, +1.8420f, +1.4930f, +1.4885f,
    +1.9482f, +1.0596f, +2.2407f, +1.4312f, +1.7864f, +0.9982f, +2.5973f, +1.7720f, +1.8540f,
    -0.7812f, -0.0488f, +2.8292f, -0.3666f, +1.1805f, +2.0476f, +0.7925f, +0.7122f, +0.6547f,
    +0.0915f, -0.1899f, +2.0839f, -0.1899f, +0.5002f, +1.4885f, +2.0839f, +1.4885f, +0.6721f,
    -0.6380f, -0.0795f, +0.4635f, -0.3173f, +0.2006f, +1.8540f, +0.2971f, -0.0193f, +0.3584f,
    +0.6898f, +2.7027f, -0.4682f, -0.8849f, -2.0163f, -0.8360f, +0.6050f, +2.7299f, -1.6496f,
    +0.0268f, +0.1175f, -1.5438f, -0.2395f, +0.3695f, -1.0318f, +1.0268f, +1.9482f, -0.6380f,
    +0.9217f, +2.9936f, +0.6950f, +2.9936f, +1.2007f, +3.8426f, +0.6950f, +3.8426f, +0.6136f,
    -0.8849f, +0.5643f, -1.3574f, +0.0598f, +0.6863f, -0.5209f, +0.0320f, +1.2939f, -0.3372f,
    -0.2395f, +0.5761f, -1.3629f, +0.3412f, +0.8392f, +0.9590f, +0.6101f, +1.0596f, -0.0795f,
    +2.9936f, +1.5677f, +0.6430f, +2.8150f, +3.1321f, +2.6732f, +0.3404f, +0.9865f, -0.0682f,
    +0.6050f, +1.6447f, +0.4614f, +0.0320f, +0.1050f, +0.3869f, +1.0838f, +2.1001f, +0.4526f,
    +1.0268f, +1.0985f, +0.1117f, +0.6101f, +0.6477f, +0.6363f, +2.0318f, +2.2407f, +0.4635f,
    +0.6950f, +0.6430f, +0.3573f, +0.3404f, +0.6612f, +0.7702f, +0.6655f, +0.5388f, +0.4472f,
    +2.7027f, +3.3622f, -1.1689f, +0.5643f, +2.5232f, -0.2414f, +1.6447f, +2.4465f, -0.0451f,
    +0.1175f, +0.6674f, +0.0380f, +0.5761f, +1.3121f, -0.2966f, +1.0985f, +1.4312f, -0.3173f,
    +2.9936f, +2.8150f, +0.3404f, +1.5677f, +3.1321f, +0.9865f, +0.6430f, +2.6732f, -0.0682f,
    -2.0163f, +2.5232f, -1.9356f, +0.6863f, +1.3760f, -0.5108f, +0.1050f, +2.9514f, +0.6471f,
    +0.3695f, +1.3121f, +1.1844f, +0.8392f, +0.5685f, +0.3001f, +0.6477f, +1.7864f, +0.2006f,
    +1.2007f, +3.1321f, +0.6612f, +3.1321f, +2.6918f, +2.4327f, +0.6612f, +2.4327f, -0.0117f,
    +2.7299f, +2.4465f, +2.7166f, +1.2939f, +2.9514f, +1.1228f, +2.1001f, +1.0611f, +0.5302f,
    +1.9482f, +1.4312f, +2.5973f, +1.0596f, +1.7864f, +1.7720f, +2.2407f, +0.9982f, +1.8540f,
    +3.8426f, +2.6732f, +0.7702f, +0.9865f, +2.4327f, +0.5344f, +0.5388f, +1.1909f, +0.6306f,
    -0.4682f, -1.1689f, -0.4281f, -1.3574f, -1.9356f, -0.2967f, +0.4614f, +2.7166f, +0.2594f,
    -1.5438f, +0.0380f, -0.1749f, -1.3629f, +1.1844f, +0.2033f, +0.1117f, +2.5973f, +0.2971f,
    +0.6950f, +0.3404f, +0.6655f, +0.6430f, +0.6612f, +0.5388f, +0.3573f, +0.7702f, +0.4472f,
    -0.8360f, -0.2414f, -0.2967f, -0.5209f, -0.5108f, +0.0526f, +0.3869f, +1.1228f, +0.1132f,
    -1.0318f, -0.2966f, +0.2033f, +0.9590f, +0.3001f, +0.5531f, +0.6363f, +1.7720f, -0.0193f,
    +3.8426f, +0.9865f, +0.5388f, +2.6732f, +2.4327f, +1.1909f, +0.7702f, +0.5344f, +0.6306f,
    -1.6496f, -0.0451f, +0.2594f, -0.3372f, +0.6471f, +0.1132f, +0.4526f, +0.5302f, +0.5439f,
    -0.6380f, -0.3173f, +0.2971f, -0.0795f, +0.2006f, -0.0193f, +0.4635f, +1.8540f, +0.3584f,
    +0.6136f, -0.0682f, +0.4472f, -0.0682f, -0.0117f, +0.6306f, +0.4472f, +0.6306f, +0.5866f
};

inline int ring6_pattern_code(const Board& board, int cell, Colour player) {
    const auto& ring = board.topo->ring6[cell];
    const auto* col = board.colour.data();
    const int red_edge_st = (player == RED) ? 1 : 2;
    const int blue_edge_st = 3 - red_edge_st;
    auto state_at = [&](std::int16_t nb) -> int {
        if (nb >= 0) {
            const Colour c = col[nb];
            return (c == EMPTY) ? 0 : ((c == player) ? 1 : 2);
        }
        if (nb == RING_RED_EDGE) return red_edge_st;
        if (nb == RING_BLUE_EDGE) return blue_edge_st;
        return 0;
    };
    if (player == RED) {
        int code = state_at(ring[5]);
        code = code * 3 + state_at(ring[4]);
        code = code * 3 + state_at(ring[3]);
        code = code * 3 + state_at(ring[2]);
        code = code * 3 + state_at(ring[1]);
        code = code * 3 + state_at(ring[0]);
        return code;
    }
    int code = state_at(ring[0]);
    code = code * 3 + state_at(ring[1]);
    code = code * 3 + state_at(ring[2]);
    code = code * 3 + state_at(ring[3]);
    code = code * 3 + state_at(ring[4]);
    code = code * 3 + state_at(ring[5]);
    return code;
}

inline std::array<float, 729> build_pattern_weights(double temp) {
    std::array<float, 729> w{};
    const double t = temp < 0.0 ? 0.0 : (temp > 2.0 ? 2.0 : temp);
    for (int i = 0; i < 729; ++i) w[i] = static_cast<float>(std::exp(t * PAT_LOGIT[i]));
    return w;
}

// Fast MoHex 2.0-style local-neighborhood + 2-choice global pattern rollout move selector.
inline int pattern_rollout_move(const Board& board, int last_move, Colour player,
                                const std::array<float, 729>& pat_w, FastRng& rng) {
    if (last_move >= 0) {
        const auto& topo = *board.topo;
        const auto deg = topo.deg[last_move];
        const auto& nbs = topo.neighbors[last_move];
        int cand[6];
        float cw[6];
        int cnt = 0;
        float local_sum = 0.0f;
        for (int k = 0; k < deg; ++k) {
            const int nb = nbs[k];
            if (board.colour[nb] == EMPTY) {
                const float w = pat_w[ring6_pattern_code(board, nb, player)];
                cand[cnt] = nb;
                cw[cnt] = w;
                local_sum += w;
                ++cnt;
            }
        }
        // Respond locally around last_move with probability local_sum / (local_sum + 10.0).
        if (cnt > 0) {
            float pick = static_cast<float>(rng.next_uniform()) * (local_sum + 10.0f);
            if (pick < local_sum) {
                for (int i = 0; i < cnt; ++i) {
                    pick -= cw[i];
                    if (pick <= 0.0f) return cand[i];
                }
                return cand[cnt - 1];
            }
        }
    }
    // Global 2-choice pattern-weighted selection (O(1), avoids dead/redundant shapes).
    const int m1 = board.empty[rng.next_bounded(board.empty_count)];
    if (board.empty_count == 1) return m1;
    const int m2 = board.empty[rng.next_bounded(board.empty_count)];
    if (m1 == m2) return m1;
    const float w1 = pat_w[ring6_pattern_code(board, m1, player)];
    const float w2 = pat_w[ring6_pattern_code(board, m2, player)];
    return (static_cast<float>(rng.next_uniform()) * (w1 + w2) < w1) ? m1 : m2;
}

// Fast bucket-queue Two-Distance (2-distance connectivity) potential on the Hex component graph.
// For player P connecting edge_bit 1 to edge_bit 2, d2[e] is the minimum number of stones
// needed so that P has TWO independent paths from the target edge to empty cell e.
constexpr int TWO_DIST_INF = 24;

inline void compute_two_distance_from_edge(const Board& board, Colour player, std::uint8_t edge_bit,
                                           std::array<std::uint8_t, MAX_CELLS>& out_dist) {
    const auto& topo = *board.topo;
    const int cells = board.cells;
    // Map each stone of `player` to its Union-Find root and collect stones per active group.
    std::array<std::int16_t, MAX_CELLS> group_head{};
    std::array<std::int16_t, MAX_CELLS> group_next{};
    std::array<std::int16_t, MAX_CELLS> cell_root{};
    group_head.fill(-1);
    for (int i = 0; i < cells; ++i) {
        if (board.colour[i] == player) {
            const int r = board.find(i);
            cell_root[i] = static_cast<std::int16_t>(r);
            group_next[i] = group_head[r];
            group_head[r] = static_cast<std::int16_t>(i);
        } else {
            cell_root[i] = -1;
        }
    }

    // Vertex space: empty cells (0..cells-1) AND friendly group roots (0..cells-1, disjoint indices!).
    std::array<std::uint8_t, MAX_CELLS> best1{}, best2{}, dist{};
    best1.fill(TWO_DIST_INF);
    best2.fill(TWO_DIST_INF);
    dist.fill(TWO_DIST_INF);

    // Fixed-size flat buckets with append-only entries (zero linked-list aliasing).
    struct QEntry { std::int16_t v; std::int16_t next; };
    std::array<QEntry, MAX_CELLS * 6> q_pool{};
    int q_size = 0;
    std::array<std::int16_t, TWO_DIST_INF + 1> bucket_head{};
    bucket_head.fill(-1);
    std::array<std::uint8_t, MAX_CELLS> finalized{};
    auto push_bucket = [&](int v, int d) {
        if (d >= TWO_DIST_INF || finalized[v]) return;
        if (d < dist[v] && q_size < static_cast<int>(q_pool.size())) {
            dist[v] = static_cast<std::uint8_t>(d);
            q_pool[q_size] = {static_cast<std::int16_t>(v), bucket_head[d]};
            bucket_head[d] = static_cast<std::int16_t>(q_size++);
        }
    };

    // Seed distance 0 on friendly groups touching `edge_bit`, and distance 1 on empty cells
    // directly touching `edge_bit` or a distance-0 friendly group.
    for (int i = 0; i < cells; ++i) {
        const Colour c = board.colour[i];
        if (c == player) {
            const int r = cell_root[i];
            if (i == r && (board.edge_flags[r] & edge_bit) != 0) {
                dist[r] = 0;
            }
        } else if (c == EMPTY) {
            bool touches_zero = (topo.edge_mask[player][i] & edge_bit) != 0;
            if (!touches_zero) {
                const auto deg = topo.deg[i];
                const auto& nbs = topo.neighbors[i];
                for (int k = 0; k < deg; ++k) {
                    const int nb = nbs[k];
                    if (board.colour[nb] == player && (board.edge_flags[cell_root[nb]] & edge_bit) != 0) {
                        touches_zero = true;
                        break;
                    }
                }
            }
            if (touches_zero) {
                push_bucket(i, 1);
            }
        }
    }

    // Track deduplication stamps so a friendly group only relaxes each adjacent empty cell once
    // and an empty cell only relaxes each adjacent friendly group once.
    std::array<std::uint16_t, MAX_CELLS> stamp{};
    std::uint16_t cur_stamp = 0;

    auto relax = [&](int target, int d, bool is_empty_target) {
        if (d < best1[target]) {
            best2[target] = best1[target];
            best1[target] = static_cast<std::uint8_t>(d);
        } else if (d < best2[target]) {
            best2[target] = static_cast<std::uint8_t>(d);
        } else {
            return;
        }
        if (best2[target] < TWO_DIST_INF) {
            const int cand = static_cast<int>(best2[target]) + (is_empty_target ? 1 : 0);
            if (cand < dist[target]) push_bucket(target, cand);
        }
    };

    for (int d = 1; d < TWO_DIST_INF; ++d) {
        while (bucket_head[d] >= 0) {
            const int entry_id = bucket_head[d];
            const int u = q_pool[entry_id].v;
            bucket_head[d] = q_pool[entry_id].next;
            if (dist[u] != d || finalized[u]) continue;
            finalized[u] = 1;

            if (board.colour[u] == EMPTY) {
                ++cur_stamp;
                const auto deg = topo.deg[u];
                const auto& nbs = topo.neighbors[u];
                for (int k = 0; k < deg; ++k) {
                    const int nb = nbs[k];
                    const Colour nc = board.colour[nb];
                    if (nc == EMPTY) {
                        if (dist[nb] > d + 1) relax(nb, d, true);
                    } else if (nc == player) {
                        const int r = cell_root[nb];
                        if (dist[r] > d && stamp[r] != cur_stamp) {
                            stamp[r] = cur_stamp;
                            relax(r, d, false);
                        }
                    }
                }
            } else {
                // Friendly group root `u` finalized at distance `d`: relax every unique adjacent empty cell.
                ++cur_stamp;
                for (int stone = group_head[u]; stone >= 0; stone = group_next[stone]) {
                    const auto deg = topo.deg[stone];
                    const auto& nbs = topo.neighbors[stone];
                    for (int k = 0; k < deg; ++k) {
                        const int nb = nbs[k];
                        if (board.colour[nb] == EMPTY && dist[nb] > d + 1 && stamp[nb] != cur_stamp) {
                            stamp[nb] = cur_stamp;
                            relax(nb, d, true);
                        }
                    }
                }
            }
        }
    }

    for (int i = 0; i < cells; ++i) out_dist[i] = dist[i];
}

struct TwoDistPotential {
    std::array<std::uint8_t, MAX_CELLS> pot_red{};
    std::array<std::uint8_t, MAX_CELLS> pot_blue{};
    int min_red = TWO_DIST_INF * 2;
    int min_blue = TWO_DIST_INF * 2;
    int min_comb = TWO_DIST_INF * 4;
};

inline TwoDistPotential compute_two_distance_potential(const Board& board) {
    std::array<std::uint8_t, MAX_CELLS> rt, rb, bl, br;
    compute_two_distance_from_edge(board, RED, 1U, rt);
    compute_two_distance_from_edge(board, RED, 2U, rb);
    compute_two_distance_from_edge(board, BLUE, 1U, bl);
    compute_two_distance_from_edge(board, BLUE, 2U, br);

    TwoDistPotential res;
    for (int i = 0; i < board.empty_count; ++i) {
        const int m = board.empty[i];
        const int pr = std::min(TWO_DIST_INF * 2, static_cast<int>(rt[m]) + static_cast<int>(rb[m]) - 1);
        const int pb = std::min(TWO_DIST_INF * 2, static_cast<int>(bl[m]) + static_cast<int>(br[m]) - 1);
        res.pot_red[m] = static_cast<std::uint8_t>(pr);
        res.pot_blue[m] = static_cast<std::uint8_t>(pb);
        if (pr < res.min_red) res.min_red = pr;
        if (pb < res.min_blue) res.min_blue = pb;
        if (pr + pb < res.min_comb) res.min_comb = pr + pb;
    }
    return res;
}

// Heuristic prior score quantized into [0, 1000] for move ordering & progressive bias.
inline std::uint16_t compute_prior_bonus(const Board& board, int move, Colour player, int last_move, int save_move,
                                         const TwoDistPotential* td = nullptr, bool use_pat_prior = true) {
    if (move == save_move) return 960;
    const auto& topo = *board.topo;
    const int n = board.n;
    const int x = move / n, y = move % n;
    const double pat_l = use_pat_prior ? static_cast<double>(PAT_LOGIT[ring6_pattern_code(board, move, player)]) : 0.0;
    double score = 0.0;
    if (td != nullptr) {
        const int my_pot = (player == RED) ? td->pot_red[move] : td->pot_blue[move];
        const int opp_pot = (player == RED) ? td->pot_blue[move] : td->pot_red[move];
        const int my_min = (player == RED) ? td->min_red : td->min_blue;
        const int opp_min = (player == RED) ? td->min_blue : td->min_red;
        const int comb_gap = (my_pot + opp_pot) - td->min_comb;
        const int my_gap = my_pot - my_min;
        const int opp_gap = opp_pot - opp_min;
        // Blend global Two-Distance choke points with learned MoHex 2.0 6-ring pattern logits.
        score = 7.5 - 1.5 * comb_gap - 0.85 * my_gap - 0.75 * opp_gap + 1.2 * pat_l;
        if (last_move >= 0) {
            const int dx = x - last_move / n, dy = y - last_move % n;
            const int dist = (std::abs(dx) + std::abs(dy) + std::abs(dx + dy)) / 2;
            if (dist == 2) score += 2.4;
            else if (dist == 1) score += 1.4;
        }
        const double norm = (score + 10.0) / 22.0;
        const double clamped = norm < 0.05 ? 0.05 : (norm > 0.94 ? 0.94 : norm);
        return static_cast<std::uint16_t>(clamped * 1000.0);
    }
    if (use_pat_prior) {
        // Fast O(1) learned MoHex 2.0 local pattern prior for deep nodes (depth > 2).
        score = 2.2 * pat_l + topo.center_score[move] * 0.45;
        if (last_move >= 0) {
            const int dx = x - last_move / n, dy = y - last_move % n;
            const int dist = (std::abs(dx) + std::abs(dy) + std::abs(dx + dy)) / 2;
            if (dist == 1) score += 2.6;
            else if (dist == 2) score += 2.2;
        }
        const double norm = (score + 7.0) / 18.0;
        const double clamped = norm < 0.05 ? 0.05 : (norm > 0.93 ? 0.93 : norm);
        return static_cast<std::uint16_t>(clamped * 1000.0);
    }
    score = topo.center_score[move] * 1.2;
    if (last_move >= 0) {
        const int dx = x - last_move / n, dy = y - last_move % n;
        const int dist = (std::abs(dx) + std::abs(dy) + std::abs(dx + dy)) / 2;
        if (dist == 2) score += 4.0;
        else if (dist == 1) score += 1.5;
    }
    int friendly = 0, enemy = 0;
    const auto deg = topo.deg[move];
    const auto& nbs = topo.neighbors[move];
    for (int k = 0; k < deg; ++k) {
        const Colour c = board.colour[nbs[k]];
        if (c == player) ++friendly;
        else if (c != EMPTY) ++enemy;
    }
    score += friendly * 1.4 + enemy * 0.6;
    if (player == RED && (x == 1 || x == n - 2)) score += 1.0;
    if (player == BLUE && (y == 1 || y == n - 2)) score += 1.0;
    const double norm = (score + 12.0) / 22.0;
    const double clamped = norm < 0.05 ? 0.05 : (norm > 0.90 ? 0.90 : norm);
    return static_cast<std::uint16_t>(clamped * 1000.0);
}

// Expand a node full-width (with MCTS-Solver exact threat/mustplay pruning,
// proven dead-cell pruning, and node-cap safety).
bool expand_node(SearchTree& tree, int node_id, const Board& board, int last_move, const Config& cfg,
                 int node_cap, int max_amaf_tables, FastRng& rng, bool& cap_reached, int depth = 0) {
    Node& node = tree.arena[node_id];
    if (node.expanded()) return true;
    const Colour w = board.winner();
    if (w != EMPTY || board.empty_count == 0) {
        node.state |= NODE_TERMINAL;
        if (cfg.solver && w != EMPTY) {
            node.state |= (w == node.to_play) ? NODE_PROVEN_WIN : NODE_PROVEN_LOSS;
        }
        return false;
    }
    const int avail = node_cap - static_cast<int>(tree.arena.size());
    if (avail <= 0) {
        cap_reached = true;
        return false;
    }

    const Colour player = node.to_play;
    const Colour opp = opposite(player);
    // Exact Disjoint-Carrier VC-Solver inside the tree (proves wins/losses 10-15 plies early).
    if (cfg.solver && node_id > 0 &&
        (board.cells - board.empty_count >= board.n) &&
        (depth <= 3 || board.empty_count <= 32)) {
        if (has_disjoint_vc_win(board, opp)) {
            node.state |= (NODE_TERMINAL | NODE_PROVEN_LOSS);
            return false;
        }
        if (has_disjoint_vc_win(board, player)) {
            node.state |= (NODE_TERMINAL | NODE_PROVEN_WIN);
            return false;
        }
    }
    // MCTS-Solver tactical expansion:
    //   1) If to_play has a 1-ply win -> expand ONLY that winning move & prove NODE_PROVEN_WIN.
    //   2) Else if opponent has >= 2 simultaneous 1-ply wins -> prove NODE_PROVEN_LOSS immediately.
    //   3) Else if opponent has exactly 1 immediate win -> mustplay (expand ONLY that blocking move).
    // Respect --tactics 0 at root (node_id == 0) so benchmark/ablation tests stay clean.
    if (cfg.solver && (node_id > 0 || cfg.tactics) &&
        (board.cells - board.empty_count >= 2 * board.n - 3)) {
        const int win_move = tactical(board, player);
        if (win_move >= 0) {
            const auto first = static_cast<std::int32_t>(tree.arena.size());
            Node child;
            child.move = static_cast<std::int16_t>(win_move);
            child.to_play = opp;
            child.prior_bonus = 1000;
            child.state = NODE_TERMINAL | NODE_PROVEN_LOSS; // opp loses immediately
            tree.arena.push_back(child);
            Node& updated = tree.arena[node_id];
            updated.first_child = first;
            updated.child_count = 1;
            updated.state |= (NODE_EXPANDED | NODE_PROVEN_WIN);
            if (cfg.rave() && updated.amaf_offset < 0) updated.amaf_offset = tree.allocate_amaf(max_amaf_tables);
            return true;
        }
        int block_move = -1;
        const int opp_threats = count_threats(board, opp, block_move);
        if (opp_threats >= 2) {
            node.state |= NODE_PROVEN_LOSS;
            return false;
        }
        if (opp_threats == 1) {
            const auto first = static_cast<std::int32_t>(tree.arena.size());
            Node child;
            child.move = static_cast<std::int16_t>(block_move);
            child.to_play = opp;
            child.prior_bonus = 990;
            tree.arena.push_back(child);
            Node& updated = tree.arena[node_id];
            updated.first_child = first;
            updated.child_count = 1;
            updated.state |= NODE_EXPANDED;
            if (cfg.rave() && updated.amaf_offset < 0) updated.amaf_offset = tree.allocate_amaf(max_amaf_tables);
            return true;
        }
    }

    std::array<std::pair<std::uint16_t, int>, MAX_CELLS> candidates;
    int cand_count = 0;
    const int save_move = cfg.bridge ? bridge_save(board, last_move, player) : -1;
    TwoDistPotential td_storage;
    const TwoDistPotential* td_ptr = nullptr;
    if (cfg.ordering && cfg.two_dist && depth <= 4) {
        td_storage = compute_two_distance_potential(board);
        td_ptr = &td_storage;
    }
    if (cfg.prune_dead) {
        for (int i = 0; i < board.empty_count; ++i) {
            const int m = board.empty[i];
            if (is_dead_cell(board, m)) {
                ++tree.dead_pruned;
                continue;
            }
            const std::uint16_t prior = cfg.ordering ? compute_prior_bonus(board, m, player, last_move, save_move, td_ptr, cfg.pat_prior) : 500;
            candidates[cand_count++] = {prior, m};
        }
    }
    // Safety fallback if every empty cell was dead (never leave a nonterminal node without children).
    if (cand_count == 0) {
        for (int i = 0; i < board.empty_count; ++i) {
            const int m = board.empty[i];
            const std::uint16_t prior = cfg.ordering ? compute_prior_bonus(board, m, player, last_move, save_move, td_ptr, cfg.pat_prior) : 500;
            candidates[cand_count++] = {prior, m};
        }
    }
    // Deterministic Fisher-Yates shuffle for tie-breaking.
    for (int i = cand_count - 1; i > 0; --i) {
        const int j = rng.next_bounded(i + 1);
        std::swap(candidates[i], candidates[j]);
    }
    int to_add = cand_count;
    bool truncated = false;
    if (to_add > avail) {
        cap_reached = true;
        truncated = true;
        if (cfg.ordering) {
            std::stable_sort(candidates.begin(), candidates.begin() + cand_count,
                             [](const auto& a, const auto& b) { return a.first > b.first; });
        }
        to_add = avail;
    }
    const auto first = static_cast<std::int32_t>(tree.arena.size());
    for (int i = 0; i < to_add; ++i) {
        Node child;
        child.move = static_cast<std::int16_t>(candidates[i].second);
        child.to_play = opp;
        child.prior_bonus = candidates[i].first;
        tree.arena.push_back(child);
    }
    // Re-fetch reference after push_back in case vector reallocated.
    Node& updated = tree.arena[node_id];
    updated.first_child = first;
    updated.child_count = static_cast<std::uint16_t>(to_add);
    updated.state |= NODE_EXPANDED;
    if (truncated) updated.state |= NODE_TRUNCATED;
    if (cfg.rave() && updated.amaf_offset < 0) {
        updated.amaf_offset = tree.allocate_amaf(max_amaf_tables);
    }
    return true;
}

inline double classic_rave_beta(std::uint32_t parent_visits, const Config& cfg) {
    return cfg.rave_k == 0.0 ? 0.0 : std::sqrt(cfg.rave_k / (3.0 * parent_visits + cfg.rave_k));
}

int select_child(const SearchTree& tree, int parent_id, std::int32_t amaf_base,
                 const Config& cfg, FastRng& rng) {
    const Node& parent = tree.arena[parent_id];
    if (parent.child_count == 0) throw std::logic_error("Selection on an empty node.");
    const bool use_rave = cfg.rave() && amaf_base >= 0;
    const std::uint32_t* av = use_rave ? &tree.amaf_visits[amaf_base] : nullptr;
    const std::uint32_t* aw = use_rave ? &tree.amaf_wins[amaf_base] : nullptr;
    const bool use_grave_formula = cfg.rave_bias > 0.0;
    const double log_parent = std::log(static_cast<double>(parent.visits) + 1.0);
    const double classic_beta_val = use_rave && !use_grave_formula ? classic_rave_beta(parent.visits, cfg) : 0.0;
    const double pw = cfg.prior_weight;

    int best = -1;
    double best_score = -std::numeric_limits<double>::infinity();
    int fallback_loss = -1;
    std::uint32_t fallback_visits = 0;
    const int first = parent.first_child;
    const int end = first + parent.child_count;

    for (int id = first; id < end; ++id) {
        const Node& child = tree.arena[id];
        if (cfg.solver) {
            // Child is PROVEN_LOSS for opponent => immediate PROVEN_WIN for parent!
            if (child.proven_loss()) return id;
            // Child is PROVEN_WIN for opponent => proven losing move for parent; skip unless all lose.
            if (child.proven_win()) {
                if (fallback_loss < 0 || child.visits > fallback_visits) {
                    fallback_loss = id;
                    fallback_visits = child.visits;
                }
                continue;
            }
        }
        const double n_mc = static_cast<double>(child.visits);
        const double w_mc = static_cast<double>(child.visits - child.wins); // parent's wins
        const double amaf_n = use_rave ? static_cast<double>(av[child.move]) : 0.0;
        const double amaf_w = use_rave ? static_cast<double>(aw[child.move]) : 0.0;
        const bool has_amaf = use_rave && amaf_n > 0.0;
        double beta = 0.0;
        if (has_amaf) {
            beta = use_grave_formula
                ? amaf_n / (n_mc + amaf_n + cfg.rave_bias * n_mc * amaf_n)
                : classic_beta_val;
        }
        double score;
        if (cfg.thompson()) {
            if (cfg.policy == "legacy_ts") {
                const double mc_weight = n_mc / (1000.0 + n_mc);
                score = rng.sample_beta(mc_weight * w_mc + 1.0, mc_weight * child.wins + 1.0);
            } else if (use_grave_formula) {
                const double prior_p = 0.35 + 0.30 * (child.prior_bonus * 0.001);
                const double n_eff_mc = n_mc + pw;
                const double q_mc = n_eff_mc > 0.0 ? (w_mc + pw * prior_p) / n_eff_mc : 0.5;
                const double q_amaf = has_amaf ? (amaf_w / amaf_n) : 0.5;
                const double q = has_amaf ? ((1.0 - beta) * q_mc + beta * q_amaf) : q_mc;
                // When borrowing an ancestor's AMAF table (GRAVE), cap borrowed pseudo-count so
                // high ancestor volume informs the posterior mean without collapsing TS variance.
                const bool from_ancestor = (amaf_base != parent.amaf_offset);
                const double amaf_cap = from_ancestor ? 32.0 : cfg.rave_k;
                const double eff_n = n_eff_mc + (has_amaf ? beta * std::min(amaf_n, amaf_cap) : 0.0);
                score = rng.sample_beta(1.0 + q * eff_n, 1.0 + (1.0 - q) * eff_n);
            } else {
                const double mc_weight = 1.0 - beta;
                const double eff_w = mc_weight * w_mc + (has_amaf ? beta * amaf_w : 0.0);
                const double eff_l = mc_weight * child.wins + (has_amaf ? beta * (amaf_n - amaf_w) : 0.0);
                score = rng.sample_beta(eff_w + 1.0, eff_l + 1.0);
            }
        } else {
            if (use_grave_formula) {
                const double prior_p = 0.35 + 0.30 * (child.prior_bonus * 0.001);
                const double n_eff_mc = n_mc + pw;
                const double q_mc = n_eff_mc > 0.0 ? (w_mc + pw * prior_p) / n_eff_mc : 0.5;
                const double q_amaf = has_amaf ? (amaf_w / amaf_n) : 0.5;
                const double q = has_amaf ? ((1.0 - beta) * q_mc + beta * q_amaf) : q_mc;
                score = q + cfg.exploration * std::sqrt(log_parent / (n_mc + 1.0));
            } else if (child.visits == 0) {
                // Classic UCB / RAVE-UCB explores every unvisited child first (ordered by prior).
                score = 1e9 + child.prior_bonus;
            } else {
                double q = w_mc / n_mc;
                if (has_amaf) q = (1.0 - beta) * q + beta * (amaf_w / amaf_n);
                score = q + cfg.exploration * std::sqrt(log_parent / n_mc);
            }
        }
        if (score > best_score) {
            best_score = score;
            best = id;
        }
    }
    if (best < 0 && fallback_loss >= 0) return fallback_loss;
    if (best < 0) throw std::logic_error("Selection failed to choose a child.");
    return best;
}

std::uint64_t backpropagate(SearchTree& tree, const std::vector<Path>& path,
                            const std::vector<Action>& history, Colour winner, bool use_amaf,
                            bool use_solver = false) {
    std::uint64_t updates = 0;
    for (std::size_t idx = path.size(); idx-- > 0;) {
        const auto& entry = path[idx];
        Node& node = tree.arena[entry.node];
        ++node.visits;
        if (winner == node.to_play) ++node.wins;
        if (use_amaf && node.amaf_offset >= 0) {
            std::uint32_t* av = &tree.amaf_visits[node.amaf_offset];
            std::uint32_t* aw = &tree.amaf_wins[node.amaf_offset];
            const bool won = (winner == node.to_play);
            for (std::size_t i = entry.start; i < history.size(); ++i) {
                if (history[i].player != node.to_play) continue;
                const int move = history[i].move;
                ++av[move];
                if (won) ++aw[move];
                ++updates;
            }
        }
        // Bottom-up MCTS-Solver propagation:
        //   - Any child with PROVEN_LOSS (for child's player) => parent is PROVEN_WIN.
        //   - All children with PROVEN_WIN (and parent not truncated) => parent is PROVEN_LOSS.
        if (use_solver && !node.proven() && node.expanded() && node.child_count > 0) {
            bool any_child_loss = false;
            bool all_children_win = !node.truncated();
            const int first = node.first_child;
            const int end = first + node.child_count;
            for (int cid = first; cid < end; ++cid) {
                const Node& c = tree.arena[cid];
                if (c.proven_loss()) {
                    any_child_loss = true;
                    break;
                }
                if (!c.proven_win()) all_children_win = false;
            }
            if (any_child_loss) node.state |= NODE_PROVEN_WIN;
            else if (all_children_win) node.state |= NODE_PROVEN_LOSS;
        }
    }
    return updates;
}

struct WorkerResult {
    int id = 0;
    std::uint64_t seed = 0, iterations = 0, rave_updates = 0;
    std::uint64_t reused_nodes = 0, reused_visits = 0, dead_cells_pruned = 0, solver_cutoffs = 0;
    int nodes = 0, amaf_tables = 0;
    double seconds = 0;
    bool cap_reached = false, root_proven_win = false, root_proven_loss = false;
    std::array<std::uint64_t, MAX_CELLS> visits{}, wins{};
    std::array<std::int8_t, MAX_CELLS> proven{}; // +1: proven win for root, -1: proven loss for root
};

// Attempt to reuse the worker's previous search tree by matching 1 or 2 plies forward.
void prepare_worker_tree(SearchTree& tree, const Request& req, const Config& cfg,
                         int node_cap, int max_amaf_tables, WorkerResult& out) {
    if (cfg.tree_reuse && tree.valid && req.command == "CHANGE" &&
        tree.root_board.n == req.board.n && !tree.arena.empty()) {
        // Case A: 2 plies forward (our last move + opponent's reply).
        if (tree.last_decision_move >= 0 && req.last_move >= 0) {
            Board expected(req.board.n);
            expected.copy_from(tree.root_board);
            if (expected.colour[tree.last_decision_move] == EMPTY) {
                expected.play_unchecked(tree.last_decision_move, tree.root_player);
                if (expected.colour[req.last_move] == EMPTY) {
                    expected.play_unchecked(req.last_move, opposite(tree.root_player));
                    if (expected.same_stones(req.board)) {
                        const int c1 = tree.find_child(0, tree.last_decision_move);
                        const int c2 = c1 >= 0 ? tree.find_child(c1, req.last_move) : -1;
                        if (c2 >= 0 && tree.rebase_subtree(c2, req.board, req.player, node_cap, max_amaf_tables)) {
                            out.reused_nodes = tree.arena.size();
                            out.reused_visits = tree.arena[0].visits;
                            return;
                        }
                    }
                }
            }
        }
        // Case B: 1 ply forward (e.g. opponent moved right after a forced state).
        if (req.last_move >= 0) {
            Board expected(req.board.n);
            expected.copy_from(tree.root_board);
            if (expected.colour[req.last_move] == EMPTY) {
                expected.play_unchecked(req.last_move, tree.root_player);
                if (expected.same_stones(req.board)) {
                    const int c1 = tree.find_child(0, req.last_move);
                    if (c1 >= 0 && tree.rebase_subtree(c1, req.board, req.player, node_cap, max_amaf_tables)) {
                        out.reused_nodes = tree.arena.size();
                        out.reused_visits = tree.arena[0].visits;
                        return;
                    }
                }
            }
        }
    }
    tree.reset(req.board.cells);
    tree.arena.reserve(std::min(node_cap, 65536));
    Node root;
    root.move = -1;
    root.to_play = req.player;
    tree.arena.push_back(root);
    tree.root_board.copy_from(req.board);
    tree.root_player = req.player;
    tree.valid = true;
}

WorkerResult search_worker(SearchTree& tree, const Request& req, const Config& cfg, int worker,
                           std::uint64_t count, int node_cap, int max_amaf_tables,
                           Clock::time_point deadline) {
    const auto begin = Clock::now();
    std::uint64_t position_hash = mixed(static_cast<std::uint64_t>(req.board.n));
    for (int m = 0; m < req.board.cells; ++m)
        position_hash = mixed(position_hash ^ (static_cast<std::uint64_t>(req.board.colour[m] + 1) * (m + 1)));
    WorkerResult result;
    result.id = worker;
    result.seed = mixed(cfg.seed ^ position_hash ^ mixed(static_cast<std::uint64_t>(req.turn)) ^
                        mixed(worker + 1) ^ mixed(static_cast<std::uint64_t>(req.player) + 123));
    FastRng rng(result.seed);

    prepare_worker_tree(tree, req, cfg, node_cap, max_amaf_tables, result);
    const std::uint64_t dead_before = tree.dead_pruned;

    // Expand root immediately if budget permits (so even 1 iteration uses root children).
    if (!tree.arena[0].expanded() && count > 0) {
        expand_node(tree, 0, req.board, req.last_move, cfg, node_cap, max_amaf_tables, rng, result.cap_reached);
    }

    std::vector<Action> history;
    std::vector<Path> path;
    history.reserve(static_cast<std::size_t>(req.board.cells));
    path.reserve(static_cast<std::size_t>(req.board.cells) + 1);
    Board board(req.board.n);

    const bool use_grave = cfg.grave();
    const bool use_rave = cfg.rave();
    const bool use_lgr = cfg.lgr;
    const bool use_bridge = cfg.bridge;
    const bool use_solver = cfg.solver;
    const bool use_pat_rollout = cfg.pat_rollout;
    const auto pat_w = use_pat_rollout ? build_pattern_weights(cfg.pat_temp) : std::array<float, 729>{};

    for (std::uint64_t iteration = 0; iteration < count; ++iteration) {
        // Early stop in timed mode if root is mathematically solved (avoids spinning no-op cutoffs).
        if (use_solver && !cfg.explicit_iterations && tree.arena[0].proven()) break;
        // Check deadline periodically (every iteration when few iterations, or every 64 iterations
        // after the first few to keep steady_clock overhead negligible while staying responsive).
        if ((iteration & 63ULL) == 0ULL || iteration < 64ULL) {
            if (Clock::now() >= deadline) break;
        }
        board.copy_from(req.board);
        history.clear();
        path.clear();
        path.push_back({0, 0});
        int current = 0;
        int last_move = req.last_move;
        Colour winner = board.winner();
        std::int32_t ref_amaf[2] = {-1, -1};

        while (winner == EMPTY) {
            const Node& node = tree.arena[current];
            // Never short-circuit at root (current == 0); always descend so root children accumulate stats.
            if (current > 0 && use_solver && node.proven()) break;
            if (use_rave && node.amaf_offset >= 0) {
                if (!use_grave || node.visits >= static_cast<std::uint32_t>(cfg.grave_ref) ||
                    ref_amaf[node.to_play] < 0) {
                    ref_amaf[node.to_play] = node.amaf_offset;
                }
            }
            if (!node.expanded()) {
                if (!node.terminal() && node.visits >= static_cast<std::uint32_t>(cfg.expand_threshold)) {
                    if (expand_node(tree, current, board, last_move, cfg, node_cap, max_amaf_tables, rng, result.cap_reached,
                                    static_cast<int>(path.size()) - 1)) {
                        const Node& expanded_node = tree.arena[current];
                        if (use_rave && expanded_node.amaf_offset >= 0 &&
                            (!use_grave || ref_amaf[expanded_node.to_play] < 0)) {
                            ref_amaf[expanded_node.to_play] = expanded_node.amaf_offset;
                        }
                        if (expanded_node.child_count > 0) {
                            const std::int32_t amaf_src = use_grave ? ref_amaf[expanded_node.to_play] : expanded_node.amaf_offset;
                            const int child = select_child(tree, current, amaf_src, cfg, rng);
                            const Colour player = expanded_node.to_play;
                            const int move = tree.arena[child].move;
                            board.play_unchecked(move, player);
                            history.push_back({move, player});
                            last_move = move;
                            current = child;
                            path.push_back({current, history.size()});
                            winner = board.winner();
                        }
                    }
                }
                break;
            }
            if (node.child_count == 0) break;
            const std::int32_t amaf_src = use_grave ? ref_amaf[node.to_play] : node.amaf_offset;
            const int child = select_child(tree, current, amaf_src, cfg, rng);
            const Colour player = node.to_play;
            const int move = tree.arena[child].move;
            board.play_unchecked(move, player);
            history.push_back({move, player});
            last_move = move;
            current = child;
            path.push_back({current, history.size()});
            winner = board.winner();
        }

        if (winner != EMPTY) {
            Node& leaf = tree.arena[current];
            leaf.state |= NODE_TERMINAL;
            if (use_solver) {
                leaf.state |= (winner == leaf.to_play) ? NODE_PROVEN_WIN : NODE_PROVEN_LOSS;
            }
        } else if (use_solver && tree.arena[current].proven()) {
            const Node& leaf = tree.arena[current];
            winner = leaf.proven_win() ? leaf.to_play : opposite(leaf.to_play);
            ++result.solver_cutoffs;
        }

        const std::size_t rollout_start = history.size();
        Colour player = tree.arena[current].to_play;
        while (winner == EMPTY && board.empty_count > 0) {
            int move = use_bridge ? bridge_save(board, last_move, player) : -1;
            if (move < 0 && use_lgr && last_move >= 0) {
                const std::int16_t reply = tree.lgr[player][last_move];
                if (reply >= 0 && board.colour[reply] == EMPTY) move = reply;
            }
            if (move < 0 && use_pat_rollout) move = pattern_rollout_move(board, last_move, player, pat_w, rng);
            if (move < 0) move = board.empty[rng.next_bounded(board.empty_count)];
            board.play_unchecked(move, player);
            history.push_back({move, player});
            winner = board.winner();
            last_move = move;
            player = opposite(player);
        }
        if (winner == EMPTY) throw std::logic_error("A full Hex board must have a winner.");

        // Update LGRF-2 (Last-Good-Reply with Forgetting) from rollout continuations.
        if (use_lgr) {
            for (std::size_t i = rollout_start; i < history.size(); ++i) {
                const int prev = (i > 0) ? history[i - 1].move : req.last_move;
                if (prev < 0) continue;
                const Colour p = history[i].player;
                const auto m = static_cast<std::int16_t>(history[i].move);
                if (p == winner) {
                    tree.lgr[p][prev] = m;
                } else if (tree.lgr[p][prev] == m) {
                    tree.lgr[p][prev] = -1; // forget bad reply
                }
            }
        }

        result.rave_updates += backpropagate(tree, path, history, winner, use_rave, use_solver);
        ++result.iterations;
    }

    result.nodes = static_cast<int>(tree.arena.size());
    result.amaf_tables = tree.amaf_tables();
    result.dead_cells_pruned = tree.dead_pruned - dead_before;
    result.cap_reached = result.cap_reached || result.nodes >= node_cap;
    const Node& root = tree.arena[0];
    result.root_proven_win = root.proven_win();
    result.root_proven_loss = root.proven_loss();
    if (root.expanded() && root.first_child >= 0) {
        for (int i = 0; i < root.child_count; ++i) {
            const Node& child = tree.arena[root.first_child + i];
            result.visits[child.move] = child.visits;
            result.wins[child.move] = child.visits - child.wins;
            if (child.proven_loss()) result.proven[child.move] = 1;
            else if (child.proven_win()) result.proven[child.move] = -1;
        }
    }
    result.seconds = elapsed(begin);
    return result;
}

// ============================================================================
// Step 3: Lock-Free Shared-Tree Parallel MCTS with Virtual Loss
// ============================================================================
struct SharedNode {
    std::int16_t move = -1;
    Colour to_play = RED;
    std::atomic<std::uint8_t> state{0};
    std::atomic<std::uint32_t> visits{0};
    std::atomic<std::uint32_t> wins{0};
    std::atomic<std::uint16_t> vloss{0};
    std::uint16_t child_count = 0;
    std::uint16_t prior_bonus = 500;
    std::int32_t first_child = -1;
    std::int32_t amaf_offset = -1;

    inline void init(std::int16_t mv, Colour tp, std::uint16_t prior, std::uint8_t st = 0) {
        move = mv;
        to_play = tp;
        prior_bonus = prior;
        first_child = -1;
        child_count = 0;
        amaf_offset = -1;
        visits.store(0, std::memory_order_relaxed);
        wins.store(0, std::memory_order_relaxed);
        vloss.store(0, std::memory_order_relaxed);
        state.store(st, std::memory_order_relaxed);
    }
};

struct SharedSearchTree {
    int board_cells = 0;
    int node_cap = 0;
    int max_amaf_tables = 0;
    std::unique_ptr<SharedNode[]> nodes;
    std::unique_ptr<std::atomic<std::uint32_t>[]> amaf_visits;
    std::unique_ptr<std::atomic<std::uint32_t>[]> amaf_wins;
    std::atomic<int> node_count{0};
    std::atomic<int> amaf_count{0};
    std::atomic<std::uint64_t> dead_pruned{0};
    std::atomic<bool> cap_reached{false};
    bool valid = false;
    Board root_board;
    Colour root_player = RED;
    int last_decision_move = -1;

    void ensure_capacity(int want_nodes, int want_amaf_tables, int cells) {
        if (want_nodes > node_cap) {
            nodes.reset(new SharedNode[static_cast<std::size_t>(want_nodes)]);
            node_cap = want_nodes;
        }
        const std::size_t need_amaf = static_cast<std::size_t>(want_amaf_tables) * static_cast<std::size_t>(cells);
        const std::size_t cur_amaf = static_cast<std::size_t>(max_amaf_tables) * static_cast<std::size_t>(board_cells);
        if (need_amaf > cur_amaf && need_amaf > 0) {
            amaf_visits.reset(new std::atomic<std::uint32_t>[need_amaf]);
            amaf_wins.reset(new std::atomic<std::uint32_t>[need_amaf]);
        }
        max_amaf_tables = want_amaf_tables;
        board_cells = cells;
    }

    void reset(const Board& board, Colour player, int want_nodes, int want_amaf_tables) {
        ensure_capacity(want_nodes, want_amaf_tables, board.cells);
        node_count.store(1, std::memory_order_relaxed);
        amaf_count.store(0, std::memory_order_relaxed);
        dead_pruned.store(0, std::memory_order_relaxed);
        cap_reached.store(false, std::memory_order_relaxed);
        nodes[0].init(-1, player, 500, 0);
        root_board.copy_from(board);
        root_player = player;
        last_decision_move = -1;
        valid = true;
    }

    // Lock-free contiguous node range reservation (guaranteed <= active_node_cap).
    inline bool reserve_nodes(int want, int active_node_cap, int& first_out, int& got_out) {
        int cur = node_count.load(std::memory_order_relaxed);
        for (;;) {
            const int avail = active_node_cap - cur;
            if (avail <= 0) {
                cap_reached.store(true, std::memory_order_relaxed);
                return false;
            }
            const int take = std::min(want, avail);
            if (node_count.compare_exchange_weak(cur, cur + take, std::memory_order_relaxed)) {
                first_out = cur;
                got_out = take;
                if (take < want) cap_reached.store(true, std::memory_order_relaxed);
                return true;
            }
        }
    }

    // Lock-free AMAF slice allocation (zeroes only newly claimed slice -> lazy OS page commit).
    inline std::int32_t allocate_amaf(int active_amaf_cap) {
        if (active_amaf_cap <= 0 || !amaf_visits) return -1;
        int cur = amaf_count.load(std::memory_order_relaxed);
        for (;;) {
            if (cur >= active_amaf_cap) return -1;
            if (amaf_count.compare_exchange_weak(cur, cur + 1, std::memory_order_relaxed)) {
                const std::int32_t off = static_cast<std::int32_t>(cur * board_cells);
                for (int i = 0; i < board_cells; ++i) {
                    amaf_visits[off + i].store(0, std::memory_order_relaxed);
                    amaf_wins[off + i].store(0, std::memory_order_relaxed);
                }
                return off;
            }
        }
    }

    int find_child(int parent_id, int move) const {
        if (parent_id < 0 || parent_id >= node_count.load(std::memory_order_relaxed)) return -1;
        const SharedNode& p = nodes[parent_id];
        if ((p.state.load(std::memory_order_relaxed) & NODE_EXPANDED) == 0 || p.first_child < 0) return -1;
        for (int i = 0; i < p.child_count; ++i) {
            if (nodes[p.first_child + i].move == move) return p.first_child + i;
        }
        return -1;
    }

    // Single-threaded subtree compaction across turns (called before worker threads spawn).
    bool rebase_subtree(int sub_root, const Board& new_board, Colour new_player, int active_node_cap, int active_amaf_cap) {
        const int cur_nodes = node_count.load(std::memory_order_relaxed);
        if (sub_root < 0 || sub_root >= cur_nodes) return false;
        struct SnapNode {
            std::int16_t move;
            Colour to_play;
            std::uint8_t state;
            std::uint32_t visits, wins;
            std::int32_t first_child;
            std::uint16_t child_count, prior_bonus;
            std::int32_t amaf_offset;
        };
        std::vector<SnapNode> compacted;
        std::vector<std::uint32_t> new_av, new_aw;
        std::vector<int> old_queue;
        compacted.reserve(std::min(cur_nodes, active_node_cap));
        old_queue.reserve(1024);

        auto snapshot_of = [&](int id) -> SnapNode {
            const SharedNode& s = nodes[id];
            std::uint8_t st = static_cast<std::uint8_t>(s.state.load(std::memory_order_relaxed) & (~NODE_EXPANDING));
            return {s.move, s.to_play, st, s.visits.load(std::memory_order_relaxed),
                    s.wins.load(std::memory_order_relaxed), -1, 0, s.prior_bonus, -1};
        };

        SnapNode root_snap = snapshot_of(sub_root);
        root_snap.move = -1;
        if ((root_snap.state & NODE_TERMINAL) == 0) {
            root_snap.state &= static_cast<std::uint8_t>(~(NODE_EXPANDED | NODE_PROVEN_WIN | NODE_PROVEN_LOSS | NODE_TRUNCATED));
        } else {
            root_snap.state &= static_cast<std::uint8_t>(~NODE_EXPANDED);
        }
        compacted.push_back(root_snap);
        old_queue.push_back(sub_root);
        int amaf_used = 0;

        for (std::size_t qi = 0; qi < old_queue.size(); ++qi) {
            const int old_id = old_queue[qi];
            const SharedNode& old_n = nodes[old_id];
            const std::uint8_t old_st = old_n.state.load(std::memory_order_relaxed);
            if (old_n.amaf_offset >= 0 && amaf_used < active_amaf_cap && amaf_visits) {
                const auto off = static_cast<std::int32_t>(new_av.size());
                new_av.resize(new_av.size() + static_cast<std::size_t>(board_cells));
                new_aw.resize(new_aw.size() + static_cast<std::size_t>(board_cells));
                for (int k = 0; k < board_cells; ++k) {
                    new_av[off + k] = amaf_visits[old_n.amaf_offset + k].load(std::memory_order_relaxed);
                    new_aw[off + k] = amaf_wins[old_n.amaf_offset + k].load(std::memory_order_relaxed);
                }
                compacted[qi].amaf_offset = off;
                ++amaf_used;
            }
            if ((old_st & NODE_EXPANDED) != 0 && old_n.child_count > 0 &&
                static_cast<int>(compacted.size()) + old_n.child_count <= active_node_cap) {
                const auto first = static_cast<std::int32_t>(compacted.size());
                compacted[qi].first_child = first;
                compacted[qi].child_count = old_n.child_count;
                compacted[qi].state |= NODE_EXPANDED;
                if ((old_st & NODE_TRUNCATED) != 0) compacted[qi].state |= NODE_TRUNCATED;
                for (int c = 0; c < old_n.child_count; ++c) {
                    const int old_child = old_n.first_child + c;
                    SnapNode ch = snapshot_of(old_child);
                    if ((ch.state & NODE_EXPANDED) != 0) {
                        ch.state &= static_cast<std::uint8_t>(~(NODE_EXPANDED | NODE_PROVEN_WIN | NODE_PROVEN_LOSS | NODE_TRUNCATED));
                    }
                    compacted.push_back(ch);
                    old_queue.push_back(old_child);
                }
            } else if ((old_st & NODE_EXPANDED) == 0 && (old_st & (NODE_PROVEN_WIN | NODE_PROVEN_LOSS)) != 0) {
                compacted[qi].state = static_cast<std::uint8_t>(old_st & (~NODE_EXPANDING));
            }
        }
        // Bottom-up proven-flag recomputation for 100% parent-child consistency.
        for (std::size_t idx = compacted.size(); idx-- > 0;) {
            auto& nd = compacted[idx];
            if ((nd.state & NODE_EXPANDED) == 0 || nd.child_count == 0) continue;
            bool any_child_loss = false;
            bool all_children_win = (nd.state & NODE_TRUNCATED) == 0;
            for (int c = 0; c < nd.child_count; ++c) {
                const std::uint8_t cst = compacted[nd.first_child + c].state;
                if ((cst & NODE_PROVEN_LOSS) != 0) { any_child_loss = true; break; }
                if ((cst & NODE_PROVEN_WIN) == 0) all_children_win = false;
            }
            if (any_child_loss) nd.state |= NODE_PROVEN_WIN;
            else if (all_children_win) nd.state |= NODE_PROVEN_LOSS;
        }

        ensure_capacity(active_node_cap, active_amaf_cap, new_board.cells);
        for (std::size_t i = 0; i < compacted.size(); ++i) {
            const auto& s = compacted[i];
            nodes[i].move = s.move;
            nodes[i].to_play = s.to_play;
            nodes[i].first_child = s.first_child;
            nodes[i].child_count = s.child_count;
            nodes[i].prior_bonus = s.prior_bonus;
            nodes[i].amaf_offset = s.amaf_offset;
            nodes[i].visits.store(s.visits, std::memory_order_relaxed);
            nodes[i].wins.store(s.wins, std::memory_order_relaxed);
            nodes[i].vloss.store(0, std::memory_order_relaxed);
            nodes[i].state.store(s.state, std::memory_order_relaxed);
        }
        for (std::size_t k = 0; k < new_av.size(); ++k) {
            amaf_visits[k].store(new_av[k], std::memory_order_relaxed);
            amaf_wins[k].store(new_aw[k], std::memory_order_relaxed);
        }
        node_count.store(static_cast<int>(compacted.size()), std::memory_order_relaxed);
        amaf_count.store(amaf_used, std::memory_order_relaxed);
        cap_reached.store(false, std::memory_order_relaxed);
        root_board.copy_from(new_board);
        root_player = new_player;
        valid = true;
        return true;
    }
};

// Lock-free expansion of a SharedNode via atomic NODE_EXPANDING claim & release-store publish.
bool expand_node_shared(SharedSearchTree& tree, int node_id, const Board& board, int last_move,
                        const Config& cfg, int active_node_cap, int active_amaf_cap,
                        FastRng& rng, int depth = 0) {
    SharedNode& node = tree.nodes[node_id];
    const std::uint8_t cur_st = node.state.load(std::memory_order_acquire);
    if ((cur_st & NODE_EXPANDED) != 0) return true;
    if ((cur_st & (NODE_EXPANDING | NODE_TERMINAL | NODE_PROVEN_WIN | NODE_PROVEN_LOSS)) != 0) return false;

    const Colour w = board.winner();
    if (w != EMPTY || board.empty_count == 0) {
        std::uint8_t flags = NODE_TERMINAL;
        if (cfg.solver && w != EMPTY) flags |= (w == node.to_play) ? NODE_PROVEN_WIN : NODE_PROVEN_LOSS;
        node.state.fetch_or(flags, std::memory_order_release);
        return false;
    }
    // Atomically claim exclusive right to expand this node (other threads proceed directly to rollout).
    const std::uint8_t prev = node.state.fetch_or(NODE_EXPANDING, std::memory_order_acq_rel);
    if ((prev & (NODE_EXPANDED | NODE_EXPANDING | NODE_TERMINAL | NODE_PROVEN_WIN | NODE_PROVEN_LOSS)) != 0) {
        return (prev & NODE_EXPANDED) != 0;
    }

    const Colour player = node.to_play;
    const Colour opp = opposite(player);
    // Exact Disjoint-Carrier VC-Solver inside the shared tree (proves wins/losses 10-15 plies early).
    if (cfg.solver && node_id > 0 &&
        (board.cells - board.empty_count >= board.n) &&
        (depth <= 3 || board.empty_count <= 32)) {
        if (has_disjoint_vc_win(board, opp)) {
            node.state.store(NODE_TERMINAL | NODE_PROVEN_LOSS, std::memory_order_release);
            return false;
        }
        if (has_disjoint_vc_win(board, player)) {
            node.state.store(NODE_TERMINAL | NODE_PROVEN_WIN, std::memory_order_release);
            return false;
        }
    }
    // MCTS-Solver tactical expansion (1-ply win, >=2 opp threats loss, 1 opp threat mustplay).
    if (cfg.solver && (node_id > 0 || cfg.tactics) &&
        (board.cells - board.empty_count >= 2 * board.n - 3)) {
        const int win_move = tactical(board, player);
        if (win_move >= 0) {
            int first = -1, got = 0;
            if (tree.reserve_nodes(1, active_node_cap, first, got)) {
                tree.nodes[first].init(static_cast<std::int16_t>(win_move), opp, 1000, NODE_TERMINAL | NODE_PROVEN_LOSS);
                node.first_child = first;
                node.child_count = 1;
                if (cfg.rave() && node.amaf_offset < 0) node.amaf_offset = tree.allocate_amaf(active_amaf_cap);
                node.state.store(NODE_EXPANDED | NODE_PROVEN_WIN, std::memory_order_release);
                return true;
            }
            node.state.store(NODE_PROVEN_WIN, std::memory_order_release);
            return false;
        }
        int block_move = -1;
        const int opp_threats = count_threats(board, opp, block_move);
        if (opp_threats >= 2) {
            node.state.store(NODE_PROVEN_LOSS, std::memory_order_release);
            return false;
        }
        if (opp_threats == 1) {
            int first = -1, got = 0;
            if (tree.reserve_nodes(1, active_node_cap, first, got)) {
                tree.nodes[first].init(static_cast<std::int16_t>(block_move), opp, 990, 0);
                node.first_child = first;
                node.child_count = 1;
                if (cfg.rave() && node.amaf_offset < 0) node.amaf_offset = tree.allocate_amaf(active_amaf_cap);
                node.state.store(NODE_EXPANDED, std::memory_order_release);
                return true;
            }
            node.state.fetch_and(static_cast<std::uint8_t>(~NODE_EXPANDING), std::memory_order_release);
            return false;
        }
    }

    std::array<std::pair<std::uint16_t, int>, MAX_CELLS> candidates;
    int cand_count = 0;
    const int save_move = cfg.bridge ? bridge_save(board, last_move, player) : -1;
    TwoDistPotential td_storage;
    const TwoDistPotential* td_ptr = nullptr;
    if (cfg.ordering && cfg.two_dist && depth <= 4) {
        td_storage = compute_two_distance_potential(board);
        td_ptr = &td_storage;
    }
    std::uint64_t local_dead = 0;
    if (cfg.prune_dead) {
        for (int i = 0; i < board.empty_count; ++i) {
            const int m = board.empty[i];
            if (is_dead_cell(board, m)) {
                ++local_dead;
                continue;
            }
            const std::uint16_t prior = cfg.ordering ? compute_prior_bonus(board, m, player, last_move, save_move, td_ptr, cfg.pat_prior) : 500;
            candidates[cand_count++] = {prior, m};
        }
    }
    if (local_dead > 0) tree.dead_pruned.fetch_add(local_dead, std::memory_order_relaxed);
    if (cand_count == 0) {
        for (int i = 0; i < board.empty_count; ++i) {
            const int m = board.empty[i];
            const std::uint16_t prior = cfg.ordering ? compute_prior_bonus(board, m, player, last_move, save_move, td_ptr, cfg.pat_prior) : 500;
            candidates[cand_count++] = {prior, m};
        }
    }
    for (int i = cand_count - 1; i > 0; --i) {
        const int j = rng.next_bounded(i + 1);
        std::swap(candidates[i], candidates[j]);
    }
    int first = -1, got = 0;
    if (!tree.reserve_nodes(cand_count, active_node_cap, first, got)) {
        node.state.fetch_and(static_cast<std::uint8_t>(~NODE_EXPANDING), std::memory_order_release);
        return false;
    }
    const bool truncated = got < cand_count;
    if (truncated && cfg.ordering) {
        std::stable_sort(candidates.begin(), candidates.begin() + cand_count,
                         [](const auto& a, const auto& b) { return a.first > b.first; });
    }
    for (int i = 0; i < got; ++i) {
        tree.nodes[first + i].init(static_cast<std::int16_t>(candidates[i].second), opp, candidates[i].first, 0);
    }
    node.first_child = first;
    node.child_count = static_cast<std::uint16_t>(got);
    if (cfg.rave() && node.amaf_offset < 0) node.amaf_offset = tree.allocate_amaf(active_amaf_cap);
    std::uint8_t pub = NODE_EXPANDED | (truncated ? NODE_TRUNCATED : 0U);
    node.state.store(pub, std::memory_order_release);
    return true;
}

int select_child_shared(const SharedSearchTree& tree, int parent_id, std::int32_t amaf_base,
                        const Config& cfg, FastRng& rng) {
    const SharedNode& parent = tree.nodes[parent_id];
    if (parent.child_count == 0) throw std::logic_error("Selection on an empty shared node.");
    const bool use_rave = cfg.rave() && amaf_base >= 0 && tree.amaf_visits;
    const std::atomic<std::uint32_t>* av = use_rave ? &tree.amaf_visits[amaf_base] : nullptr;
    const std::atomic<std::uint32_t>* aw = use_rave ? &tree.amaf_wins[amaf_base] : nullptr;
    const bool use_grave_formula = cfg.rave_bias > 0.0;
    const std::uint32_t parent_v = parent.visits.load(std::memory_order_relaxed);
    const double log_parent = std::log(static_cast<double>(parent_v) + 1.0);
    const double classic_beta_val = use_rave && !use_grave_formula ? classic_rave_beta(parent_v, cfg) : 0.0;
    const double pw = cfg.prior_weight;
    const bool from_ancestor = use_rave && (amaf_base != parent.amaf_offset);
    const double amaf_cap = from_ancestor ? 32.0 : cfg.rave_k;

    int best = -1;
    double best_score = -std::numeric_limits<double>::infinity();
    int fallback_loss = -1;
    std::uint32_t fallback_visits = 0;
    const int first = parent.first_child;
    const int end = first + parent.child_count;

    for (int id = first; id < end; ++id) {
        const SharedNode& child = tree.nodes[id];
        if (cfg.solver) {
            const std::uint8_t cst = child.state.load(std::memory_order_relaxed);
            if ((cst & NODE_PROVEN_LOSS) != 0) return id;
            if ((cst & NODE_PROVEN_WIN) != 0) {
                const std::uint32_t cv = child.visits.load(std::memory_order_relaxed);
                if (fallback_loss < 0 || cv > fallback_visits) {
                    fallback_loss = id;
                    fallback_visits = cv;
                }
                continue;
            }
        }
        const std::uint32_t n_raw = child.visits.load(std::memory_order_relaxed);
        const std::uint32_t w_child = child.wins.load(std::memory_order_relaxed);
        const std::uint16_t vl = child.vloss.load(std::memory_order_relaxed);
        const std::uint32_t w_parent_raw = (n_raw >= w_child) ? (n_raw - w_child) : 0U;
        // Virtual loss penalizes in-flight branches so threads diversify across distinct moves.
        const double n_mc = static_cast<double>(n_raw) + 2.0 * static_cast<double>(vl);
        const double w_mc = static_cast<double>(w_parent_raw);
        std::uint32_t an_raw = 0, aw_raw = 0;
        if (use_rave) {
            an_raw = av[child.move].load(std::memory_order_relaxed);
            aw_raw = std::min(an_raw, aw[child.move].load(std::memory_order_relaxed));
        }
        const double amaf_n = static_cast<double>(an_raw);
        const double amaf_w = static_cast<double>(aw_raw);
        const bool has_amaf = use_rave && an_raw > 0U;
        double beta = 0.0;
        if (has_amaf) {
            beta = use_grave_formula
                ? amaf_n / (n_mc + amaf_n + cfg.rave_bias * n_mc * amaf_n)
                : classic_beta_val;
        }
        double score;
        if (cfg.thompson()) {
            if (cfg.policy == "legacy_ts") {
                const double mc_weight = n_mc / (1000.0 + n_mc);
                score = rng.sample_beta(mc_weight * w_mc + 1.0, mc_weight * (n_mc - w_mc) + 1.0);
            } else if (use_grave_formula) {
                const double prior_p = 0.35 + 0.30 * (child.prior_bonus * 0.001);
                const double n_eff_mc = n_mc + pw;
                const double q_mc = n_eff_mc > 0.0 ? (w_mc + pw * prior_p) / n_eff_mc : 0.5;
                const double q_amaf = has_amaf ? (amaf_w / amaf_n) : 0.5;
                const double q = has_amaf ? ((1.0 - beta) * q_mc + beta * q_amaf) : q_mc;
                const double eff_n = n_eff_mc + (has_amaf ? beta * std::min(amaf_n, amaf_cap) : 0.0);
                score = rng.sample_beta(1.0 + q * eff_n, 1.0 + (1.0 - q) * eff_n);
            } else {
                const double mc_weight = 1.0 - beta;
                const double eff_w = mc_weight * w_mc + (has_amaf ? beta * amaf_w : 0.0);
                const double eff_l = mc_weight * (n_mc - w_mc) + (has_amaf ? beta * (amaf_n - amaf_w) : 0.0);
                score = rng.sample_beta(eff_w + 1.0, eff_l + 1.0);
            }
        } else {
            if (use_grave_formula) {
                const double prior_p = 0.35 + 0.30 * (child.prior_bonus * 0.001);
                const double n_eff_mc = n_mc + pw;
                const double q_mc = n_eff_mc > 0.0 ? (w_mc + pw * prior_p) / n_eff_mc : 0.5;
                const double q_amaf = has_amaf ? (amaf_w / amaf_n) : 0.5;
                const double q = has_amaf ? ((1.0 - beta) * q_mc + beta * q_amaf) : q_mc;
                score = q + cfg.exploration * std::sqrt(log_parent / (n_mc + 1.0));
            } else if (n_raw == 0 && vl == 0) {
                score = 1e9 + child.prior_bonus;
            } else {
                const double denom = n_mc > 0.0 ? n_mc : 1.0;
                double q = w_mc / denom;
                if (has_amaf) q = (1.0 - beta) * q + beta * (amaf_w / amaf_n);
                score = q + cfg.exploration * std::sqrt(log_parent / denom);
            }
        }
        if (score > best_score) {
            best_score = score;
            best = id;
        }
    }
    if (best < 0 && fallback_loss >= 0) return fallback_loss;
    if (best < 0) throw std::logic_error("Selection failed to choose a shared child.");
    return best;
}

std::uint64_t backpropagate_shared(SharedSearchTree& tree, const std::vector<Path>& path,
                                   const std::vector<Action>& history, Colour winner,
                                   bool use_amaf, bool use_solver) {
    std::uint64_t updates = 0;
    for (std::size_t idx = path.size(); idx-- > 0;) {
        const auto& entry = path[idx];
        SharedNode& node = tree.nodes[entry.node];
        if (idx > 0) node.vloss.fetch_sub(1, std::memory_order_relaxed);
        node.visits.fetch_add(1, std::memory_order_relaxed);
        if (winner == node.to_play) node.wins.fetch_add(1, std::memory_order_relaxed);
        if (use_amaf && node.amaf_offset >= 0 && tree.amaf_visits) {
            std::atomic<std::uint32_t>* av = &tree.amaf_visits[node.amaf_offset];
            std::atomic<std::uint32_t>* aw = &tree.amaf_wins[node.amaf_offset];
            const bool won = (winner == node.to_play);
            for (std::size_t i = entry.start; i < history.size(); ++i) {
                if (history[i].player != node.to_play) continue;
                const int move = history[i].move;
                av[move].fetch_add(1, std::memory_order_relaxed);
                if (won) aw[move].fetch_add(1, std::memory_order_relaxed);
                ++updates;
            }
        }
        if (use_solver) {
            const std::uint8_t st = node.state.load(std::memory_order_acquire);
            if ((st & (NODE_PROVEN_WIN | NODE_PROVEN_LOSS)) == 0 &&
                (st & NODE_EXPANDED) != 0 && node.child_count > 0) {
                bool any_child_loss = false;
                bool all_children_win = (st & NODE_TRUNCATED) == 0;
                const int first = node.first_child;
                const int end = first + node.child_count;
                for (int cid = first; cid < end; ++cid) {
                    const std::uint8_t cst = tree.nodes[cid].state.load(std::memory_order_relaxed);
                    if ((cst & NODE_PROVEN_LOSS) != 0) {
                        any_child_loss = true;
                        break;
                    }
                    if ((cst & NODE_PROVEN_WIN) == 0) all_children_win = false;
                }
                if (any_child_loss) node.state.fetch_or(NODE_PROVEN_WIN, std::memory_order_release);
                else if (all_children_win) node.state.fetch_or(NODE_PROVEN_LOSS, std::memory_order_release);
            }
        }
    }
    return updates;
}

WorkerResult search_worker_shared(SharedSearchTree& tree, const Request& req, const Config& cfg, int worker,
                                  std::uint64_t count, int active_node_cap, int active_amaf_cap,
                                  Clock::time_point deadline,
                                  const std::atomic<bool>* external_stop = nullptr) {
    const auto begin = Clock::now();
    std::uint64_t position_hash = mixed(static_cast<std::uint64_t>(req.board.n));
    for (int m = 0; m < req.board.cells; ++m)
        position_hash = mixed(position_hash ^ (static_cast<std::uint64_t>(req.board.colour[m] + 1) * (m + 1)));
    WorkerResult result;
    result.id = worker;
    result.seed = mixed(cfg.seed ^ position_hash ^ mixed(static_cast<std::uint64_t>(req.turn)) ^
                        mixed(worker + 1) ^ mixed(static_cast<std::uint64_t>(req.player) + 123));
    FastRng rng(result.seed);

    std::vector<Action> history;
    std::vector<Path> path;
    history.reserve(static_cast<std::size_t>(req.board.cells));
    path.reserve(static_cast<std::size_t>(req.board.cells) + 1);
    Board board(req.board.n);
    std::array<std::array<std::int16_t, MAX_CELLS>, 2> local_lgr{};
    local_lgr[0].fill(-1);
    local_lgr[1].fill(-1);

    const bool use_grave = cfg.grave();
    const bool use_rave = cfg.rave();
    const bool use_lgr = cfg.lgr;
    const bool use_bridge = cfg.bridge;
    const bool use_solver = cfg.solver;
    const bool use_pat_rollout = cfg.pat_rollout;
    const auto pat_w = use_pat_rollout ? build_pattern_weights(cfg.pat_temp) : std::array<float, 729>{};

    for (std::uint64_t iteration = 0; iteration < count; ++iteration) {
        if (use_solver && !cfg.explicit_iterations &&
            (tree.nodes[0].state.load(std::memory_order_relaxed) & (NODE_PROVEN_WIN | NODE_PROVEN_LOSS)) != 0) break;
        if ((iteration & 63ULL) == 0ULL || iteration < 64ULL) {
            if (external_stop != nullptr) {
                if (external_stop->load(std::memory_order_acquire)) break;
                if (tree.node_count.load(std::memory_order_relaxed) >= active_node_cap - 256) break;
            }
            if (Clock::now() >= deadline) break;
        }
        board.copy_from(req.board);
        history.clear();
        path.clear();
        path.push_back({0, 0});
        int current = 0;
        int last_move = req.last_move;
        Colour winner = board.winner();
        std::int32_t ref_amaf[2] = {-1, -1};

        while (winner == EMPTY) {
            SharedNode& node = tree.nodes[current];
            const std::uint8_t st = node.state.load(std::memory_order_acquire);
            if (current > 0 && use_solver && (st & (NODE_PROVEN_WIN | NODE_PROVEN_LOSS)) != 0) break;
            if ((st & NODE_EXPANDED) != 0 && use_rave && node.amaf_offset >= 0) {
                if (!use_grave || node.visits.load(std::memory_order_relaxed) >= static_cast<std::uint32_t>(cfg.grave_ref) ||
                    ref_amaf[node.to_play] < 0) {
                    ref_amaf[node.to_play] = node.amaf_offset;
                }
            }
            if ((st & NODE_EXPANDED) == 0) {
                if ((st & (NODE_TERMINAL | NODE_EXPANDING | NODE_PROVEN_WIN | NODE_PROVEN_LOSS)) == 0 &&
                    node.visits.load(std::memory_order_relaxed) >= static_cast<std::uint32_t>(cfg.expand_threshold)) {
                    if (expand_node_shared(tree, current, board, last_move, cfg, active_node_cap, active_amaf_cap,
                                           rng, static_cast<int>(path.size()) - 1)) {
                        const std::uint8_t est = node.state.load(std::memory_order_acquire);
                        if ((est & NODE_EXPANDED) != 0 && node.child_count > 0) {
                            if (use_rave && node.amaf_offset >= 0 && (!use_grave || ref_amaf[node.to_play] < 0)) {
                                ref_amaf[node.to_play] = node.amaf_offset;
                            }
                            const std::int32_t amaf_src = use_grave ? ref_amaf[node.to_play] : node.amaf_offset;
                            const int child = select_child_shared(tree, current, amaf_src, cfg, rng);
                            tree.nodes[child].vloss.fetch_add(1, std::memory_order_relaxed);
                            const Colour player = node.to_play;
                            const int move = tree.nodes[child].move;
                            board.play_unchecked(move, player);
                            history.push_back({move, player});
                            last_move = move;
                            current = child;
                            path.push_back({current, history.size()});
                            winner = board.winner();
                        }
                    }
                }
                break;
            }
            if (node.child_count == 0) break;
            const std::int32_t amaf_src = use_grave ? ref_amaf[node.to_play] : node.amaf_offset;
            const int child = select_child_shared(tree, current, amaf_src, cfg, rng);
            tree.nodes[child].vloss.fetch_add(1, std::memory_order_relaxed);
            const Colour player = node.to_play;
            const int move = tree.nodes[child].move;
            board.play_unchecked(move, player);
            history.push_back({move, player});
            last_move = move;
            current = child;
            path.push_back({current, history.size()});
            winner = board.winner();
        }

        if (winner != EMPTY) {
            SharedNode& leaf = tree.nodes[current];
            std::uint8_t flags = NODE_TERMINAL;
            if (use_solver) flags |= (winner == leaf.to_play) ? NODE_PROVEN_WIN : NODE_PROVEN_LOSS;
            leaf.state.fetch_or(flags, std::memory_order_release);
        } else if (use_solver) {
            const SharedNode& leaf = tree.nodes[current];
            const std::uint8_t lst = leaf.state.load(std::memory_order_relaxed);
            if ((lst & (NODE_PROVEN_WIN | NODE_PROVEN_LOSS)) != 0) {
                winner = ((lst & NODE_PROVEN_WIN) != 0) ? leaf.to_play : opposite(leaf.to_play);
                ++result.solver_cutoffs;
            }
        }

        const std::size_t rollout_start = history.size();
        Colour player = tree.nodes[current].to_play;
        while (winner == EMPTY && board.empty_count > 0) {
            int move = use_bridge ? bridge_save(board, last_move, player) : -1;
            if (move < 0 && use_lgr && last_move >= 0) {
                const std::int16_t reply = local_lgr[player][last_move];
                if (reply >= 0 && board.colour[reply] == EMPTY) move = reply;
            }
            if (move < 0 && use_pat_rollout) move = pattern_rollout_move(board, last_move, player, pat_w, rng);
            if (move < 0) move = board.empty[rng.next_bounded(board.empty_count)];
            board.play_unchecked(move, player);
            history.push_back({move, player});
            winner = board.winner();
            last_move = move;
            player = opposite(player);
        }
        if (winner == EMPTY) throw std::logic_error("A full Hex board must have a winner.");

        if (use_lgr) {
            for (std::size_t i = rollout_start; i < history.size(); ++i) {
                const int prev = (i > 0) ? history[i - 1].move : req.last_move;
                if (prev < 0) continue;
                const Colour p = history[i].player;
                const auto m = static_cast<std::int16_t>(history[i].move);
                if (p == winner) local_lgr[p][prev] = m;
                else if (local_lgr[p][prev] == m) local_lgr[p][prev] = -1;
            }
        }

        result.rave_updates += backpropagate_shared(tree, path, history, winner, use_rave, use_solver);
        ++result.iterations;
    }

    result.seconds = elapsed(begin);
    return result;
}

void prepare_shared_tree(SharedSearchTree& tree, const Request& req, const Config& cfg,
                         int active_node_cap, int active_amaf_cap,
                         std::uint64_t& reused_nodes, std::uint64_t& reused_visits) {
    reused_nodes = 0;
    reused_visits = 0;
    if (cfg.tree_reuse && tree.valid && req.command == "CHANGE" &&
        tree.root_board.n == req.board.n && tree.node_count.load(std::memory_order_relaxed) > 0) {
        if (tree.last_decision_move >= 0 && req.last_move >= 0) {
            Board expected(req.board.n);
            expected.copy_from(tree.root_board);
            if (expected.colour[tree.last_decision_move] == EMPTY) {
                expected.play_unchecked(tree.last_decision_move, tree.root_player);
                if (expected.colour[req.last_move] == EMPTY) {
                    expected.play_unchecked(req.last_move, opposite(tree.root_player));
                    if (expected.same_stones(req.board)) {
                        const int c1 = tree.find_child(0, tree.last_decision_move);
                        const int c2 = c1 >= 0 ? tree.find_child(c1, req.last_move) : -1;
                        if (c2 >= 0 && tree.rebase_subtree(c2, req.board, req.player, active_node_cap, active_amaf_cap)) {
                            reused_nodes = static_cast<std::uint64_t>(tree.node_count.load(std::memory_order_relaxed));
                            reused_visits = tree.nodes[0].visits.load(std::memory_order_relaxed);
                            return;
                        }
                    }
                }
            }
        }
        if (req.last_move >= 0) {
            Board expected(req.board.n);
            expected.copy_from(tree.root_board);
            if (expected.colour[req.last_move] == EMPTY) {
                expected.play_unchecked(req.last_move, tree.root_player);
                if (expected.same_stones(req.board)) {
                    const int c1 = tree.find_child(0, req.last_move);
                    if (c1 >= 0 && tree.rebase_subtree(c1, req.board, req.player, active_node_cap, active_amaf_cap)) {
                        reused_nodes = static_cast<std::uint64_t>(tree.node_count.load(std::memory_order_relaxed));
                        reused_visits = tree.nodes[0].visits.load(std::memory_order_relaxed);
                        return;
                    }
                }
            }
        }
    }
    tree.reset(req.board, req.player, active_node_cap, active_amaf_cap);
}

struct Decision {
    int move = -1;
    std::string reason;
    std::string solver_status = "none";
    bool used_shared_tree = false;
    std::uint64_t iterations = 0, rave_updates = 0, chosen_visits = 0, chosen_wins = 0;
    std::uint64_t reused_nodes = 0, reused_visits = 0, dead_cells_pruned = 0, solver_cutoffs = 0;
    int nodes = 0, amaf_tables = 0, effective_node_cap = 0;
    double seconds = 0;
    double effective_allowance = 0;
    std::vector<WorkerResult> workers;
};

struct EngineSession {
    std::vector<SearchTree> trees;
    SharedSearchTree shared_tree;
    void reset() {
        for (auto& t : trees) t.valid = false;
        shared_tree.valid = false;
    }
};

struct PonderController {
    std::atomic<bool> stop{false};
    std::atomic<std::uint64_t> iterations{0};
    std::vector<std::thread> threads;
    bool active = false;

    ~PonderController() { stop_and_join(); }

    std::uint64_t stop_and_join() {
        if (!active) return 0;
        stop.store(true, std::memory_order_release);
        for (auto& t : threads) {
            if (t.joinable()) t.join();
        }
        threads.clear();
        active = false;
        return iterations.load(std::memory_order_relaxed);
    }

    void start(EngineSession& session, const Request& req, const Config& cfg) {
        stop_and_join();
        if (!cfg.tree_reuse || req.board.winner() != EMPTY || req.board.empty_count <= 1) return;
        const double total_bytes = cfg.memory_mb * 1024.0 * 1024.0;
        const double node_bytes_share = cfg.rave() ? 0.35 * total_bytes : 0.90 * total_bytes;
        const int memory_nodes = static_cast<int>(std::min(20000000.0, node_bytes_share / static_cast<double>(sizeof(SharedNode))));
        const int full_node_cap = std::max(cfg.workers, std::min(cfg.node_cap, memory_nodes));
        const int ponder_node_cap = std::max(4096, (full_node_cap * 85) / 100);
        const std::size_t amaf_table_bytes = static_cast<std::size_t>(req.board.cells) * 2 * sizeof(std::uint32_t);
        const int total_amaf_tables = cfg.rave()
            ? std::max(cfg.workers, static_cast<int>((0.65 * total_bytes) / static_cast<double>(amaf_table_bytes)))
            : 0;

        SharedSearchTree& stree = session.shared_tree;
        std::uint64_t reused_n = 0, reused_v = 0;
        prepare_shared_tree(stree, req, cfg, full_node_cap, total_amaf_tables, reused_n, reused_v);
        if ((stree.nodes[0].state.load(std::memory_order_relaxed) & NODE_EXPANDED) == 0) {
            FastRng root_rng(mixed(cfg.seed ^ 0x9E3779B97F4A7C15ULL ^ static_cast<std::uint64_t>(req.turn)));
            expand_node_shared(stree, 0, req.board, req.last_move, cfg, full_node_cap, total_amaf_tables, root_rng, 0);
        }
        if ((stree.nodes[0].state.load(std::memory_order_relaxed) & (NODE_PROVEN_WIN | NODE_PROVEN_LOSS)) != 0) return;

        // Clear last_decision_move because the tree is now already rooted at the opponent's turn;
        // on the next V3 request, prepare_shared_tree's 1-ply rebase matches the opponent's reply directly.
        stree.last_decision_move = -1;
        stree.valid = true;

        stop.store(false, std::memory_order_release);
        iterations.store(0, std::memory_order_relaxed);
        const int n_threads = std::max(1, cfg.workers > 2 ? cfg.workers - 2 : cfg.workers);
        const auto deadline = Clock::now() + std::chrono::hours(1);
        Config ponder_cfg = cfg;
        ponder_cfg.explicit_iterations = false;
        ponder_cfg.iterations = 1000000000ULL;
        const Request req_copy = req;

        threads.reserve(static_cast<std::size_t>(n_threads));
        for (int w = 0; w < n_threads; ++w) {
            threads.emplace_back([&, w, req_copy, ponder_cfg, ponder_node_cap, total_amaf_tables, deadline]() {
                try {
                    auto r = search_worker_shared(stree, req_copy, ponder_cfg, w + 100, 1000000000ULL,
                                                  ponder_node_cap, total_amaf_tables, deadline, &stop);
                    iterations.fetch_add(r.iterations, std::memory_order_relaxed);
                } catch (...) {}
            });
        }
        active = true;
    }
};

Decision decide(const Request& req, const Config& cfg, double already_used, EngineSession* session = nullptr) {
    const auto begin = Clock::now();
    if (req.board.winner() != EMPTY) throw std::invalid_argument("Terminal board: no move is legal after the game ends.");
    if (req.board.empty_count == 0) throw std::invalid_argument("Full board: no legal move remains.");
    Decision result;
    if (cfg.opening_book && cfg.swap && !cfg.explicit_iterations &&
        req.turn == 1 && req.player == RED && req.board.n == 11 &&
        req.board.empty_count == req.board.cells) {
        if (session) session->reset();
        result.move = pie_rule_opening_11x11(cfg.seed);
        result.reason = "pie_rule_opening_book";
        result.seconds = elapsed(begin);
        return result;
    }
    if (cfg.swap && req.turn == 2 && req.player == BLUE && req.board.empty_count == req.board.cells - 1 && req.last_move >= 0) {
        if (should_swap(req.board, req.last_move)) {
            if (session) session->reset();
            result.reason = "pie_rule_swap";
            result.seconds = elapsed(begin);
            return result;
        }
    }
    CellBitSet root_vc_mustplay;
    int root_vc_mp_count = 0;
    if (cfg.tactics) {
        result.move = cfg.win_check ? tactical(req.board, req.player) : -1;
        if (result.move >= 0) {
            if (session) session->reset();
            result.reason = "tactical_win";
            result.solver_status = "proven_win";
            result.seconds = elapsed(begin);
            return result;
        }
        result.move = cfg.block_check ? tactical(req.board, opposite(req.player)) : -1;
        if (result.move >= 0) {
            if (session) session->reset();
            result.reason = "tactical_block";
            result.seconds = elapsed(begin);
            return result;
        }
        if (cfg.solver) {
            if (cfg.win_check) {
                const int vc_win = find_vc_win_move(req.board, req.player);
                if (vc_win >= 0) {
                    if (session) session->reset();
                    result.move = vc_win;
                    result.reason = "vc_proven_win";
                    result.solver_status = "proven_win";
                    result.seconds = elapsed(begin);
                    return result;
                }
            }
            if (cfg.block_check) {
                root_vc_mp_count = compute_vc_mustplay(req.board, opposite(req.player), root_vc_mustplay);
                if (root_vc_mp_count == 1) {
                    for (int i = 0; i < req.board.empty_count; ++i) {
                        const int m = req.board.empty[i];
                        if (root_vc_mustplay.test(m)) {
                            if (session) session->reset();
                            result.move = m;
                            result.reason = "vc_mustplay_forced";
                            result.seconds = elapsed(begin);
                            return result;
                        }
                    }
                }
            }
        }
    }
    double remaining = std::max(0.0, cfg.game_seconds - already_used);
    if (req.external_remaining >= 0) remaining = std::min(remaining, req.external_remaining);
    double allowance = cfg.seconds > 0 ? std::min(cfg.seconds, remaining) : remaining;
    if (req.move_allowance >= 0) allowance = std::min(allowance, req.move_allowance);
    result.effective_allowance = allowance;
    // Reserve a small part of a finite wall-clock budget for aggregation and serialization.
    const double margin = std::min(0.010, allowance * 0.05);
    auto deadline = begin + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(std::max(0.0, allowance - margin)));

    // Compact memory budget: reserve ~35% for compact nodes and ~65% for lazy AMAF tables.
    const bool use_shared = cfg.use_shared_tree(req);
    const double total_bytes = cfg.memory_mb * 1024.0 * 1024.0;
    const double node_bytes_share = cfg.rave() ? 0.35 * total_bytes : 0.90 * total_bytes;
    const std::size_t node_sz = use_shared ? sizeof(SharedNode) : sizeof(Node);
    const int memory_nodes = static_cast<int>(std::min(20000000.0, node_bytes_share / static_cast<double>(node_sz)));
    result.effective_node_cap = std::max(cfg.workers, std::min(cfg.node_cap, memory_nodes));
    result.used_shared_tree = use_shared;

    const std::size_t amaf_table_bytes = static_cast<std::size_t>(req.board.cells) * 2 * sizeof(std::uint32_t);
    const int total_amaf_tables = cfg.rave()
        ? std::max(cfg.workers, static_cast<int>((0.65 * total_bytes) / static_cast<double>(amaf_table_bytes)))
        : 0;

    EngineSession local_session;
    EngineSession& active = session ? *session : local_session;

    result.workers.resize(cfg.workers);
    std::vector<std::thread> threads;
    std::vector<std::exception_ptr> failures(cfg.workers);
    threads.reserve(cfg.workers);

    std::array<std::uint64_t, MAX_CELLS> visits{}, wins{};
    std::array<std::int8_t, MAX_CELLS> proven{};
    bool any_root_win = false, any_root_loss = false;

    if (use_shared) {
        SharedSearchTree& stree = active.shared_tree;
        prepare_shared_tree(stree, req, cfg, result.effective_node_cap, total_amaf_tables,
                            result.reused_nodes, result.reused_visits);
        const std::uint64_t dead_before = stree.dead_pruned.load(std::memory_order_relaxed);
        // Expand root single-threaded before launching parallel workers.
        if ((stree.nodes[0].state.load(std::memory_order_relaxed) & NODE_EXPANDED) == 0 && cfg.iterations > 0) {
            FastRng root_rng(mixed(cfg.seed ^ static_cast<std::uint64_t>(req.turn) ^ 0x51a7eULL));
            expand_node_shared(stree, 0, req.board, req.last_move, cfg, result.effective_node_cap, total_amaf_tables, root_rng, 0);
        }
        // Apply proven VC-Mustplay pruning at root: every child outside root_vc_mustplay
        // hands opponent a proven disjoint-carrier VC win, so mark it NODE_PROVEN_WIN (for opp).
        if (root_vc_mp_count > 1 && (stree.nodes[0].state.load(std::memory_order_relaxed) & NODE_EXPANDED) != 0) {
            const int first = stree.nodes[0].first_child;
            const int cnt = stree.nodes[0].child_count;
            int kept = 0;
            for (int i = 0; i < cnt; ++i) {
                if (root_vc_mustplay.test(stree.nodes[first + i].move)) ++kept;
            }
            if (kept > 0) {
                for (int i = 0; i < cnt; ++i) {
                    if (!root_vc_mustplay.test(stree.nodes[first + i].move)) {
                        stree.nodes[first + i].state.fetch_or(NODE_PROVEN_WIN, std::memory_order_release);
                    }
                }
            }
        }
        try {
            for (int worker = 0; worker < cfg.workers; ++worker) {
                const std::uint64_t count = cfg.iterations / cfg.workers +
                    (static_cast<std::uint64_t>(worker) < cfg.iterations % cfg.workers ? 1 : 0);
                threads.emplace_back([&, worker, count] {
                    try {
                        result.workers[worker] = search_worker_shared(stree, req, cfg, worker, count,
                                                                      result.effective_node_cap, total_amaf_tables, deadline);
                    } catch (...) {
                        failures[worker] = std::current_exception();
                    }
                });
            }
        } catch (...) {
            for (auto& t : threads) if (t.joinable()) t.join();
            throw;
        }
        for (auto& t : threads) t.join();
        for (const auto& failure : failures) if (failure) std::rethrow_exception(failure);

        const int total_nodes = stree.node_count.load(std::memory_order_relaxed);
        const int total_amaf = stree.amaf_count.load(std::memory_order_relaxed);
        const bool shared_cap = stree.cap_reached.load(std::memory_order_relaxed) || total_nodes >= result.effective_node_cap;
        for (auto& worker : result.workers) {
            worker.nodes = total_nodes;
            worker.amaf_tables = total_amaf;
            worker.cap_reached = shared_cap;
            result.iterations += worker.iterations;
            result.rave_updates += worker.rave_updates;
            result.solver_cutoffs += worker.solver_cutoffs;
        }
        result.nodes = total_nodes;
        result.amaf_tables = total_amaf;
        result.dead_cells_pruned = stree.dead_pruned.load(std::memory_order_relaxed) - dead_before;
        const SharedNode& root = stree.nodes[0];
        const std::uint8_t rst = root.state.load(std::memory_order_relaxed);
        any_root_win = (rst & NODE_PROVEN_WIN) != 0;
        any_root_loss = (rst & NODE_PROVEN_LOSS) != 0;
        if ((rst & NODE_EXPANDED) != 0 && root.first_child >= 0) {
            for (int i = 0; i < root.child_count; ++i) {
                const SharedNode& ch = stree.nodes[root.first_child + i];
                const std::uint32_t cv = ch.visits.load(std::memory_order_relaxed);
                const std::uint32_t cw = ch.wins.load(std::memory_order_relaxed);
                visits[ch.move] = cv;
                wins[ch.move] = (cv >= cw) ? (cv - cw) : 0U;
                const std::uint8_t cst = ch.state.load(std::memory_order_relaxed);
                if ((cst & NODE_PROVEN_LOSS) != 0) proven[ch.move] = 1;
                else if ((cst & NODE_PROVEN_WIN) != 0) proven[ch.move] = -1;
            }
        }
    } else {
        if (static_cast<int>(active.trees.size()) != cfg.workers) {
            active.trees.clear();
            active.trees.resize(cfg.workers);
        }
        try {
            for (int worker = 0; worker < cfg.workers; ++worker) {
                const std::uint64_t count = cfg.iterations / cfg.workers +
                    (static_cast<std::uint64_t>(worker) < cfg.iterations % cfg.workers ? 1 : 0);
                const int cap = result.effective_node_cap / cfg.workers +
                    (worker < result.effective_node_cap % cfg.workers ? 1 : 0);
                const int amaf_cap = total_amaf_tables / cfg.workers +
                    (worker < total_amaf_tables % cfg.workers ? 1 : 0);
                if (cfg.workers == 1) {
                    result.workers[0] = search_worker(active.trees[0], req, cfg, 0, count, cap, amaf_cap, deadline);
                } else {
                    threads.emplace_back([&, worker, count, cap, amaf_cap] {
                        try {
                            result.workers[worker] = search_worker(active.trees[worker], req, cfg, worker, count, cap, amaf_cap, deadline);
                        } catch (...) {
                            failures[worker] = std::current_exception();
                        }
                    });
                }
            }
        } catch (...) {
            for (auto& t : threads) if (t.joinable()) t.join();
            throw;
        }
        for (auto& t : threads) t.join();
        for (const auto& failure : failures) if (failure) std::rethrow_exception(failure);

        for (const auto& worker : result.workers) {
            result.iterations += worker.iterations;
            result.nodes += worker.nodes;
            result.amaf_tables += worker.amaf_tables;
            result.rave_updates += worker.rave_updates;
            result.reused_nodes += worker.reused_nodes;
            result.reused_visits += worker.reused_visits;
            result.dead_cells_pruned += worker.dead_cells_pruned;
            result.solver_cutoffs += worker.solver_cutoffs;
            any_root_win = any_root_win || worker.root_proven_win;
            any_root_loss = any_root_loss || worker.root_proven_loss;
            for (int move = 0; move < req.board.cells; ++move) {
                visits[move] += worker.visits[move];
                wins[move] += worker.wins[move];
                if (worker.proven[move] > 0) proven[move] = 1;
                else if (worker.proven[move] < 0 && proven[move] == 0) proven[move] = -1;
            }
        }
    }
    if (any_root_win) result.solver_status = "proven_win";
    else if (any_root_loss) result.solver_status = "proven_loss";
    result.move = -1;
    for (int move = 0; move < req.board.cells; ++move) {
        if (req.board.colour[move] != EMPTY) continue;
        if (result.move < 0) { result.move = move; continue; }
        const int pm = cfg.solver ? proven[move] : 0;
        const int pb = cfg.solver ? proven[result.move] : 0;
        if (pm != pb) {
            if (pm > pb) result.move = move;
            continue;
        }
        if (visits[move] > visits[result.move] ||
            (visits[move] == visits[result.move] && wins[move] > wins[result.move])) result.move = move;
    }
    if (result.move < 0) throw std::logic_error("Search did not produce a legal action.");
    if (use_shared) active.shared_tree.last_decision_move = result.move;
    else for (auto& t : active.trees) t.last_decision_move = result.move;
    result.chosen_visits = visits[result.move];
    result.chosen_wins = wins[result.move];
    result.reason = (result.iterations == 0 && result.solver_status == "none") ? "budget_exhausted_fallback" :
        ((result.chosen_visits == 0 && result.solver_status == "none") ? "node_cap_fallback" : "search");
    result.seconds = elapsed(begin);
    return result;
}

std::string json_quote(const std::string& value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(c) << std::dec;
        else out << c;
    }
    out << '"';
    return out.str();
}

void diagnostics(const Request& req, const Config& cfg, const Decision& d, double game_used) {
    std::cerr << std::setprecision(10) << "{\"kind\":\"hex_search_move\",\"version\":\"1.2.0\",\"policy\":" << json_quote(cfg.policy)
              << ",\"turn\":" << req.turn << ",\"colour\":\"" << (req.player == RED ? 'R' : 'B')
              << "\",\"seed\":" << cfg.seed << ",\"move\":[" << (d.move < 0 ? -1 : d.move / req.board.n)
              << ',' << (d.move < 0 ? -1 : d.move % req.board.n) << "],\"reason\":" << json_quote(d.reason)
              << ",\"iterations\":" << d.iterations << ",\"nodes\":" << d.nodes
              << ",\"amaf_tables\":" << d.amaf_tables << ",\"rave_updates\":" << d.rave_updates
              << ",\"reused_nodes\":" << d.reused_nodes << ",\"reused_visits\":" << d.reused_visits
              << ",\"dead_cells_pruned\":" << d.dead_cells_pruned
              << ",\"solver_status\":" << json_quote(d.solver_status)
              << ",\"solver_cutoffs\":" << d.solver_cutoffs
              << ",\"shared_tree\":" << (d.used_shared_tree ? "true" : "false")
              << ",\"seconds\":" << d.seconds << ",\"game_seconds_used\":" << game_used
              << ",\"protocol\":" << json_quote(req.move_allowance >= 0 ? "V3" : "V2")
              << ",\"requested_allowance_seconds\":" << req.move_allowance
              << ",\"external_remaining_seconds\":" << req.external_remaining
              << ",\"effective_search_allowance_seconds\":" << d.effective_allowance
              << ",\"node_cap\":" << d.effective_node_cap << ",\"chosen_visits\":" << d.chosen_visits
              << ",\"chosen_wins\":" << d.chosen_wins << ",\"workers\":[";
    bool first = true;
    for (const auto& w : d.workers) {
        if (!first) std::cerr << ',';
        first = false;
        std::cerr << "{\"id\":" << w.id << ",\"seed\":" << w.seed << ",\"iterations\":" << w.iterations
                  << ",\"nodes\":" << w.nodes << ",\"amaf_tables\":" << w.amaf_tables
                  << ",\"rave_updates\":" << w.rave_updates << ",\"reused_nodes\":" << w.reused_nodes
                  << ",\"seconds\":" << w.seconds
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
            int ax = x + RING_DX[k], ay = y + RING_DY[k], next = ax * board.n + ay;
            if (board.inside(ax, ay) && !seen[next] && board.colour[next] == player) { seen[next] = true; queue.push(next); }
        }
    }
    return false;
}

void require(bool value, const std::string& message) {
    if (!value) throw std::logic_error("Self-test: " + message);
}

void self_test() {
    int checks = 0;
    // 1. Exhaustive connectivity oracle on all 3^9 = 19,683 3x3 boards.
    // 2. Formal soundness proof of is_dead_cell() across all nonterminal 3x3 boards & all completions.
    std::uint64_t dead_cell_verifications = 0;
    for (int encoded = 0; encoded < 19683; ++encoded) {
        Board board(3);
        int value = encoded;
        for (int move = 0; move < 9; ++move) {
            int col = value % 3;
            value /= 3;
            if (col != 2) board.play(move, static_cast<Colour>(col));
        }
        require(board.wins(RED) == oracle_win(board, RED), "red connectivity oracle");
        require(board.wins(BLUE) == oracle_win(board, BLUE), "blue connectivity oracle");
        if (board.winner() == EMPTY) {
            for (int c = 0; c < 9; ++c) {
                if (board.colour[c] == EMPTY && is_dead_cell(board, c)) {
                    // Verify EVERY completion of remaining empty cells yields the identical winner
                    // regardless of whether cell c is RED or BLUE.
                    std::vector<int> others;
                    for (int m = 0; m < 9; ++m) if (m != c && board.colour[m] == EMPTY) others.push_back(m);
                    const int combos = 1 << static_cast<int>(others.size());
                    for (int mask = 0; mask < combos; ++mask) {
                        Board as_red(3), as_blue(3);
                        as_red.copy_from(board);
                        as_blue.copy_from(board);
                        as_red.play(c, RED);
                        as_blue.play(c, BLUE);
                        for (std::size_t bit = 0; bit < others.size(); ++bit) {
                            const Colour col = ((mask >> bit) & 1) ? BLUE : RED;
                            as_red.play(others[bit], col);
                            as_blue.play(others[bit], col);
                        }
                        require(as_red.winner() == as_blue.winner(), "dead cell altered completion winner");
                    }
                    ++dead_cell_verifications;
                }
            }
        }
    }
    require(dead_cell_verifications > 0, "dead cell detector must identify dead cells on 3x3");
    checks += 2;

    // 3. AMAF backpropagation perspective & same-player suffix check.
    Config cfg;
    cfg.policy = "rave_ts";
    cfg.finalize_defaults();
    cfg.ordering = false;
    cfg.swap = false;
    FastRng rng(42);
    SearchTree tree;
    tree.reset(9);
    Node n0; n0.to_play = RED; n0.amaf_offset = tree.allocate_amaf(10);
    Node n1; n1.to_play = BLUE; n1.move = 0; n1.amaf_offset = tree.allocate_amaf(10);
    tree.arena = {n0, n1};
    std::vector<Path> path{{0, 0}, {1, 1}};
    std::vector<Action> history{{0, RED}, {1, BLUE}, {2, RED}, {3, BLUE}};
    require(backpropagate(tree, path, history, BLUE, true) == 4, "AMAF update count");
    require(tree.amaf_visits[tree.arena[0].amaf_offset + 0] == 1 &&
            tree.amaf_visits[tree.arena[0].amaf_offset + 2] == 1 &&
            tree.amaf_visits[tree.arena[0].amaf_offset + 1] == 0, "AMAF same-player suffix");
    require(tree.amaf_wins[tree.arena[0].amaf_offset + 0] == 0 &&
            tree.amaf_wins[tree.arena[1].amaf_offset + 1] == 1 &&
            tree.amaf_wins[tree.arena[1].amaf_offset + 3] == 1, "AMAF winner perspective");
    require(tree.arena[0].wins == 0 && tree.arena[1].wins == 1, "node-to-play reward perspective");
    ++checks;

    // 4. Parent-child reward inversion (both Red and Blue maximize own win rate).
    Config ucb = cfg;
    ucb.policy = "ucb";
    ucb.finalize_defaults();
    ucb.exploration = 0;
    tree.reset(9);
    Node root; root.to_play = RED; root.visits = 20; root.first_child = 1; root.child_count = 2; root.state = NODE_EXPANDED;
    Node c1; c1.move = 0; c1.to_play = BLUE; c1.visits = 10; c1.wins = 10;
    Node c2; c2.move = 1; c2.to_play = BLUE; c2.visits = 10; c2.wins = 0;
    tree.arena = {root, c1, c2};
    require(select_child(tree, 0, -1, ucb, rng) == 2, "parent must invert child's rewards");
    tree.arena[0].to_play = BLUE; tree.arena[1].to_play = tree.arena[2].to_play = RED;
    require(select_child(tree, 0, -1, ucb, rng) == 2, "opponent also maximizes its own reward");
    ++checks;

    // 5. GRAVE ancestor AMAF inheritance check.
    Config grave_cfg;
    grave_cfg.policy = "grave_ucb";
    grave_cfg.finalize_defaults();
    grave_cfg.exploration = 0.0;
    grave_cfg.prior_weight = 0.0;
    tree.reset(9);
    const auto anc_amaf = tree.allocate_amaf(10);
    tree.amaf_visits[anc_amaf + 0] = 50; tree.amaf_wins[anc_amaf + 0] = 5;
    tree.amaf_visits[anc_amaf + 1] = 50; tree.amaf_wins[anc_amaf + 1] = 48;
    Node g_parent; g_parent.to_play = RED; g_parent.visits = 1; g_parent.first_child = 1; g_parent.child_count = 2;
    g_parent.state = NODE_EXPANDED; g_parent.amaf_offset = -1; // no local AMAF yet
    Node gc1; gc1.move = 0; gc1.to_play = BLUE; gc1.visits = 0;
    Node gc2; gc2.move = 1; gc2.to_play = BLUE; gc2.visits = 0;
    tree.arena = {g_parent, gc1, gc2};
    require(select_child(tree, 0, anc_amaf, grave_cfg, rng) == 2, "GRAVE must use ancestor AMAF for unvisited children");
    ++checks;

    // 6. Fast Beta/Gamma sampler statistical accuracy check across small and large regimes.
    FastRng stat_rng(12345);
    for (const auto& params : std::array<std::pair<double, double>, 3>{{{1.5, 4.5}, {8.0, 2.0}, {40.0, 60.0}}}) {
        const double a = params.first, b = params.second;
        double sum = 0.0, sq = 0.0;
        constexpr int N = 20000;
        for (int i = 0; i < N; ++i) {
            const double x = stat_rng.sample_beta(a, b);
            require(x > 0.0 && x < 1.0, "Beta sample must stay in (0, 1)");
            sum += x;
            sq += x * x;
        }
        const double mean = sum / N;
        const double var = sq / N - mean * mean;
        const double exp_mean = a / (a + b);
        const double exp_var = (a * b) / ((a + b) * (a + b) * (a + b + 1.0));
        require(std::abs(mean - exp_mean) < 0.015, "Beta sampler mean within tolerance");
        require(std::abs(var - exp_var) < 0.01, "Beta sampler variance within tolerance");
    }
    ++checks;

    // 7. Immediate tactical win and single-threat block + individual switches.
    Board win(3); win.play(0, RED); win.play(3, RED);
    require(tactical(win, RED) == 6, "immediate winning move");
    ++checks;
    Request winning{RED, win, -1, 5, "CHANGE"};
    require(decide(winning, cfg, 0).reason == "tactical_win", "root tactical win");
    winning.player = BLUE; require(decide(winning, cfg, 0).move == 6, "root tactical block");
    ++checks;
    Config no_win = cfg; no_win.win_check = false; no_win.iterations = 1;
    winning.player = RED;
    require(decide(winning, no_win, 0).reason != "tactical_win", "individual win-check switch");
    Config no_block = cfg; no_block.block_check = false; no_block.iterations = 1;
    winning.player = BLUE;
    require(decide(winning, no_block, 0).reason != "tactical_block", "individual block-check switch");
    ++checks;

    // 8. Terminal board rejection.
    win.play(6, RED);
    bool terminal_rejected = false;
    try { decide({BLUE, win, 6, 6, "CHANGE"}, cfg, 0); } catch (const std::invalid_argument&) { terminal_rejected = true; }
    require(terminal_rejected, "terminal board must not expand or return a move");
    ++checks;

    // 9. Bridge saves (interior + goal edge).
    Board bridge(5); bridge.play(1 * 5 + 2, RED); bridge.play(3 * 5 + 1, RED); bridge.play(2 * 5 + 2, BLUE);
    require(bridge_save(bridge, 2 * 5 + 2, RED) == 2 * 5 + 1, "interior bridge save");
    ++checks;
    Board wall(5); wall.play(1 * 5 + 1, RED); wall.play(0 * 5 + 2, BLUE);
    require(bridge_save(wall, 2, RED) == 1, "goal-edge bridge save");
    ++checks;

    // 10. Fixed-seed repeatability across all policies (including grave_ucb and grave_ts).
    for (const std::string policy : {"ucb", "ts", "rave_ucb", "rave_ts", "grave_ucb", "grave_ts"}) {
        Config pcfg;
        pcfg.policy = policy;
        pcfg.finalize_defaults();
        pcfg.workers = 3;
        pcfg.iterations = 301;
        pcfg.tactics = false;
        pcfg.node_cap = 2000;
        Request req{RED, Board(5), -1, 1, "START"};
        auto first = decide(req, pcfg, 0), second = decide(req, pcfg, 0);
        require(first.iterations == 301 && first.workers[0].iterations == 101 && first.workers[1].iterations == 100,
                "total worker iteration split");
        require(first.move == second.move && first.chosen_visits == second.chosen_visits && first.chosen_wins == second.chosen_wins,
                "fixed-seed repeatability");
        require((first.rave_updates > 0) == pcfg.rave(), "RAVE enabled counters must update");
        for (int i = 0; i < 3; ++i)
            require(first.workers[i].seed == second.workers[i].seed && first.workers[i].rave_updates == second.workers[i].rave_updates,
                    "worker repeatability");
    }
    ++checks;

    // 11. Tree reuse verification across 2 plies (and clean reset on mismatched state).
    {
        Config reuse_cfg;
        reuse_cfg.policy = "grave_ts";
        reuse_cfg.finalize_defaults();
        reuse_cfg.workers = 1;
        reuse_cfg.iterations = 600;
        reuse_cfg.tactics = false;
        reuse_cfg.swap = false;
        reuse_cfg.tree_reuse = true;
        EngineSession session;
        Board b5(5);
        auto d1 = decide({RED, b5, -1, 1, "START"}, reuse_cfg, 0, &session);
        require(d1.reused_nodes == 0, "fresh START must not reuse");
        b5.play(d1.move, RED);
        // Pick an opponent reply that is in the expanded tree.
        int opp_reply = -1;
        for (int m = 0; m < 25; ++m) if (b5.colour[m] == EMPTY) { opp_reply = m; break; }
        b5.play(opp_reply, BLUE);
        auto d2 = decide({RED, b5, opp_reply, 3, "CHANGE"}, reuse_cfg, 0, &session);
        require(d2.reused_nodes >= 1, "tree reuse should carry subtree across 2 plies");
        // Now send an unrelated board; reuse must safely reset.
        Board unrelated(5); unrelated.play(0, RED); unrelated.play(24, BLUE);
        auto d3 = decide({RED, unrelated, 24, 3, "CHANGE"}, reuse_cfg, 0, &session);
        require(d3.reused_nodes == 0, "unrelated board must reset tree reuse");
    }
    ++checks;

    // 12. Node cap bounds allocation without cancelling rollouts, and root-only fallback.
    cfg.node_cap = 3; cfg.iterations = 100; cfg.workers = 1; cfg.tactics = false;
    auto capped = decide({RED, Board(5), -1, 1, "START"}, cfg, 0);
    require(capped.nodes <= 3 && capped.workers[0].cap_reached && capped.iterations == 100,
            "node cap bounds allocation without cancelling rollouts");
    ++checks;
    cfg.node_cap = 1;
    auto root_only = decide({RED, Board(5), -1, 1, "START"}, cfg, 0);
    require(root_only.nodes == 1 && root_only.reason == "node_cap_fallback", "root-only cap must be labelled as fallback");
    ++checks;

    // 13. Monotonic deadline & game budget exhaustion.
    cfg.node_cap = 10000; cfg.seconds = 0.005; cfg.iterations = 10000000;
    auto timed = decide({RED, Board(11), -1, 1, "START"}, cfg, 0);
    require(timed.seconds < 1 && timed.iterations < cfg.iterations, "monotonic deadline completes promptly");
    ++checks;
    auto exhausted = decide({RED, Board(11), -1, 1, "START"}, cfg, cfg.game_seconds);
    require(exhausted.iterations == 0 && exhausted.reason == "budget_exhausted_fallback", "game budget exhaustion");
    ++checks;

    // 14. Protocol V2/V3 parsing and validation.
    auto parsed = parse_request("V2;B;3;SWAP;;000,000,000;3\r");
    require(parsed.player == BLUE && parsed.last_move == -1 && parsed.turn == 3, "explicit swap colour");
    bool malformed_rejected = false;
    try { parse_request("V2;R;3;START;;000,000,000,;1"); } catch (const std::exception&) { malformed_rejected = true; }
    require(malformed_rejected, "malformed board rejection");
    ++checks;
    auto external = parse_request("V3;R;3;START;;000,000,000;1;0.004;0.002");
    require(external.move_allowance == .004 && external.external_remaining == .002, "V3 independent referee budgets");
    cfg.tactics = false; cfg.swap = false; cfg.seconds = 0; cfg.iterations = 10000000;
    auto external_limited = decide(external, cfg, 0);
    require(external_limited.effective_allowance == .002 && external_limited.iterations < cfg.iterations,
            "V3 allowance cannot exceed external remaining game time");
    external.move_allowance = 0;
    auto external_exhausted = decide(external, cfg, 0);
    require(external_exhausted.iterations == 0 && external_exhausted.move >= 0,
            "zero V3 allocation produces a legal fallback");
    external.move_allowance = 1; external.external_remaining = 1;
    auto own_exhausted = decide(external, cfg, cfg.game_seconds);
    require(own_exhausted.iterations == 0, "external request cannot bypass configured game ceiling");
    bool invalid_external = false;
    try { parse_request("V3;R;3;START;;000,000,000;1;nan;2"); } catch (const std::exception&) { invalid_external = true; }
    require(invalid_external, "nonfinite external allocation rejection");
    ++checks;

    // 15. MCTS-Solver: 2-ply double-threat forced win on 5x5 (no 1-ply win for either side).
    {
        Board b5(5);
        b5.play(0 * 5 + 2, RED);
        b5.play(1 * 5 + 2, RED);
        b5.play(2 * 5 + 2, RED);
        b5.play(3 * 5 + 2, BLUE);
        b5.play(2 * 5 + 3, BLUE);
        require(tactical(b5, RED) < 0 && tactical(b5, BLUE) < 0, "no 1-ply win in 2-ply solver test");
        Config scfg;
        scfg.policy = "grave_ts";
        scfg.finalize_defaults();
        scfg.workers = 1;
        scfg.iterations = 400;
        scfg.explicit_iterations = false; // allow early stop on proven win
        scfg.tactics = true;
        scfg.swap = false;
        scfg.solver = true;
        auto solved = decide({RED, b5, 2 * 5 + 3, 6, "CHANGE"}, scfg, 0);
        require(solved.solver_status == "proven_win", "solver must prove 2-ply double-threat win");
        Board after(5); after.copy_from(b5); after.play(solved.move, RED);
        int t = -1;
        require(count_threats(after, RED, t) >= 2, "chosen proven winning move must create double threat");
    }
    ++checks;

    // 16. MCTS-Solver exact soundness proof against independent 3x3 minimax oracle.
    {
        auto oracle_minimax = [](auto&& self, const Board& b, Colour to_play) -> Colour {
            const Colour w = b.winner();
            if (w != EMPTY) return w;
            for (int i = 0; i < b.empty_count; ++i) {
                Board next(b.n); next.copy_from(b);
                next.play_unchecked(b.empty[i], to_play);
                if (self(self, next, opposite(to_play)) == to_play) return to_play;
            }
            return opposite(to_play);
        };
        Config scfg;
        scfg.policy = "grave_ts";
        scfg.finalize_defaults();
        scfg.workers = 1;
        scfg.iterations = 1500;
        scfg.explicit_iterations = true;
        scfg.tactics = false;
        scfg.swap = false;
        scfg.solver = true;
        FastRng test_rng(98765);
        int proven_checked = 0;
        for (int trial = 0; trial < 40; ++trial) {
            Board b3(3);
            int plies = 2 + test_rng.next_bounded(4);
            Colour turn_c = RED;
            for (int p = 0; p < plies && b3.winner() == EMPTY; ++p) {
                b3.play_unchecked(b3.empty[test_rng.next_bounded(b3.empty_count)], turn_c);
                turn_c = opposite(turn_c);
            }
            if (b3.winner() != EMPTY) continue;
            const Colour exact = oracle_minimax(oracle_minimax, b3, turn_c);
            auto d = decide({turn_c, b3, -1, plies + 1, "START"}, scfg, 0);
            if (d.solver_status == "proven_win") {
                require(exact == turn_c, "proven_win contradicted exact 3x3 minimax");
                Board after(3); after.copy_from(b3); after.play_unchecked(d.move, turn_c);
                require(oracle_minimax(oracle_minimax, after, opposite(turn_c)) == turn_c,
                        "proven_win move did not preserve exact minimax win");
                ++proven_checked;
            } else if (d.solver_status == "proven_loss") {
                require(exact == opposite(turn_c), "proven_loss contradicted exact 3x3 minimax");
                ++proven_checked;
            }
        }
        require(proven_checked >= 15, "solver should solve nonterminal 3x3 positions");

        // Exhaustive 3x3 soundness proof for Disjoint-Carrier VC-Solver across all 19,683 boards:
        // whenever has_disjoint_vc_win(b, p) is true on a nonterminal board, exact minimax MUST
        // prove p wins even when opposite(p) moves first (zero false positives!).
        int vc_verified = 0;
        for (int mask = 0; mask < 19683; ++mask) {
            Board b3(3);
            int tmp = mask;
            for (int c = 0; c < 9; ++c, tmp /= 3) {
                const int v = tmp % 3;
                if (v == 1) b3.play(c, RED);
                else if (v == 2) b3.play(c, BLUE);
            }
            if (b3.winner() != EMPTY) continue;
            for (Colour p : {RED, BLUE}) {
                if (has_disjoint_vc_win(b3, p)) {
                    require(oracle_minimax(oracle_minimax, b3, opposite(p)) == p,
                            "VC-Solver false positive contradicted exact 3x3 minimax");
                    ++vc_verified;
                }
            }
        }
        require(vc_verified >= 500, "VC-Solver must detect nonterminal 3x3 virtual connections");

        // 11x11 5-stone disjoint-carrier bridge chain VC-win and VC-mustplay verification.
        Board b11(11);
        b11.play(1 * 11 + 5, RED);
        b11.play(3 * 11 + 4, RED);
        // Leave (5, 3) empty!
        b11.play(7 * 11 + 2, RED);
        b11.play(9 * 11 + 1, RED);
        require(!has_disjoint_vc_win(b11, RED), "incomplete 11x11 VC chain must not trigger");
        require(find_vc_win_move(b11, RED) == 5 * 11 + 3, "find_vc_win_move must find 11x11 bridge completion");
        CellBitSet mp;
        const int mp_cnt = compute_vc_mustplay(b11, RED, mp);
        require(mp_cnt >= 1 && mp_cnt <= 15 && mp.test(5 * 11 + 3),
                "compute_vc_mustplay must prune >85% of 11x11 board and include winning move");
    }
    ++checks;

    // 17. Two-Distance connectivity verification (edge bridges, choke points, transpose symmetry).
    {
        Board e5(5);
        std::array<std::uint8_t, MAX_CELLS> rt{};
        compute_two_distance_from_edge(e5, RED, 1U, rt);
        // Row 0 touches top edge directly (d2=1); row 1 cells (1,0..3) have 2-cell bridge to row 0 (d2=2);
        // (1,4) has only one row-0 neighbour (0,4), so d2 must be 3!
        for (int y = 0; y < 5; ++y) require(rt[0 * 5 + y] == 1, "two-distance row 0 must be 1");
        for (int y = 0; y < 4; ++y) require(rt[1 * 5 + y] == 2, "two-distance row 1 interior bridge must be 2");
        require(rt[1 * 5 + 4] == 3, "two-distance obtuse side (1,4) without bridge must be 3");
        // Transpose + colour-swap symmetry test on a nontrivial 5x5 position.
        Board a5(5), b5(5);
        a5.play(0 * 5 + 2, RED); a5.play(1 * 5 + 2, RED); a5.play(3 * 5 + 1, RED);
        a5.play(2 * 5 + 3, BLUE); a5.play(2 * 5 + 0, BLUE);
        b5.play(2 * 5 + 0, BLUE); b5.play(2 * 5 + 1, BLUE); b5.play(1 * 5 + 3, BLUE);
        b5.play(3 * 5 + 2, RED); b5.play(0 * 5 + 2, RED);
        auto pa = compute_two_distance_potential(a5);
        auto pb = compute_two_distance_potential(b5);
        require(pa.min_red == pb.min_blue && pa.min_blue == pb.min_red, "two-distance transpose symmetry");
        // Bridging choke point (2,1) or (2,2) must have strictly lower RED potential than far corner (4,4).
        require(pa.pot_red[2 * 5 + 2] < pa.pot_red[4 * 5 + 4], "two-distance must highlight critical choke cell");
    }
    ++checks;

    // 18. Lock-Free Shared-Tree Parallel MCTS: 4 threads, zero leftover virtual loss, tree reuse & solver.
    {
        Config stcfg;
        stcfg.policy = "grave_ts";
        stcfg.finalize_defaults();
        stcfg.workers = 4;
        stcfg.iterations = 4000;
        stcfg.explicit_iterations = true;
        stcfg.shared_tree_mode = 1;
        stcfg.tactics = false;
        stcfg.swap = false;
        stcfg.tree_reuse = true;
        stcfg.solver = true;
        EngineSession s_sess;
        Board b5(5);
        auto d1 = decide({RED, b5, -1, 1, "START"}, stcfg, 0, &s_sess);
        require(d1.used_shared_tree && d1.iterations == 4000 && d1.nodes > 1, "shared tree must execute 4 threads");
        // Verify virtual loss returned to exact 0 on every allocated node.
        const int ncnt = s_sess.shared_tree.node_count.load(std::memory_order_relaxed);
        for (int i = 0; i < ncnt; ++i) {
            require(s_sess.shared_tree.nodes[i].vloss.load(std::memory_order_relaxed) == 0,
                    "shared tree virtual loss leaked");
        }
        b5.play(d1.move, RED);
        int opp_m = -1;
        for (int m = 0; m < 25; ++m) if (b5.colour[m] == EMPTY) { opp_m = m; break; }
        b5.play(opp_m, BLUE);
        auto d2 = decide({RED, b5, opp_m, 3, "CHANGE"}, stcfg, 0, &s_sess);
        require(d2.reused_nodes >= 1, "shared tree reuse must carry subtree across 2 plies");
    }
    ++checks;

    // 19. MoHex 2.0 6-ring pattern code RED/BLUE transpose symmetry & pattern-rollout legality.
    {
        Board a5(5), b5(5);
        a5.play(0 * 5 + 2, RED); a5.play(1 * 5 + 3, RED); a5.play(2 * 5 + 1, RED);
        a5.play(2 * 5 + 2, BLUE); a5.play(3 * 5 + 0, BLUE);
        b5.play(2 * 5 + 0, BLUE); b5.play(3 * 5 + 1, BLUE); b5.play(1 * 5 + 2, BLUE);
        b5.play(2 * 5 + 2, RED); b5.play(0 * 5 + 3, RED);
        for (int x = 0; x < 5; ++x) {
            for (int y = 0; y < 5; ++y) {
                const int cr = ring6_pattern_code(a5, x * 5 + y, RED);
                const int cb = ring6_pattern_code(b5, y * 5 + x, BLUE);
                require(cr == cb, "6-ring pattern code must match under transpose + colour swap");
            }
        }
        auto pw = build_pattern_weights(0.45);
        FastRng prng(2026);
        for (int trial = 0; trial < 50; ++trial) {
            int mv = pattern_rollout_move(a5, 2 * 5 + 2, RED, pw, prng);
            require(mv >= 0 && mv < 25 && a5.colour[mv] == EMPTY, "pattern rollout must return legal empty cell");
        }
    }
    ++checks;

    // 20. Pie-rule opening book, calibrated 11x11 swap map, and lock-free Pondering zero-vloss + subtree reuse.
    {
        Board b11(11);
        require(!should_swap(b11, 0 * 11 + 5), "row 0 should not be swapped");
        require(!should_swap(b11, 3 * 11 + 1), "weak b4/j8 should not be swapped");
        require(should_swap(b11, 5 * 11 + 5), "center f6 must be swapped");
        require(should_swap(b11, 1 * 11 + 8), "acute-side i2 must be swapped");
        Config bkcfg;
        bkcfg.policy = "grave_ts";
        bkcfg.finalize_defaults();
        bkcfg.opening_book = true;
        bkcfg.swap = true;
        bkcfg.seconds = 1.0;
        auto dbk = decide({RED, b11, -1, 1, "START"}, bkcfg, 0, nullptr);
        require(dbk.reason == "pie_rule_opening_book" && dbk.move >= 0 && dbk.move < 121,
                "opening book must return balanced 11x11 opening");

        // Pondering start/stop + 1-ply subtree inheritance + zero virtual-loss leak.
        Config pcfg;
        pcfg.policy = "grave_ts";
        pcfg.finalize_defaults();
        pcfg.workers = 4;
        pcfg.seconds = 0.05;
        pcfg.iterations = 1000000ULL;
        pcfg.shared_tree_mode = 1;
        pcfg.tactics = false;
        pcfg.swap = false;
        pcfg.tree_reuse = true;
        EngineSession psess;
        PonderController pctrl;
        Board b5(5);
        b5.play(2 * 5 + 2, RED);
        Request preq{BLUE, b5, 2 * 5 + 2, 2, "CHANGE"};
        pctrl.start(psess, preq, pcfg);
        std::this_thread::sleep_for(std::chrono::milliseconds(40));
        const std::uint64_t piters = pctrl.stop_and_join();
        require(piters > 0, "pondering must accumulate background iterations");
        const int pncnt = psess.shared_tree.node_count.load(std::memory_order_relaxed);
        for (int i = 0; i < pncnt; ++i) {
            require(psess.shared_tree.nodes[i].vloss.load(std::memory_order_relaxed) == 0,
                    "pondering virtual loss leaked");
        }
        // Pick the most-visited child under pondered root as opponent's reply and verify 1-ply inheritance.
        int best_opp = -1;
        std::uint32_t best_v = 0;
        const auto& proot = psess.shared_tree.nodes[0];
        for (int i = 0; i < static_cast<int>(proot.child_count); ++i) {
            const auto& ch = psess.shared_tree.nodes[proot.first_child + i];
            const auto cv = ch.visits.load(std::memory_order_relaxed);
            if (cv > best_v) { best_v = cv; best_opp = ch.move; }
        }
        require(best_opp >= 0 && best_v > 0, "pondered root must have visited children");
        b5.play(best_opp, BLUE);
        auto dafter = decide({RED, b5, best_opp, 3, "CHANGE"}, pcfg, 0, &psess);
        require(dafter.reused_visits >= best_v, "decide must inherit pondered subtree visits");
    }
    ++checks;

    std::cout << "{\"kind\":\"hex_search_self_test\",\"status\":\"passed\",\"checks\":" << checks
              << ",\"exhaustive_connectivity_positions\":19683,\"dead_cell_verifications\":"
              << dead_cell_verifications << "}" << std::endl;
}

// ============================================================================
// Step 5: Standard Hex GTP (Go Text Protocol) Interface (--gtp)
// Compatible with HexGui, Benzene/MoHex, twogtp, and Little Golem conventions:
//   - Columns: a..s (includes 'i', standard Hex algebraic notation)
//   - Rows: 1..n (top to bottom)
//   - Black ('b'/'black'/'red'/'r'): connects Top (row 1) to Bottom (row n)
//   - White ('w'/'white'/'blue'):    connects Left (col a) to Right (col n)
// ============================================================================
inline std::string to_lower_ascii(std::string s) {
    for (char& ch : s) if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
    return s;
}
inline std::string gtp_format_move(int move, int n) {
    if (move < 0) return "swap-pieces";
    const int row = move / n, col = move % n;
    return std::string(1, static_cast<char>('a' + col)) + std::to_string(row + 1);
}
inline bool gtp_parse_move(const std::string& tok, int n, int& move_out, bool& is_swap_pieces, bool& is_swap_sides) {
    is_swap_pieces = false;
    is_swap_sides = false;
    const std::string t = to_lower_ascii(tok);
    if (t == "swap-pieces") { is_swap_pieces = true; move_out = -1; return true; }
    if (t == "swap" || t == "swap-sides") { is_swap_sides = true; move_out = -1; return true; }
    if (t.size() < 2 || t[0] < 'a' || t[0] >= 'a' + n) return false;
    const int col = t[0] - 'a';
    const std::string num = t.substr(1);
    if (num.find_first_not_of("0123456789") != std::string::npos) return false;
    const int row = std::stoi(num) - 1;
    if (row < 0 || row >= n) return false;
    move_out = row * n + col;
    return true;
}
inline bool gtp_parse_colour(const std::string& tok, Colour& out) {
    const std::string t = to_lower_ascii(tok);
    if (t == "b" || t == "black" || t == "r" || t == "red") { out = RED; return true; }
    if (t == "w" || t == "white" || t == "blue") { out = BLUE; return true; }
    return false;
}
inline std::string gtp_showboard(const Board& board) {
    std::ostringstream out;
    out << "\n  ";
    for (int y = 0; y < board.n; ++y) out << ' ' << static_cast<char>('a' + y);
    out << "\n";
    for (int x = 0; x < board.n; ++x) {
        out << std::setw(2) << (x + 1) << std::string(static_cast<std::size_t>(x + 1), ' ');
        for (int y = 0; y < board.n; ++y) {
            const Colour c = board.colour[x * board.n + y];
            out << (c == RED ? 'B' : (c == BLUE ? 'W' : '.'));
            if (y + 1 < board.n) out << ' ';
        }
        out << " " << (x + 1) << "\n";
    }
    return out.str();
}

void run_gtp_loop(Config cfg) {
    Board board(11);
    EngineSession session;
    int last_move = -1;
    int turn = 1;
    double remaining[2] = {cfg.game_seconds, cfg.game_seconds};
    bool has_clock = false;

    auto reply = [](const std::string& id, bool ok, const std::string& body) {
        std::cout << (ok ? '=' : '?') << id;
        if (!body.empty()) std::cout << ' ' << body;
        std::cout << "\n\n" << std::flush;
    };

    std::string line;
    while (std::getline(std::cin, line)) {
        const auto hash_pos = line.find('#');
        if (hash_pos != std::string::npos) line.erase(hash_pos);
        std::istringstream iss(line);
        std::vector<std::string> tokens;
        std::string tok;
        while (iss >> tok) tokens.push_back(tok);
        if (tokens.empty()) continue;

        std::string id;
        std::size_t idx = 0;
        if (tokens[0].find_first_not_of("0123456789") == std::string::npos) {
            id = tokens[0];
            idx = 1;
        }
        if (idx >= tokens.size()) continue;
        const std::string cmd = to_lower_ascii(tokens[idx++]);

        if (cmd == "protocol_version") { reply(id, true, "2"); }
        else if (cmd == "name") { reply(id, true, "hex-search"); }
        else if (cmd == "version") { reply(id, true, "1.2.0"); }
        else if (cmd == "list_commands") {
            reply(id, true, "protocol_version\nname\nversion\nlist_commands\nknown_command\nboardsize\nclear_board\nplay\ngenmove\nshowboard\nfinal_score\ntime_settings\ntime_left\nquit");
        } else if (cmd == "known_command") {
            if (idx >= tokens.size()) { reply(id, false, "missing command"); continue; }
            const std::string q = to_lower_ascii(tokens[idx]);
            const bool known = (q == "protocol_version" || q == "name" || q == "version" || q == "list_commands" ||
                                q == "known_command" || q == "boardsize" || q == "clear_board" || q == "play" ||
                                q == "genmove" || q == "showboard" || q == "final_score" || q == "time_settings" ||
                                q == "time_left" || q == "quit");
            reply(id, true, known ? "true" : "false");
        } else if (cmd == "boardsize") {
            if (idx >= tokens.size()) { reply(id, false, "missing boardsize"); continue; }
            try {
                const int sz = bounded_integer(tokens[idx], 3, MAX_SIZE);
                board = Board(sz);
                session.reset();
                last_move = -1;
                turn = 1;
                remaining[0] = remaining[1] = cfg.game_seconds;
                reply(id, true, "");
            } catch (const std::exception& e) { reply(id, false, e.what()); }
        } else if (cmd == "clear_board") {
            board = Board(board.n);
            session.reset();
            last_move = -1;
            turn = 1;
            remaining[0] = remaining[1] = cfg.game_seconds;
            reply(id, true, "");
        } else if (cmd == "showboard") {
            reply(id, true, gtp_showboard(board));
        } else if (cmd == "final_score") {
            const Colour w = board.winner();
            reply(id, true, w == RED ? "B+" : (w == BLUE ? "W+" : "?"));
        } else if (cmd == "time_settings") {
            if (idx >= tokens.size()) { reply(id, false, "missing time_settings"); continue; }
            try {
                const double main_t = nonnegative_number(tokens[idx]);
                cfg.game_seconds = main_t;
                remaining[0] = remaining[1] = main_t;
                has_clock = main_t > 0.0;
                reply(id, true, "");
            } catch (const std::exception& e) { reply(id, false, e.what()); }
        } else if (cmd == "time_left") {
            Colour c = RED;
            if (idx + 1 >= tokens.size() || !gtp_parse_colour(tokens[idx], c)) {
                reply(id, false, "invalid time_left");
                continue;
            }
            try {
                remaining[c] = nonnegative_number(tokens[idx + 1]);
                has_clock = true;
                reply(id, true, "");
            } catch (const std::exception& e) { reply(id, false, e.what()); }
        } else if (cmd == "play") {
            Colour c = RED;
            if (idx + 1 >= tokens.size() || !gtp_parse_colour(tokens[idx], c)) {
                reply(id, false, "invalid colour");
                continue;
            }
            int mv = -1;
            bool is_swap_pieces = false, is_swap_sides = false;
            if (!gtp_parse_move(tokens[idx + 1], board.n, mv, is_swap_pieces, is_swap_sides)) {
                reply(id, false, "invalid move");
                continue;
            }
            if (is_swap_pieces) {
                if (turn != 2 || last_move < 0) { reply(id, false, "illegal swap"); continue; }
                const int ox = last_move / board.n, oy = last_move % board.n;
                board = Board(board.n);
                const int swapped = oy * board.n + ox;
                board.play(swapped, c);
                last_move = swapped;
                ++turn;
                session.reset();
                reply(id, true, "");
            } else if (is_swap_sides) {
                if (turn != 2 || last_move < 0) { reply(id, false, "illegal swap"); continue; }
                ++turn;
                session.reset();
                reply(id, true, "");
            } else {
                if (board.colour[mv] != EMPTY || board.winner() != EMPTY) {
                    reply(id, false, "illegal move");
                    continue;
                }
                board.play(mv, c);
                last_move = mv;
                ++turn;
                reply(id, true, "");
            }
        } else if (cmd == "genmove") {
            Colour c = RED;
            if (idx >= tokens.size() || !gtp_parse_colour(tokens[idx], c)) {
                reply(id, false, "invalid colour");
                continue;
            }
            if (board.winner() != EMPTY || board.empty_count == 0) {
                reply(id, true, "resign");
                continue;
            }
            Request req{c, board, last_move, turn, last_move < 0 ? "START" : "CHANGE"};
            Config move_cfg = cfg;
            if (has_clock && cfg.seconds == 0.0 && !cfg.explicit_iterations) {
                const int est_left = std::max(8, 24 - (turn / 2));
                req.external_remaining = remaining[c];
                req.move_allowance = std::max(0.05, (remaining[c] - 0.1) / est_left);
                move_cfg.iterations = 1000000000ULL;
            } else if (cfg.seconds == 0.0 && !cfg.explicit_iterations) {
                move_cfg.seconds = 2.0;
                move_cfg.iterations = 1000000000ULL;
            }
            auto decision = decide(req, move_cfg, 0.0, &session);
            if (decision.reason == "pie_rule_swap" && turn == 2 && last_move >= 0) {
                const int ox = last_move / board.n, oy = last_move % board.n;
                board = Board(board.n);
                const int swapped = oy * board.n + ox;
                board.play(swapped, c);
                last_move = swapped;
                ++turn;
                session.reset();
                diagnostics(req, move_cfg, decision, 0.0);
                reply(id, true, "swap-pieces");
            } else {
                board.play(decision.move, c);
                last_move = decision.move;
                ++turn;
                diagnostics(req, move_cfg, decision, 0.0);
                reply(id, true, gtp_format_move(decision.move, board.n));
            }
        } else if (cmd == "quit") {
            reply(id, true, "");
            break;
        } else {
            reply(id, false, "unknown command: " + cmd);
        }
    }
}

Config arguments(int argc, char** argv) {
    Config cfg;
    bool explicit_policy = false;
    cfg.policy = "rave_ts"; // Default policy preserves CLI backward compatibility unless specified.
    int first = 1;
    if (argc >= 3 && (std::string(argv[1]) == "R" || std::string(argv[1]) == "B")) {
        bounded_integer(argv[2], 3, MAX_SIZE);
        first = 3;
    }
    for (int i = first; i < argc; ++i) {
        std::string key = argv[i];
        if (key == "--gtp") {
            cfg.gtp_mode = true;
            continue;
        }
        if (i + 1 >= argc) throw std::invalid_argument("Option requires a value: " + key);
        std::string value = argv[++i];
        if (key == "--policy") {
            if (value != "ucb" && value != "ts" && value != "rave_ucb" && value != "rave_ts" &&
                value != "legacy_ts" && value != "grave_ucb" && value != "grave_ts")
                throw std::invalid_argument("Unknown search policy.");
            cfg.policy = value;
            explicit_policy = true;
        } else if (key == "--seed") cfg.seed = unsigned_integer(value);
        else if (key == "--workers") cfg.workers = bounded_integer(value, 1, 64);
        else if (key == "--iterations") { cfg.iterations = unsigned_integer(value); cfg.explicit_iterations = true; }
        else if (key == "--seconds") cfg.seconds = nonnegative_number(value);
        else if (key == "--game-seconds") cfg.game_seconds = nonnegative_number(value);
        else if (key == "--memory-mb") cfg.memory_mb = nonnegative_number(value);
        else if (key == "--node-cap") cfg.node_cap = bounded_integer(value, 1, 20000000);
        else if (key == "--rave-k") cfg.rave_k = nonnegative_number(value);
        else if (key == "--rave-bias") { cfg.rave_bias = nonnegative_number(value); cfg.explicit_rave_bias = true; }
        else if (key == "--grave-ref") { cfg.grave_ref = bounded_integer(value, 0, 1000000); cfg.explicit_grave_ref = true; }
        else if (key == "--exploration") { cfg.exploration = nonnegative_number(value); cfg.explicit_exploration = true; }
        else if (key == "--expand-threshold") { cfg.expand_threshold = bounded_integer(value, 0, 10000); cfg.explicit_expand_threshold = true; }
        else if (key == "--prior-weight") { cfg.prior_weight = nonnegative_number(value); cfg.explicit_prior_weight = true; }
        else if (key == "--bridge") cfg.bridge = bounded_integer(value, 0, 1) != 0;
        else if (key == "--ordering") cfg.ordering = bounded_integer(value, 0, 1) != 0;
        else if (key == "--swap") cfg.swap = bounded_integer(value, 0, 1) != 0;
        else if (key == "--tactics") cfg.tactics = bounded_integer(value, 0, 1) != 0;
        else if (key == "--win-check") cfg.win_check = bounded_integer(value, 0, 1) != 0;
        else if (key == "--block-check") cfg.block_check = bounded_integer(value, 0, 1) != 0;
        else if (key == "--lgr") cfg.lgr = bounded_integer(value, 0, 1) != 0;
        else if (key == "--prune-dead") cfg.prune_dead = bounded_integer(value, 0, 1) != 0;
        else if (key == "--tree-reuse") cfg.tree_reuse = bounded_integer(value, 0, 1) != 0;
        else if (key == "--solver") cfg.solver = bounded_integer(value, 0, 1) != 0;
        else if (key == "--two-dist") cfg.two_dist = bounded_integer(value, 0, 1) != 0;
        else if (key == "--shared-tree") cfg.shared_tree_mode = bounded_integer(value, 0, 1);
        else if (key == "--pat-prior") cfg.pat_prior = bounded_integer(value, 0, 1) != 0;
        else if (key == "--pat-rollout") cfg.pat_rollout = bounded_integer(value, 0, 1) != 0;
        else if (key == "--pat-temp") cfg.pat_temp = nonnegative_number(value);
        else if (key == "--opening-book") cfg.opening_book = bounded_integer(value, 0, 1) != 0;
        else throw std::invalid_argument("Unknown option: " + key);
    }
    if (cfg.gtp_mode && !explicit_policy) cfg.policy = "grave_ts";
    if (cfg.gtp_mode && cfg.swap) cfg.opening_book = true;
    cfg.finalize_defaults();
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
        if (argc == 2 && std::string(argv[1]) == "--version") { std::cout << "hex-search 1.2.0 C++17\n"; return 0; }
        if (argc == 2 && std::string(argv[1]) == "--self-test") { hex::self_test(); return 0; }
        if (argc == 2 && std::string(argv[1]) == "--help") {
            std::cout << "Usage: hex-search [R|B BOARD_SIZE] [options]\n"
                "Reads V2/V3 protocol lines from stdin (plus PONDER;/STOP_PONDER), or runs standard Hex GTP with --gtp.\n"
                "Options: --gtp --policy ucb|ts|rave_ucb|rave_ts|grave_ucb|grave_ts|legacy_ts\n"
                " --seed UINT --workers 1..64 --iterations TOTAL --seconds SEC --game-seconds SEC\n"
                " --node-cap TOTAL --memory-mb MIB --rave-k NUMBER --rave-bias NUMBER\n"
                " --grave-ref INT --exploration NUMBER --expand-threshold INT --prior-weight NUMBER\n"
                " --bridge 0|1 --ordering 0|1 --lgr 0|1 --prune-dead 0|1 --tree-reuse 0|1\n"
                " --solver 0|1 --two-dist 0|1 --shared-tree 0|1 --pat-prior 0|1 --pat-rollout 0|1\n"
                " --pat-temp NUMBER --opening-book 0|1 --swap 0|1 --tactics 0|1 --win-check 0|1 --block-check 0|1\n"
                "Use --self-test for exhaustive connectivity, dead-cell, solver, pondering, and search checks.\n";
            return 0;
        }
        auto cfg = hex::arguments(argc, argv);
        if (cfg.gtp_mode) {
            hex::run_gtp_loop(cfg);
            return 0;
        }
        hex::EngineSession session;
        hex::PonderController ponder;
        double game_used = 0;
        int last_turn = 0;
        std::string line;
        while (std::getline(std::cin, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line.empty()) continue;
            if (line == "STOP_PONDER") {
                const auto piters = ponder.stop_and_join();
                std::cerr << "{\"kind\":\"hex_search_ponder_stopped\",\"iterations\":" << piters << "}" << std::endl;
                continue;
            }
            if (line.rfind("PONDER;", 0) == 0) {
                ponder.stop_and_join();
                auto preq = hex::parse_request("V2" + line.substr(6));
                ponder.start(session, preq, cfg);
                std::cerr << "{\"kind\":\"hex_search_ponder_started\",\"turn\":" << preq.turn << "}" << std::endl;
                continue;
            }
            const auto ponder_iters = ponder.stop_and_join();
            if (ponder_iters > 0) {
                std::cerr << "{\"kind\":\"hex_search_ponder_stopped\",\"iterations\":" << ponder_iters << "}" << std::endl;
            }
            const auto request_start = hex::Clock::now();
            auto request = hex::parse_request(line);
            if (request.command == "START" || request.command == "SWAP" || request.turn <= last_turn) {
                game_used = 0;
                if (request.command == "START" || request.command == "SWAP") session.reset();
            }
            const double parse_seconds = hex::elapsed(request_start);
            auto request_cfg = cfg;
            if (request.move_allowance >= 0 && !cfg.explicit_iterations) request_cfg.iterations = 1000000000ULL;
            const double used = request.external_remaining >= 0 ?
                std::max(0.0, cfg.game_seconds - request.external_remaining) : game_used;
            auto result = hex::decide(request, request_cfg, used + parse_seconds, &session);
            result.seconds = hex::elapsed(request_start);
            game_used += result.seconds;
            last_turn = request.turn;
            hex::diagnostics(request, cfg, result, game_used);
            std::cout << (result.move < 0 ? -1 : result.move / request.board.n) << ','
                      << (result.move < 0 ? -1 : result.move % request.board.n) << std::endl;
        }
        ponder.stop_and_join();
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "{\"kind\":\"hex_search_error\",\"error\":" << hex::json_quote(error.what()) << '}' << std::endl;
        return 2;
    }
}
