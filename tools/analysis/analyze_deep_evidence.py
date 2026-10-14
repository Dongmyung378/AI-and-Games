"""Describe measured cost and tactics without selecting a new search policy."""
from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path


def quantile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = fraction * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def distribution(values):
    return {"count": len(values), "p50": quantile(values, .5),
            "p95": quantile(values, .95), "min": min(values) if values else None,
            "max": max(values) if values else None}


def describe_actor(games, actor):
    responses, requests, rss, search_seconds, iterations, nodes = [], [], [], [], [], []
    reasons = Counter()
    response_by_reason = defaultdict(list)
    saturated, worker_requests, cap_observations, missing_rss = 0, 0, 0, 0
    historical_cap_requests, historical_cap_observations = 0, 0
    for game in games:
        external_responses = {move["turn"]: move["response_seconds"] for move in game["moves"]
                              if move["actor"] == actor and not move.get("forced_opening", False)}
        responses.append(game["participant_seconds"][actor])
        requests.append(sum(not move.get("forced_opening", False) and move["actor"] == actor
                            for move in game["moves"]))
        measured_rss = game.get("process_peak_rss_bytes", {}).get(actor)
        if measured_rss is None:
            missing_rss += 1
        else:
            rss.append(measured_rss)
        for item in game.get("telemetry", {}).get(actor, []):
            reason = item.get("reason", "unknown")
            reasons[reason] += 1
            if item.get("turn") in external_responses:
                response_by_reason[reason].append(external_responses[item["turn"]])
            if reason != "search":
                continue
            search_seconds.append(item["seconds"])
            iterations.append(item["iterations"])
            nodes.append(item["nodes"])
            if "original_iteration_cap_reached" in item:
                historical_cap_observations += 1
                historical_cap_requests += bool(item["original_iteration_cap_reached"])
            for worker in item.get("workers", []):
                worker_requests += 1
                if "node_cap_reached" in worker:
                    cap_observations += 1
                    saturated += bool(worker["node_cap_reached"])
    measured_seconds = sum(search_seconds)
    return {
        "completed_games": len(games),
        "external_response_seconds_per_game": distribution(responses),
        "engine_requests_per_game": distribution(requests),
        "sampled_process_peak_rss_bytes": distribution(rss),
        "games_without_rss_measurement": missing_rss,
        "native_search_response_seconds": distribution(search_seconds),
        "native_search_iterations_per_response": distribution(iterations),
        "native_nodes_per_search_response": distribution(nodes),
        "native_total_search_iterations": sum(iterations),
        "native_total_search_response_seconds": measured_seconds,
        "native_search_iterations_per_response_second":
            sum(iterations) / measured_seconds if measured_seconds else None,
        "telemetry_reasons": dict(sorted(reasons.items())),
        "external_response_seconds_by_native_reason":
            {reason: distribution(values) for reason, values in sorted(response_by_reason.items())},
        "worker_search_requests": worker_requests,
        "worker_requests_with_node_cap_telemetry": cap_observations,
        "worker_requests_reaching_node_cap": saturated,
        "worker_node_cap_fraction": saturated / cap_observations if cap_observations else None,
        "historical_search_requests_with_iteration_cap_telemetry": historical_cap_observations,
        "historical_search_requests_reaching_original_iteration_cap": historical_cap_requests,
    }


def analyze(summary_path, run_dirs, expected_games):
    summary_path = Path(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary["recorded_games"] != expected_games or summary["missing_game_ids"]:
        raise ValueError("Only a complete frozen suite can be described for publication.")
    games, ids, fingerprints = [], set(), set()
    for directory in map(Path, run_dirs):
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        for path in sorted((directory / "games").glob("*.json")):
            game = json.loads(path.read_text(encoding="utf-8"))
            if game["game_id"] in ids:
                raise ValueError("Duplicate game in cost analysis.")
            if game["execution_signature"] != metadata["execution_signature"]:
                raise ValueError("Game execution signature differs from its recorded run.")
            if game["manifest_sha256"] != summary["manifest_sha256"]:
                raise ValueError("Game does not belong to the summarized frozen suite.")
            ids.add(game["game_id"])
            fingerprints.add(game["manifest_sha256"])
            games.append(game)
    if len(games) != expected_games or len(fingerprints) != 1:
        raise ValueError("Saved game coverage differs from the complete aggregate.")
    completed = [game for game in games if game["status"] == "completed"]
    if len(completed) != summary["completed_games"]:
        raise ValueError("Completed game denominator differs from aggregate.")
    comparisons = []
    clock_violations = []
    for comparison in summary["comparisons"]:
        left, right = comparison["left"], comparison["right"]
        selected = [game for game in completed if {game["red"], game["blue"]} == {left, right}]
        environments = defaultdict(list)
        for game in selected:
            key = game["execution_signature"]["hardware"]["hardware_sha256"]
            environments[key].append(game)
            allowance = game.get("budget_accounting", {}).get("external_game_allowance_seconds")
            if allowance is not None:
                for actor, spent in game["participant_seconds"].items():
                    if spent > allowance + 1e-6:
                        clock_violations.append({"game_id": game["game_id"], "actor": actor,
                                                 "seconds": spent, "allowance": allowance})
        comparisons.append({
            "left": left, "right": right, "completed_games": len(selected),
            "game_wall_seconds": distribution([game["wall_seconds"] for game in selected]),
            "turns": distribution([game["turns"] for game in selected]),
            "actors": {actor: describe_actor(selected, actor) for actor in (left, right)},
            "hardware_classes": {
                key: {"completed_games": len(items),
                      "system": items[0]["execution_signature"]["hardware"]["hardware"]["system"],
                      "actors": {actor: describe_actor(items, actor) for actor in (left, right)}}
                for key, items in sorted(environments.items())
            },
        })
    return {
        "schema_version": 1, "suite_id": summary["suite_id"],
        "manifest_sha256": summary["manifest_sha256"],
        "aggregate_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "recorded_games": len(games), "completed_games": len(completed),
        "failed_games": len(games) - len(completed),
        "clock_violations_in_completed_games": clock_violations,
        "comparisons": comparisons,
        "scope": "Descriptive saved telemetry from completed games. Costs are not causal explanations of wins. RSS is sampled, not an OS memory limit. The ratio uses summed native search response elapsed time, not summed per-worker elapsed wall time. Worker elapsed telemetry is not CPU usage time. No policy selection or new games.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--expected-games", type=int, default=400)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.summary, args.runs, args.expected_games)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"suite": report["suite_id"], "completed_games": report["completed_games"],
                      "failed_games": report["failed_games"],
                      "clock_violations": len(report["clock_violations_in_completed_games"])}))


if __name__ == "__main__":
    main()
