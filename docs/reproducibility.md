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

## Reproduce the deeper release

The maintained runtime remains standard-library Python plus a C++17 compiler.
Build both comparison engines from the repository root:

```bash
python -m hexai doctor
python -m hexai build
python scripts/build_legacy_benchmark.py --output .local/bin/legacy_benchmark
python -m unittest discover -s tests -v
```

The explicit adapter output matches the portable relative path in the frozen
shared-time manifest. On Windows the builder preserves the requested destination
name and its matching receipt; do not edit a frozen manifest to insert a host's
absolute path. Build for the target OS. The controlled adapter is separately
generated and never replaces the preserved historical source or shipped binary.

Run the complete declared comparisons in separate fresh output directories:

```bash
python -m hexai evaluate --config configs/deep/shared-time.json --output .local/deep-shared-time --max-wall-seconds 33000 --checkpoint-margin-seconds 120
python -m hexai evaluate --config configs/deep/tactical-ablation.json --output .local/deep-tactical-ablation --max-wall-seconds 33000 --checkpoint-margin-seconds 120
```

The shared-time manifest schedules 400 games; the tactical manifest separately
schedules another 400. These commands can require substantial CPU time. The
wall guard stops between games with an explicit checkpoint and missing-game
coverage, allowing a compatible resumed run rather than declaring an incomplete
suite complete. Resume by adding `--resume` to the same command. A saved failure
stays a failure; it is not silently replayed until a win is obtained.

For local/Kaggle division, add `--shard-index INDEX --shard-count 10` to the
shared-time command. Its pair grouping assigns 40 games to each of the ten
shards. Do not divide the two legs of a pair between hosts. Every result carries
the same full-manifest fingerprint and its actual hardware/source signature.

```bash
python -m hexai aggregate --inputs .local/deep-shard0 .local/deep-shard1 --output .local/deep-partial.json
```

Supply all ten nonoverlapping shared-time shards and add `--require-complete`
for the final 400-game aggregate. Two shard directories alone are not a complete
study. Coverage means a result exists for every planned game, not that every
game succeeded. Keep per-environment outcomes and measured time consumed.

### Generate the public Kaggle CPU package

```bash
python scripts/package_kaggle_cpu.py --owner YOUR_ACCOUNT --slug hex-deep-cpu-reproduction --config configs/deep/shared-time.json --output .local/kaggle-deep-package --shard-index 0 --shard-count 10 --sanitizers
```

This command only prepares `kernel.py`, Kaggle metadata and integrity receipts.
It never uploads credentials, submits a job or starts training. Submit the
generated private CPU script under your own account when ready. It embeds the
reviewed source and frozen config, builds both engines on Linux and saves a
top-level result archive and completion JSON. No existing native executable is
used as a substitute for a source build. The optional sanitizer check verifies
the maintained and controlled historical paths under ASan and UBSan.

The public tool's short end-to-end run is distinct from the long shared-time
study. Session CPU count and quota must be measured again with `doctor`; the
study's allocation does not guarantee future Kaggle resources. Retain manifests,
metadata, generated source and patch/build receipts when downloading results.

The latest actual public-tool Kaggle run passed 107 Python test executions, 15 native self-test checks and six ASan/UBSan protocol tests. All four short V3 games completed and all 100 saved moves replayed. A separate checkpoint run recorded zero evaluation games; it does not claim completion of the 400-game manifest. [Public execution evidence](deep-runtime.md) retains the actual source-version scope.

For a short V3 integration run, use:

```bash
python -m hexai evaluate --config configs/deep/public-runtime-smoke.json --output .local/public-runtime-smoke
python -m hexai aggregate --inputs .local/public-runtime-smoke --output .local/public-runtime-summary.json --require-complete
```

### Repeat the six-position worker benchmark

```bash
python -m hexai benchmark --fixtures reports/deep/benchmarks/fixtures.json --workers 1 2 4 8 --iterations 16000 --repeats 7 --policy rave_ts --output .local/deep-workers.json
```

Use the frozen fixture file and explicitly record the actual repetition count.
Repeat separately on Windows and Kaggle; their standard libraries and CPU
allocations differ. Preserve all raw trials, p50/p95 responses and nullable RSS.
The benchmark disables instant tactical decisions and checks that each request
completed the stated total iteration count. It does not establish playing
strength or make cross-platform bitwise search equality a requirement.

### Saved-source verification and optional graphics

The extended manifest is `reports/release-manifest-v2.json`. Its old suites use
the archived first-release source and original hashes; new suites retain their
actual generated-adapter source and source/build receipts. Do not rewrite old
metadata to match new runtime files.

```bash
python scripts/verify_release.py --manifest reports/release-manifest-v2.json --output .local/deep-release-verification.json
```

Verification checks saved hashes, coverage, legality, colour changes, allocation
accounting and recorded winners. A fresh match rerun is a separate action. A
changed host, source, binary or shard assignment must use a separate compatible
run allocation instead of bypassing the resume fingerprint check.

The numerical SVGs use optional Matplotlib tooling, not a runtime dependency.
The [figure tools](../tools/figures/) require Python 3.11 or newer for the pinned
Matplotlib 3.11.2, whose installed metadata declares `Requires-Python >=3.11`.
This does not change the standard-library runtime's Python 3.10 minimum.
With a Python 3.11-or-newer interpreter, create a separate environment:

```bash
python -m venv .local/figure-env
.local/figure-env/bin/python -m pip install -r tools/figures/requirements.txt
.local/figure-env/bin/python tools/figures/render_hex_deep_scientific.py --data assets/figures/deep-visual-input.json --output .local/figures --language both
```

On Windows use `.local/figure-env/Scripts/python.exe` instead. A Korean font is
required for Korean figures; `--korean-font PATH_TO_FONT` can select it explicitly.
Keep the actual input reports and figure-generation receipt with the figures;
the receipt binds the plotting version, data, code and Korean font hashes.
Exported Korean SVG glyph paths display without requiring the viewer to install
that font. Graphs must use actual recorded results and retain failed and missing
denominators instead of portraying them as lost or won games.

### Reanalyze the recorded tactical games

The optional standard-library [analysis tools](../tools/analysis/) read saved
games without building an agent or playing new matches. These commands use the
two actual published tactical run directories:

```bash
python tools/analysis/analyze_deep_evidence.py --summary reports/deep/aggregates/tactical-ablation.json --runs reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard00 reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard01 --expected-games 400 --output .local/tactical-costs.json
python tools/analysis/analyze_tactical_traces.py --summary reports/deep/aggregates/tactical-ablation.json --runs reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard00 reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard01 --output .local/tactical-trace-analysis
```

The first describes per-actor cost and reasons. The second reconstructs physical
trace equality, mirrored recorded seeds, matched-position latency and the plain
opponent-keyed `tactical-metrics.json` consumed by figure and Site tooling. These
analyses remain descriptive and never reselect the frozen policy. They do not
require Matplotlib and do not change the Python 3.10-or-newer runtime requirement.

## Actual source-build and saved-record validation

The [source-validation summary](../reports/deep/verification/source-validation-summary.json) publishes actual environment-specific evidence. A fresh Windows environment with pip and system packages disabled passed 64 maintained tests, 18 preserved referee tests and 23 adapter tests. Two preserved Linux-binary tests were skipped; two corresponding V2 contracts separately passed against freshly Windows-built original source. Kaggle Linux passed 107 Python test executions with no skips, 15 native self-test checks including 19,683 connectivity states, and six sanitizer protocol tests.

The fresh Windows environment also replayed 1,336 saved games and 53,199 moves across nine evaluation suites. These records include the four short integration games; the zero-game checkpoint contributes no games. This is project-internal verification in a separate execution environment, rather than an external human replication. Final source-ZIP integrity is checked separately after documentation and figures are finalized.

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

The preserved first-release measurements used one common nonterminal snapshot. The current command supports named fixture lists and equal total iteration counts; the deeper study uses the explicit six-position fixture file above. It records externally measured response time, iterations per second, per-worker diagnostics and process peak RSS. It is not a win-rate experiment. RSS excludes the Python driver; a missing memory value is not proof of zero memory use.

Repeat the benchmark separately on each host. Eight workers can run on a four-CPU allocation but share that allocation. Choose worker settings from measured throughput and reliability, not from the number of launched threads.

Host-specific measurements and trial diagnostics are in [the Windows benchmark](../reports/benchmarks/windows.json) and [the Kaggle benchmark](../reports/benchmarks/kaggle.json). [The experiment record](experiments.md) compares workers within each host.

Iteration budgets compare a controlled amount of search work, while time budgets compare practical decisions under a host's measured speed. Native game and response limits remain active in both modes. Tactical or opening shortcuts may correctly choose a move with zero search iterations. Time mode is not expected to reproduce the exact simulation count or winning trajectory between runs.

## Initial-executable time reference

[`configs/final-time-reference.json`](../configs/final-time-reference.json) is a separate four-game Kaggle/Linux reference using the actual preserved original source rebuilt into a separate executable. Both participants use eight workers and a 300-second per-player game ceiling. The maintained participant has an additional five-second per-move cap; the original participant retains its original adaptive time manager. This is not an equal-per-move-budget policy experiment or a statistically strong claim against the original submission.

On Linux, after building the maintained executable:

```bash
python -m hexai build --legacy
python -m hexai evaluate --config configs/final-time-reference.json --output .local/final-time-reference
```

`--legacy` builds `deployment/agents/Group026/RAVE_TS.cpp` under `.local/bin/` and preserves the original shipped binary. This actual-original reference differs from the maintained `legacy_ts` control in the final fixed-iteration suite. It is limited to the original 11×11 capability, and no external Davis or HexHex opponent is substituted.

The original shipped Linux executable's hash and runtime portability are checked separately. That check is not counted as new match evidence or substituted for the four games against the rebuilt original source.

## Verify the saved result bundle

The public release's `reports/release-manifest-v2.json` pins search source, manifests, aggregates and saved-game records. This command checks saved artifacts without building or playing new matches:

```bash
python scripts/verify_release.py --manifest reports/release-manifest-v2.json --output .local/release-verification.json
```

The verifier checks original-inventory hashes, per-run manifests and runner/source hashes, missing or duplicate game IDs, referee replay of every saved move and agreement with stored aggregates. It verifies saved artifacts; it does not play new games or assess external-opponent strength.

## Statistical interpretation and provenance

The main paired interval resamples complete side-reversal pairs using a fixed bootstrap seed. A game's Wilson interval is also available, but it ignores within-pair dependence and is presented as descriptive. Failure rates, missing results, completed games and completed pairs must accompany any win percentage. A high completed-game score alone does not prove reliable execution if failures are frequent.

Historical Davis and HexHex screenshots remain separate from the new internal evaluation. Their opponent executables and complete original evaluation settings are unavailable here. The `legacy_ts` control shares the maintained engine and is not an exact historical replay.

[The original source inventory](../reports/baseline/original-source-inventory.json) identifies preserved framework, deployment and match-evidence files. Public result releases retain reproducible commands and hashes with portable relative locations. Authentication files and private activity notes do not belong in the source ZIP or published result artifacts.
