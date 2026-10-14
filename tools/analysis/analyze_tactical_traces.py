"""Descriptive analysis of the actual frozen 400 tactical games, no new matches."""
from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import statistics




def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    p = (len(values) - 1) * fraction
    low = int(p)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (p - low)


def durations(values):
    return {"count": len(values), "p50_seconds": statistics.median(values) if values else None,
            "p95_seconds": percentile(values, .95), "minimum_seconds": min(values) if values else None,
            "maximum_seconds": max(values) if values else None}


def physical_trace(game):
    return [(move["turn"], move["colour"], tuple(move["move"]), bool(move.get("forced_opening"))) for move in game["moves"]]


def decisions(game):
    telemetry = {}
    for actor, events in game["telemetry"].items():
        for event in events:
            if event.get("kind") == "hex_search_move":
                key = (actor, event["turn"])
                if key in telemetry:
                    raise ValueError("Duplicate native decision.")
                telemetry[key] = event
    result = []
    for move in game["moves"]:
        if not move.get("forced_opening"):
            event = telemetry[(move["actor"], move["turn"])]
            if list(event["move"]) != list(move["move"]):
                raise ValueError("Native decision and referee move differ.")
            parts = move["message"].split(";")
            position = (move["turn"], move["colour"], parts[5])
            result.append({"actor": move["actor"], "position": position, "move": tuple(move["move"]),
                           "reason": event["reason"], "native_seconds": event["seconds"],
                           "external_seconds": move["response_seconds"], "iterations": event["iterations"],
                           "worker_seeds": tuple(worker["seed"] for worker in event["workers"])})
    return result


def analyze(summary_path, run_directories, output_directory):
    summary_path = Path(summary_path)
    run_directories = list(map(Path, run_directories))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary["recorded_games"] != 400 or summary["completed_games"] != 400:
        raise ValueError("Expected actual complete 400-game tactical suite.")
    games = {}
    sources = []
    for directory in run_directories:
        for path in sorted((directory / "games").glob("*.json")):
            game = json.loads(path.read_text(encoding="utf-8"))
            if game["status"] != "completed" or game["manifest_sha256"] != summary["manifest_sha256"]:
                raise ValueError("Unexpected status or frozen manifest.")
            if game["game_id"] in games:
                raise ValueError("Duplicate actual game.")
            games[game["game_id"]] = game
            sources.append({"game_id": game["game_id"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if len(games) != 400:
        raise ValueError("Actual shard coverage is not 400.")
    grouped = defaultdict(list)
    for game in games.values():
        opponent = game["blue"] if game["red"] == "selected" else game["red"]
        grouped[opponent].append(game)
    reports, metric_mapping = {}, {}
    for opponent, records in grouped.items():
        actor_stats = {}
        for actor in ("selected", opponent):
            items = [item for game in records for item in decisions(game) if item["actor"] == actor]
            by_reason = {}
            for reason in sorted({item["reason"] for item in items}):
                selected = [item for item in items if item["reason"] == reason]
                by_reason[reason] = {"decisions": len(selected), "iterations": dict(Counter(item["iterations"] for item in selected)),
                                     "native_time": durations([item["native_seconds"] for item in selected]),
                                     "external_response_time": durations([item["external_seconds"] for item in selected])}
            actor_stats[actor] = {"decision_count": len(items), "reasons": dict(Counter(item["reason"] for item in items)),
                                  "by_reason": by_reason, "native_time": durations([item["native_seconds"] for item in items]),
                                  "external_response_time": durations([item["external_seconds"] for item in items]),
                                  "consumed_game_time": durations([game["participant_seconds"][actor] for game in records])}
        pairs = defaultdict(list)
        for game in records:
            pairs[game["pair_id"]].append(game)
        pair_scores = Counter()
        identical, same_winning_colour, different = 0, 0, []
        same_positions = Counter()
        matched_tactical = defaultdict(lambda: {"pairs": 0, "same_action": 0, "focus_native": [], "opponent_native": [], "focus_external": [], "opponent_external": []})
        for pair_id, pair in sorted(pairs.items()):
            if len(pair) != 2:
                raise ValueError("Incomplete side pair.")
            a, b = sorted(pair, key=lambda game: game["game_id"])
            if (a["red"], a["blue"]) != (b["blue"], b["red"]) or a["seed"] != b["seed"] or a["opening_moves"] != b["opening_moves"]:
                raise ValueError("Not the frozen side reversal.")
            score = sum(game["winner"] == "selected" for game in pair) / 2
            pair_scores[str(score)] += 1
            ta, tb = physical_trace(a), physical_trace(b)
            if ta == tb:
                identical += 1
            else:
                prefix = 0
                for ma, mb in zip(ta, tb):
                    if ma != mb:
                        break
                    prefix += 1
                different.append({"pair_id": pair_id, "common_move_prefix": prefix,
                                  "lengths": [len(ta), len(tb)], "winning_colours": [a["winning_colour"], b["winning_colour"]],
                                  "selected_wins": int(score * 2)})
            same_winning_colour += a["winning_colour"] == b["winning_colour"]
            da = {item["position"]: item for item in decisions(a)}
            db = {item["position"]: item for item in decisions(b)}
            for position in da.keys() & db.keys():
                x, y = da[position], db[position]
                if x["actor"] == y["actor"]:
                    raise ValueError("Mirrored position did not reverse actor identity.")
                focus, control = (x, y) if x["actor"] == "selected" else (y, x)
                same_positions["shared_position_decisions"] += 1
                same_positions["same_action"] += focus["move"] == control["move"]
                same_positions["same_reason"] += focus["reason"] == control["reason"]
                if focus["reason"] == control["reason"] == "search":
                    same_positions["both_search"] += 1
                    same_positions["same_search_worker_seeds"] += focus["worker_seeds"] == control["worker_seeds"]
                    same_positions["same_search_action"] += focus["move"] == control["move"]
                if focus["reason"] in {"pie_rule_swap", "tactical_win", "tactical_block"} and control["reason"] == "search":
                    row = matched_tactical[focus["reason"]]
                    row["pairs"] += 1
                    row["same_action"] += focus["move"] == control["move"]
                    row["focus_native"].append(focus["native_seconds"])
                    row["opponent_native"].append(control["native_seconds"])
                    row["focus_external"].append(focus["external_seconds"])
                    row["opponent_external"].append(control["external_seconds"])
        matching = {reason: {"matched_position_decisions": row["pairs"], "same_action": row["same_action"],
                             **{key: durations(value) for key, value in row.items() if key not in {"pairs", "same_action"}}}
                    for reason, row in matched_tactical.items()}
        reports[opponent] = {"completed_games": len(records), "pairs": len(pairs), "pair_selected_score_counts": dict(pair_scores),
                             "identical_physical_trace_pairs": identical, "different_trace_pairs": len(different),
                             "same_winning_colour_pairs": same_winning_colour, "different_trace_examples": different,
                             "matched_positions": dict(same_positions), "matched_tactical_vs_search": matching,
                             "actors": actor_stats}
        focus, control = actor_stats["selected"], actor_stats[opponent]
        metric_mapping[opponent] = {"completed_games": len(records), "focus_reasons": focus["reasons"], "opponent_reasons": control["reasons"],
                                    "focus_median_response_seconds": focus["external_response_time"]["p50_seconds"],
                                    "opponent_median_response_seconds": control["external_response_time"]["p50_seconds"],
                                    "focus_median_game_seconds": focus["consumed_game_time"]["p50_seconds"],
                                    "opponent_median_game_seconds": control["consumed_game_time"]["p50_seconds"]}
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "suite_id": summary["suite_id"], "manifest_sha256": summary["manifest_sha256"],
              "status": "analyzed_actual_400_completed_games", "aggregate_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
              "coverage": {"games": 400, "failures": 0, "pairs": 200}, "comparisons": reports,
              "sources": sources, "scope": "Recorded move/seed equality and measured completed-game responses only. No new games, retuning or causal attribution of all outcome differences."}
    (destination / "analysis.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (destination / "tactical-metrics.json").write_text(json.dumps(metric_mapping, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.summary, args.runs, args.output)
    print(json.dumps({"status": report["status"], "coverage": report["coverage"],
                      "outputs": ["analysis.json", "tactical-metrics.json"]}))


if __name__ == "__main__":
    main()
