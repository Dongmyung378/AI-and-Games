"""Render a portfolio thumbnail from one actual Hex finish and identifier-bound paired results."""
from __future__ import annotations

import argparse
from collections import deque
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import RegularPolygon

from hex_visual_data import Inputs, PALETTE, sha, summary_from, tr
from render_hex_deep_scientific import configure_font, text_layout


def winning_path(board, colour):
    size = len(board)
    starts = [(0, column) for column in range(size)] if colour == "R" else [(row, 0) for row in range(size)]
    queue = deque(point for point in starts if board[point[0]][point[1]] == colour)
    previous = {point: None for point in queue}
    while queue:
        point = queue.popleft()
        row, column = point
        if (colour == "R" and row == size - 1) or (colour == "B" and column == size - 1):
            path = []
            while point is not None:
                path.append(point)
                point = previous[point]
            return list(reversed(path))
        for dr, dc in [(-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0)]:
            next_point = (row + dr, column + dc)
            if (0 <= next_point[0] < size and 0 <= next_point[1] < size
                    and next_point not in previous and board[next_point[0]][next_point[1]] == colour):
                previous[next_point] = point
                queue.append(next_point)
    raise ValueError("The actual thumbnail finish has no connecting path for its recorded winning colour.")


def draw(inputs, language):
    section = inputs.data["thumbnail"]
    summary, rows = summary_from(inputs, section)
    by_opponent = {row["opponent"]: row for row in rows}
    order = ["ucb", "ts", "rave_ucb", "historical_algorithm"]
    if set(by_opponent) != set(order) or summary["completed_games"] != 400:
        raise ValueError("The thumbnail requires the actual complete four-opponent suite.")
    game = inputs.load(section["game_path"])
    if game["status"] != "completed" or game["winner"] != section.get("focus", "selected") or game["manifest_sha256"] != summary["manifest_sha256"]:
        raise ValueError("Thumbnail board and aggregate must belong to the same completed selected-agent evaluation.")
    board = game["final_board"].split(",")
    if len(board) != 11 or any(len(row) != 11 or set(row) - set("0RB") for row in board):
        raise ValueError("Actual final board must be valid 11×11 Hex cells.")
    path = winning_path(board, game["winning_colour"])
    fig = plt.figure(figsize=(12.8, 7.2), facecolor=PALETTE["ivory"])
    fig.text(.045, .94, tr(language, "Hex Search Agent", "Hex 탐색 에이전트"),
             va="top", fontsize=36, weight="bold", color=PALETTE["navy"])
    fig.text(.047, .835, tr(language, "RAVE-TS with the same game-time allowance", "같은 경기 시간 예산으로 평가한 RAVE-TS"),
             va="top", fontsize=16, color=PALETTE["muted"])
    board_ax = fig.add_axes([.025, .13, .43, .60])
    board_ax.set_aspect("equal")
    board_ax.set_xticks([])
    board_ax.set_yticks([])
    board_ax.set_axis_off()
    xy = lambda row, column: (column + row / 2, (10 - row) * math.sqrt(3) / 2)
    for row in range(11):
        for column in range(11):
            cell = board[row][column]
            fill = PALETTE["red"] if cell == "R" else PALETTE["navy"] if cell == "B" else PALETTE["paper"]
            board_ax.add_patch(RegularPolygon(xy(row, column), 6, radius=.535, orientation=math.pi / 6,
                                              facecolor=fill, edgecolor=PALETTE["line"], linewidth=.7))
    points = [xy(*point) for point in path]
    board_ax.plot([point[0] for point in points], [point[1] for point in points],
                  color=PALETTE["paper"], linewidth=2.0, alpha=.85, zorder=3)
    board_ax.set_xlim(-.85, 15.85)
    board_ax.set_ylim(-.8, 9.48)
    fig.text(.05, .12, tr(language, "One recorded final board", "실제 평가 경기의 종료 보드"),
             fontsize=13, color=PALETTE["muted"])
    plot = fig.add_axes([.51, .275, .45, .425], facecolor=PALETTE["ivory"])
    values = [by_opponent[identifier]["mean"] * 100 for identifier in order]
    intervals = [by_opponent[identifier]["ci95"] for identifier in order]
    if any(interval is None for interval in intervals):
        raise ValueError("A published paired interval is required for every thumbnail bar.")
    lows = [value - interval[0] * 100 for value, interval in zip(values, intervals)]
    highs = [interval[1] * 100 - value for value, interval in zip(values, intervals)]
    plot.bar(range(4), values, width=.66,
             color=[PALETTE["navy"], PALETTE["steel"], PALETTE["red"], PALETTE["sand"]], zorder=2)
    plot.errorbar(range(4), values, yerr=[lows, highs], fmt="none", color=PALETTE["navy"],
                   elinewidth=1.6, capsize=5, zorder=3)
    for index, value in enumerate(values):
        plot.text(index, value - 12, f"{value:.0f}%", fontsize=25, weight="bold",
                  color=PALETTE["paper"], ha="center", va="center")
    plot.set_ylim(0, 100)
    plot.set_xlim(-.6, 3.6)
    plot.set_xticks(range(4), ["UCB", "TS", "RAVE-UCB", tr(language, "Initial C++", "초기 C++")], fontsize=18)
    plot.set_yticks([0, 50, 100], ["0", "50", "100"], fontsize=11)
    plot.tick_params(length=0, labelcolor=PALETTE["navy"], pad=7)
    plot.grid(axis="y", color=PALETTE["line"], linewidth=.8, zorder=0)
    for side in ["top", "right", "left", "bottom"]:
        plot.spines[side].set_visible(False)
    fig.text(.51, .725, tr(language, "Win rate against each opponent", "상대별 승률"),
             fontsize=18, color=PALETTE["navy"], weight="bold")
    failed = summary["recorded_games"] - summary["completed_games"]
    fig.text(.51, .145, tr(language, f"{summary['completed_games']} games, {failed} failures", f"{summary['completed_games']}경기, 실행 실패 {failed}건"),
             fontsize=23, color=PALETTE["navy"], weight="bold")
    fig.text(.51, .095, tr(language, f"{summary['budget']['game_seconds']:g}s / participant, 100 games / opponent",
                         f"참가자별 {summary['budget']['game_seconds']:g}초, 상대별 100경기"),
             fontsize=13, color=PALETTE["muted"])
    fig.text(.045, .035, tr(language, "Caps: hardware-stratified side-pair bootstrap 95% interval", "윗선: 실행 조건별 교대 쌍의 부트스트랩 95% 구간"),
             fontsize=11, color=PALETTE["muted"])
    return fig, {"actual_game_id": game["game_id"], "actual_winning_colour": game["winning_colour"],
                 "actual_final_board": game["final_board"], "connecting_path": [list(point) for point in path],
                 "results_by_opponent": {identifier: by_opponent[identifier] for identifier in order}}


def render(data_path, output, language="both", korean_font=None):
    inputs, output = Inputs(data_path), Path(output).resolve()
    languages = ["en", "ko"] if language == "both" else [language]
    fonts, files, checks, actual = {}, [], {}, None
    for locale in languages:
        font = configure_font(locale, korean_font)
        fonts[locale] = font
        with matplotlib.rc_context({"font.family": font["family"], "svg.fonttype": "path",
                                    "svg.hashsalt": "hex-actual-thumbnail-v1", "figure.dpi": 100,
                                    "axes.unicode_minus": False}):
            fig, actual = draw(inputs, locale)
            try:
                checks[locale] = text_layout(fig)
                if checks[locale]["text_outside_figure"]:
                    raise ValueError("Thumbnail text falls outside its canvas.")
                path = output / locale / "hex-deep-thumbnail.svg"
                path.parent.mkdir(parents=True, exist_ok=True)
                fig.savefig(path, format="svg", metadata={"Date": None, "Creator": "Matplotlib actual Hex thumbnail renderer"})
                payload = path.read_bytes().replace(b"\r\n", b"\n")
                path.write_bytes(payload)
                ET.fromstring(payload)
                files.append({"path": path.relative_to(output).as_posix(), "sha256": sha(path), "bytes": len(payload)})
            finally:
                plt.close(fig)
    receipt = {"schema_version": 1, "status": "rendered_from_actual_game_and_identifier_bound_results",
               "matplotlib_version": matplotlib.__version__, "fonts": fonts, "palette": PALETTE,
               "input_data_sha256": sha(data_path), "inputs": inputs.receipts, "files": files,
               "generator_sha256": sha(__file__), "data_parser_sha256": sha(Path(__file__).with_name("hex_visual_data.py")),
               "actual_data": actual, "layout": checks, "illustrative_board_or_scores": False}
    (output / "thumbnail-visual-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=["en", "ko", "both"], default="both")
    parser.add_argument("--korean-font", type=Path)
    args = parser.parse_args()
    print(json.dumps(render(args.data, args.output, args.language, args.korean_font), indent=2))
