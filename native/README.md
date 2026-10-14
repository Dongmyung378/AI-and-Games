# Maintained C++17 Hex search engine

[한국어](README.ko.md) | **English**

This implementation lives beside the preserved coursework submission. It does not
overwrite `deployment/agents/Group026/RAVE_TS.cpp`, its binary, or historical match
records. It uses only the C++17 standard library.

## Build and validate

```bash
g++ -std=c++17 -O3 -Wall -Wextra -Wpedantic -pthread native/hex_search.cpp -o hex-search
./hex-search --self-test
./hex-search --help
```

On Windows with MinGW, use `-o native/hex-search.exe` and
`native\hex-search.exe --self-test`. Build for the target OS; a Windows executable
is not a Linux executable. A compatible compiler is required for source builds.

The self-test checks 19,683 exhaustive 3x3 board colourings against an independent
BFS connection oracle, per-node AMAF suffixes, alternating reward perspectives,
terminal states, immediate wins and blocks, interior and goal-edge bridges,
fixed-seed worker reproducibility, exact iteration allocation, memory node caps,
deadlines, and input validation. The checks verify implementation invariants;
they do not establish competitive playing strength.

## Protocol and options

The existing version-two request format is unchanged:

```text
V2;R|B;board_size;START|CHANGE|SWAP;opponent_x,y-or-empty;comma-separated-rows;turn
```

Rows contain `0`, `R`, or `B`. RED connects the first coordinate's opposite
edges; BLUE connects the second coordinate's opposite edges. Coordinates are
zero-based. The maintained engine accepts sizes 3 through 19; final project
evaluations should explicitly name their board size, including the original
11x11 setting. Each request's colour is authoritative after a swap.

An optional initial `R|B BOARD_SIZE` pair retains adapter compatibility. Per move,
stdout contains exactly `x,y`, or `-1,-1` for a legal pie-rule swap. Stderr emits
one JSON diagnostic tagged `hex_search_move`. Invalid inputs and terminal boards
emit `hex_search_error` and exit with status 2; they never return an illegal move.

```bash
./hex-search --policy rave_ts --seed 378 --workers 4 --iterations 10000
./hex-search --policy ts --seed 378 --workers 4 --seconds 0.5 --game-seconds 300
```

| Option | Meaning and default |
| --- | --- |
| `--policy` | `ucb`, `ts`, `rave_ucb`, `rave_ts`, or diagnostic `legacy_ts`; default `rave_ts` |
| `--seed` | Unsigned base seed; default 378 |
| `--workers` | Independent root workers; default 1, maximum 64 |
| `--iterations` | **Total** iterations across workers per move; default 10,000 |
| `--seconds` | Optional per-move wall-clock cap; default 0 disables that cap |
| `--game-seconds` | Cumulative decision budget per agent process/game; default 300 |
| `--node-cap` | Total allocated nodes across workers; default 60,000 |
| `--memory-mb` | Tree allocation allowance in MiB; default 128, not a process RSS guarantee |
| `--rave-k` | RAVE blend schedule constant; default 300; zero disables its selection weight |
| `--bridge` | Bridge defence in rollouts, 0 or 1; default 1 |
| `--ordering` | Expansion move ordering, 0 or 1; default 1 |
| `--swap` | Preserved central-opening pie-rule heuristic, 0 or 1; default 1 |
| `--tactics` | Root immediate-win/block checks, 0 or 1; default 1 |

With `--seconds` and no explicit `--iterations`, the deadline controls search.
With both options, whichever limit is reached first stops the search. Worker
allocation for an iteration total `I` is `I/W` plus one for the first `I%W`
workers. Tactical wins, blocks, and swaps use zero iterations and are reported
separately. A shared monotonic deadline includes tactical work; completed
iterations are counted, and every iteration checks the deadline. A small margin
is reserved for aggregation. Timing cannot be an OS scheduling guarantee.

Once the node cap is reached, expansion stops and existing nodes plus rollouts
continue within the iteration/time budget. This bounds tree growth rather than
silently changing the requested iteration count. Telemetry reports whether each
worker reached its cap. Extremely small caps can produce weak or fallback play.

`START` or a non-increasing turn number starts a fresh cumulative game budget.
Decision time includes input parsing and tactics. Use a fresh subprocess per
game and log the agent seed and every configuration option.

The raw native executable defaults `--rave-k` to **300**. The Python CLI and evaluation manifests explicitly use **1000**, as does [the selected configuration](../reports/selection.json). For a direct native invocation of that configuration, pass `--rave-k 1000`; evaluations follow their frozen manifests.

## Statistic conventions

Every node stores wins from **that node's player-to-move perspective**. A parent
inverts its child's win count when selecting an action. This applies at both
players' turns. Terminal nodes are never expanded or rolled out.

Each RAVE node has a separate action-indexed AMAF count and win count. A node's
AMAF suffix contains all subsequent tree and rollout actions by that node's
player, including actions that have not yet become children. Hex is a placement
game, so each action occurs at most once in a continuation. This avoids searching
for an already-played child action in a rollout-only history, the failure mode
identified in the preserved implementation.

For RAVE variants, `beta = sqrt(k / (3 * node_visits + k))`. If an action has no
AMAF observations, its beta is zero. RAVE-UCB blends the Monte Carlo and AMAF win
rates and retains the ordinary child-visit UCB exploration term. RAVE-TS blends
Monte Carlo and AMAF success/failure counts with the same beta and draws from a
Beta posterior with unit success/failure priors. These are explicitly documented
engineering variants, not a claim of reproducing every published RAVE formula.

The extra `legacy_ts` policy is a **same-engine diagnostic control**. It keeps
AMAF disabled and multiplies Monte Carlo successes and failures by
`child_visits / (1000 + child_visits)` before Thompson sampling, reflecting the
historical zero-AMAF blend's effect. It is not the old executable: board handling,
deadlines, allocation, seeding, and other engine details remain maintained code.

## Reproducibility limits

Workers use deterministic seeds derived from the configured base seed, board,
turn, role, and worker ID. Aggregation follows worker ID order; final ties use
visits, then wins, then ascending action ID. Fixed-iteration runs with the same
build, flags, and request history are reproducible while no time cap interrupts
them. Different worker counts deliberately create different random streams.

Cross-platform bitwise move equivalence is not promised: the C++ standard does
not require `shuffle`, integer distributions, or gamma distributions to consume
identical random streams across standard libraries. Time-based runs also vary
with scheduling and hardware. Record OS, compiler, flags, CPU, worker count,
iteration budget, elapsed time, and opponent settings alongside each result.
