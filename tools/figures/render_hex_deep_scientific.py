"""Optional Matplotlib figures from actual frozen Hex reports, in English and Korean.

The application/runtime has no Matplotlib dependency. Only this separate figure
generation command imports plotting libraries. Missing metrics are never invented.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, ticker
from matplotlib.lines import Line2D

from hex_visual_data import Inputs, NAMES, PALETTE, comparisons, finite, game_metrics, integer, name, sha, summary_from, tr


def configure_font(language, korean_font=None):
    if language == "en":
        found = font_manager.findfont("DejaVu Sans")
    else:
        candidates = [Path(korean_font)] if korean_font else [Path("C:/Windows/Fonts/malgun.ttf")]
        found = next((str(path.resolve()) for path in candidates if path.is_file()), None)
        if not found:
            for family in ("Noto Sans CJK KR", "Noto Sans KR", "Malgun Gothic", "NanumGothic"):
                try:
                    found = font_manager.findfont(family, fallback_to_default=False)
                    break
                except ValueError:
                    pass
        if not found:
            raise ValueError("A Korean font is required. Install Noto Sans CJK or pass --korean-font FONT_FILE.")
    font_manager.fontManager.addfont(found)
    family = font_manager.FontProperties(fname=found).get_name()
    return {"family": family, "font_filename": Path(found).name, "font_sha256": sha(found)}


def header(fig, title, subtitle, language):
    fig.text(.055, .962, title, fontsize=24, weight="bold", color=PALETTE["navy"], va="top")
    fig.text(.055, .926, subtitle, fontsize=14, color=PALETTE["muted"], va="top")


def clean_axis(ax):
    ax.set_facecolor(PALETTE["paper"])
    ax.tick_params(labelsize=13, colors=PALETTE["navy"], length=0, pad=10)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(PALETTE["line"])


def pair_plot(ax, rows, language):
    for index, row in enumerate(rows):
        mean, ci = row["mean"], row["ci95"]
        if mean is not None:
            # The numerical plot is Matplotlib's errorbar primitive. A missing
            # paired interval is a point only, never a substituted Wilson CI.
            if ci and not ci[0] <= mean <= ci[1]:
                raise ValueError("The reported pair interval does not enclose its plotted mean.")
            errors = [[mean - ci[0]], [ci[1] - mean]] if ci else None
            ax.errorbar(mean, index, xerr=errors, fmt="o", color=PALETTE["red"],
                        ecolor=PALETTE["navy"], markersize=9, capsize=7, elinewidth=2.7, capthick=2,
                        clip_on=False, zorder=3)
            ax.annotate(f"{mean * 100:.1f}%", (mean, index), xytext=(0, 17), textcoords="offset points",
                        ha="center", fontsize=15, weight="bold", color=PALETTE["red"])
        ax.text(1.08, index - .16, tr(language, f"Wins {row['wins']} / complete {row['completed']}", f"승리 {row['wins']} / 완료 {row['completed']}"),
                transform=ax.get_yaxis_transform(), fontsize=12, color=PALETTE["navy"], va="center", clip_on=False)
        ax.text(1.08, index + .08, tr(language, f"Failed {row['failed']} / recorded {row['recorded']}",
                                     f"실패 {row['failed']} / 기록 {row['recorded']}"),
                transform=ax.get_yaxis_transform(), fontsize=11, color=PALETTE["muted"], va="center", clip_on=False)
        ax.text(1.08, index + .31, tr(language, f"Missing {row['missing']} / plan {row['scheduled']}",
                                     f"미기록 {row['missing']} / 계획 {row['scheduled']}"),
                transform=ax.get_yaxis_transform(), fontsize=11, color=PALETTE["muted"], va="center", clip_on=False)
    ax.set_yticks(list(range(len(rows))), [name(row["opponent"], language) + "\n" +
                  tr(language, f"{row['pairs']} complete pairs", f"완결 {row['pairs']}쌍") for row in rows])
    ax.set_xticks([0, .25, .5, .75, 1], ["0", "25", "50", "75", "100"])
    ax.set_xlim(-.045, 1.045)
    ax.set_ylim(len(rows) - .45, -.68)
    ax.set_xlabel(tr(language, "Mean score of complete side-reversal pairs (%)", "완결된 선후공 교대 쌍의 평균 승률 (%)"), fontsize=13, labelpad=13)
    ax.axvline(.5, color=PALETTE["sand"], linewidth=1.8, linestyle="--", zorder=0)
    ax.grid(axis="x", color=PALETTE["line"], linewidth=1)
    clean_axis(ax)


def table(ax, rows, columns, widths=None, font_size=12):
    ax.axis("off")
    result = ax.table(cellText=rows, colLabels=columns, colWidths=widths,
                      cellLoc="left", colLoc="left", loc="center", bbox=[0, 0, 1, 1])
    result.auto_set_font_size(False)
    result.set_fontsize(font_size)
    for (row, column), cell in result.get_celld().items():
        cell.set_edgecolor(PALETTE["line"])
        cell.set_linewidth(.7)
        cell.PAD = .05
        cell.set_facecolor(PALETTE["paper"] if row % 2 else PALETTE["ivory"])
        cell.get_text().set_color(PALETTE["navy"])
        if row == 0:
            cell.set_facecolor(PALETTE["navy"])
            cell.get_text().set_color(PALETTE["paper"])
            cell.get_text().set_weight("bold")
    return result


def environment_rows(summary, section, focus, inputs):
    summaries = []
    for item in section.get("environment_summaries", []):
        summaries.append((item["id"], inputs.load(item["summary_path"])))
    if not summaries:
        mapping = section.get("environment_id_map", {"Windows": "windows", "Linux": "linux"})
        summaries = [(mapping.get(item.get("environment", {}).get("system"), item.get("environment", {}).get("system", "unknown")), item["summary"])
                     for item in summary.get("environment_summaries", [])]
    # Embedded environment summaries repeat the complete scheduled plan. Group
    # only actual outcomes, never add those plan denominators across shards.
    grouped = defaultdict(lambda: {"wins": 0, "completed": 0, "failed": 0})
    for environment, report in summaries:
        for row in comparisons(report, focus):
            if row["recorded"]:
                target = grouped[(environment, row["opponent"])]
                for key in target:
                    target[key] += row[key]
    return grouped


def shared_figure(inputs, section, language):
    summary, rows = summary_from(inputs, section)
    budget = summary["budget"]
    if budget.get("mode") != "game_time":
        raise ValueError("Shared-time figure requires actual game_time results.")
    order = {label: index for index, label in enumerate(("ucb", "ts", "rave_ucb", "historical_algorithm"))}
    rows.sort(key=lambda row: order.get(row["opponent"], 99))
    for comparison in summary["comparisons"]:
        if comparison.get("paired_cluster_bootstrap_95") and "pair_strata" not in comparison:
            raise ValueError("Shared paired intervals must retain their hardware-stratum evidence.")
    metrics = game_metrics(inputs, section, summary.get("manifest_sha256"))
    env_rows = environment_rows(summary, section, section.get("focus", "selected"), inputs)
    detail = []
    for row in rows:
        metric = metrics.get(row["opponent"])
        if metric:
            if metric.get("completed_games") != row["completed"]:
                raise ValueError("Time metrics must cover the same completed games.")
            game = metric.get("focus_median_game_seconds")
            response = metric.get("focus_median_response_seconds")
            detail.append([name(row["opponent"], language),
                           f"{finite(game, 'game median'):.2f}" if game is not None else tr(language, "unavailable", "미측정"),
                           f"{finite(response, 'response median'):.4f}" if response is not None else tr(language, "unavailable", "미측정")])
    height = 9.2 + .35 * len(env_rows) + (.25 * len(detail) if detail else 0)
    fig = plt.figure(figsize=(16.67, height), facecolor=PALETTE["ivory"])
    header(fig, tr(language, "Hex with a shared game-time budget", "같은 경기 시간 예산에서의 Hex 성능"),
           tr(language, f"{budget['game_seconds']:g}s per participant, {budget['workers']} workers, 11×11 board",
              f"참가자별 {budget['game_seconds']:g}초, 워커 {budget['workers']}개, 11×11 보드"), language)
    fig.text(.055, .89, tr(language, "Points: complete-pair mean. Error bars: hardware-stratified pair bootstrap 95% interval.",
                           "점은 교대 쌍의 평균 승률이며, 선은 실행 조건별로 재표집한 쌍의 부트스트랩 95% 구간입니다."), fontsize=12, color=PALETTE["muted"])
    ax = fig.add_axes([.25, .49, .46, .34])
    pair_plot(ax, rows, language)
    bottom_top = .36
    if detail:
        fig.text(.055, bottom_top + .018, tr(language, "Actual time consumed by the selected agent", "선정 정책이 실제로 사용한 시간"), fontsize=14, weight="bold", color=PALETTE["navy"])
        table(fig.add_axes([.055, .24, .89, .115]), detail,
              [tr(language, "Opponent", "상대"), tr(language, "Median game time (s)", "경기 소비 시간 중앙값 (초)"), tr(language, "Median response (s)", "응답 중앙값 (초)")], [.36, .34, .30], 12)
        bottom_top = .19
    if env_rows:
        environment_values = [[name(environment, language), name(opponent, language), value["wins"], value["completed"], value["failed"]]
                              for (environment, opponent), value in sorted(env_rows.items())]
        fig.text(.055, bottom_top + .02, tr(language, "Outcomes retained separately by environment", "장비별 결과를 각각 보존"), fontsize=14, weight="bold", color=PALETTE["navy"])
        table_height = bottom_top - .07
        table(fig.add_axes([.055, .07, .89, table_height]), environment_values,
              [tr(language, "Environment", "환경"), tr(language, "Opponent", "상대"), tr(language, "Wins", "승리"), tr(language, "Completed", "완료"), tr(language, "Failed", "실패")],
              [.26, .35, .13, .13, .13], 11)
    fig.text(.055, .038, tr(language, f"The {budget['game_seconds']:g}-second setting is an allowance, not full consumption. Failed games are never counted as wins.",
                           f"{budget['game_seconds']:g}초는 경기 시간 상한이며 실제 소비 시간이 아닙니다. 실행 실패는 승리로 계산하지 않습니다."), fontsize=11, color=PALETTE["muted"])
    return fig


def tactical_figure(inputs, section, language):
    summary, rows = summary_from(inputs, section)
    budget = summary["budget"]
    if budget.get("mode") != "iterations":
        raise ValueError("Tactical figure requires the frozen equal-iteration results.")
    order = {label: index for index, label in enumerate(("no_swap", "no_win_check", "no_block_check", "no_tactics"))}
    rows.sort(key=lambda row: order.get(row["opponent"], 99))
    metrics = game_metrics(inputs, section, summary.get("manifest_sha256"))
    values = []
    for row in rows:
        metric = metrics.get(row["opponent"])
        if not metric:
            continue
        if metric.get("completed_games") != row["completed"]:
            raise ValueError("Activation metrics must cover the same completed games.")
        for prefix, label in (("focus", tr(language, "Selected", "선정 정책")), ("opponent", tr(language, "Ablated", "제외 정책"))):
            counts = metric.get(prefix + "_reasons")
            if not isinstance(counts, dict):
                raise ValueError("Missing reason counts must not be replaced by zero.")
            med = metric.get(prefix + "_median_response_seconds")
            values.append([name(row["opponent"], language), label,
                           *[integer(counts.get(reason, 0), reason) for reason in ("pie_rule_swap", "tactical_win", "tactical_block")],
                           f"{finite(med, 'response median'):.4f}" if med is not None else tr(language, "unavailable", "미측정")])
    fig = plt.figure(figsize=(16.67, 12.4), facecolor=PALETTE["ivory"])
    header(fig, tr(language, "Hex tactical-feature ablations", "Hex 전술 기능의 개별 제외 실험"),
           tr(language, f"Equal {budget['iterations']:,} total iterations per move, {budget['workers']} workers, separate final seeds",
              f"한 수마다 전체 {budget['iterations']:,}회 탐색, 워커 {budget['workers']}개, 별도의 최종 평가 시드"), language)
    fig.text(.055, .89, tr(language, "The plotted score belongs to the unchanged selected agent, facing each ablation.",
                           "기능을 제외한 정책을 상대로 앞서 선정한 정책이 기록한 승률입니다."), fontsize=13, color=PALETTE["muted"])
    pair_plot(fig.add_axes([.30, .51, .40, .32]), rows, language)
    fig.text(.055, .413, tr(language, "Actual completed-game activations and measured response medians", "완료 경기에서 확인한 작동 횟수와 응답 중앙값"), fontsize=14, weight="bold", color=PALETTE["navy"])
    if values:
        table(fig.add_axes([.055, .12, .89, .27]), values,
              [tr(language, "Removed feature", "제외한 기능"), tr(language, "Policy", "정책"), tr(language, "Swap", "스왑"),
               tr(language, "Immediate win", "즉시 승리"), tr(language, "Block", "방어"), tr(language, "p50 response (s)", "응답 p50 (초)")],
              [.32, .15, .09, .14, .09, .21], 11)
    else:
        fig.text(.055, .30, tr(language, "Activation data unavailable; no counts have been inferred.", "작동 기록이 아직 집계되지 않아 횟수를 추정하지 않았습니다."), fontsize=13, color=PALETTE["muted"])
    fig.text(.055, .078, tr(language, "Error bars: hardware-stratified pair bootstrap 95% intervals. Failure denominators remain separate.",
                           "선은 실행 조건별로 재표집한 교대 쌍의 부트스트랩 95% 구간입니다. 실패의 분모는 별도로 표시합니다."), fontsize=11, color=PALETTE["muted"])
    if any(row["ci95"] == [0.5, 0.5] or row["ci95"] == (0.5, 0.5) for row in rows):
        fig.text(.055, .057, tr(language, "The 50–50% intervals reflect zero variation in observed pair scores, not proven equivalence.",
                               "50–50% 구간은 관측한 모든 쌍의 점수가 같아 생긴 결과이며, 두 정책의 동등함을 입증하지 않습니다."), fontsize=11, color=PALETTE["muted"])
    fig.text(.055, .035, tr(language, "Fixed budget and base policy. An observed effect is not a guarantee for every position.",
                           "예산과 기본 정책을 고정했습니다. 관측한 효과가 모든 보드 상태에서 유지된다는 의미는 아닙니다."), fontsize=11, color=PALETTE["muted"])
    return fig


def worker_figure(inputs, entries, language):
    reports = {entry["id"]: inputs.load(entry["path"]) for entry in entries}
    if set(reports) != {"windows", "kaggle"} or len(entries) != 2:
        raise ValueError("Provide actual Windows and Kaggle reports separately.")
    first, second = reports["windows"], reports["kaggle"]
    if first["fixtures_sha256"] != second["fixtures_sha256"] or first["iterations_per_move"] != second["iterations_per_move"]:
        raise ValueError("Worker fixtures and iteration budgets must match exactly.")
    fixtures = [fixture["id"] for fixture in first["fixtures"]]
    if len(fixtures) != 6 or len(set(fixtures)) != 6:
        raise ValueError("Six distinct actual fixtures are required.")
    fig, axes = plt.subplots(6, 2, figsize=(16.67, 22.5), facecolor=PALETTE["ivory"])
    fig.subplots_adjust(left=.085, right=.955, top=.865, bottom=.075, hspace=.85, wspace=.21)
    header(fig, tr(language, "Hex worker scaling across six positions", "여섯 보드 상태에서 측정한 Hex 워커 성능"),
           tr(language, f"Equal {first['iterations_per_move']:,} total iterations. Measured response p50 / p95 and maximum process RSS.",
              f"전체 탐색 {first['iterations_per_move']:,}회로 동일. 실제 응답 p50 / p95와 최대 프로세스 RSS."), language)
    fig.text(.085, .887, name("windows", language), fontsize=18, weight="bold", color=PALETTE["red"])
    fig.text(.57, .887, name("kaggle", language), fontsize=18, weight="bold", color=PALETTE["navy"])
    fig.legend(handles=[Line2D([0], [0], color=PALETTE["steel"], linewidth=9, label=tr(language, "Bar: median response", "막대: 응답 중앙값")),
                        Line2D([0], [0], color=PALETTE["navy"], marker="_", linewidth=1.5, label=tr(language, "Cap: response p95", "윗선: 응답 95백분위"))],
               loc="upper right", bbox_to_anchor=(.955, .913), ncol=2, frameon=False, fontsize=11)
    for column, identifier in enumerate(("windows", "kaggle")):
        report = reports[identifier]
        for row_index, fixture in enumerate(fixtures):
            ax = axes[row_index, column]
            rows = sorted([value for value in report["summaries"] if value["fixture_id"] == fixture], key=lambda value: value["workers"])
            if [row["workers"] for row in rows] != [1, 2, 4, 8] or not all(row["all_exact_iteration_budget"] for row in rows):
                raise ValueError("Each actual fixture must complete its total budget with workers 1/2/4/8.")
            medians = [finite(row["median_response_seconds"], "response median") for row in rows]
            p95 = [finite(row["p95_response_seconds"], "response p95") for row in rows]
            if any(high < low for low, high in zip(medians, p95)):
                raise ValueError("Response p95 is below its median.")
            x = list(range(4))
            ax.bar(x, medians, width=.48, color=PALETTE["red"] if identifier == "windows" else PALETTE["navy"], alpha=.9, zorder=2)
            ax.errorbar(x, medians, yerr=[[0] * 4, [high - low for low, high in zip(medians, p95)]], fmt="none",
                        color=PALETTE["navy"], capsize=6, elinewidth=1.6, zorder=3)
            ymax = max(p95) * 1.35 if max(p95) else 1
            ax.set_ylim(0, ymax)
            ax.set_xlim(-.5, 3.5)
            ax.set_xticks(x, ["1", "2", "4", "8"])
            ax.set_xlabel(tr(language, "Workers", "워커 수"), fontsize=11, labelpad=4)
            ax.set_ylabel(tr(language, "Seconds", "초"), fontsize=11)
            ax.set_title(name(fixture, language) + tr(language, f" / {report['repeats']} repeats", f" / {report['repeats']}회 반복"),
                         fontsize=13, weight="bold", loc="left", pad=13)
            ax.grid(axis="y", color=PALETTE["line"], linewidth=.8, zorder=0)
            ax.yaxis.set_major_locator(ticker.MaxNLocator(3))
            for index, (median, high, row) in enumerate(zip(medians, p95, rows)):
                ax.text(index, high + ymax * .045, f"{median:.3f} / {high:.3f}", ha="center", fontsize=10, color=PALETTE["navy"])
                rss = row.get("max_process_peak_rss_bytes")
                label = f"{finite(rss, 'process RSS') / 1048576:.1f} MiB" if rss is not None else tr(language, "unavailable", "미측정")
                ax.text(index, -.35, label, transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=10, color=PALETTE["muted"], clip_on=False)
            clean_axis(ax)
    fig.text(.055, .032, tr(language, "Three legal Red-first histories and three transposed, colour-exchanged static states; transformed-state reachability is not asserted.",
                           "합법적인 적색 선공 수순 3개와 전치 및 색 교환 정적 상태 3개입니다. 교환 상태의 경기 도달 가능성은 주장하지 않습니다."), fontsize=10, color=PALETTE["muted"])
    fig.text(.055, .017, tr(language, "Each panel has its own latency scale. RSS includes native workers, not Python. p95 is descriptive, not a win rate or confidence interval.",
                           "패널마다 시간 축을 표시합니다. RSS는 네이티브 워커를 포함하며 Python은 제외합니다. p95는 승률이나 신뢰구간이 아닙니다."), fontsize=10, color=PALETTE["muted"])
    return fig


def text_layout(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    width, height = fig.canvas.get_width_height()
    clipped = []
    for artist in fig.findobj(match=lambda value: isinstance(value, matplotlib.text.Text)):
        if not artist.get_visible() or not artist.get_text():
            continue
        if any(character in artist.get_text() for character in "·ㆍ•"):
            raise ValueError("Middle-dot characters are prohibited in chart prose.")
        box = artist.get_window_extent(renderer)
        if box.x0 < -1 or box.y0 < -1 or box.x1 > width + 1 or box.y1 > height + 1:
            clipped.append({"text": artist.get_text(), "bounds": [box.x0, box.y0, box.x1, box.y1]})
    return {"canvas_pixels": [width, height], "text_outside_figure": clipped}


def render(data_path, output, language="both", figures=None, korean_font=None):
    inputs = Inputs(data_path)
    output = Path(output).resolve()
    languages = ("en", "ko") if language == "both" else (language,)
    supplied = set(figures or ("shared_time", "tactical", "workers"))
    requested = [key for key in ("shared_time", "tactical", "workers") if key in supplied]
    creators = {"shared_time": ("hex-shared-time.svg", shared_figure),
                "tactical": ("hex-tactical-ablation.svg", tactical_figure),
                "workers": ("hex-worker-positions.svg", worker_figure)}
    rendered, fonts, layout = {}, {}, {}
    try:
        for locale in languages:
            font = configure_font(locale, korean_font)
            fonts[locale] = font
            with matplotlib.rc_context({"font.family": font["family"], "svg.fonttype": "path", "svg.hashsalt": "hex-deep-scientific-v1",
                                        "axes.unicode_minus": False, "figure.dpi": 100, "savefig.dpi": 150,
                                        "text.color": PALETTE["navy"], "axes.labelcolor": PALETTE["navy"], "font.size": 12}):
                for key in requested:
                    filename, creator = creators[key]
                    section = inputs.data["worker_reports"] if key == "workers" else inputs.data[key]
                    fig = creator(inputs, section, locale)
                    check = text_layout(fig)
                    if check["text_outside_figure"]:
                        raise ValueError("Chart text falls outside the figure: " + repr(check["text_outside_figure"]))
                    rendered[(locale, filename)] = fig
                    layout[locale + "/" + filename] = check
        files = []
        # Data and layout are checked for every requested locale before publishing
        # an artifact to the private output directory.
        for (locale, filename), fig in rendered.items():
            path = output / locale / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(path, format="svg", facecolor=PALETTE["ivory"], metadata={"Date": None, "Creator": "Matplotlib frozen Hex report renderer"})
            # Preserve the receipt hash when Git exports text assets on Windows.
            payload = path.read_bytes()
            normalized = payload.replace(b"\r\n", b"\n")
            if payload != normalized:
                path.write_bytes(normalized)
            ET.fromstring(path.read_text(encoding="utf-8"))
            files.append({"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
        receipts = {(item["filename"], item["sha256"]): item for item in inputs.receipts}
        report = {"schema_version": 1, "status": "rendered_from_actual_reports", "plotting_library": "Matplotlib",
                  "matplotlib_version": matplotlib.__version__, "svg_fonttype": "path", "fonts": fonts, "palette": PALETTE,
                  "files": files, "inputs": list(receipts.values()), "input_data_sha256": sha(data_path),
                  "generator_sha256": sha(__file__), "data_parser_sha256": sha(Path(__file__).with_name("hex_visual_data.py")),
                  "layout": layout, "scope": "Numerical graphs use Matplotlib errorbar/bar, explicit ticks and measured data. Actual denominator and source validation passed. SVG glyph paths preserve Korean text without depending on the viewer's fonts. Browser visual inspection remains required."}
        output.mkdir(parents=True, exist_ok=True)
        (output / "scientific-visual-receipt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        return report
    finally:
        for fig in rendered.values():
            plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=("en", "ko", "both"), default="both")
    parser.add_argument("--figures", nargs="+", choices=("shared_time", "tactical", "workers"))
    parser.add_argument("--korean-font", type=Path)
    args = parser.parse_args()
    print(json.dumps(render(args.data, args.output, args.language, args.figures, args.korean_font), indent=2))
