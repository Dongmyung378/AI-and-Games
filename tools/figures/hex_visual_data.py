"""Validated actual Hex report inputs for optional portfolio figure generation."""
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics

PALETTE = {"ivory": "#F7F3EA", "paper": "#FFFCF6", "navy": "#17304A", "red": "#A74445",
           "muted": "#66717A", "line": "#D9D3C9", "sand": "#C8AE82", "steel": "#45768D"}


NAMES = {
    "selected": ("Selected RAVE-TS", "선정한 RAVE-TS"),
    "ucb": ("UCB", "UCB"), "ts": ("Thompson Sampling", "톰슨 샘플링"),
    "rave_ucb": ("RAVE-UCB", "RAVE-UCB"),
    "historical_algorithm": ("Controlled historical C++", "기존 C++ 알고리즘"),
    "no_swap": ("Swap heuristic removed", "스왑 판단 제외"),
    "no_win_check": ("Immediate-win check removed", "즉시 승리 검사 제외"),
    "no_block_check": ("Immediate block removed", "즉시 방어 검사 제외"),
    "no_tactics": ("Both tactical checks removed", "전술 검사 모두 제외"),
    "opening": ("Opening", "초반"), "middle": ("Middle game", "중반"), "late": ("Late game", "후반"),
    "opening-transpose-exchange": ("Opening, transposed roles", "초반의 좌표와 색상 교환"),
    "middle-transpose-exchange": ("Middle, transposed roles", "중반의 좌표와 색상 교환"),
    "late-transpose-exchange": ("Late, transposed roles", "후반의 좌표와 색상 교환"),
    "windows": ("Local Windows", "로컬 Windows"), "kaggle": ("Kaggle Linux CPU", "Kaggle Linux CPU"),
    "linux": ("Linux CPU", "Linux CPU"),
}


def tr(language, english, korean):
    return english if language == "en" else korean


def name(identifier, language):
    pair = NAMES.get(identifier)
    return pair[0 if language == "en" else 1] if pair else identifier.replace("_", " ")


def finite(value, label, low=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < low:
        raise ValueError(f"{label} must be finite and at least {low}.")
    return value


def integer(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(label + " must be a nonnegative integer.")
    return value


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Inputs:
    def __init__(self, data_path):
        self.data_path = Path(data_path).resolve()
        self.directory = self.data_path.parent
        self.receipts = []
        self.expected = {}
        self.repository_root = None
        self.data = self.load(self.data_path)
        if self.data.get("schema_version") != 1:
            raise ValueError("Visual input needs schema_version 1.")
        if "repository_root" in self.data:
            self.repository_root = self.resolve(self.data["repository_root"])
        for relative, spec in self.data.get("expected_inputs", {}).items():
            path = self.resolve(relative)
            digest = spec.get("sha256") if isinstance(spec, dict) else None
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("Every guarded figure input requires a lowercase SHA-256.")
            if self.repository_root and not path.is_relative_to(self.repository_root):
                raise ValueError("Guarded figure input is outside the published repository.")
            self.expected[path] = digest

    def resolve(self, path):
        path = Path(path)
        return path.resolve() if path.is_absolute() else (self.directory / path).resolve()

    def load(self, path):
        path = self.resolve(path)
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if path in self.expected and digest != self.expected[path]:
            raise ValueError("Figure input bytes differ from their published SHA-256: " + path.name)
        data = json.loads(payload)
        receipt = {"filename": path.name, "sha256": digest, "bytes": len(payload)}
        if self.repository_root and path.is_relative_to(self.repository_root):
            receipt["repository_path"] = path.relative_to(self.repository_root).as_posix()
        self.receipts.append(receipt)
        return data


def comparisons(summary, focus):
    rows = []
    for original in summary["comparisons"]:
        left = original["left"] == focus
        if not left and original["right"] != focus:
            continue
        scheduled = integer(original["scheduled_games"], "scheduled_games")
        recorded = integer(original["recorded_games"], "recorded_games")
        completed = integer(original["completed_games"], "completed_games")
        wins = integer(original["left_wins"] if left else original["right_wins"], "wins")
        if not 0 <= wins <= completed <= recorded <= scheduled:
            raise ValueError("Invalid scheduled/recorded/completed/win denominators.")
        if sum(original.get("failures", {}).values()) != recorded - completed:
            raise ValueError("Failure counts do not match completed denominators.")
        pairs = integer(original["complete_side_pairs"], "complete_side_pairs")
        if pairs * 2 > completed:
            raise ValueError("Side pairs exceed completed games.")
        mean = original.get("paired_mean_win_rate")
        if mean is not None:
            finite(mean, "paired_mean_win_rate")
            if mean > 1:
                raise ValueError("Pair score exceeds 1.")
            if not left:
                mean = 1 - mean
        interval = original.get("paired_cluster_bootstrap_95")
        if interval is not None:
            if len(interval) != 2 or not 0 <= interval[0] <= interval[1] <= 1:
                raise ValueError("Pair bootstrap interval is invalid.")
            if not left:
                interval = [1 - interval[1], 1 - interval[0]]
        rows.append({"opponent": original["right"] if left else original["left"], "scheduled": scheduled,
                     "recorded": recorded, "completed": completed, "wins": wins, "failed": recorded - completed,
                     "missing": scheduled - recorded, "pairs": pairs, "mean": mean, "ci95": interval})
    if not rows:
        raise ValueError("Focus participant has no comparisons.")
    return rows


def summary_from(inputs, section):
    if "summary_path" not in section:
        raise ValueError("A real summary_path is required; inline example scores are not accepted.")
    summary = inputs.load(section["summary_path"])
    if section.get("manifest_sha256") and summary.get("manifest_sha256") != section["manifest_sha256"]:
        raise ValueError("Figure summary belongs to a different frozen manifest.")
    return summary, comparisons(summary, section.get("focus", "selected"))


def game_metrics(inputs, section, expected_manifest=None):
    """Count actual engine decisions and measured responses in completed games."""
    if "metrics_path" in section:
        return inputs.load(section["metrics_path"])
    paths = []
    for directory in section.get("game_directories", []):
        paths.extend(sorted(inputs.resolve(directory).glob("games/*.json")))
    focus = section.get("focus", "selected")
    grouped = defaultdict(lambda: {"focus_reasons": Counter(), "opponent_reasons": Counter(),
                                   "focus_response_seconds": [], "opponent_response_seconds": [],
                                   "focus_game_seconds": [], "opponent_game_seconds": [], "completed_games": 0})
    seen = {}
    for path in paths:
        game = inputs.load(path)
        if expected_manifest and game.get("manifest_sha256") != expected_manifest:
            raise ValueError("Raw activation/time record belongs to a different frozen manifest.")
        game_id, fingerprint = game["game_id"], sha(path)
        if game_id in seen:
            if seen[game_id] != fingerprint:
                raise ValueError("Duplicate game IDs have different recorded bytes.")
            continue
        seen[game_id] = fingerprint
        if game["status"] != "completed" or focus not in (game["red"], game["blue"]):
            continue
        opponent = game["blue"] if game["red"] == focus else game["red"]
        row = grouped[opponent]
        row["completed_games"] += 1
        for label, prefix in ((focus, "focus"), (opponent, "opponent")):
            spent = game.get("participant_seconds", {}).get(label)
            if spent is not None:
                row[prefix + "_game_seconds"].append(finite(spent, "participant_seconds"))
            for event in game.get("telemetry", {}).get(label, []):
                if event.get("kind") == "hex_search_move":
                    row[prefix + "_reasons"][event["reason"]] += 1
            for event in game.get("moves", []):
                if event.get("actor") == label and not event.get("forced_opening"):
                    row[prefix + "_response_seconds"].append(finite(event["response_seconds"], "response_seconds"))
    metrics = {}
    for label, row in grouped.items():
        value = {"completed_games": row["completed_games"]}
        for prefix in ("focus", "opponent"):
            value[prefix + "_reasons"] = dict(row[prefix + "_reasons"])
            for key in ("response_seconds", "game_seconds"):
                numbers = row[prefix + "_" + key]
                value[prefix + "_median_" + key] = statistics.median(numbers) if numbers else None
        metrics[label] = value
    return metrics
