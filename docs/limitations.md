# Evidence boundaries and retained experiments

[한국어](limitations.ko.md) | **English** | [Project overview](../README.md)

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

## Interpreting the completed additional experiments

All 400 shared-time games and 400 separate tactical games completed without failures or missing results. Selected-policy wins were 81/100 against the controlled historical algorithm, 84/100 against RAVE-UCB, 73/100 against TS and 70/100 against UCB. This does not establish superiority on every host: the Windows UCB stratum scored 9/20. [The experiment record](experiments.md) reports hardware strata and intervals based on 50 side-reversal pairs per opponent.

All 18,514 native requests and 800 participant-game clock accounts stayed within the external allowance. The maintained engine reached its tree node allowance in 27,298 of 30,078 instrumented worker searches; rollouts continue after expansion reaches that allowance. These events are not failed searches. The historical algorithm retains its memory allocation design, so equal time and worker counts do not make this an equal-RAM experiment. Sampled process RSS is not an OS-enforced memory limit.

Tactical comparisons scored 51/100 against swap removal and 50/100 against each immediate-win, immediate-block and combined-check removal. When all observed pair scores equal 0.5, the empirical interval collapses to 50–50%; this is not exact population strength or evidence of feature equivalence. Lower response times at matched tactical inputs are conditional measurements, not whole-agent speedup factors.

Each host benchmark contains 168 requests: six positions, four worker settings and seven repeats in fixed order. Seven-repeat p95 values do not precisely estimate a production tail. Windows and Kaggle differ in CPU and compiler as well as operating system, so their difference cannot isolate one causal factor. Eight Kaggle workers share the observed four-CPU allocation; they do not create eight cores.
