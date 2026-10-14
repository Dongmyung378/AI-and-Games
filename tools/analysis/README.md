# Inspect the saved evaluation records

[한국어](README.ko.md) | **English**

These optional Python standard-library tools describe saved, complete evaluation suites. They do not launch agents, play new games, change the frozen policy or measure performance on the current machine. Run them from the repository root with Python 3.10 or newer.

## Timing and resource measurements

```bash
python tools/analysis/analyze_deep_evidence.py --summary reports/deep/aggregates/tactical-ablation.json --runs reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard00 reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard01 --output .local/tactical-costs.json
```

The output groups external response time, native search telemetry, sampled process RSS and recorded node-cap observations by participant and hardware allocation. It checks complete game coverage and execution signatures against the saved aggregate. Missing measurements remain missing. Native throughput divides total search iterations by summed native response elapsed time, which is different from summed per-worker elapsed wall time. Worker elapsed telemetry does not measure CPU usage time. Costs describe the recorded execution; they do not establish why one policy won.

## Tactical traces and conditional decision costs

```bash
python tools/analysis/analyze_tactical_traces.py --summary reports/deep/aggregates/tactical-ablation.json --runs reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard00 reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard01 --output .local/tactical-traces
```

This command writes `analysis.json` and the opponent-keyed `tactical-metrics.json` used by the figures. It compares physical move traces and recorded worker seeds within each side-reversal pair. Conditional timing comparisons require the same board, turn and colour to appear in both legs; they are not whole-agent speedup estimates. Raw game hashes are retained for inspection. Timing values describe the recorded Windows or Kaggle environment and need not recur on another machine.

See the [experiment interpretation](../../docs/experiments.md) for the distinction between fixed-iteration strength, a shared game-time budget and worker throughput.

The published [tactical costs](../../reports/deep/analysis/tactical-costs.json), [trace analysis](../../reports/deep/analysis/tactical-traces.json) and [figure metrics](../../reports/deep/analysis/tactical-metrics.json) describe the same saved 400 games. Raw source hashes remain attached to the records and release inventory.
