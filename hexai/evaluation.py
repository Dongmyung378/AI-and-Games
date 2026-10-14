"""Frozen-manifest, sequential, resumable evaluations with honest failures."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import time
from collections import Counter, defaultdict

from .native import EngineError, NativeProcess, environment, executable_default, sha256
from .referee import Colour, Referee

POLICIES = {"ucb", "ts", "rave_ucb", "rave_ts", "legacy_ts"}
CSV_FIELDS = ["game_id", "pair_id", "red", "blue", "status", "winner", "winning_colour",
              "failure_actor", "turns", "wall_seconds", "seed", "opening_seed", "manifest_sha256"]


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def manifest_hash(data):
    return hashlib.sha256(canonical(data).encode("utf-8")).hexdigest()


def validate_manifest(data):
    if data.get("schema_version") != 1 or data.get("split") not in {"development", "final"}:
        raise ValueError("Manifest needs schema_version=1 and split=development or final.")
    if not isinstance(data.get("suite_id"), str) or not data["suite_id"]:
        raise ValueError("Manifest needs a nonempty suite_id.")
    size = data.get("board_size", 11)
    if isinstance(size, bool) or not isinstance(size, int) or not 3 <= size <= 19:
        raise ValueError("board_size must be an integer from 3 to 19.")
    participants = data.get("participants", {})
    if len(participants) < 2:
        raise ValueError("At least two labelled participants are required.")
    for label, participant in participants.items():
        if not label or not isinstance(participant, dict):
            raise ValueError("Each participant needs a nonempty label and settings.")
        kind = participant.get("kind", "native")
        if kind not in {"native", "legacy"}:
            raise ValueError("Participant kind must be native or legacy.")
        if kind == "native" and participant.get("policy", "rave_ts") not in POLICIES:
            raise ValueError("Unknown native policy.")
        if kind == "native":
            for key in ("workers", "node_cap", "memory_mb"):
                value = participant.get(key, 1)
                if type(value) is not int or value <= 0:
                    raise ValueError("Native " + key + " must be a positive integer.")
            for key in ("bridge", "ordering", "swap", "tactics"):
                if key in participant and type(participant[key]) is not bool:
                    raise ValueError(key + " must be a JSON boolean.")
            value = participant.get("rave_k", 1000)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("rave_k must be positive and finite.")
        if kind == "legacy" and size != 11:
            raise ValueError("The preserved legacy agent supports only 11x11.")
        if kind == "legacy" and set(participant) - {"kind", "executable", "legacy_executable", "description"}:
            raise ValueError("Legacy settings are immutable: eight workers and 300-second internal game budget.")
    budget = data.get("budget", {})
    mode = budget.get("mode")
    if mode not in {"iterations", "time"}:
        raise ValueError("Budget mode must be iterations or time.")
    key = "iterations" if mode == "iterations" else "seconds"
    value = budget.get(key)
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        raise ValueError("Budget needs a positive finite " + key + ".")
    if mode == "iterations" and not isinstance(value, int):
        raise ValueError("Iteration budget must be an integer.")
    for key, default in (("workers", 1), ("node_cap", 60000), ("memory_mb", 128)):
        value = budget.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(key + " must be a positive integer.")
    for key, default in (("game_seconds", 300), ("response_timeout", 30)):
        value = budget.get(key, default)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(key + " must be positive and finite.")
    games = data.get("games", [])
    if not games:
        raise ValueError("Manifest contains no games.")
    ids = set()
    for game in games:
        ident = game.get("game_id")
        if not isinstance(ident, str) or not ident or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in ident) or ident in ids:
            raise ValueError("game_id must be unique and filename-safe.")
        ids.add(ident)
        if game.get("red") not in participants or game.get("blue") not in participants or game["red"] == game["blue"]:
            raise ValueError("Games need distinct known red and blue participants.")
        for key in ("seed", "opening_seed"):
            if key not in game or not isinstance(game[key], int) or isinstance(game[key], bool) or game[key] < 0:
                raise ValueError("Each game needs nonnegative integer seed and opening_seed.")
        state = Referee(size, game["red"], game["blue"])
        for move in game.get("opening_moves", []):
            if not isinstance(move, list) or len(move) != 2 or any(type(x) is not int for x in move):
                raise ValueError("Opening moves must be integer coordinate pairs.")
            state.play(tuple(move))
            if state.winner:
                raise ValueError("A forced opening cannot already finish the game.")
    # A pair is a true same-condition side reversal, never a loose grouping.
    pairs = defaultdict(list)
    for game in games:
        if game.get("pair_id"):
            pairs[game["pair_id"]].append(game)
    for pair_id, paired in pairs.items():
        if len(paired) != 2:
            raise ValueError("Each pair_id must identify exactly two games: " + str(pair_id))
        a, b = paired
        if (a["red"], a["blue"]) != (b["blue"], b["red"]) or any(a.get(key) != b.get(key) for key in ("seed", "opening_seed", "opening_moves")):
            raise ValueError("Pairs must reverse sides with identical seed and forced opening.")
    return data


def load_manifest(path: Path):
    return validate_manifest(json.loads(Path(path).read_text(encoding="utf-8")))


def participant_command(participant, budget, game, colour, executable):
    if participant.get("kind", "native") == "legacy":
        path = participant.get("legacy_executable", participant.get("executable"))
        if not path:
            raise ValueError("Legacy participant needs its rebuilt legacy_executable path.")
        return [str(Path(path).resolve()), colour, "11"]
    command = [str(Path(participant.get("executable", executable)).resolve()), "--policy", participant.get("policy", "rave_ts"),
               "--seed", str(game["seed"]), "--workers", str(participant.get("workers", budget.get("workers", 1))),
               "--game-seconds", str(budget.get("game_seconds", 300)),
               "--node-cap", str(participant.get("node_cap", budget.get("node_cap", 60000))),
               "--memory-mb", str(participant.get("memory_mb", budget.get("memory_mb", 128))),
               "--bridge", str(int(participant.get("bridge", True))),
               "--ordering", str(int(participant.get("ordering", True))),
               "--tactics", str(int(participant.get("tactics", True))),
               "--swap", str(int(participant.get("swap", True))),
               "--rave-k", str(participant.get("rave_k", 1000))]
    if budget["mode"] == "iterations":
        command += ["--iterations", str(budget["iterations"])]
    else:
        command += ["--seconds", str(budget["seconds"])]
    return command


def run_game(manifest, game, executable=None, process_factory=NativeProcess):
    """Failure ends with winner=None. Only verified connectivity produces a win."""
    executable = Path(executable or executable_default())
    state = Referee(manifest.get("board_size", 11), game["red"], game["blue"])
    started = time.perf_counter()
    moves, engines, commands = [], {}, {}
    spent = {game["red"]: 0.0, game["blue"]: 0.0}
    result = {"schema_version": 1, **game, "manifest_sha256": manifest_hash(manifest),
              "status": "incomplete", "winner": None, "winning_colour": None, "failure_actor": None}
    budget = manifest["budget"]
    try:
        for move in game.get("opening_moves", []):
            moves.append({"turn": state.turn, "actor": state.actor, "colour": Colour.get_char(state.colour),
                          "move": move, "forced_opening": True, "response_seconds": 0.0})
            state.play(tuple(move))
        for label, colour in ((game["red"], "R"), (game["blue"], "B")):
            command = participant_command(manifest["participants"][label], budget, game, colour, executable)
            commands[label] = command
            try:
                engines[label] = process_factory(command)
            except OSError as error:
                result.update(status="process_error", failure_actor=label, error=str(error))
                return result
        while state.winner is None and state.turn <= state.board.size ** 2 + 1:
            actor, colour, message = state.actor, Colour.get_char(state.colour), state.message()
            remaining = budget.get("game_seconds", 300) - spent[actor]
            timeout = min(remaining, budget.get("response_timeout", 30))
            try:
                move, elapsed = engines[actor].request(message, timeout)
                spent[actor] += elapsed
                if elapsed > remaining:
                    raise EngineError("timeout", "External measured game budget was exhausted.")
                event = {"turn": state.turn, "actor": actor, "colour": colour, "move": list(move),
                         "forced_opening": False, "response_seconds": elapsed,
                         "message": message}
                try:
                    state.play(move)
                except ValueError as error:
                    event["accepted"] = False
                    moves.append(event)
                    raise EngineError("illegal_move", str(error)) from None
                event["accepted"] = True
                moves.append(event)
            except EngineError as error:
                result.update(status=error.status, failure_actor=actor, error=str(error))
                break
        if state.winner:
            result.update(status="completed", winner=state.winner,
                          winning_colour=Colour.get_char(state.board.get_winner()))
        elif result["status"] == "incomplete":
            result.update(status="referee_error", error="Legal game exhausted its turn bound without connectivity.")
    finally:
        telemetry, memory = {}, {}
        for label, engine in engines.items():
            engine.close()
            telemetry[label] = list(engine.telemetry)
            memory[label] = getattr(engine, "peak_rss_bytes", None)
        result.update(moves=moves, final_board=state.board_text(), turns=len(moves),
                      wall_seconds=time.perf_counter() - started, participant_seconds=spent,
                      commands=commands, telemetry=telemetry, process_peak_rss_bytes=memory)
    return result


def wilson(wins, count):
    if not count:
        return None
    z = 1.959963984540054
    p = wins / count
    divisor = 1 + z * z / count
    centre = (p + z * z / (2 * count)) / divisor
    half = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / divisor
    return [max(0.0, centre - half), min(1.0, centre + half)]


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    index = (len(values) - 1) * fraction
    lower = math.floor(index)
    return values[lower] + (values[math.ceil(index)] - values[lower]) * (index - lower)


def paired_bootstrap(values, seed=378, samples=2000):
    if len(values) < 2:
        return None
    generator = random.Random(seed)
    draws = [statistics.fmean(generator.choices(values, k=len(values))) for _ in range(samples)]
    return [percentile(draws, 0.025), percentile(draws, 0.975)]


def summarize(manifest, results):
    by_id = {item["game_id"]: item for item in results}
    if len(by_id) != len(results):
        raise ValueError("Duplicate game results cannot be counted twice.")
    expected = {game["game_id"]: game for game in manifest["games"]}
    if set(by_id) - set(expected):
        raise ValueError("Unexpected game_id in results.")
    groups = defaultdict(list)
    for game in manifest["games"]:
        groups[tuple(sorted((game["red"], game["blue"])))].append(game)
    comparisons = []
    for (left, right), games in sorted(groups.items()):
        records = [by_id[game["game_id"]] for game in games if game["game_id"] in by_id]
        completed = [item for item in records if item["status"] == "completed"]
        wins = sum(item["winner"] == left for item in completed)
        pairs = defaultdict(list)
        for item in completed:
            if item.get("pair_id"):
                pairs[item["pair_id"]].append(item)
        pair_values = [sum(item["winner"] == left for item in values) / 2 for values in pairs.values() if len(values) == 2]
        comparisons.append({"left": left, "right": right, "scheduled_games": len(games),
                            "recorded_games": len(records), "completed_games": len(completed),
                            "left_wins": wins, "right_wins": len(completed) - wins,
                            "left_win_rate_completed_games": wins / len(completed) if completed else None,
                            "wilson_95_game_interval": wilson(wins, len(completed)),
                            "wilson_caveat": "Descriptive game-level interval; side-paired games are dependent.",
                            "complete_side_pairs": len(pair_values),
                            "paired_mean_win_rate": statistics.fmean(pair_values) if pair_values else None,
                            "paired_cluster_bootstrap_95": paired_bootstrap(pair_values),
                            "bootstrap_resamples": 2000, "bootstrap_seed": 378,
                            "failures": dict(Counter(item["status"] for item in records if item["status"] != "completed")),
                            "failures_by_actor": dict(Counter(item.get("failure_actor") for item in records if item["status"] != "completed")),
                            "failure_rate_recorded": sum(item["status"] != "completed" for item in records) / len(records) if records else None,
                            "left_first_wins": sum(item["winner"] == left and item["red"] == left for item in completed),
                            "left_second_wins": sum(item["winner"] == left and item["blue"] == left for item in completed)})
    return {"schema_version": 1, "suite_id": manifest["suite_id"], "split": manifest["split"],
            "manifest_sha256": manifest_hash(manifest), "budget": manifest["budget"],
            "scheduled_games": len(manifest["games"]), "recorded_games": len(results),
            "completed_games": sum(item["status"] == "completed" for item in results),
            "missing_game_ids": sorted(set(expected) - set(by_id)), "comparisons": comparisons,
            "interpretation": "Wins require verified connecting paths. Timeouts, illegal moves and protocol/process failures are excluded from playing-strength wins and reported separately. Pair bootstrap resamples complete side-reversal pairs only. Hardware environments must be reported separately."}


def write_csv(path, results):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda item: item["game_id"]))


def evaluate(config, output, executable=None, shard_index=0, shard_count=1, resume=False):
    manifest = load_manifest(Path(config))
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("Require shard_count >=1 and 0 <= shard_index < shard_count.")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    frozen = output / "manifest.json"
    fingerprint = manifest_hash(manifest)
    if frozen.exists():
        if not resume:
            raise ValueError("Output already exists; use --resume with exactly the same manifest.")
        if manifest_hash(json.loads(frozen.read_text(encoding="utf-8"))) != fingerprint:
            raise ValueError("Resume manifest differs from the frozen original.")
    else:
        atomic_json(frozen, manifest)
    executable = Path(executable or executable_default())
    binaries = {}
    for label, participant in manifest["participants"].items():
        path = Path(participant.get("legacy_executable", participant.get("executable", executable)))
        if not path.is_file():
            raise ValueError("Executable missing for " + label + ": " + str(path))
        build_receipt = path.with_name(path.name + ".build.json")
        receipt = json.loads(build_receipt.read_text(encoding="utf-8")) if build_receipt.exists() else None
        fingerprint_binary = sha256(path)
        if receipt and receipt.get("executable_sha256") != fingerprint_binary:
            raise ValueError("Executable no longer matches its build receipt: " + str(path))
        binaries[label] = {"path": str(path.resolve()), "sha256": fingerprint_binary, "build_receipt": receipt}
    meta = {"manifest_sha256": fingerprint, "environment": environment(), "binaries": binaries,
            "shard_index": shard_index, "shard_count": shard_count,
            "runner_sha256": {name: sha256(Path(__file__).with_name(name)) for name in ("native.py", "referee.py", "evaluation.py", "cli.py")},
            "execution": "Sequential games; each participant process may use declared root-parallel workers."}
    meta_path = output / "metadata.json"
    if meta_path.exists():
        old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if canonical(old_meta) != canonical(meta):
            raise ValueError("Resume environment, shard or executable metadata changed. Use a separate output directory.")
    else:
        atomic_json(meta_path, meta)
    # Keep colour-reversed pairs on one host so pair intervals do not mix devices.
    group_indexes = {}
    selected = []
    for game in manifest["games"]:
        group = "pair:" + game["pair_id"] if game.get("pair_id") else "game:" + game["game_id"]
        if group not in group_indexes:
            group_indexes[group] = len(group_indexes)
        if group_indexes[group] % shard_count == shard_index:
            selected.append(game)
    results = []
    for game in selected:
        path = output / "games" / (game["game_id"] + ".json")
        if path.exists():
            result = json.loads(path.read_text(encoding="utf-8"))
            if result.get("manifest_sha256") != fingerprint or result.get("game_id") != game["game_id"]:
                raise ValueError("Saved result does not match the frozen manifest.")
            replay(result)
        else:
            result = run_game(manifest, game, executable)
            replay(result)
            atomic_json(path, result)
            with path.with_suffix(".jsonl").open("w", encoding="utf-8") as handle:
                for item in result["moves"]:
                    handle.write(canonical({"kind": "referee_move", **item}) + "\n")
                for label, telemetry in result["telemetry"].items():
                    for item in telemetry:
                        handle.write(canonical({"participant": label, "kind": "engine_telemetry", "payload": item}) + "\n")
        results.append(result)
        write_csv(output / "games.csv", results)
        atomic_json(output / "summary.json", summarize(manifest, results))
        print(canonical({"game_id": game["game_id"], "status": result["status"], "winner": result["winner"], "finished": len(results), "shard_games": len(selected)}), flush=True)
    return summarize(manifest, results)


def replay(result):
    rows = result["final_board"].split(",")
    state = Referee(len(rows), result["red"], result["blue"])
    for event in result["moves"]:
        if event["turn"] != state.turn or event["actor"] != state.actor or event["colour"] != Colour.get_char(state.colour):
            raise ValueError("Replay turn, identity or pie-rule colour mismatch.")
        if event.get("accepted", True):
            state.play(tuple(event["move"]))
        else:
            if result["status"] != "illegal_move":
                raise ValueError("Rejected move must be recorded as illegal_move.")
            try:
                state.play(tuple(event["move"]))
            except ValueError:
                pass
            else:
                raise ValueError("A recorded rejected move was actually legal.")
    if state.board_text() != result["final_board"]:
        raise ValueError("Replay board differs from recorded board.")
    if result["status"] == "completed":
        if state.winner != result["winner"] or Colour.get_char(state.board.get_winner()) != result["winning_colour"]:
            raise ValueError("Recorded winner lacks the replayed connecting path.")
    elif result.get("winner") is not None or state.winner is not None:
        raise ValueError("A failed game must not fabricate a winner.")
    return {"game_id": result["game_id"], "status": result["status"], "replayed_moves": len(result["moves"]), "verified": True}


def aggregate(inputs, output, require_complete=False):
    manifest, results, metadata = None, {}, []
    for directory in map(Path, inputs):
        candidate = load_manifest(directory / "manifest.json")
        if manifest is None:
            manifest = candidate
        elif manifest_hash(candidate) != manifest_hash(manifest):
            raise ValueError("Cannot mix different frozen manifests.")
        meta = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        metadata.append(meta)
        for path in sorted((directory / "games").glob("*.json")):
            item = json.loads(path.read_text(encoding="utf-8"))
            if item.get("manifest_sha256") != manifest_hash(manifest):
                raise ValueError("Result manifest fingerprint mismatch.")
            if item["game_id"] in results:
                raise ValueError("Duplicate game_id across inputs: " + item["game_id"])
            replay(item)
            results[item["game_id"]] = item
    if manifest is None:
        raise ValueError("No input directories provided.")
    summary = summarize(manifest, list(results.values()))
    if require_complete and summary["missing_game_ids"]:
        raise ValueError("Manifest is incomplete: " + str(len(summary["missing_game_ids"])) + " games missing.")
    # Environment-specific summaries avoid confusing different machine speeds.
    environment_groups = defaultdict(list)
    for index, directory in enumerate(map(Path, inputs)):
        key = canonical(metadata[index]["environment"])
        for path in sorted((directory / "games").glob("*.json")):
            environment_groups[key].append(json.loads(path.read_text(encoding="utf-8")))
    summary["environment_summaries"] = [{"environment": json.loads(key), "summary": summarize(manifest, records)} for key, records in environment_groups.items()]
    summary["run_metadata"] = metadata
    atomic_json(Path(output), summary)
    write_csv(Path(output).with_suffix(".csv"), list(results.values()))
    return summary
