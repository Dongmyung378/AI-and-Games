# Source builds and public CPU verification

[한국어](deep-runtime.ko.md) | **English** | [Project overview](../README.md)

The maintained Hex agent and the controlled initial-algorithm adapter can be built from source on Windows, Linux or WSL. Both use CPU search and require Python 3.10 or newer and a C++17 compiler. The Python runtime uses the standard library; a GPU, Docker and a trained checkpoint are not required.

## Build the two engines

Run these commands from the repository root:

~~~bash
python -m hexai doctor
python -m hexai build
python scripts/build_legacy_benchmark.py
python -m unittest discover -s tests -v
~~~

Inspect the compiler entry in the doctor output. An actual successful build establishes compiler readiness. If necessary, pass an explicit compiler to both builders:

~~~bash
python -m hexai build --compiler clang++
python scripts/build_legacy_benchmark.py --compiler clang++
~~~

The maintained executable is .local/bin/hex_search.exe on Windows and .local/bin/hex_search on Linux. The controlled adapter always uses the extensionless .local/bin/legacy_benchmark path named in the portable manifests. On Windows it remains a PE executable: the builder compiles to an explicit temporary .exe name and installs the result at the exact requested extensionless pathname. Actual Windows CreateProcess tests verify that this path launches. An explicitly requested .exe output is also supported.

Both builders retain source, compiler and executable fingerprints. The controlled adapter additionally writes generated C++ source and a patch receipt beside the executable. The platform filename fix changes the build layer; it leaves the generated initial algorithm source unchanged at SHA-256 f42ab37e1893ba2bf0ac1eb212381803c95132b68d7e2a18a085d46ab240291e. The earlier builder is preserved separately in reports/deep/source/build_legacy_benchmark.frozen.py.

## Quick integration check

~~~bash
python -m hexai evaluate --config configs/deep/public-runtime-smoke.json --output .local/public-runtime-smoke
python -m hexai aggregate --inputs .local/public-runtime-smoke --output .local/public-runtime-summary.json --require-complete
~~~

This manifest contains four side-balanced games, one worker per participant and five seconds of external decision time per participant. It exercises the V3 budget protocol against the controlled initial-algorithm adapter. Check that all four games completed and that the failure and missing-game counts are zero. Four games establish integration, not a reliable playing-strength estimate.

## Kaggle CPU package

~~~bash
python scripts/package_kaggle_cpu.py --owner YOUR_KAGGLE_USER --slug hex-public-runtime --config configs/deep/public-runtime-smoke.json --output .local/kaggle-public-runtime --sanitizers
~~~

The command prepares a package and does not submit a notebook. It creates kernel.py, kernel-metadata.json, source-inventory.json and package-receipt.json. The metadata requests a private CPU-only script with GPU, TPU and internet disabled. The script embeds only selected source, tests and one frozen manifest; it embeds no credentials, model weights or existing native executables. An existing nonempty output directory is rejected rather than overwritten.

Upload the generated script using your own Kaggle account. The script checks archive and source-file SHA-256 values, compiles the maintained and controlled historical engines, runs the maintained tests and preserved referee and adapter tests, then executes the frozen games. With --sanitizers, it also builds and exercises both engines under AddressSanitizer and UndefinedBehaviorSanitizer.

Two top-level output files make retrieval independent of recursive directory support:

| File | Contents |
| --- | --- |
| hex-public-cpu-results.zip | Logs, source inventory, build receipts, generated adapter source, sanitizer report and all game records |
| hex-public-cpu-completion.json | Completion state, manifest hash, source hash and output ZIP hash |

The bounded packager defaults to --max-wall-seconds 33000 and --checkpoint-margin-seconds 120. Build and test time is subtracted before assigning the evaluator's remaining wall allowance. It checkpoints between games and writes the same flat ZIP for a checkpointed run. Status is scoped to the assigned shard: complete means that shard finished successfully, completed_with_failures retains its failures, and checkpointed names unfinished assigned games and any partial pair. It does not label 40 recorded games as completion of a 400-game manifest.

For the 400-game shared-time suite, prepare ten whole-pair shards. Each shard contains 40 games and 20 pairs. For shard zero:

~~~bash
python scripts/package_kaggle_cpu.py --owner YOUR_KAGGLE_USER --slug hex-shared-time-cpu-shard-00 --config configs/deep/shared-time.json --output .local/kaggle-shared-time-00 --shard-index 0 --shard-count 10 --max-wall-seconds 33000 --checkpoint-margin-seconds 120 --sanitizers
~~~

Repeat preparation with indexes 1 through 9, distinct slugs and distinct output directories. The two 300-second participant ceilings contribute at most 24,000 seconds of decision allowances per 40-game shard; compilation, process handling and output storage also take time. Do not attempt the full 400-game time suite in one notebook. Keep actual job folders separate, retain checkpointed records and combine only complete same-run pairs. An interrupted pair must not be completed by moving its second leg from another job into the first job's folder.

The bounded packaging changes have both local contract checks and an actual Kaggle checkpoint-only execution. Local checks cover saved-flat-ZIP verification, assigned/global completion counterexamples and 400-game ten-way assignment. The separate Kaggle checkpoint job rebuilt the sources and passed its tests, then stopped before launching any evaluation-game participants and exported its flat ZIP. It verifies checkpoint handling; its zero recorded games are excluded from playing-strength evaluation. It does not establish completion of a 400-game suite.

The result archive includes build-evidence/legacy_benchmark.cpp and its build and patch receipts. These files bind the measured historical control to the exact adapted source. The preserved original adapter's disposable test fixture is rebuilt from original source and checked against its historical source checksum; it is identified explicitly as a rebuild rather than the original shipped binary.

## Verified execution scope

The latest bounded public-tool v3 was executed in two separate Kaggle CPU jobs. Each passed 64 maintained tests, 18 preserved referee tests and 25 adapter/referee tests: 107 Python test executions with no skips. Each also passed the native self-test's 15 checks, including all 19,683 colourings of a 3x3 board against an independent connectivity oracle, and six native protocol tests under ASan and UBSan. These repeated checks are attributed to each job's pinned source archive.

| Latest actual v3 job | Manifest and assignment | Recorded evaluation games | Result |
| --- | --- | ---: | --- |
| Integration smoke | Four games, two side-reversal pairs | 4 | All completed without failures; all 100 saved moves replayed |
| Checkpoint only | 400-game manifest, shard 0 of 10; 40 games and 20 pairs assigned | 0 | checkpointed before the first evaluation game; all 40 assigned games remain missing |

The smoke job used the default 33,000-second wall allowance and 120-second checkpoint margin. Build and test time left 32,931.367 seconds for evaluation. The checkpoint job deliberately requested a one-second wall allowance and no margin. After source builds and tests, the evaluator received the minimum 0.001-second allowance; its guard rejected the projected 600-second first-game ceiling and saved the flat ZIP. This is a post-build checkpoint check, not an end-to-end one-second hard timeout. Native processes ran during unit and protocol tests, but no evaluation-game participant processes started. Zero-game checkpoint output is not a completed match suite and adds no games to the strength results.

Both latest jobs recorded Linux x86_64, Python 3.13.15, g++ 13.3.0, four visible and process-allowed CPUs and cgroup cpu.max=400000 100000. Their packaged source inventories, generated historical source, build receipts and result ZIPs were verified against pinned hashes. The Windows filename repair separately passed five actual build and process-launch contracts and retained the same generated C++ algorithm hash.

Earlier receipts remain separate: the initial public v1 integration had 96 Python test executions and four games with 98 replayed moves; v2b had 103 Python test executions and four games with 92 replayed moves. Those observations belong to their own source snapshots and are not reassigned to v3 or combined as additional latest smoke games.

Compiler, standard-library and host changes can change byte-level outputs and stochastic trajectories. Fixed source and executable hashes, seeds, worker counts and budgets make comparisons inspectable. Time-based reruns are expected to produce different simulation counts.

## Larger frozen experiments

~~~bash
python -m hexai evaluate --config configs/deep/shared-time.json --output .local/deep-shared-time --max-wall-seconds 39600 --checkpoint-margin-seconds 120
python -m hexai evaluate --config configs/deep/tactical-ablation.json --output .local/deep-tactical-ablation
~~~

The wall-time guard stops between games and preserves finished game files. The shared-time manifest uses a 300-second external per-participant ceiling. That ceiling is an allowance, not a claim that every participant consumes all 300 seconds.

Use --resume only with the same manifest, binary and recorded environment. For local and Kaggle parallel work, assign whole side-reversal pairs using --shard-index and --shard-count, and combine nonoverlapping outputs with aggregate. Keep host-specific timing and hardware results visible. A stopped or incomplete suite is not a final strength result.

Allocation fingerprints do not uniquely identify physical machines. Preserve each actual job's run directory and pair provenance; the release verifier requires both pair legs to remain in the same recorded run, including when two jobs expose identical CPU and build metadata.

## Saved evidence verification

~~~bash
python scripts/verify_release.py --output .local/release-verification.json
~~~

The verifier selects reports/release-manifest-v2.json when present. It checks pinned files, the 64 original files, all declared manifests and recorded game traces, and agreement with saved aggregates. The six prior suites remain unchanged and are checked against reports/historical/release-v1-source.zip, which preserves their evaluated engine and runner versions. Saved-game replay checks rule legality and recorded winners; it does not run search again or establish general Hex strength.
