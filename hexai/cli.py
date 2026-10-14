"""Standard-library entry point for builds, reproducible matches and inspection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

from .evaluation import (aggregate, atomic_json, canonical, evaluate, load_manifest,
                         participant_command, percentile, replay)
from .native import (ROOT, NativeProcess, build, environment, executable_default,
                     resolve_compiler, sha256)
from .referee import parse_board


def search_arguments(parser):
    parser.add_argument("--executable", type=Path, default=executable_default())
    parser.add_argument("--policy", choices=["ucb", "ts", "rave_ucb", "rave_ts", "legacy_ts"], default="rave_ts")
    parser.add_argument("--seed", type=int, default=378)
    parser.add_argument("--workers", type=int, default=1)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--iterations", type=int, default=None)
    group.add_argument("--seconds", type=float, default=None)
    parser.add_argument("--game-seconds", type=float, default=300)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--node-cap", type=int, default=60000)
    parser.add_argument("--memory-mb", type=int, default=128)
    parser.add_argument("--bridge", type=int, choices=[0, 1], default=1)
    parser.add_argument("--ordering", type=int, choices=[0, 1], default=1)
    parser.add_argument("--tactics", type=int, choices=[0, 1], default=1)
    parser.add_argument("--swap", type=int, choices=[0, 1], default=1)
    parser.add_argument("--rave-k", type=float, default=1000)


def predict(args):
    board = parse_board(args.board)
    if args.turn < 1:
        raise ValueError("turn must be at least 1.")
    participant = {"policy": args.policy, "bridge": bool(args.bridge), "ordering": bool(args.ordering),
                   "swap": bool(args.swap), "tactics": bool(args.tactics), "rave_k": args.rave_k}
    budget = {"mode": "time" if args.seconds is not None else "iterations", "workers": args.workers,
              "game_seconds": args.game_seconds, "node_cap": args.node_cap, "memory_mb": args.memory_mb}
    if args.seconds is not None:
        budget["seconds"] = args.seconds
    else:
        budget["iterations"] = args.iterations if args.iterations is not None else 2000
    command = participant_command(participant, budget, {"seed": args.seed}, args.colour, args.executable)
    message = f"V2;{args.colour};{board.size};START;;{args.board};{args.turn}"
    with NativeProcess(command) as engine:
        move, elapsed = engine.request(message, args.timeout)
    return {"move": list(move), "response_seconds": elapsed, "telemetry": engine.telemetry,
            "command": command, "executable_sha256": sha256(args.executable)}


def benchmark(args):
    if args.repeats < 1 or args.iterations < 1 or any(worker < 1 for worker in args.workers):
        raise ValueError("Benchmark repeats, iterations and workers must be positive.")
    board_text = args.board or ",".join("0" * args.board_size for _ in range(args.board_size))
    board = parse_board(board_text)
    # One off-centre forced opening avoids the native empty-board opening shortcut.
    if args.board is None:
        rows = board_text.split(",")
        rows[0] = "R" + rows[0][1:]
        board_text = ",".join(rows)
    records = []
    for workers in args.workers:
        for trial in range(args.repeats):
            command = participant_command({"policy": args.policy, "swap": False, "rave_k": args.rave_k},
                                          {"mode": "iterations", "iterations": args.iterations,
                                           "workers": workers, "node_cap": args.node_cap, "game_seconds": 300},
                                          {"seed": args.seed + trial}, "B", args.executable)
            with NativeProcess(command) as engine:
                move, elapsed = engine.request(f"V2;B;{board.size};CHANGE;0,0;{board_text};2", args.timeout)
            telemetry = [item for item in engine.telemetry if isinstance(item, dict) and item.get("kind") == "hex_search_move"]
            iterations = sum(item.get("iterations", 0) for item in telemetry)
            native_seconds = sum(item.get("seconds", 0) for item in telemetry)
            records.append({"workers": workers, "trial": trial, "seed": args.seed + trial,
                            "move": list(move), "response_seconds": elapsed,
                            "completed_iterations": iterations,
                            "iterations_per_second_external": iterations / elapsed if elapsed else None,
                            "native_search_seconds": native_seconds,
                            "iterations_per_second_native": iterations / native_seconds if native_seconds else None,
                            "process_peak_rss_bytes": engine.peak_rss_bytes,
                            "telemetry": telemetry, "command": command})
    summaries = []
    for workers in args.workers:
        values = [record for record in records if record["workers"] == workers]
        summaries.append({"workers": workers,
                          "median_response_seconds": statistics.median(item["response_seconds"] for item in values),
                          "p95_response_seconds": percentile([item["response_seconds"] for item in values], .95),
                          "median_iterations_per_second": statistics.median(item["iterations_per_second_external"] for item in values),
                          "median_native_search_seconds": statistics.median(item["native_search_seconds"] for item in values),
                          "median_native_iterations_per_second": statistics.median(item["iterations_per_second_native"] for item in values),
                          "max_process_peak_rss_bytes": max((item["process_peak_rss_bytes"] or 0 for item in values), default=0),
                          "all_exact_iteration_budget": all(item["completed_iterations"] == args.iterations for item in values)})
    report = {"schema_version": 1, "environment": environment(), "executable_sha256": sha256(args.executable),
              "board": board_text, "iterations_per_move": args.iterations, "repeats": args.repeats,
              "summaries": summaries, "trials": records,
              "scope": "Single nonterminal snapshot. Throughput is not a win-rate measurement. Process peak RSS includes all native workers, but not the Python driver. Missing memory metrics are zero/null, not measured zero usage."}
    atomic_json(args.output, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m hexai", description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    doctor = subs.add_parser("doctor", help="Inspect platform, CPU allocation and compiler availability.")
    doctor.add_argument("--compiler")
    builder = subs.add_parser("build", help="Build the reviewed source without replacing historical files.")
    builder.add_argument("--source", type=Path)
    builder.add_argument("--output", type=Path)
    builder.add_argument("--compiler")
    builder.add_argument("--legacy", action="store_true")
    runner = subs.add_parser("evaluate", help="Sequential frozen-manifest evaluation with per-game checkpoints.")
    runner.add_argument("--config", type=Path, required=True)
    runner.add_argument("--output", type=Path, required=True)
    runner.add_argument("--executable", type=Path, default=executable_default())
    runner.add_argument("--shard-index", type=int, default=0)
    runner.add_argument("--shard-count", type=int, default=1)
    runner.add_argument("--resume", action="store_true")
    collector = subs.add_parser("aggregate", help="Join exact-manifest shards and retain per-environment results.")
    collector.add_argument("--inputs", nargs="+", type=Path, required=True)
    collector.add_argument("--output", type=Path, required=True)
    collector.add_argument("--require-complete", action="store_true")
    predictor = subs.add_parser("predict", help="Inspect one native search and its telemetry.")
    search_arguments(predictor)
    predictor.add_argument("--board", required=True)
    predictor.add_argument("--colour", choices=["R", "B"], required=True)
    predictor.add_argument("--turn", type=int, required=True)
    tester = subs.add_parser("benchmark", help="Measure worker scaling for an equal total iteration budget.")
    tester.add_argument("--executable", type=Path, default=executable_default())
    tester.add_argument("--workers", nargs="+", type=int, default=[1, 2, 4, 8])
    tester.add_argument("--iterations", type=int, default=10000)
    tester.add_argument("--repeats", type=int, default=3)
    tester.add_argument("--board-size", type=int, default=11)
    tester.add_argument("--board")
    tester.add_argument("--policy", choices=["ucb", "ts", "rave_ucb", "rave_ts", "legacy_ts"], default="rave_ts")
    tester.add_argument("--seed", type=int, default=378)
    tester.add_argument("--node-cap", type=int, default=60000)
    tester.add_argument("--rave-k", type=float, default=1000)
    tester.add_argument("--timeout", type=float, default=60)
    tester.add_argument("--output", type=Path, required=True)
    playback = subs.add_parser("replay", help="Verify every saved move and the recorded winner.")
    playback.add_argument("--input", type=Path, required=True)
    validator = subs.add_parser("validate", help="Validate final seeds are disjoint from development seeds.")
    validator.add_argument("--config", type=Path, required=True)
    validator.add_argument("--development", nargs="*", type=Path, default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            info = environment()
            try:
                compiler = resolve_compiler(args.compiler)
                version = subprocess.run(compiler + ["--version"], capture_output=True, text=True, timeout=20)
                info["compiler"] = {"command": compiler, "version": version.stdout.strip()}
            except ValueError as error:
                info["compiler"] = {"error": str(error)}
            result = info
        elif args.command == "build":
            result = build(args.source, args.output, args.compiler, args.legacy)
        elif args.command == "evaluate":
            result = evaluate(args.config, args.output, args.executable, args.shard_index, args.shard_count, args.resume)
        elif args.command == "aggregate":
            result = aggregate(args.inputs, args.output, args.require_complete)
        elif args.command == "predict":
            result = predict(args)
        elif args.command == "benchmark":
            result = benchmark(args)
        elif args.command == "replay":
            result = replay(json.loads(args.input.read_text(encoding="utf-8")))
        else:
            config = load_manifest(args.config)
            for path in args.development:
                development = load_manifest(path)
                if config["split"] != "final" or development["split"] != "development":
                    raise ValueError("Disjointness check requires final config and development manifests.")
                for key in ("seed", "opening_seed"):
                    if {game[key] for game in config["games"]} & {game[key] for game in development["games"]}:
                        raise ValueError("Final and development " + key + " overlap.")
            result = {"valid": True, "games": len(config["games"]), "disjoint_development_manifests": len(args.development)}
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True), file=sys.stderr)
        return 2
