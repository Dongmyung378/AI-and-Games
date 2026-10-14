"""Standard-library entry point for builds, reproducible matches and inspection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

from .evaluation import (aggregate, atomic_json, canonical, evaluate, load_manifest,
                         manifest_hash, participant_command, percentile, replay)
from .native import (ROOT, NativeProcess, build, environment, executable_default,
                     resolve_compiler, sha256)
from .referee import Colour, Referee, parse_board


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
    parser.add_argument("--win-check", type=int, choices=[0, 1], default=1)
    parser.add_argument("--block-check", type=int, choices=[0, 1], default=1)
    parser.add_argument("--swap", type=int, choices=[0, 1], default=1)
    parser.add_argument("--rave-k", type=float, default=1000)


def predict(args):
    board = parse_board(args.board)
    if args.turn < 1:
        raise ValueError("turn must be at least 1.")
    participant = {"policy": args.policy, "bridge": bool(args.bridge), "ordering": bool(args.ordering),
                   "swap": bool(args.swap), "tactics": bool(args.tactics), "rave_k": args.rave_k,
                   "win_check": bool(args.win_check), "block_check": bool(args.block_check)}
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


def benchmark_fixtures(size):
    """Three frozen, legal, nonterminal positions; disabling tactics avoids shortcuts."""
    fixtures = []
    for name, plies in (("opening", 1), ("middle", max(2, size * size // 3)),
                        ("late", max(3, 2 * size * size // 3))):
        plies = min(plies, size * size - 2)
        for attempt in range(1000):
            state = Referee(size, "red", "blue")
            randomizer = random.Random(90378 + attempt)
            choices = [(x, y) for x in range(size) for y in range(size)]
            randomizer.shuffle(choices)
            trace = []
            for move in choices[:plies]:
                trace.append(list(move))
                state.play(move)
                if state.winner:
                    break
            if not state.winner:
                fixtures.append({"id": name, "board": state.board_text(),
                                 "colour": Colour.get_char(state.colour), "turn": state.turn,
                                 "previous_move": list(state.previous_move), "legal_trace": trace,
                                 "construction_seed": 90378 + attempt})
                break
        else:
            raise ValueError("Could not construct a nonterminal benchmark fixture.")
    return fixtures


def validate_fixtures(fixtures):
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError("Benchmark fixtures must be a nonempty list.")
    identifiers = set()
    for fixture in fixtures:
        identifier = fixture.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("Each benchmark fixture needs a unique nonempty id.")
        identifiers.add(identifier)
        board = parse_board(fixture["board"])
        if any(board.has_ended(colour) for colour in (Colour.RED, Colour.BLUE)):
            raise ValueError("Benchmark fixtures must not already contain a winner.")
        if fixture.get("colour") not in {"R", "B"} or type(fixture.get("turn")) is not int or fixture["turn"] < 2:
            raise ValueError("Benchmark colour or turn is invalid; an empty-board shortcut is unsuitable.")
        if "legal_trace" in fixture:
            state = Referee(board.size, "red", "blue")
            for move in fixture["legal_trace"]:
                state.play(tuple(move))
            if state.board_text() != fixture["board"] or state.turn != fixture["turn"] or Colour.get_char(state.colour) != fixture["colour"]:
                raise ValueError("Benchmark fixture does not match its legal trace.")
    return fixtures


def benchmark(args):
    if args.repeats < 1 or args.iterations < 1 or any(worker < 1 for worker in args.workers):
        raise ValueError("Benchmark repeats, iterations and workers must be positive.")
    if getattr(args, "fixtures", None):
        payload = json.loads(args.fixtures.read_text(encoding="utf-8"))
        fixtures = payload.get("fixtures", payload) if isinstance(payload, dict) else payload
    elif args.board:
        fixtures = [{"id": "custom", "board": args.board, "colour": args.colour,
                     "turn": args.turn, "previous_move": None}]
    else:
        fixtures = benchmark_fixtures(args.board_size)
    validate_fixtures(fixtures)
    records = []
    for workers in args.workers:
        for fixture in fixtures:
          for trial in range(args.repeats):
            board = parse_board(fixture["board"])
            command = participant_command({"policy": args.policy, "swap": False, "tactics": False, "rave_k": args.rave_k},
                                          {"mode": "iterations", "iterations": args.iterations,
                                           "workers": workers, "node_cap": args.node_cap, "game_seconds": 300},
                                          {"seed": args.seed + trial}, fixture["colour"], args.executable)
            previous = fixture.get("previous_move")
            action, move_text = ("CHANGE", ",".join(map(str, previous))) if previous is not None else ("START", "")
            message = f"V2;{fixture['colour']};{board.size};{action};{move_text};{fixture['board']};{fixture['turn']}"
            with NativeProcess(command) as engine:
                move, elapsed = engine.request(message, args.timeout)
            telemetry = [item for item in engine.telemetry if isinstance(item, dict) and item.get("kind") == "hex_search_move"]
            iterations = sum(item.get("iterations", 0) for item in telemetry)
            native_seconds = sum(item.get("seconds", 0) for item in telemetry)
            records.append({"fixture_id": fixture["id"], "workers": workers, "trial": trial, "seed": args.seed + trial,
                            "move": list(move), "response_seconds": elapsed,
                            "completed_iterations": iterations,
                            "iterations_per_second_external": iterations / elapsed if elapsed else None,
                            "native_search_seconds": native_seconds,
                            "iterations_per_second_native": iterations / native_seconds if native_seconds else None,
                            "process_peak_rss_bytes": engine.peak_rss_bytes,
                            "telemetry": telemetry, "command": command, "message": message})
    summaries = []
    for fixture in fixtures:
      for workers in args.workers:
        values = [record for record in records if record["workers"] == workers and record["fixture_id"] == fixture["id"]]
        memory = [item["process_peak_rss_bytes"] for item in values if item["process_peak_rss_bytes"] is not None]
        summaries.append({"fixture_id": fixture["id"], "workers": workers,
                          "median_response_seconds": statistics.median(item["response_seconds"] for item in values),
                          "p95_response_seconds": percentile([item["response_seconds"] for item in values], .95),
                          "median_iterations_per_second": statistics.median(item["iterations_per_second_external"] for item in values if item["iterations_per_second_external"] is not None),
                          "median_native_search_seconds": statistics.median(item["native_search_seconds"] for item in values),
                          "median_native_iterations_per_second": statistics.median(item["iterations_per_second_native"] for item in values if item["iterations_per_second_native"] is not None),
                          "max_process_peak_rss_bytes": max(memory) if memory else None,
                          "memory_measurements_available": len(memory),
                          "all_exact_iteration_budget": all(item["completed_iterations"] == args.iterations for item in values)})
    report = {"schema_version": 1, "environment": environment(), "executable_sha256": sha256(args.executable),
              "fixtures": fixtures, "fixtures_sha256": manifest_hash(fixtures),
              "iterations_per_move": args.iterations, "repeats": args.repeats,
              "summaries": summaries, "trials": records,
              "scope": "Equal total iteration budgets on named nonterminal snapshots. Swap and instant tactical shortcuts are disabled for measurement. Throughput is not playing strength. Report each position and environment separately. Peak RSS includes native workers, not the Python driver. Unavailable RSS is null, never a measured zero."}
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
    runner.add_argument("--max-wall-seconds", type=float, help="Stop between games before the session deadline; completed games are checkpointed.")
    runner.add_argument("--checkpoint-margin-seconds", type=float, default=60)
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
    tester.add_argument("--fixtures", type=Path, help="JSON list (or object with fixtures key) of frozen benchmark positions.")
    tester.add_argument("--colour", choices=["R", "B"], default="B")
    tester.add_argument("--turn", type=int, default=2)
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
            result = evaluate(args.config, args.output, args.executable, args.shard_index, args.shard_count, args.resume,
                              args.max_wall_seconds, args.checkpoint_margin_seconds)
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
