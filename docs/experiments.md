# Experiments and Evidence

[한국어](experiments.ko.md) | **English** | [Documentation](README.md)

## Question

Which tree-selection policy gives the strongest practical Hex agent when the rest of the Python MCTS pipeline is held constant, and what engineering changes are needed once Python simulation speed becomes the limiting factor?

## Controlled variants

All four agents inherit the same implementation in [`mcts_core.py`](../engine/agents/Group26/mcts_core.py). They share legal-move generation, expansion, randomized rollouts, backpropagation, a 300-second match budget, and final choice by root visit count.

| Variant | Selection rule | Intended effect |
| --- | --- | --- |
| UCB | Win rate plus an exploration bonus | Deterministic optimism under uncertainty |
| Thompson sampling | Sample from a beta posterior | Probability-matched exploration |
| RAVE-UCB | Blend direct and all-moves-as-first estimates, then add UCB | Faster early estimates with explicit exploration |
| RAVE-TS | Blend direct and RAVE counts in a beta posterior | Fast early sharing with stochastic exploration |

The original project record identifies RAVE-TS as the strongest of these implementations in self-play and the internal group tournament. The repository does not contain the underlying tournament CSV, so this is presented as a historical finding rather than an independently reproducible aggregate metric.

## Recorded match gallery

Machine-readable metadata for these screenshots is available in [`recorded-matches.csv`](../assets/results/recorded-matches.csv).

### RAVE-TS vs Davis 7 - win as first player

![RAVE-TS win against Davis 7](../assets/results/rave-vs-davis-7-win.png)

The captured referee output records a RAVE win after 47 turns.

### RAVE-TS vs Davis 10 - win as first player

![RAVE-TS win against Davis 10](../assets/results/rave-vs-davis-10-win.png)

The captured referee output records a RAVE win after 33 turns.

### RAVE-TS vs HexHex - loss as second player

![RAVE-TS loss against HexHex](../assets/results/rave-vs-hexhex-loss.png)

The stronger external agent won the recorded game after 40 turns.

### MCTS baseline vs HexHex - loss as second player

![MCTS loss against HexHex](../assets/results/mcts-vs-hexhex-loss.png)

The baseline loss was recorded after 50 turns. Because this is a separate game rather than a matched multi-seed experiment, the turn counts alone do not establish the size of RAVE's improvement.

## What changed in the final agent

The optimized version preserves RAVE-guided Thompson sampling and adds:

- a C++17 hot path;
- union-find connectivity checks;
- eight independent root-parallel searches;
- per-worker pooled allocation;
- bridge-saving simulation moves;
- heuristic move ordering;
- immediate win and block detection;
- an opening swap rule based on hex distance;
- turn-aware use of the remaining match time.

These changes target throughput and search quality simultaneously, so the current artifacts do not isolate each feature's individual contribution.

## Evaluation limits

- The four screenshots are individual outcomes, not statistically significant win rates.
- Opponent versions, hardware, random seeds, and full command lines were not captured alongside every image.
- The repository has no committed benchmark table for simulations per second or ablation results.
- First-player and second-player results should not be compared without controlling the opening and the pie rule.
- Historical notes describe larger self-play and internal tournament work, but the raw datasets are not included here.

## Recommended next evaluation

For a portfolio-grade follow-up, run at least 100 paired games per matchup with alternating colours and fixed seed lists. Record agent commit, hardware, wall-clock time, simulations, move count, colour, swap decision, and outcome as CSV. Compare RAVE-TS against each baseline and publish Wilson confidence intervals together with simulations per second. Ablate parallelism, bridge saving, move ordering, and the swap heuristic one at a time.
