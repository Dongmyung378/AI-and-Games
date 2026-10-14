"""Bind completed public Hex reports to reproducible figure inputs, without modifying evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hex_visual_data import Inputs, comparisons, game_metrics, sha


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def prepare(repository_root):
    root = Path(repository_root).resolve()
    directory = root / "assets/figures"
    shared = root / "reports/deep/aggregates/shared-time.json"
    tactical = root / "reports/deep/aggregates/tactical-ablation.json"
    reports = {"shared": json.loads(shared.read_bytes()), "tactical": json.loads(tactical.read_bytes())}
    expected_opponents = {"shared": {"ucb", "ts", "rave_ucb", "historical_algorithm"},
                          "tactical": {"no_swap", "no_win_check", "no_block_check", "no_tactics"}}
    for label, summary in reports.items():
        if [summary.get(key) for key in ("scheduled_games", "recorded_games", "completed_games")] != [400, 400, 400]:
            raise ValueError("Only actual complete 400-game suites may bind final figures.")
        rows = comparisons(summary, "selected")
        if {row["opponent"] for row in rows} != expected_opponents[label] or any(row["completed"] != 100 or row["pairs"] != 50 for row in rows):
            raise ValueError("Opponent identifiers and paired coverage do not match the final protocol.")
    directories = sorted((root / "reports/deep/evaluation/shared-time").glob("*/evaluation-shard*"))
    if len(directories) != 10:
        raise ValueError("The shared suite requires its actual ten completed source shards.")
    # Use the same source parser as the renderer; collect raw records directly.
    # A temporary in-memory Inputs object avoids creating any example scores.
    inputs = Inputs.__new__(Inputs)
    inputs.directory, inputs.repository_root = directory, root
    inputs.receipts, inputs.expected = [], {}
    section = {"focus": "selected", "game_directories": [path.relative_to(root).as_posix() for path in directories]}
    section["game_directories"] = ["../../" + path for path in section["game_directories"]]
    metrics = game_metrics(inputs, section, reports["shared"]["manifest_sha256"])
    if set(metrics) != expected_opponents["shared"] or any(value["completed_games"] != 100 for value in metrics.values()):
        raise ValueError("Actual source records do not cover all four completed 100-game comparisons.")
    metric_path = root / "reports/deep/analysis/shared-time-metrics.json"
    write_json(metric_path, metrics)
    write_json(directory / "deep-metric-provenance.json", {
        "schema_version": 1, "focus": "selected", "manifest_sha256": reports["shared"]["manifest_sha256"],
        "aggregate_repository_path": shared.relative_to(root).as_posix(), "aggregate_sha256": sha(shared),
        "metrics_repository_path": metric_path.relative_to(root).as_posix(), "metrics_sha256": sha(metric_path),
        "actual_completed_games": 400, "raw_source_files": inputs.receipts,
        "preparer_repository_path": "tools/figures/prepare_hex_visual_inputs.py", "preparer_sha256": sha(__file__),
        "scope": "Exact raw-record response medians and activation counts; no model change or retuning."})
    # Pick one recorded selected-agent win for the thumbnail's board, by stable
    # game ID, rather than draw an illustrative position or synthesize a score.
    games = []
    for path in sorted((root / "reports/deep/evaluation/shared-time").glob("*/evaluation-shard*/games/*.json")):
        game = json.loads(path.read_bytes())
        if game.get("status") == "completed" and game.get("winner") == "selected":
            games.append((game["game_id"], path))
    game_path = min(games)[1]
    relative = lambda path: "../../" + path.relative_to(root).as_posix()
    tactical_metrics = root / "reports/deep/analysis/tactical-metrics.json"
    windows, kaggle = (root / ("reports/deep/benchmarks/" + name + ".json") for name in ["windows", "kaggle"])
    guarded = [shared, tactical, metric_path, tactical_metrics, windows, kaggle, game_path]
    data = {"schema_version": 1, "repository_root": "../..",
            "expected_inputs": {relative(path): {"sha256": sha(path), "hash_mode": "raw_bytes"} for path in guarded},
            "shared_time": {"summary_path": relative(shared), "metrics_path": relative(metric_path),
                            "manifest_sha256": reports["shared"]["manifest_sha256"], "focus": "selected",
                            "environment_id_map": {"Windows": "windows", "Linux": "kaggle"}},
            "tactical": {"summary_path": relative(tactical), "metrics_path": relative(tactical_metrics),
                         "manifest_sha256": reports["tactical"]["manifest_sha256"], "focus": "selected"},
            "worker_reports": [{"id": "windows", "path": relative(windows)}, {"id": "kaggle", "path": relative(kaggle)}],
            "thumbnail": {"summary_path": relative(shared), "game_path": relative(game_path),
                          "manifest_sha256": reports["shared"]["manifest_sha256"], "focus": "selected"}}
    write_json(directory / "deep-visual-input.json", data)
    return {"status": "bound_actual_complete_reports", "data_path": "assets/figures/deep-visual-input.json",
            "selected_results_by_opponent": {row["opponent"]: {"wins": row["wins"], "completed": row["completed"], "paired_ci95": row["ci95"]} for row in comparisons(reports["shared"], "selected")},
            "completed_source_games": len(inputs.receipts), "thumbnail_game_id": min(games)[0]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(prepare(args.repository_root), indent=2))
