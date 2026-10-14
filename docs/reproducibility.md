# Reproducibility Guide

[한국어](reproducibility.ko.md) | **English** | [Project overview](../README.md)

## What can be reproduced

The source, frozen manifests, evaluator and saved game results support three checks that answer different questions.

1. Build and run the maintained agent on a new host.
2. Replay saved moves to verify legality, pie-rule identities, final boards and connecting-path winners.
3. Rerun the declared matches and compare the reported statistics within their runtime and sampling scope.

Replay does not repeat the search or prove that a move was strategically optimal. A fresh run with a different compiler, C++ standard library or hardware may not produce byte-identical search trajectories. Fixed-iteration repeats with the same source, binary, seed and worker settings are checked separately from time-budget experiments.

## Prerequisites and build

Use Python 3.10 or newer and a C++17 compiler available as `g++`, `clang++` or `zig c++`. The maintained Python runtime needs no third-party packages. The source checkout or source ZIP is sufficient; Kaggle and Docker are not required for local verification.

From the repository root:

```bash
python -m hexai doctor
python -m hexai build
python -m unittest discover -s tests -v
```

`doctor` reports platform, Python, visible logical CPUs, Linux CPU affinity and available cgroup limits. It also reports compiler availability. A zero exit code can still accompany a JSON `compiler.error`, so inspect the output and perform the actual `build` to establish readiness.

An explicitly selected compiler can be used with:

```bash
python -m hexai doctor --compiler clang++
python -m hexai build --compiler clang++
```

The build uses `-std=c++17 -O3 -pthread`, runs the native self-test and stores the executable and its build receipt in `.local/bin/`. It rejects outputs that would overwrite `engine/`, `deployment/` or the original executable. The receipt records compiler version, build command and source/compiler/executable hashes.

To inspect a short search independently of the match runner:

```bash
python -m hexai predict --board "R00,000,000" --colour B --turn 2 --policy rave_ts --iterations 1000 --workers 1 --swap 0
```

The board uses comma-separated rows with `R`, `B` and `0`. Coordinates are zero-based. `predict` is a snapshot inspection command; the complete evaluation runner manages pie swaps, participant identities and cumulative game budgets.

## Frozen manifests and evaluation splits

Each manifest fixes participant settings, board size, budget, game IDs, seed, forced opening and side-reversal pair ID. The canonical manifest hash is recorded with every game and output directory. A pair has exactly two games with the same seed and opening and reversed starting participant assignments.

The declared development suites are:

| Manifest | Role | Declared scale |
| --- | --- | --- |
| `configs/development-policy.json` | Four-policy comparison | 96 games, 48 side-reversal pairs |
| `configs/development-features.json` | Bridge, ordering and RAVE-weight comparisons | 64 games, 32 side-reversal pairs |

Both use 4,000 total iterations per move and two workers. The [study plan](../reports/study-plan.json) records the selection criterion before results are inspected. Policy selection uses the balanced completed-game score, with declared tie handling. Optional changes require a score at least five percentage points above 50% and a pair-bootstrap lower bound above 50%. Unsuccessful candidates are recorded and stopped. Correctness repairs are not optional win-rate experiments.

Final search settings are recorded in [`reports/selection.json`](../reports/selection.json) before evaluating new seeds. [`configs/final-policy.json`](../configs/final-policy.json) schedules 256 games, or 128 side-reversal pairs, against the three alternative maintained policies and `legacy_ts`. The selected policy is excluded from its own opponent list. The [final-plan addendum](../reports/final-plan-addendum.json) records this scope without rewriting the original study plan.

Final seeds and opening seeds are disjoint from development. Fresh opening seeds do not guarantee unique board coordinates or unseen opening positions. The chosen policy is not changed after viewing the final outcome.

```bash
python -m hexai validate --config configs/final-policy.json --development configs/development-policy.json configs/development-features.json
python -m hexai evaluate --config configs/final-policy.json --output .local/final-policy
```

Public aggregates are in [the aggregate directory](../reports/aggregates/); raw records are in [the per-run directory](../reports/evaluation/). Primary suites are `development-policy`, `development-features`, `final-policy` and `final-time-reference`; additions are `supplemental-time-policy` and `supplemental-workers`. Development and primary policy runs use `windows-shard0`, `windows-shard1`, `kaggle-shard2` and `kaggle-shard3`. Original-source time and supplemental suites contain Kaggle records. Each run preserves `manifest.json`, `metadata.json` and `games/`. The raw native `rave_k=300` default differs from the selected setting of `1000`.

## Single-host evaluation and resume

[The supplemental plan](../reports/supplemental-plan.json) separately freezes equal-time measurements. The policy suite uses two workers and 0.25 seconds per move; the worker suite compares RAVE-TS with 1, 2, 4 and 8 workers against a fixed two-worker UCB opponent. These exploratory measurements were added after primary final execution began and do not reselect the policy.

```bash
python -m hexai evaluate --config configs/supplemental-time-policy.json --output .local/supplemental-time-policy
python -m hexai evaluate --config configs/supplemental-workers.json --output .local/supplemental-workers
```

Pairs run sequentially on the same host. Do not interpret times from overlapping CPU workloads as isolated runs. The worker suite controls wall time, not total CPU work.

```bash
python -m hexai evaluate --config configs/development-policy.json --output .local/development-policy
python -m hexai evaluate --config configs/development-policy.json --output .local/development-policy --resume
```

The first command requires a fresh output directory. The second checks the frozen manifest, host metadata, runner hashes, executable hashes and shard assignment before resuming. If any of these change, use a separate output directory rather than merging incompatible runs.

After each finished game, the runner writes a JSON result, JSONL move/diagnostic stream, CSV and updated summary. Existing game files are replay-verified before being skipped. A game interrupted before its result file was saved is rerun. A previously recorded failed game remains a recorded failure; it is not silently replaced by a more favorable outcome.

```text
.local/development-policy/
├── manifest.json            Frozen input
├── metadata.json            Host, runner and binary fingerprints
├── games.csv                Per-game results and failure statuses
├── summary.json             Coverage and comparison statistics
└── games/
    ├── GAME_ID.json          Moves, outcome, commands and telemetry
    └── GAME_ID.jsonl         Referee and engine event stream
```

## Local and Kaggle CPU shards

The same manifest can be split between two hosts. Sharding uses entire pairs, so the two side-reversed games stay on one host. Run the local shard as:

```bash
python -m hexai evaluate --config configs/development-policy.json --output .local/development-policy-local --shard-index 0 --shard-count 2
```

On a CPU-only Kaggle session, extract the same source release, build its executable and run the other shard:

```bash
python -m hexai doctor
python -m hexai build
python -m hexai evaluate --config configs/development-policy.json --output .local/development-policy-kaggle --shard-index 1 --shard-count 2
```

The measured Kaggle probe for this study reported four visible logical CPUs, affinity to four CPUs and a cgroup CPU quota of `400000 100000`, equivalent to four CPUs of time allocation. Its memory limit was 30 GiB. The probe used Python 3.13.15 and g++ 13.3.0 on x86_64 Linux with no GPU requested. These are this session's measured resources, not a guarantee for every future Kaggle session. Run `doctor` again and inspect quota as well as the visible CPU count.

Copy the Kaggle output directory back without flattening its `games/` subdirectory or altering its manifest and metadata. Then aggregate:

```bash
python -m hexai aggregate --inputs .local/development-policy-local .local/development-policy-kaggle --output .local/development-policy-combined.json --require-complete
```

Aggregation rejects different manifests, duplicate game IDs and replay failures. `--require-complete` means every scheduled game has a recorded result; it does not mean every recorded game completed successfully. The output includes separate environment summaries. Keep host-specific throughput and time measurements separate even when reporting combined fixed-budget matchup scores.

Kaggle session restarts may change host metadata. An incompatible host is treated as a separate run and requires an explicitly documented allocation of nonoverlapping games. Do not edit metadata merely to bypass the resume check or aggregate duplicate results.

## Saved-game replay

For the first local policy-comparison game:

```bash
python -m hexai replay --input .local/development-policy-local/games/development-policy-ucb-vs-ts-000-0.json
```

Replay checks turn order, participant identity, current colour, accepted moves, pie swaps and the final board. A completed result must have its recorded winner and connecting path. Failed games must not contain a fabricated winner. The evaluator and aggregator already replay every result they consume.

## Worker scaling and time budgets

```bash
python -m hexai benchmark --workers 1 2 4 8 --iterations 10000 --repeats 3 --board-size 11 --policy rave_ts --output .local/worker-benchmark.json
```

This uses a common nonterminal board snapshot and equal total iteration counts. It records externally measured response time, iterations per second, per-worker diagnostics and process peak RSS. It is not a win-rate experiment. RSS excludes the Python driver; a missing memory value is not proof of zero memory use.

Repeat the benchmark separately on each host. Eight workers can run on a four-CPU allocation but share that allocation. Choose worker settings from measured throughput and reliability, not from the number of launched threads.

Host-specific measurements and trial diagnostics are in [the Windows benchmark](../reports/benchmarks/windows.json) and [the Kaggle benchmark](../reports/benchmarks/kaggle.json). [The experiment record](experiments.md) compares workers within each host.

Iteration budgets compare a controlled amount of search work, while time budgets compare practical decisions under a host's measured speed. Native game and response limits remain active in both modes. Tactical or opening shortcuts may correctly choose a move with zero search iterations. Time mode is not expected to reproduce the exact simulation count or winning trajectory between runs.

## Original-executable time reference

[`configs/final-time-reference.json`](../configs/final-time-reference.json) is a separate four-game Kaggle/Linux reference using the actual preserved original source rebuilt into a separate executable. Both participants use eight workers and a 300-second per-player game ceiling. The maintained participant has an additional five-second per-move cap; the original participant retains its original adaptive time manager. This is not an equal-per-move-budget policy experiment or a statistically strong claim against the original submission.

On Linux, after building the maintained executable:

```bash
python -m hexai build --legacy
python -m hexai evaluate --config configs/final-time-reference.json --output .local/final-time-reference
```

`--legacy` builds `deployment/agents/Group026/RAVE_TS.cpp` under `.local/bin/` and preserves the original shipped binary. This actual-original reference differs from the maintained `legacy_ts` control in the final fixed-iteration suite. It is limited to the original 11×11 capability, and no external Davis or HexHex opponent is substituted.

The original shipped Linux executable's hash and runtime portability are checked separately. That check is not counted as new match evidence or substituted for the four games against the rebuilt original source.

## Verify the saved result bundle

The public release's `reports/release-manifest.json` pins search source, manifests, aggregates and saved-game records. This command checks saved artifacts without building or playing new matches:

```bash
python scripts/verify_release.py --manifest reports/release-manifest.json --output .local/release-verification.json
```

The verifier checks original-inventory hashes, per-run manifests and runner/source hashes, missing or duplicate game IDs, referee replay of every saved move and agreement with stored aggregates. It verifies saved artifacts; it does not play new games or assess external-opponent strength.

## Statistical interpretation and provenance

The main paired interval resamples complete side-reversal pairs using a fixed bootstrap seed. A game's Wilson interval is also available, but it ignores within-pair dependence and is presented as descriptive. Failure rates, missing results, completed games and completed pairs must accompany any win percentage. A high completed-game score alone does not prove reliable execution if failures are frequent.

Historical Davis and HexHex screenshots remain separate from the new internal evaluation. Their opponent executables and complete original evaluation settings are unavailable here. The `legacy_ts` control shares the maintained engine and is not an exact historical replay.

[The original source inventory](../reports/baseline/original-source-inventory.json) identifies preserved framework, deployment and match-evidence files. Public result releases retain reproducible commands and hashes with portable relative locations. Authentication files and private activity notes do not belong in the source ZIP or published result artifacts.
