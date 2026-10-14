# Experiments and Evidence

[한국어](experiments.ko.md) | **English** | [Project overview](../README.md)

## Questions and scope

Which selection policy is strongest in a common CPU search engine? Do bridge defence, move ordering or a different RAVE weight improve the declared development matchups? How do root-worker counts affect response time and memory under an equal total iteration budget?

This work covers CPU search, correctness repairs, recorded games, parallel measurements and reproducibility tools. It does not retrain a neural model. The original Python research agents, original C++ submission and historical external-opponent images remain preserved as distinct evidence.

## Extended final diagnostics

The deeper study was specified after the first release, with separate seeds and
frozen manifests before the new outcomes. It tests remaining questions; it does
not rewrite the original development procedure or call all later observations
independent confirmations. No new result is used to reselect the base policy.

| Manifest | Question | Games / same-host side pairs | Budget |
| --- | --- | --- | --- |
| `configs/deep/shared-time.json` | Same-allowance strength against UCB, TS, RAVE-UCB and the controlled historical algorithm | 400 / 200, 100 games per opponent | 300-second external per-agent game allowance, two workers |
| `configs/deep/tactical-ablation.json` | Swap, immediate win, immediate block and combined tactical checks | 400 / 200, 100 games per removal | 16,000 total iterations per move, two workers |

The existing 160 development games, 256 fixed-iteration final games, four
original-source time-reference games, 48 short time-policy games and 64
worker-count games remain **532 distinct earlier games**. Their original
manifests, raw records, scores and selection are preserved. The first release's
saved-source snapshot allows replay against the source version that created
those records rather than today's runner.

### Shared external 300-second comparison

![Shared game-time results](../assets/figures/hex-shared-time.svg)

The frozen shared-time evaluation recorded all 400 scheduled games across ten shards, with 400 completed games and 0 failures. Each opponent received 100 games in 50 colour-reversal pairs. Every participant used two native search workers and the same 300-second external per-player allowance. That allowance is a ceiling; early wins, tactical decisions and swap decisions can finish before the time bank is consumed.

| Opponent | Verified selected wins / completed games | Completed-game win rate | Paired bootstrap 95% interval | Failures / scheduled games |
| --- | ---: | ---: | ---: | ---: |
| Controlled historical algorithm | 81 / 100 | 81.0% | 73.0–88.0% | 0 / 100 |
| RAVE-UCB | 84 / 100 | 84.0% | 77.0–90.0% | 0 / 100 |
| Thompson sampling (TS) | 73 / 100 | 73.0% | 65.0–81.0% | 0 / 100 |
| UCB | 70 / 100 | 70.0% | 61.0–79.0% | 0 / 100 |

The paired interval resamples whole completed colour-reversal pairs within the recorded host, hardware and adapter signatures, using 2000 resamples and seed 378. Both legs of every pair retain the same host, executable/source signatures, seed and forced initial stone. Verified wins per all 100 scheduled games and failure counts remain separate denominators; failed games are never credited as strength wins.

The historical comparison uses the preserved search algorithm with its documented seed, worker, protocol and time-control adapter. The generated C++ source and patch receipts bind that execution to the preserved original source. These measurements compare the frozen declared opponents and openings under recorded CPU allocations. They do not establish online-agent performance, an external independent review or superiority outside this evaluation. Worker throughput and the earlier fixed-iteration experiments remain separate evidence.

| Opponent | Recorded hardware | Selected verified wins / completed games |
| --- | --- | ---: |
| Controlled historical algorithm | Windows, Intel64 Family 6 Model 141 Stepping 1, GenuineIntel | 17 / 20 |
| Controlled historical algorithm | Linux, Intel(R) Xeon(R) CPU @ 2.20GHz | 50 / 60 |
| Controlled historical algorithm | Linux, AMD EPYC 7B12 | 14 / 20 |
| RAVE-UCB | Windows, Intel64 Family 6 Model 141 Stepping 1, GenuineIntel | 15 / 20 |
| RAVE-UCB | Linux, Intel(R) Xeon(R) CPU @ 2.20GHz | 50 / 60 |
| RAVE-UCB | Linux, AMD EPYC 7B12 | 19 / 20 |
| Thompson sampling (TS) | Windows, Intel64 Family 6 Model 141 Stepping 1, GenuineIntel | 14 / 20 |
| Thompson sampling (TS) | Linux, Intel(R) Xeon(R) CPU @ 2.20GHz | 44 / 60 |
| Thompson sampling (TS) | Linux, AMD EPYC 7B12 | 15 / 20 |
| UCB | Windows, Intel64 Family 6 Model 141 Stepping 1, GenuineIntel | 9 / 20 |
| UCB | Linux, Intel(R) Xeon(R) CPU @ 2.20GHz | 48 / 60 |
| UCB | Linux, AMD EPYC 7B12 | 13 / 20 |

Each comparison contains five recorded host/adapter pair strata. Hardware labels in the table combine equivalent recorded hardware fingerprints: 20 Windows games, 60 Xeon Kaggle games and 20 EPYC Kaggle games per opponent. Both participants stay on the same VM within each pair. Each remote VM reported four logical and affinity CPUs with cgroup quota 400000/100000; two concurrent game drivers used two native search workers each.

| Opponent | Selected wins when initially first / games | Selected wins when initially second / games |
| --- | ---: | ---: |
| Controlled historical algorithm | 40 / 50 | 41 / 50 |
| RAVE-UCB | 41 / 50 | 43 / 50 |
| Thompson sampling (TS) | 35 / 50 | 38 / 50 |
| UCB | 34 / 50 | 36 / 50 |

These side counts use the initial participant assignment. The pie rule can exchange participant colours after the first stone, so they are not final-colour win rates.

| Opponent | Participant | Sampled process RSS median / p95 (MiB) | Search-response iterations median | Worker node-cap hits / observations |
| --- | --- | ---: | ---: | ---: |
| Controlled historical algorithm | historical_algorithm | 694.9 / 1680.0 | 240,691 | Not instrumented |
| Controlled historical algorithm | Selected RAVE-TS | 125.4 / 128.3 | 174,026.5 | 3,934 / 4,436 |
| RAVE-UCB | rave_ucb | 125.5 / 127.9 | 641,657.5 | 3,991 / 4,052 |
| RAVE-UCB | Selected RAVE-TS | 125.4 / 128.6 | 170,866 | 3,860 / 4,258 |
| Thompson sampling (TS) | Selected RAVE-TS | 125.4 / 128.3 | 169,701 | 4,114 / 4,696 |
| Thompson sampling (TS) | ts | 107.0 / 108.6 | 190,167 | 3,884 / 4,546 |
| UCB | Selected RAVE-TS | 125.4 / 128.8 | 172,074 | 3,711 / 4,150 |
| UCB | ucb | 107.0 / 108.6 | 642,997 | 3,804 / 3,940 |

All 800 participant-game RSS measurements were available. RSS is sampled process memory, not a hard OS memory cap. The maintained engine uses a finite tree node allowance derived from its 128 MiB tree budget and continues rollouts after expansion reaches that allowance. The historical algorithm retains its original allocation design; time and worker allowances match, but memory designs do not. Node-cap observations describe bounded expansion, not failed searches. The controlled historical adapter reported 2003 search responses with its original iteration-cap flag and zero hits; it does not instrument per-worker node-cap or elapsed-time fields.

Search throughput uses summed native iterations divided by summed outer native response elapsed seconds. Parallel worker elapsed values overlap and are not CPU usage time or the throughput denominator. Aggregate timing and memory across different machines are descriptive; they are not a direct same-hardware speed or memory reduction claim.

The benchmark compares deployed algorithms and declared resource settings.
Different tree representations, random streams, old iteration caps and memory
growth prevent attributing the whole score difference to AMAF alone. The old
four-game source-exact comparison remains a limited execution reference with
different time managers, not a substitute for this study.

Full evidence is retained in the [shared-time aggregate](../reports/deep/aggregates/shared-time.json), [response and resource analysis](../reports/deep/analysis/shared-time-costs.json) and [per-game records](../reports/deep/evaluation/shared-time/).

### Tactical ablations and activation counts

![Individual tactical removals](../assets/figures/hex-tactical-ablation.svg)

All 400 tactical games completed, with zero failures and zero missing games.

| Removed feature | Selected wins / completed games | Complete pairs | Pair mean and 95% interval |
| --- | ---: | ---: | --- |
| Swap heuristic | 51 / 100 | 50 | 51.0%, 46.0–56.0% |
| Immediate-win check | 50 / 100 | 50 | 50.0%, 50.0–50.0% |
| Immediate block | 50 / 100 | 50 | 50.0%, 50.0–50.0% |
| Both tactical checks | 50 / 100 | 50 | 50.0%, 50.0–50.0% |

These outcomes do not demonstrate a strength gain. Each observed pair in the
three immediate-check comparisons split one win each, so their empirical
pair-bootstrap intervals collapse to 50–50%. This is zero variance in the
observed pair scores, not exact population strength or evidence of equivalence.
Recorded full physical traces were identical in 48/50 immediate-win pairs and
27/50 pairs for both block and combined checks. The differing immediate-win
traces changed only the final winning coordinate. All 7,407 shared ordinary-search
positions across the four comparisons recorded the same worker seeds and moves.

At 50 matched winning positions, the immediate check's median external response
was 0.191 ms versus 231.654 ms for ordinary search. At 68 matched blocking
positions, it was 0.256 ms versus 687.677 ms. These are conditional responses
at the same input; some chosen actions differ. They are not whole-agent speedup
factors. Median response across all moves remained about 1.16–1.22 seconds.
The fixed selected policy was not retuned using these final diagnostics.

The four controls are `no_swap`, `no_win_check`, `no_block_check` and `no_tactics`.
All remaining settings match the fixed selected participant. Per-game telemetry
records actual `pie_rule_swap`, `tactical_win` and `tactical_block` decisions for
both participants, plus externally measured responses. Activation counts and
response medians must state which completed games they cover.

These four related comparisons are descriptive. Rare tactical opportunities can
make win-rate contrasts weakly informative. An interval crossing 50% does not
prove equality, while an isolated interval excluding 50% does not establish a
multiple-comparison-adjusted discovery. The final diagnostic set is not a
pick-the-best-feature tuning set. Unsuccessful optional candidates are recorded
and stopped; predefined final game coverage is not stopped after a favorable
intermediate score.

The frozen 11×11 scenario set contains 61 positions: 45 replayed legal Red-first histories and 16 static symmetry states. It covers central, edge and corner openings, immediate wins and single opponent threats. All 488 responses passed; all 244 V2/V3 comparisons matched both move and reason, and all four invalid-input or terminal-state rejection checks passed. Red-first match-history reachability is not asserted for the static counterparts. [The raw scenario receipt](../reports/deep/correctness/scenarios/receipt.json) records branch and protocol correctness, not a full-game win rate. A disabled branch can still find the same move through ordinary search.

### Six-position worker measurements

![Six-position worker costs](../assets/figures/hex-worker-positions.svg)

Windows and Kaggle Linux each completed 168 searches on the same fixture hash: 336 requests in total. Six states, four worker settings and seven repeats used exactly 16,000 total iterations per request, giving 2,688,000 iterations per host and 5,376,000 combined.

Three states replay legal Red-first histories at turns 2, 41 and 81. Three counterparts transpose those boards and exchange colours; they are static nonterminal states, not asserted reachable Red-first match histories.

| Environment | 4 vs 1 workers: median latency speedup | 8 vs 4: median time reduction | Observed logical CPUs |
| --- | --- | --- | --- |
| Local Windows | 3.34–3.68× | 39.52–43.33% | 16 |
| Kaggle Linux | 3.20–3.49× | 1.60–8.36% | 4 |

Ratios are calculated within each environment. Hardware, compiler and operating system differ together, so cross-host differences do not isolate an algorithm improvement or an operating-system effect. Kaggle ran eight workers within a four-CPU allocation; this does not provide eight CPU cores.

Cells show request-to-response p50 / p95 in milliseconds. p95 is a descriptive linear interpolation of seven observations.

**Local Windows**

| State | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | --- | --- | --- | --- |
| Opening, turn 2 | 750.8 / 772.8 | 380.9 / 418.0 | 221.4 / 235.4 | 126.1 / 132.5 |
| Middle, turn 41 | 744.5 / 775.3 | 377.1 / 403.3 | 202.1 / 210.5 | 120.8 / 122.6 |
| Late, turn 81 | 446.0 / 456.9 | 220.9 / 256.9 | 129.6 / 137.5 | 78.4 / 82.9 |
| Opening static symmetry | 748.1 / 776.0 | 374.6 / 392.5 | 219.4 / 238.1 | 128.7 / 134.6 |
| Middle static symmetry | 733.3 / 751.0 | 361.1 / 398.3 | 207.9 / 227.9 | 117.8 / 123.6 |
| Late static symmetry | 425.5 / 438.4 | 219.0 / 229.4 | 127.3 / 138.0 | 76.9 / 80.2 |

Maximum recorded native-process peak RSS across seven repeats per setting, MiB:

| State | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | --- | --- | --- | --- |
| Opening, turn 2 | 36.73 | 36.96 | 36.21 | 37.12 |
| Middle, turn 41 | 31.84 | 32.39 | 32.70 | 32.06 |
| Late, turn 81 | 26.91 | 27.31 | 28.07 | 27.20 |
| Opening static symmetry | 36.74 | 36.86 | 37.13 | 35.83 |
| Middle static symmetry | 31.84 | 32.21 | 32.29 | 31.97 |
| Late static symmetry | 26.88 | 26.99 | 27.89 | 27.69 |

**Kaggle Linux**

| State | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | --- | --- | --- | --- |
| Opening, turn 2 | 994.7 / 1017.2 | 463.5 / 472.0 | 310.5 / 316.4 | 300.9 / 304.7 |
| Middle, turn 41 | 1018.6 / 1053.0 | 469.1 / 492.0 | 292.1 / 293.6 | 273.2 / 279.9 |
| Late, turn 81 | 574.6 / 580.6 | 276.2 / 281.2 | 175.1 / 177.0 | 160.5 / 164.6 |
| Opening static symmetry | 996.4 / 1021.1 | 463.6 / 466.6 | 310.5 / 356.9 | 305.6 / 327.6 |
| Middle static symmetry | 1002.1 / 1039.9 | 464.1 / 477.6 | 289.8 / 296.2 | 276.7 / 282.7 |
| Late static symmetry | 578.6 / 590.0 | 273.9 / 276.8 | 173.2 / 175.8 | 160.4 / 166.1 |

Maximum recorded native-process peak RSS across seven repeats per setting, MiB:

| State | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | --- | --- | --- | --- |
| Opening, turn 2 | 35.41 | 35.52 | 35.26 | 28.77 |
| Middle, turn 41 | 30.67 | 30.38 | 30.14 | 30.20 |
| Late, turn 81 | 25.39 | 25.36 | 25.62 | 21.57 |
| Opening static symmetry | 35.29 | 35.40 | 35.29 | 29.07 |
| Middle static symmetry | 30.48 | 30.46 | 30.23 | 26.86 |
| Late static symmetry | 25.48 | 25.45 | 25.48 | 19.75 |

Every response selected a legal empty cell, and per-worker iterations summed to exactly 16,000. Recorded node-cap hits: 0. RSS includes native workers and excludes the Python driver. Windows records PeakWorkingSetSize and Linux records VmHWM; the cross-host memory values do not come from an identical measurement API. The memory setting bounds native node pools; it is not an OS-enforced whole-process memory ceiling. Swap and immediate tactical shortcuts were disabled, so every request followed the search path.

Each request used a fresh native process, and settings ran in fixed order. The request-to-response clock excludes the Python process-creation call but can include native initialization still in progress. Dividing iterations among independent trees changes trajectories and work per iteration, so ratios are not pure parallel efficiency or playing-strength gains. Seven-repeat p95 values do not precisely estimate a production tail. These outcomes did not retune the selected policy. Raw records remain in `reports/deep/benchmarks/windows.json` and `reports/deep/benchmarks/kaggle.json`.

The new benchmark keeps three nonterminal positions replayed from legal
Red-first histories at turns 2, 41 and 81, plus three transposed, colour-exchanged
static nonterminal states. Reachability from a legal Red-first match history is
not asserted for those three static counterparts. Workers 1, 2,
4 and 8 each complete the same total iteration count. Swap and immediate
tactical shortcuts are disabled for these timing requests. Fixtures are pinned
by hash rather than regenerated independently on each host.

Report p50 and p95 external response times, throughput, repetitions and process
peak RSS separately for every position and environment. RSS covers native
workers and excludes the Python driver. Missing measurements remain null. The
earlier single-position timings are retained as historical measurements, not
overwritten by these more varied states. CPU competition during a run must be
stated; a visible CPU count alone does not establish exclusive physical cores.

### Public execution and historical replay

The generated public CPU package was actually executed on Kaggle. It extracted
and checked its embedded source archive, compiled maintained and historical
sources, ran maintained/referee/adapter tests and ASan/UBSan checks, and recorded
four completed V3 games under a five-second per-agent allowance. This is an
end-to-end packaging check, not part of the 400-game performance study.

The latest public-tool v3 execution passed 107 Python test executions without skips, 15 native self-test checks and six sanitizer protocol tests. Its four V3 games all completed and all 100 saved moves replayed. A separate checkpoint execution assigned 40 games from the 400-game manifest and stopped before the first evaluation game, recording zero games. That checkpoint contributes no strength samples. [Public runtime evidence](deep-runtime.md) and [limitations](limitations.md) separate these claims.

The original 532 games and 16,768 moves were replayed from their saved source
snapshot. The extended release verifier must bind each old and new suite to its
actual source and runner receipts. Replaying saved moves proves legal transitions
and recorded connecting-path winners; it does not replay search or prove
strategic optimality. Another runtime under the same author's account is not an
independent external person's review.

## Procedure fixed before results

[The study plan](../reports/study-plan.json) was frozen before development outcomes. Development comparisons used 11×11 boards, 4,000 total iterations per move across two workers, a 100,000-node cap, a 300-second per-player game ceiling and a 60-second response deadline. The two legs of a side-reversal pair shared the seed and forced opening and ran on the same host. Local Windows and Kaggle CPU records are also summarized separately by environment.

| Manifest | Purpose | Games / side-reversal pairs |
| --- | --- | --- |
| `development-policy` | Four-policy round robin | 96 / 48 |
| `development-features` | Four optional RAVE-TS changes | 64 / 32 |
| `final-policy` | Selected policy against four controls, new seeds | 256 / 128 |
| `final-time-reference` | Execution reference against rebuilt original source | 4 / 2 |
| `supplemental-time-policy` | Equal-time policy comparison | 48 / 24 |
| `supplemental-workers` | Equal-time worker-count matches | 64 / 32 |

Policy selection uses balanced completed-game scores. Ties retain RAVE-TS, then follow the declared policy order. An optional change requires at least a 55% score and a paired-bootstrap 95% lower bound **strictly above** 50%. Failed candidates are stopped. Correctness repairs are not optional features rolled back according to win rate.

[The final-plan addendum](../reports/final-plan-addendum.json) explains excluding a selected policy from its own opponents and adding `legacy_ts` as a diagnostic control. [Selection](../reports/selection.json) and [the freeze receipt](../reports/final-freeze.json) pin the settings and final-manifest hashes.

## Development policy comparison: 96 completed games, zero failures

| Policy | Wins / completed games | Development selection score |
| --- | --- | --- |
| RAVE-TS | 44 / 48 | 91.7% |
| RAVE-UCB | 22 / 48 | 45.8% |
| Thompson sampling | 18 / 48 | 37.5% |
| UCB | 12 / 48 | 25.0% |

Each game contributes once to each participant's score, so the policy denominators sum to 192 for 96 games. **RAVE-TS was selected** using these scores; they are not independent final estimates.

| Left policy | Right policy | Left wins / completed games | Complete pairs | Paired 95% interval for left score |
| --- | --- | --- | --- | --- |
| RAVE-TS | RAVE-UCB | 14 / 16 | 8 | 68.8–100% |
| RAVE-TS | Thompson sampling | 14 / 16 | 8 | 75.0–100% |
| RAVE-TS | UCB | 16 / 16 | 8 | 100–100% |
| RAVE-UCB | Thompson sampling | 9 / 16 | 8 | 25.0–87.5% |
| RAVE-UCB | UCB | 11 / 16 | 8 | 43.8–87.7% |
| Thompson sampling | UCB | 9 / 16 | 8 | 37.5–75.0% |

Intervals resample observed complete pairs 2,000 times with bootstrap seed 378. If all observed pairs are wins, the empirical nonparametric interval can collapse to 100–100%. This does not guarantee future wins or establish generalization beyond the small development sample and observed openings. Game-level Wilson intervals are descriptive fields in the aggregate JSON.

## Optional features: 64 completed games, zero failures

The full baseline is RAVE-TS with bridge defence and move ordering enabled and `rave_k=1000`. Rates and intervals below are from the **candidate's** perspective against that baseline.

| Candidate change | Candidate wins / completed games | Candidate score | Paired 95% interval | Adoption |
| --- | --- | --- | --- | --- |
| Remove bridge defence | 3 / 16 | 18.8% | 0–37.5% | Stopped |
| Remove move ordering | 8 / 16 | 50.0% | 25.0–75.0% | Stopped |
| `rave_k=300` | 8 / 16 | 50.0% | 18.8–81.2% | Stopped |
| `rave_k=3000` | 12 / 16 | 75.0% | 50.0–100% | Stopped |

Each comparison contains eight complete pairs. `rave_k=3000` had the highest point score but a lower bound of exactly 50%, so it failed the strict adoption gate. Retaining move ordering does not establish a measured isolated benefit from ordering. The final configuration remained RAVE-TS, bridge defence and ordering enabled, `rave_k=1000`, with no further candidate tuning.

## Worker throughput and memory: measured results

The common 11×11 snapshot has Red at `(0,0)` and Blue to move on turn two. Swap is disabled and **16,000 total iterations** are divided across 1, 2, 4 and 8 workers. Trial seeds start at 378, with bridge defence and ordering enabled. Windows used seven repeats and Kaggle five; every trial completed exactly 16,000 iterations.

| Host | Workers | Median external response, seconds | External iterations/second | Speedup over one worker | Maximum native peak RSS, MiB |
| --- | --- | --- | --- | --- | --- |
| Windows | 1 | 0.754 | 21,216 | 1.00× | 36.7 |
| Windows | 2 | 0.396 | 40,420 | 1.91× | 37.0 |
| Windows | 4 | 0.231 | 69,383 | 3.27× | 37.3 |
| Windows | 8 | 0.131 | 122,474 | 5.77× | 38.1 |
| Kaggle CPU | 1 | 1.897 | 8,436 | 1.00× | 35.6 |
| Kaggle CPU | 2 | 0.980 | 16,321 | 1.93× | 35.3 |
| Kaggle CPU | 4 | 0.714 | 22,413 | 2.66× | 35.1 |
| Kaggle CPU | 8 | 0.683 | 23,412 | 2.78× | 32.7 |

Throughput is the median of completed iterations divided by externally measured response time; speedup compares that metric within the same host. RSS is the largest per-process peak across repeats and excludes the Python runner. Different tree partitions, allocation and trajectories mean RSS need not rise monotonically with workers.

Windows recorded Python 3.12.7 and 16 visible logical CPUs. Kaggle recorded x86_64 Linux, Python 3.13.15 and four visible and affinity CPUs. Its `cpu.max=400000 100000` provided four CPUs of time allocation. These hosts used different toolchains and processors; cross-host throughput is not an algorithmic improvement factor. Kaggle's small observed gain from four to eight workers is also specific to this snapshot and session.

This is a **single-snapshot throughput benchmark**. It is not a match win rate or mean response time throughout a game. Worker-count playing outcomes appear in the separate time-budget experiment below. Raw repeats are in [the Windows JSON](../reports/benchmarks/windows.json) and [the Kaggle JSON](../reports/benchmarks/kaggle.json).

## Final evaluation

<!-- FINAL_RESULTS_BEGIN -->
All 256 frozen final games are recorded: 256 completed, 0 failed and zero missing. Win rates use completed games; failures are not converted to wins.

| Opponent | RAVE-TS wins / completed games | Win rate | Complete pairs | Paired 95% interval | Failures |
| --- | --- | --- | --- | --- | --- |
| legacy_ts | 55 / 64 | 85.9% | 32 | 78.1–93.8% | 0 |
| RAVE-UCB | 54 / 64 | 84.4% | 32 | 76.6–92.2% | 0 |
| Thompson sampling | 53 / 64 | 82.8% | 32 | 75.0–90.6% | 0 |
| UCB | 57 / 64 | 89.1% | 32 | 79.7–96.9% | 0 |

These new-seed outcomes were not used for selection. They apply to the declared internal opponents, openings and CPU budgets. [The final aggregate](../reports/aggregates/final-policy.json) also provides environment-specific results and failure details.
<!-- FINAL_RESULTS_END -->

`legacy_ts` is a diagnostic inside the maintained engine with AMAF disabled and the historical direct-count attenuation. It is neither the original executable nor an exact replay of its games. Conclusions remain conditional on the declared internal opponents, openings, budgets and implementation.

## Original-source time reference

<!-- ORIGINAL_REFERENCE_BEGIN -->
The rebuilt-original time reference records 4 games: 4 completed and 0 failed. Selected RAVE-TS won 4/4 completed games. Both agents use eight workers and a 300-second per-player ceiling; only the maintained engine has a five-second per-move cap. This is an execution check over two pairs with different time managers. [Time-reference aggregate](../reports/aggregates/final-time-reference.json)
<!-- ORIGINAL_REFERENCE_END -->

This checks two executions with different time managers. It is not an equal-time same-engine policy ablation or a statistical improvement claim against the old submission. The shipped historical Linux binary remains preserved and receives a separate hash and portability check.

## Equal-time policy comparison

[The supplemental plan](../reports/supplemental-plan.json) was declared after primary final execution began but before supplemental outcomes. These two suites are exploratory additions, not initially declared confirmatory tests. Both use a 100,000-node cap, a declared 128 MiB tree allowance, a 300-second per-player ceiling and a 30-second response deadline.

<!-- SUPPLEMENTAL_TIME_BEGIN -->
All 48 supplemental games are recorded: 48 completed, 0 failed and zero missing.

| Opponent | RAVE-TS wins / completed games | Win rate | Complete pairs | Paired 95% interval | Failures |
| --- | --- | --- | --- | --- | --- |
| RAVE-UCB | 12 / 16 | 75.0% | 8 | 56.2–93.8% | 0 |
| Thompson sampling | 13 / 16 | 81.2% | 8 | 56.2–100.0% | 0 |
| UCB | 14 / 16 | 87.5% | 8 | 75.0–100.0% | 0 |

The per-move cap is 0.25 seconds, with same-host side-reversal pairs and fixed openings. This exploratory addition was not used to reselect the policy or worker setting. [Supplemental aggregate](../reports/aggregates/supplemental-time-policy.json)
<!-- SUPPLEMENTAL_TIME_END -->

## Worker-count matches under equal time

<!-- SUPPLEMENTAL_WORKERS_BEGIN -->
All 64 supplemental games are recorded: 64 completed, 0 failed and zero missing.

| Condition | RAVE-TS wins / completed games | Win rate | Complete pairs | Paired 95% interval | Failures |
| --- | --- | --- | --- | --- | --- |
| RAVE-TS w1 vs UCB w2 | 12 / 16 | 75.0% | 8 | 56.2–93.8% | 0 |
| RAVE-TS w2 vs UCB w2 | 16 / 16 | 100.0% | 8 | 100.0–100.0% | 0 |
| RAVE-TS w4 vs UCB w2 | 14 / 16 | 87.5% | 8 | 75.0–100.0% | 0 |
| RAVE-TS w8 vs UCB w2 | 14 / 16 | 87.5% | 8 | 68.8–100.0% | 0 |

The per-move cap is 0.25 seconds, with same-host side-reversal pairs and fixed openings. This exploratory addition was not used to reselect the policy or worker setting. [Supplemental aggregate](../reports/aggregates/supplemental-workers.json) Total CPU work differs; every condition faces UCB with two workers.
<!-- SUPPLEMENTAL_WORKERS_END -->

This holds per-move wall time and the opponent fixed, not total CPU work. Eight workers share Kaggle's four-CPU allocation. Each condition has only eight pairs: report intervals and failures and avoid superiority claims based on small score differences.

## Correctness and preservation evidence

In the Python diagnostic on an empty 3×3 board with 1,000 iterations, historical RAVE updated zero times while the corrected reference recorded 13,772 AMAF updates. An independent aggregation also counted 13,772. This demonstrates active statistics in that diagnostic; it is not evidence of improved win rate or throughput.

The native self-test compares both colours on all 19,683 possible 3×3 assignments against BFS connectivity, and checks node-specific updates, opponent turns, terminal states, tactics and resource limits. [The original inventory](../reports/baseline/original-source-inventory.json) pins preserved source and match assets. [The reproducibility guide](reproducibility.md) explains saved-bundle verification and new execution.

## Preserved external-opponent games

[Recorded-match metadata](../assets/results/recorded-matches.csv) identifies four historical 11×11 executions. The external Davis and HexHex executables and complete original tournament CSV are unavailable; new internal games are not claimed to reproduce those matchups.

| Historical match | Recorded result |
| --- | --- |
| RAVE-TS vs Davis 7, first | Win after 47 turns |
| RAVE-TS vs Davis 10, first | Win after 33 turns |
| RAVE-TS vs HexHex, second | Loss after 40 turns |
| MCTS baseline vs HexHex, second | Loss after 50 turns |

![RAVE-TS win against Davis 7](../assets/results/rave-vs-davis-7-win.png)

![RAVE-TS win against Davis 10](../assets/results/rave-vs-davis-10-win.png)

![RAVE-TS loss against HexHex](../assets/results/rave-vs-hexhex-loss.png)

![MCTS loss against HexHex](../assets/results/mcts-vs-hexhex-loss.png)

These images support individual outcomes. Incomplete opponent, seed and hardware records prevent treating them as a measured win rate. Differences in turn count between separate games do not establish an improvement factor.

## Scope of the preserved first release

The earlier strengthening plan also requests same-engine policy comparisons under both equal iterations and equal time, and actual playing-strength scores for 1, 2, 4 and 8 workers. Fixed-iteration development comparisons and single-snapshot worker throughput are complete. Final fixed-iteration, original-source time-reference and supplemental match manifests are recorded separately. Equal-time policy and worker-count outcomes are described only from their respective verified supplemental results, without changing the selected policy.


[Optional analysis tools](../tools/analysis/) reanalyze recorded data without new games or policy selection.
