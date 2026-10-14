# Shared external budgets and historical-algorithm controls

[한국어](deep-protocol.ko.md) | **English** | [Source builds](deep-runtime.md)

The V3 protocol gives both participants a common external clock and the same allocation rule. It separates algorithm comparisons from the different internal time managers used in the original submission and the maintained engine.

## Requests and actor identities

The preserved V2 format remains available:

~~~text
V2;R|B;size;START|CHANGE|SWAP;previous_move;board;turn
~~~

V3 appends the current search allowance and externally measured remaining game time:

~~~text
V3;R|B;size;START|CHANGE|SWAP;previous_move;board;turn;allocated_search_seconds;external_remaining_seconds
~~~

The referee sends the current colour on every request, including requests after a pie-rule swap. The actor's external time account stays attached to the participant identity when the colour changes. Native processes return one coordinate pair on stdout and JSON diagnostics on stderr.

An allowance and remaining time must be finite and nonnegative. Each engine clamps to the smaller value, its game ceiling and any explicit per-move cap. V3 without an explicit iteration limit searches until its deadline. Zero remaining time produces a legal, labelled fallback; terminal or malformed boards are rejected. The independent referee still enforces request timeouts and records failures.

## Allocation and complete accounting

The shared allocator divides the remaining time, less the I/O reserve, by the larger of the expected remaining actor moves and a minimum future-move count. The initial length assumption is 24 actor decisions. With the frozen 300-second setting, expected_actor_moves=24, minimum_future_actor_moves=8 and io_reserve_seconds=0.05, the first search allowance is approximately 12.498 seconds. Later allowances use actual measured spending, while the minimum eight future decisions preserves late-game headroom.

External measurements include process pipe response time that a C++ engine's internal clock cannot measure. Records retain every assigned allowance, remaining budget, request message, response duration and any failed request. Replay reconstructs the actor accounts and V3 messages from the moves. A failed request's time is recorded without inventing an accepted move or a winner.

Three budget modes answer different questions:

| Mode | Primary control | Interpretation |
| --- | --- | --- |
| iterations | Common total simulations across all workers per move | Comparison at controlled search work |
| time | Common per-move time cap plus a game ceiling | Practical decisions at the declared per-move cap |
| game_time | Shared adaptive allocator and external per-actor game ceiling | Practical decisions under the same game-time allowance |

A 300-second ceiling does not mean every game consumes that time. Opening, swap, immediate-win and blocking shortcuts can require zero simulations. Early wins can leave unused time.

## Three distinct historical comparisons

| Participant | What it preserves | What it cannot establish |
| --- | --- | --- |
| Maintained legacy_ts | Inactive AMAF and historical direct-count attenuation inside the common maintained engine | An exact original-submission comparison |
| Source-exact legacy | The preserved original C++ source rebuilt separately | A fair shared-clock comparison without adapting its internal time manager |
| benchmark_legacy | Original algorithm regions with auditable runtime adaptations | Byte-identical behavior to the original shipped executable |

The controlled adapter adds the V3 interface, seeded worker streams, configurable worker counts, external deadline polling and diagnostic output. Its builder checks the original source hash before generation and records every guarded replacement. Board and expansion logic, selection and rollout behavior, reward rules, swap and tactical algorithms remain unchanged. The original inactive RAVE behavior and its 1,500,001-iteration per-worker cap remain visible. Generated C++ and patch receipts are published alongside results.

The Windows executable-filename repair changes how the compiler output is installed. It does not change these generated algorithm regions or their hashes.

## Paired comparisons and failure denominators

Both legs of a side-reversal pair use the same opening, seed, host allocation, executable source and worker count. Hardware and adapter signatures are attached to every game. A pair spanning different signatures is rejected. Combined summaries resample complete pairs within hardware and adapter strata; host-specific outcomes remain visible.

The hardware fingerprint identifies an allocation class, not a unique physical host. Even a hashed runtime hostname is not proof of physical-machine identity. Same-session pairing is established by assigning whole pairs to one recorded run and retaining that run's provenance. Release verification rejects a pair whose legs occur in different run directories, even when their fingerprints are identical. Restarted sessions must retain separate run records; partial pair legs must not be merged across them.

Completed-game win rate is reported alongside verified wins per scheduled game, failures, missing games and complete pairs. Timeouts, protocol errors, illegal moves and process failures remain execution failures and are never counted as playing-strength wins. The game-level Wilson interval is descriptive because two side-reversed games are dependent.

The extended experiments retain the previously selected settings. The frozen tactical removal experiments describe the effects of swap decisions, immediate wins and immediate-threat blocks separately; they are not a new selection or adoption round. The earlier bridge, ordering and RAVE-weight candidates that failed their declared criterion remain stopped. Correctness repairs remain covered by their own implementation tests.

## Latest public-tool execution evidence

The latest bounded public v3 integration job passed 107 Python test executions, the native self-test and six sanitizer protocol tests. Its four five-second V3 games completed without failures, and all 100 saved moves replayed with their recorded messages, colour changes and external time accounts. This verifies the short integration path rather than the full 300-second playing-strength experiment.

A separate actual v3 checkpoint-only job used the 400-game shared-time manifest with 40 games and 20 complete pairs assigned to shard 0 of 10. After its own builds and 107 Python test executions plus native and sanitizer checks, the evaluator's wall guard stopped before its first evaluation game. The output correctly reports checkpointed, zero recorded games, 40 missing assigned games and an incomplete global manifest. This zero-game output verifies scheduling and durable export, not V3 game decisions or playing strength. Earlier public v1 and v2b results retain their own source-version receipts.
