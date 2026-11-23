# Hex Search v1.2 Technical Architecture

[한국어](architecture.ko.md) | [README](../README.md)

> Version progression: `v0.0` (Flat Arena GRAVE-TS core) → `v1.0` (MCTS Solver + Two-Distance + Lock-Free Shared-Tree + 6-Ring patterns) → `v1.1` (Nash pie-rule opening book + Pondering) → **`v1.2`** (Exact Disjoint-Carrier VC Solver + MoHex search calibration).

## 1. Zero-Dependency Pure-CPU Systems Design (`native/hex_search.cpp`)

The engine is implemented as a single self-contained C++17 translation unit with zero third-party dependencies (`-std=c++17 -O3 -pthread`), designed for high cache locality and multi-core scalability:

- **O(1) Edge-Bitmask Union-Find**: Each connected stone component maintains a 2-bit `edge_flags` mask (`1 = Start Edge`, `2 = End Edge`). A player wins the instant `edge_flags[root] == 3`, avoiding full-board BFS/DFS checks during playouts.
- **Precomputed `BoardTopology`**: Neighbor lists, 6-cell cyclic rings, edge bitmasks, and exact 2-bridge defense checks (interior + goal edge) are precomputed once per board size.
- **Compact Memory & Lazy Expansion**: Nodes are allocated from contiguous flat arenas (`expand_threshold = 8` for GRAVE policies) with a separate flat AMAF table pool (`65%` RAM budget for AMAF, `35%` for nodes), cutting RSS by up to `4.27×` vs naive pointer-based trees.
- **Fast Deterministic PRNG**: Inline `xoshiro256**`, division-free Lemire bounded integers, Marsaglia-Tsang Gamma/Beta sampling with exact-tail Box-Muller Gaussian acceleration for $\alpha, \beta \ge 16$.

## 2. Search Policy: Variance-Capped GRAVE-TS

At each internal node, children combine Monte Carlo estimates with Generalized RAVE (GRAVE) ancestor AMAF statistics:

$$\beta = \frac{n_{\text{amaf}}}{n_{\text{mc}} + n_{\text{amaf}} + b \cdot n_{\text{mc}} n_{\text{amaf}}}, \qquad b = 0.0005$$

- **Variance Capping**: When borrowing AMAF from an ancestor node (`amaf_base != parent.amaf_offset`), pseudo-counts are capped at `32` (`eff_n = n_mc + pw + beta * min(amaf_n, 32)`). Uncapped borrowing collapsed Beta variance and dropped win rate to `33.3%`; capping flipped it to `56.7%` and decisively beat tuned `GRAVE-UCB` (`56.7%` to `73.3%`).
- **Heuristic Prior (`prior_weight = 8.0`)**: Shallow expansions (`depth <= 4`) blend exact 4-direction bucket-queue **Two-Distance** connectivity potentials with learned **6-ring pattern logits**; deeper expansions use O(1) 6-ring logits + distance-to-last-move features.

## 3. Lock-Free Shared-Tree Parallel MCTS & Real-Time Pondering

- **Atomic Node Expansion**: Worker threads claim expansion via `state.fetch_or(NODE_EXPANDING, memory_order_acq_rel)` and publish children with `NODE_EXPANDED` (`memory_order_release`). Contending threads fall directly into rollouts without blocking on a global mutex.
- **Virtual Loss**: Descent increments atomic `vloss` (`n_mc = visits + 2 * vloss`) and decrements during backpropagation; `--self-test` verifies exact `0` residual virtual loss across all nodes.
- **1-Ply & 2-Ply Subtree Compaction**: Between turns, `rebase_subtree` compacts the live subtree and recomputes proven flags bottom-up.
- **Opponent-Turn Pondering (`PONDER;` / `STOP_PONDER`)**: Immediately after playing, the GUI issues `PONDER;` on the opponent's board; background threads expand the shared tree up to `85%` of `node_cap` and join in `<1ms` when the opponent's move arrives, passing millions of precomputed visits straight into `decide()` (`+74.8M` reused visits in the 77-move MoHex 3 victory).

## 4. Exact Disjoint-Carrier Virtual Connection (VC) Solver & Mustplay

By Shannon's Pairing Strategy (Benzene/MoHex Theorem 1), if a player possesses a Start-to-End chain of 2-bridge hyperedges $(u_i, v_i; \{a_i, b_i\})$ whose empty carrier pairs are pairwise disjoint, that player has a **100% mathematically proven forced win** even when the opponent moves next:

- **Root VC Win (`find_vc_win_move`)**: Scans legal moves for an immediate disjoint-carrier VC win, selecting the move minimizing carrier count (`popcount`) for strict monotonic convergence to physical victory (`0.00s` forced checkmate 7 plies early on Turns 71~77 vs MoHex 3).
- **Root VC Mustplay (`compute_vc_mustplay`)**: Intersects $\{m\} \cup C(m)$ over all opponent 1-move VC threats; marks every root child outside the intersection `NODE_PROVEN_WIN` (for opponent) without invalidating the pondered tree.
- **In-Tree VC Solver**: Runs at `depth <= 3 || empty_count <= 32` to backpropagate `NODE_PROVEN_WIN/LOSS` 10~15 plies early.
- **Exhaustive Soundness**: Verified with **0 false positives** across all **19,683** 3×3 boards against an independent exact minimax oracle in `--self-test`.

## 5. Self-Play 6-Ring Pattern Learning & Pie-Rule Calibration

- **6-Ring Patterns**: 216 4-way canonical symmetric 6-neighbor features trained via convex `L-BFGS-B` Plackett-Luce MLE on 10,547 pure-CPU self-play moves (`Val Top-1 49.81%`, `Top-5 71.16%`), driving both deep node priors and O(1) Boltzmann rollouts (`pat_temp = 0.35`).
- **11×11 Pie-Rule Calibration**: Empirical 50.0% winrate contour sweep calibrated both `should_swap` and a `0.00s` Nash equilibrium opening book (`h2, i2, d10, c10, e3, g9, f3, f9, j4, b8`), eliminating first-player center-swap blunders while preserving full Turn 1 clock budget.
