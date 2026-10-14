# Evidence boundaries and retained experiments

[한국어](deep-limitations.ko.md) | **English** | [Project overview](../README.md)

The release distinguishes implementation correctness, playing strength, throughput and environment portability. A test or a high score in one category does not prove every other category.

The prior six evaluation suites retain their original manifests, aggregates, source-version fingerprints and 532 saved games. Their 16,768 moves replay against a 13-file historical engine and runner source archive. New V3 results are additional evidence and are not substituted for the original experiments. The 64 original framework, deployment and historical match files remain independently pinned.

The latest bounded public v3 Kaggle integration job passed 107 Python test executions with no skips, native self-tests and six sanitizer protocol tests. All four short V3 games completed without failures and all 100 saved moves replayed. It verifies packaging, rebuilding, protocol compatibility, source hashes and the complete recording path. Four short games provide too little sampling evidence for a competitive win-rate claim. Native self-tests and ASan/UBSan exercise declared cases; they are not a proof that every possible input, compiler or workload is defect-free.

The separate actual v3 checkpoint-only job passed its own 107 Python test executions and native/sanitizer checks, then stopped before starting any evaluation game. Its 400-game manifest assigned 40 games and 20 pairs to shard 0 of 10; the output correctly preserves zero records, 40 missing assigned games, checkpointed status and an incomplete global manifest in the flat ZIP. The deliberate one-second wall request checks the evaluator guard after builds and tests, not a hard one-second total runtime. This output contributes zero games and zero wins to strength evidence. Public v1 and v2b results remain tied to their own source archives; they are not relabelled as latest v3 validation or duplicated in the latest smoke suite.

The shared external clock makes the runtime budget comparable, but it does not isolate every difference between the historical algorithm and the maintained engine. The controlled adapter changes seeded worker streams, runtime scheduling, protocol and diagnostics. Its guarded algorithm regions remain unchanged, while the original 1,500,001-iteration cap is retained and disclosed. A measured improvement against this control is conditional on that adaptation, the declared openings, seeds, board size and hardware.

A fixed-iteration score and a common-time score answer different questions. Tactical shortcuts may complete without simulations, and a 300-second allowance may remain partly unused. Report actual per-participant consumption and failures alongside results. Throughput measurements on fixed positions do not establish the typical speed of an entire game, and parallel-worker count is not equivalent to physical CPU capacity.

The earlier development candidates were not promoted merely because one point estimate was higher. Their predeclared paired criterion, completed pairs and uncertainty governed adoption, and stopped candidates remain available. The frozen extended tactical ablations describe feature effects without reopening selection. Failure rates and verified wins per scheduled game prevent a high completed-game win percentage from hiding execution problems.

Saved-result replay verifies the rules, colour changes, time accounting and winning connection. It does not rerun search or prove that an action was strategically optimal. Executable bytes and stochastic trajectories can vary across compiler and standard-library versions. Time-based outcomes may change between repeated runs on the same machine.

Local Windows and Kaggle Linux provide different host environments under the same project operator. They do not constitute an independent external reviewer. Davis is an online-site opponent from the historical project, while HexHex is another historical opponent. Their binaries and exact runtime settings are not bundled, so the new internal evaluation does not independently reproduce those earlier matches or establish a general Hex ranking.

New source ZIPs contain maintained source and retained project material. Runtime credentials, private logs and newly built host executables belong outside the published source tree. Build the maintained executables for the current platform. The original shipped Linux binary remains historical material rather than a universal executable for Windows and every Linux installation.
