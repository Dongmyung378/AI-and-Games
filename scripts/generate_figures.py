"""Deterministic zero-dependency SVG figure generator from verified JSON/SGF engine records.

Visual language: University of Manchester editorial publication palette (Manchester Purple #660099,
heritage brass gold #C69214/#E8B931, warm archival paper #F6F3F9, print crimson & slate blue boards).
Generates both English (`assets/`) and Korean (`assets/ko/` + optional portfolio dir) figure sets.
"""
from __future__ import annotations

import argparse
from html import escape
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hexai.battle import BattleReferee
from hexai.referee import Colour

# University of Manchester Editorial Palette (print / academic monograph grade)
PAPER = "#F6F3F9"         # Warm Manchester lilac ivory paper canvas
SURFACE = "#FFFFFF"       # Crisp card surface
SURFACE_TINT = "#FAF8FC"  # Subtle inner well
SURFACE_GOLD = "#FCF9F0"  # Subtle warm highlight for flagship win card
RULE = "#DDD4E6"          # Hairline structural divider & card border
GRID = "#E9E3F0"          # Subtle chart gridline
INK = "#23192D"           # Deep plum charcoal primary text
MUTED = "#5E566A"         # Secondary editorial label text
FAINT = "#8A8196"         # Footnote / citation text

# Signature University of Manchester Purple + Heritage Gold
UOM_PURPLE = "#660099"       # Official University of Manchester Purple
UOM_PURPLE_DARK = "#4A0070"  # Deep purple emphasis
UOM_PURPLE_SOFT = "#EFE6F7"  # Soft lavender tint wash
UOM_PURPLE_MID = "#8A4FB0"   # Secondary purple connector
UOM_GOLD_TEXT = "#A87908"    # High contrast brass gold for text on light paper
UOM_GOLD_BAR = "#C69214"     # Editorial brass gold for data markers/accents
UOM_GOLD_CHAIN = "#E8B931"   # Crisp gold winning chain thread on stones
UOM_GOLD_ON_DARK = "#F5CC4D" # Luminous Manchester gold on #660099 banner

# Print grade Hex board & supporting analytical colors
HEX_RED = "#B5353E"          # Dignified print crimson (Top <-> Bottom)
HEX_RED_EDGE = "#96242C"     # Slightly deeper red border/label
HEX_BLUE = "#2B5B84"         # Scholarly Oxford slate blue (Left <-> Right)
HEX_BLUE_EDGE = "#1F4464"    # Slightly deeper blue border/label
HEX_EMPTY = "#EAE4F0"        # Tactile light parchment stone empty cell
HEX_EMPTY_STROKE = "#CFC4DA" # Crisp empty cell hairline
ROSE_MUTED = "#B04A56"       # Calm terracotta rose for rejected/diagnostic items
ROSE_BG = "#F9EFF0"          # Subtle blush tag background
TRACK_BG = "#F0EBF5"         # Bar chart empty track

FONT_EN = "Inter, 'Segoe UI', -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif"
FONT_KO = "'Noto Sans KR', 'Malgun Gothic', 'Apple SD Gothic Neo', 'Segoe UI', sans-serif"
MONO = "'JetBrains Mono', Consolas, 'Courier New', monospace"


def hex_pts(cx: float, cy: float, r: float) -> str:
    coords = []
    for i in range(6):
        ang = math.radians(60 * i - 30)
        coords.append(f"{cx + r * math.cos(ang):.2f},{cy + r * math.sin(ang):.2f}")
    return " ".join(coords)


def hex_pos(row: int, col: int, r: float, ox: float, oy: float) -> tuple[float, float]:
    dx = math.sqrt(3.0) * r
    dy = 1.5 * r
    return (ox + col * dx + row * dx * 0.5, oy + row * dy)


def svg_header(w: int, h: int, title: str, desc: str, lang: str) -> list[str]:
    font = FONT_KO if lang == "ko" else FONT_EN
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="desc">{escape(desc)}</desc>',
        f'<style>text{{font-family:{font};font-variant-numeric:tabular-nums}}.mono{{font-family:{MONO}}}</style>',
        f'<rect width="{w}" height="{h}" fill="{PAPER}"/>',
    ]


def render_hex_board_svg(
    st: BattleReferee,
    ox: float,
    oy: float,
    r: float,
    win_path: list[tuple[int, int]],
    last_mv: tuple[int, int] | None = None,
    show_labels: bool = True,
) -> list[str]:
    n = st.board.size
    win_set = set(win_path)
    out: list[str] = []
    tl = hex_pos(0, 0, r, ox, oy)
    tr = hex_pos(0, n - 1, r, ox, oy)
    bl = hex_pos(n - 1, 0, r, ox, oy)
    br = hex_pos(n - 1, n - 1, r, ox, oy)
    off = r * 1.06
    w_edge = max(3.2, r * 0.30)

    # Goal edge rails
    out.append(f'<line x1="{tl[0]-off*0.32:.1f}" y1="{tl[1]-off:.1f}" x2="{tr[0]+off*0.32:.1f}" y2="{tr[1]-off:.1f}" stroke="{HEX_RED}" stroke-width="{w_edge:.1f}" stroke-linecap="round"/>')
    out.append(f'<line x1="{bl[0]-off*0.32:.1f}" y1="{bl[1]+off:.1f}" x2="{br[0]+off*0.32:.1f}" y2="{br[1]+off:.1f}" stroke="{HEX_RED}" stroke-width="{w_edge:.1f}" stroke-linecap="round"/>')
    out.append(f'<line x1="{tl[0]-off:.1f}" y1="{tl[1]-off*0.14:.1f}" x2="{bl[0]-off:.1f}" y2="{bl[1]+off*0.14:.1f}" stroke="{HEX_BLUE}" stroke-width="{w_edge:.1f}" stroke-linecap="round"/>')
    out.append(f'<line x1="{tr[0]+off:.1f}" y1="{tr[1]-off*0.14:.1f}" x2="{br[0]+off:.1f}" y2="{br[1]+off*0.14:.1f}" stroke="{HEX_BLUE}" stroke-width="{w_edge:.1f}" stroke-linecap="round"/>')

    if show_labels:
        fs = max(8.5, r * 0.58)
        for c in range(n):
            lbl = chr(ord("a") + c)
            pt = hex_pos(0, c, r, ox, oy)
            out.append(f'<text class="mono" x="{pt[0]:.1f}" y="{pt[1]-r*1.62:.1f}" text-anchor="middle" fill="{HEX_RED_EDGE}" font-size="{fs:.1f}" font-weight="700">{lbl}</text>')
        for row in range(n):
            pt = hex_pos(row, 0, r, ox, oy)
            out.append(f'<text class="mono" x="{pt[0]-r*1.86:.1f}" y="{pt[1]+fs*0.35:.1f}" text-anchor="middle" fill="{HEX_BLUE_EDGE}" font-size="{fs:.1f}" font-weight="700">{row+1}</text>')

    # Hex cells
    for row in range(n):
        for col in range(n):
            cx, cy = hex_pos(row, col, r, ox, oy)
            tc = st.board.tiles[row][col].colour
            is_wp = (row, col) in win_set
            fill = HEX_RED if tc == Colour.RED else (HEX_BLUE if tc == Colour.BLUE else HEX_EMPTY)
            if is_wp:
                stroke = UOM_GOLD_CHAIN
                sw = max(1.8, r * 0.16)
            elif tc == Colour.RED:
                stroke = HEX_RED_EDGE
                sw = 0.85
            elif tc == Colour.BLUE:
                stroke = HEX_BLUE_EDGE
                sw = 0.85
            else:
                stroke = HEX_EMPTY_STROKE
                sw = 0.85
            out.append(f'<polygon points="{hex_pts(cx, cy, r * 0.93)}" fill="{fill}" stroke="{stroke}" stroke-width="{sw:.2f}"/>')

    # Ordered Manchester Gold winning chain thread + center dots
    if len(win_path) >= 2:
        pts_str = " ".join(f"{hex_pos(rr, cc, r, ox, oy)[0]:.1f},{hex_pos(rr, cc, r, ox, oy)[1]:.1f}" for rr, cc in win_path)
        out.append(f'<polyline points="{pts_str}" fill="none" stroke="{UOM_GOLD_CHAIN}" stroke-width="{max(2.0, r * 0.21):.2f}" stroke-linecap="round" stroke-linejoin="round" opacity="0.95"/>')
    for rr, cc in win_path:
        cx, cy = hex_pos(rr, cc, r, ox, oy)
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{max(2.4, r * 0.26):.2f}" fill="{UOM_GOLD_ON_DARK}" stroke="{INK}" stroke-width="0.7"/>')

    # Last move subtle crisp ring
    if last_mv is not None:
        cx, cy = hex_pos(last_mv[0], last_mv[1], r, ox, oy)
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r * 0.56:.2f}" fill="none" stroke="#FFFFFF" stroke-width="1.8"/>')
    return out


def replay_battle_file(filename: str) -> tuple[dict, BattleReferee, list[tuple[int, int]]]:
    path = ROOT / "reports" / "online_battles" / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    st = BattleReferee(data["board_size"], data["red"], data["blue"], swap_rule="swap_pieces")
    for ev in data["moves"]:
        st.play(tuple(ev["move"]))
    wc = st.board.get_winner()
    wpath = st.board.winning_path(wc) if wc is not None else []
    return data, st, wpath


def build_thumbnail_svg(st: BattleReferee, wpath: list[tuple[int, int]], lang: str) -> str:
    w, h = 1200, 760
    if lang == "ko":
        title = "Hex Search v1.2: 순수 CPU C++17 탐색 엔진"
        desc = "GPU와 신경망 없이 순수 CPU C++17만으로 v0.0 대비 +342 Elo를 달성하고 Davis 7·10 전승 및 MoHex 3 선·후공 승리를 기록한 Hex AI 썸네일입니다."
        heading = "순수 CPU C++17 Hex 탐색 엔진"
        sub = "Lock-Free GRAVE-TS · Exact VC Solver · 실시간 Pondering"
        stats = [
            ("+342 Elo", "v0.0 → v1.2 통제 대국 기력 향상", UOM_PURPLE),
            ("4승 0패", "Davis 7 · Davis 10 선·후공 전승", HEX_BLUE),
            ("1.35억 방문", "Pondering +7,480만 · 형식 검증 오탐 0건", INK),
        ]
        board_hdr = "실전 기보: MoHex 3 선공 77수 완승 (Red 상↔하)"
        board_foot = "황금 실선: 독립 BFS 심판이 검증한 Red 승리 경로 (i1 ↔ f11)"
        banner_l1 = "MoHex 3 선·후공 모두 격파"
        banner_l2 = "GPU · 신경망 · 외부 의존성 0개 · 순수 C++17 단일 엔진"
        banner_r1 = "77수 필승"
        banner_r2 = "71수 Exact VC Solver 조기 증명"
    else:
        title = "Hex Search v1.2: Pure CPU C++17 Hex AI Engine"
        desc = "Zero-dependency pure CPU C++17 Hex search engine gaining +342 Elo over v0.0, sweeping Davis 7 and 10, and defeating MoHex 3 as both 1st and 2nd player."
        heading = "Pure CPU C++17 Hex Search Engine"
        sub = "Lock-Free GRAVE-TS · Exact VC Solver · Real-Time Pondering"
        stats = [
            ("+342 Elo", "Controlled v0.0 → v1.2 Self-Play Gain", UOM_PURPLE),
            ("4 / 4 Sweep", "Davis 7 &amp; Davis 10 (1st &amp; 2nd Player)", HEX_BLUE),
            ("135.7M Visits", "+74.8M Ponder Reuse · 0 Formal FP", INK),
        ]
        board_hdr = "Verified Game: 77 Move 1st Player Win vs MoHex 3 (Red)"
        board_foot = "Gold chain: Independently verified Red winning path (i1 ↔ f11)"
        banner_l1 = "Defeated MoHex 3 (1st &amp; 2nd)"
        banner_l2 = "Zero GPU · Zero Neural Nets · Zero External Dependencies"
        banner_r1 = "77 Moves"
        banner_r2 = "Turn 71 Exact VC Solver Mate"

    parts = svg_header(w, h, title, desc, lang)
    parts.extend([
        f'<text x="48" y="78" fill="{INK}" font-size="46" font-weight="750">{heading}</text>',
        f'<text x="48" y="124" fill="{MUTED}" font-size="25" font-weight="400">{sub}</text>',
        f'<path d="M48 148H1152" stroke="{RULE}" stroke-width="1.2"/>',
        # Left editorial metrics column
        f'<rect x="48" y="176" width="464" height="408" rx="16" fill="{SURFACE}" stroke="{RULE}" stroke-width="1.2"/>',
    ])
    for idx, (val, label, col) in enumerate(stats):
        sy = 210 + idx * 126
        if idx > 0:
            parts.append(f'<line x1="78" y1="{sy-24}" x2="482" y2="{sy-24}" stroke="{GRID}" stroke-width="1.2"/>')
        parts.append(f'<text x="78" y="{sy+34}" fill="{col}" font-size="44" font-weight="750">{val}</text>')
        parts.append(f'<text x="78" y="{sy+70}" fill="{MUTED}" font-size="21">{label}</text>')

    # Right board card
    parts.extend([
        f'<rect x="540" y="176" width="612" height="408" rx="16" fill="{SURFACE}" stroke="{RULE}" stroke-width="1.2"/>',
        f'<text x="846" y="212" text-anchor="middle" fill="{INK}" font-size="18.5" font-weight="700">{board_hdr}</text>',
    ])
    parts.extend(render_hex_board_svg(st, ox=642.0, oy=266.0, r=15.0, win_path=wpath, last_mv=(10, 5), show_labels=True))
    parts.append(f'<text x="846" y="566" text-anchor="middle" fill="{UOM_GOLD_TEXT}" font-size="15.5" font-weight="600">{board_foot}</text>')

    # Bottom University of Manchester Purple signature summary banner
    parts.extend([
        f'<rect x="48" y="610" width="1104" height="106" rx="14" fill="{UOM_PURPLE}"/>',
        f'<text x="80" y="655" fill="#FFFFFF" font-size="31" font-weight="750">{banner_l1}</text>',
        f'<text x="80" y="694" fill="#E8D8F5" font-size="21">{banner_l2}</text>',
        f'<text x="1120" y="660" text-anchor="end" fill="{UOM_GOLD_ON_DARK}" font-size="48" font-weight="750">{banner_r1}</text>',
        f'<text x="1120" y="694" text-anchor="end" fill="#E8D8F5" font-size="19">{banner_r2}</text>',
        "</svg>",
    ])
    return "\n".join(parts) + "\n"


def build_progression_svg(summary: dict, lang: str) -> str:
    w, h = 1200, 620
    acc = summary["accepted_progression"]
    rej = summary["rejected_ablations"]
    rej_ko = {
        "Uncapped Ancestor GRAVE": "무제한 조상 GRAVE",
        "Deterministic LGR Rollouts": "결정적 LGR 롤아웃",
        "Unbounded Two-Distance (all depths)": "전 깊이 Two-Distance",
        "Sharp Pattern Rollout (temp=0.60)": "고온도 패턴 롤아웃 (0.60)",
        "Forced Edge-Ladder Rollout Block": "강제 엣지 사다리 차단",
        "12-Cell Patterns inside Rollouts": "롤아웃 내 12셀 패턴",
        "Irwin-Hall(4) Thin-Tail Beta": "Irwin-Hall(4) 근사 Beta",
        "GRAVE-UCB vs GRAVE-TS (30g each)": "GRAVE-UCB vs GRAVE-TS",
    }
    rej_en = {
        "Uncapped Ancestor GRAVE": "Uncapped Ancestor GRAVE",
        "Deterministic LGR Rollouts": "Deterministic LGR Rollouts",
        "Unbounded Two-Distance (all depths)": "Unbounded Two-Distance (All)",
        "Sharp Pattern Rollout (temp=0.60)": "Sharp Pattern Rollout (0.60)",
        "Forced Edge-Ladder Rollout Block": "Forced Edge-Ladder Block",
        "12-Cell Patterns inside Rollouts": "12-Cell Patterns in Rollouts",
        "Irwin-Hall(4) Thin-Tail Beta": "Irwin-Hall(4) Thin-Tail Beta",
        "GRAVE-UCB vs GRAVE-TS (30g each)": "GRAVE-UCB vs GRAVE-TS",
    }
    if lang == "ko":
        title = "단계별 실증 Elo 진화 (v0.0 → v1.2) 및 기각된 8가지 가설"
        desc = "이전 고정 체크포인트 대비 선·후공 교대 통제 대국으로 검증된 누적 +342 Elo 상승과 50% 미만으로 기각·원복된 8가지 가설 비교 차트입니다."
        heading = "단계별 실증 기력 향상 (v0.0 → v1.2) 및 기각된 가설"
        sub = "모든 업그레이드는 이전 고정 체크포인트 대비 선·후공 교대 통제 대국에서 50% 초과 승률을 검증한 경우만 채택했습니다."
        left_title = "채택된 업그레이드 (v0.0 기준 누적 +342 Elo)"
        left_note = "x축 아래 수치는 직전 고정 버전 대비 통제 대국 승률 (Pondering 미적용)"
        right_title = "기각·원복된 8가지 가설 (실측 승률 50% 미만)"
        thresh_lbl = "채택 기준 50%"
        right_note = "이론상 유망했으나 11×11 통제 대국에서 50% 미만으로 패배해 v1.2에서 제외"
        base_lbl = "기준선"
    else:
        title = "Empirical Engine Progression (v0.0 to v1.2) & Falsified Ablations"
        desc = "Cumulative +342 Elo gain verified in color balanced controlled matches from v0.0 to v1.2 alongside 8 hypotheses rejected below 50%."
        heading = "Empirical Engine Progression (v0.0 → v1.2) &amp; Falsified Ablations"
        sub = "Every feature was accepted only after winning color balanced controlled matches against the previous frozen checkpoint."
        left_title = "Accepted Upgrades over v0.0 Baseline (+342 Elo)"
        left_note = "Bottom row: direct match win rate vs prior checkpoint (without ponder)"
        right_title = "Rejected Hypotheses (Win Rate &lt; 50% → Reverted)"
        thresh_lbl = "50% Threshold"
        right_note = "All 8 ideas scored below 50% on 11×11 and were reverted"
        base_lbl = "Base"

    parts = svg_header(w, h, title, desc, lang)
    parts.extend([
        f'<text x="40" y="54" fill="{INK}" font-size="30" font-weight="750">{heading}</text>',
        f'<text x="40" y="84" fill="{MUTED}" font-size="16">{sub}</text>',
        f'<path d="M40 100H1160" stroke="{RULE}" stroke-width="1.2"/>',
        # Left card
        f'<rect x="40" y="120" width="560" height="466" rx="14" fill="{SURFACE}" stroke="{RULE}" stroke-width="1.2"/>',
        f'<rect x="40" y="120" width="560" height="5" rx="2.5" fill="{UOM_PURPLE}"/>',
        f'<text x="64" y="156" fill="{UOM_PURPLE}" font-size="18" font-weight="700">{left_title}</text>',
    ])

    x0, y0, pw, ph = 104, 480, 464, 286
    max_elo = 380.0
    for tick in (0, 100, 200, 300, 380):
        yy = y0 - (tick / max_elo) * ph
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x0+pw}" y2="{yy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text class="mono" x="{x0-12}" y="{yy+4:.1f}" text-anchor="end" fill="{MUTED}" font-size="12">+{tick}</text>')

    pts = [("v0.0", 0, base_lbl)] + [
        (item["stage"].replace("-", " "), item["cumulative_elo"], f"{item['win_rate_pct']:.1f}%")
        for item in acc
    ]
    xs = [x0 + i * (pw / (len(pts) - 1)) for i in range(len(pts))]
    ys = [y0 - (p[1] / max_elo) * ph for p in pts]

    area_d = f"M {xs[0]:.1f} {y0} " + " ".join(f"L {xs[i]:.1f} {ys[i]:.1f}" for i in range(len(pts))) + f" L {xs[-1]:.1f} {y0} Z"
    parts.append(f'<path d="{area_d}" fill="{UOM_PURPLE_SOFT}" opacity="0.85"/>')
    line_d = " ".join(f"{'M' if i==0 else 'L'} {xs[i]:.1f} {ys[i]:.1f}" for i in range(len(pts)))
    parts.append(f'<path d="{line_d}" fill="none" stroke="{UOM_PURPLE}" stroke-width="3.2" stroke-linejoin="round"/>')

    for i, (stage, elo, wr_lbl) in enumerate(pts):
        is_final = i == len(pts) - 1
        col = UOM_GOLD_BAR if is_final else UOM_PURPLE
        txt_col = UOM_GOLD_TEXT if is_final else UOM_PURPLE_DARK
        parts.append(f'<circle cx="{xs[i]:.1f}" cy="{ys[i]:.1f}" r="{6.5 if is_final else 5.2}" fill="{col}" stroke="{SURFACE}" stroke-width="2.4"/>')
        parts.append(f'<text class="mono" x="{xs[i]:.1f}" y="{ys[i]-13:.1f}" text-anchor="middle" fill="{txt_col}" font-size="12.5" font-weight="700">+{elo}</text>')
        parts.append(f'<text class="mono" x="{xs[i]:.1f}" y="{y0+22}" text-anchor="middle" fill="{INK}" font-size="11.5" font-weight="700">{escape(stage)}</text>')
        parts.append(f'<text class="mono" x="{xs[i]:.1f}" y="{y0+39}" text-anchor="middle" fill="{MUTED}" font-size="10.8">{escape(wr_lbl)}</text>')

    parts.append(f'<text x="320" y="564" text-anchor="middle" fill="{FAINT}" font-size="12.5">{left_note}</text>')

    # Right card: 0..60% bar scale with clean right aligned values past the track (zero threshold overlap)
    parts.extend([
        f'<rect x="620" y="120" width="540" height="466" rx="14" fill="{SURFACE}" stroke="{RULE}" stroke-width="1.2"/>',
        f'<rect x="620" y="120" width="540" height="5" rx="2.5" fill="{ROSE_MUTED}"/>',
        f'<text x="644" y="156" fill="{ROSE_MUTED}" font-size="18" font-weight="700">{right_title}</text>',
    ])

    bx0, bw = 880, 198
    bar_max_pct = 60.0
    x50 = bx0 + (50.0 / bar_max_pct) * bw
    parts.append(f'<line x1="{x50:.1f}" y1="184" x2="{x50:.1f}" y2="532" stroke="{UOM_GOLD_BAR}" stroke-dasharray="4,4" stroke-width="1.6"/>')
    parts.append(f'<text x="{x50:.1f}" y="177" text-anchor="middle" fill="{UOM_GOLD_TEXT}" font-size="11.5" font-weight="700">{thresh_lbl}</text>')

    ry = 198
    for item in rej:
        wr = float(item["win_rate_pct"])
        bar_w = min(bw, (wr / bar_max_pct) * bw)
        raw_name = item["experiment"]
        name = rej_ko.get(raw_name, raw_name) if lang == "ko" else rej_en.get(raw_name, raw_name)
        parts.append(f'<text x="{bx0-14}" y="{ry+16}" text-anchor="end" fill="{INK}" font-size="12.5" font-weight="500">{escape(name)}</text>')
        parts.append(f'<rect x="{bx0}" y="{ry+2}" width="{bw}" height="20" rx="5" fill="{TRACK_BG}"/>')
        parts.append(f'<rect x="{bx0}" y="{ry+2}" width="{bar_w:.1f}" height="20" rx="5" fill="{ROSE_MUTED}"/>')
        parts.append(f'<text class="mono" x="{bx0+bw+10:.1f}" y="{ry+16}" fill="{ROSE_MUTED}" font-size="12" font-weight="700">{wr:.1f}%</text>')
        ry += 42

    parts.append(f'<text x="890" y="564" text-anchor="middle" fill="{FAINT}" font-size="12.5">{right_note}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def build_mohex_win_svg(data: dict, st: BattleReferee, wpath: list[tuple[int, int]], lang: str) -> str:
    w, h = 1200, 600
    if lang == "ko":
        title = "실전 검증: Hex Search v1.2 vs MoHex 3 선공 77수 승리"
        desc = "11×11 적응형 300초 시계에서 Hex Search v1.2가 MoHex 3를 상대로 선공 77수 만에 승리한 최종 보드와 턴별 예상 승률 및 Pondering 재사용 방문 수 그래프입니다."
        heading = "실전 검증: Hex Search v1.2 vs MoHex 3 선공 77수 완승"
        sub = "11×11 표준 파이 룰 · 300초 시계 (291.7초 사용) · 12스레드 · 직접 6,088만 + Pondering 7,480만 = 총 1.35억 방문"
        board_hdr = "최종 보드 (77수 · Red i1 ↔ f11 상하 연결)"
        chart_hdr = "턴별 AI 예상 승률 (%) 및 Pondering 재사용 방문 수 (백만)"
        c41_t = "41수: h2 사다리 탈출"
        c41_s = "+9.65M Ponder 재사용"
        c71_t = "71~77수: VC Solver 필승"
        c71_s = "4연속 0.00초 강제 체크메이트"
        leg1 = "AI 예상 승률 (%)"
        leg2 = "Pondering 재사용 방문 수 (최고 +9.75M)"
        leg3 = "Exact VC Solver 필승 구간"
        eq_lbl = "50% 균형선"
    else:
        title = "Verified 77 Move First Player Victory: Hex Search v1.2 vs MoHex 3"
        desc = "Final 11x11 board and move by move winrate and pondering reuse telemetry from the verified 77 move first player win over MoHex 3."
        heading = "Verified 77 Move 1st Player Victory: Hex Search v1.2 vs MoHex 3"
        sub = "11×11 Standard Pie Rule · 300s Adaptive Clock (291.7s used) · 12 Threads · 60.9M Direct + 74.8M Ponder = 135.7M Visits"
        board_hdr = "Final Board (Turn 77 · Red i1 ↔ f11 Connected)"
        chart_hdr = "AI Winrate Trajectory (%) &amp; Pondering Reused Visits (Millions)"
        c41_t = "T41: h2 Ladder Escape"
        c41_s = "+9.65M Ponder Reused"
        c71_t = "T71 to T77: VC Solver Win"
        c71_s = "4× 0.00s Forced Checkmate"
        leg1 = "AI Winrate (%)"
        leg2 = "Pondering Reused Visits (Peak +9.75M)"
        leg3 = "Exact VC Solver Proven Win"
        eq_lbl = "50% Even"

    parts = svg_header(w, h, title, desc, lang)
    parts.extend([
        f'<text x="40" y="52" fill="{INK}" font-size="29" font-weight="750">{heading}</text>',
        f'<text x="40" y="80" fill="{MUTED}" font-size="15.5">{sub}</text>',
        f'<path d="M40 96H1160" stroke="{RULE}" stroke-width="1.2"/>',
        # Left board card
        f'<rect x="40" y="114" width="484" height="456" rx="14" fill="{SURFACE}" stroke="{RULE}" stroke-width="1.2"/>',
        f'<text x="282" y="148" text-anchor="middle" fill="{INK}" font-size="16.5" font-weight="700">{board_hdr}</text>',
    ])
    parts.extend(render_hex_board_svg(st, ox=92.0, oy=226.0, r=14.6, win_path=wpath, last_mv=(10, 5), show_labels=True))
    parts.append(f'<text class="mono" x="282" y="550" text-anchor="middle" fill="{FAINT}" font-size="11.5">SGF: reports/online_battles/20261119T101056Z_Mohex_3_first.sgf</text>')

    # Right chart card
    parts.extend([
        f'<rect x="546" y="114" width="614" height="456" rx="14" fill="{SURFACE}" stroke="{RULE}" stroke-width="1.2"/>',
        f'<text x="572" y="148" fill="{INK}" font-size="16.5" font-weight="700">{chart_hdr}</text>',
    ])

    ai_moves = [m for m in data["moves"] if m["actor"] == data["red"]]
    cx0, cy0, cw, ch = 610, 480, 514, 292
    for pct in (0, 25, 50, 75, 100):
        yy = cy0 - (pct / 100.0) * ch
        if pct == 50:
            parts.append(f'<line x1="{cx0}" y1="{yy:.1f}" x2="{cx0+cw}" y2="{yy:.1f}" stroke="{UOM_GOLD_BAR}" stroke-dasharray="4,4" stroke-width="1.3"/>')
            parts.append(f'<text x="{cx0+cw-2}" y="{yy-6:.1f}" text-anchor="end" fill="{UOM_GOLD_TEXT}" font-size="11" font-weight="600">{eq_lbl}</text>')
        else:
            parts.append(f'<line x1="{cx0}" y1="{yy:.1f}" x2="{cx0+cw}" y2="{yy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text class="mono" x="{cx0-10}" y="{yy+4:.1f}" text-anchor="end" fill="{MUTED}" font-size="11.5">{pct}%</text>')

    max_turn = 77.0
    max_reused = 10_000_000.0
    for m in ai_moves:
        t = m["turn"]
        rv = m.get("reused_visits", 0) or 0
        if rv > 0:
            bx = cx0 + (t / max_turn) * cw
            bh = min(ch, (rv / max_reused) * ch * 0.85)
            parts.append(f'<rect x="{bx-4:.1f}" y="{cy0-bh:.1f}" width="8" height="{bh:.1f}" rx="2" fill="{HEX_BLUE}" opacity="0.24"/>')

    wr_pts = []
    for m in ai_moves:
        t = m["turn"]
        wr = 100.0 if m.get("solver_status") == "proven_win" else float(m.get("winrate_pct", 50.0))
        wr_pts.append((cx0 + (t / max_turn) * cw, cy0 - (wr / 100.0) * ch, t, wr, m.get("reason", "")))

    d_line = " ".join(f"{'M' if i==0 else 'L'} {p[0]:.1f} {p[1]:.1f}" for i, p in enumerate(wr_pts))
    parts.append(f'<path d="{d_line}" fill="none" stroke="{UOM_PURPLE}" stroke-width="3" stroke-linejoin="round"/>')
    for x, y, t, wr, reason in wr_pts:
        is_vc = reason in ("vc_proven_win", "tactical_win")
        col = UOM_GOLD_BAR if is_vc else UOM_PURPLE
        r_dot = 4.8 if t in (1, 41, 65, 71, 77) else 2.6
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r_dot}" fill="{col}" stroke="{SURFACE}" stroke-width="1.3"/>')

    for t_lbl in (1, 15, 30, 45, 60, 77):
        tx = cx0 + (t_lbl / max_turn) * cw
        parts.append(f'<text class="mono" x="{tx:.1f}" y="{cy0+22}" text-anchor="middle" fill="{MUTED}" font-size="11.5">T{t_lbl}</text>')

    # Editorial callout 1: T41 ladder escape
    t41_x = cx0 + (41 / max_turn) * cw
    parts.append(f'<line x1="{t41_x:.1f}" y1="204" x2="{t41_x:.1f}" y2="{cy0}" stroke="{HEX_BLUE}" stroke-dasharray="3,3" stroke-width="1.1"/>')
    parts.append(f'<rect x="{t41_x-86:.1f}" y="168" width="172" height="40" rx="8" fill="{SURFACE_TINT}" stroke="{HEX_BLUE}" stroke-width="1.1"/>')
    parts.append(f'<text x="{t41_x:.1f}" y="185" text-anchor="middle" fill="{HEX_BLUE_EDGE}" font-size="12" font-weight="700">{c41_t}</text>')
    parts.append(f'<text class="mono" x="{t41_x:.1f}" y="201" text-anchor="middle" fill="{MUTED}" font-size="10.5">{c41_s}</text>')

    # Editorial callout 2: T71 to T77 Exact VC Solver (cleanly left of rising slope)
    t71_x = cx0 + (71 / max_turn) * cw
    parts.append(f'<rect x="{t71_x-196:.1f}" y="206" width="184" height="40" rx="8" fill="{SURFACE_GOLD}" stroke="{UOM_GOLD_BAR}" stroke-width="1.1"/>')
    parts.append(f'<text x="{t71_x-104:.1f}" y="223" text-anchor="middle" fill="{UOM_GOLD_TEXT}" font-size="12" font-weight="700">{c71_t}</text>')
    parts.append(f'<text x="{t71_x-104:.1f}" y="239" text-anchor="middle" fill="{MUTED}" font-size="10.8">{c71_s}</text>')

    # Clean legend
    parts.append(f'<line x1="574" y1="534" x2="594" y2="534" stroke="{UOM_PURPLE}" stroke-width="3" stroke-linecap="round"/>')
    parts.append(f'<text x="602" y="538" fill="{INK}" font-size="12.5">{leg1}</text>')
    parts.append(f'<rect x="724" y="528" width="13" height="12" rx="2.5" fill="{HEX_BLUE}" opacity="0.35"/>')
    parts.append(f'<text x="744" y="538" fill="{INK}" font-size="12.5">{leg2}</text>')
    parts.append(f'<circle cx="994" cy="534" r="5" fill="{UOM_GOLD_BAR}"/>')
    parts.append(f'<text x="1006" y="538" fill="{INK}" font-size="12.5">{leg3}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def build_battle_gallery_svg(lang: str) -> str:
    """Render 4 panel visual proof gallery directly from real SGF/JSON victory logs."""
    w, h = 1200, 790
    if lang == "ko":
        title = "실전 승리 최종 보드 갤러리 (Davis 7 · Davis 10 · MoHex 3)"
        desc = "저장된 원본 SGF/JSON 기보에서 독립 심판으로 1수부터 끝까지 재생해 렌더링한 4판의 실전 승리 최종 보드와 황금 승리 연결 경로입니다."
        heading = "실전 승리 최종 보드 갤러리 (원본 SGF/JSON 전수 리플레이)"
        sub = "모든 돌 배치와 황금 승리 연결 경로는 저장된 실제 대국 기록을 독립 BFS 심판으로 재생해 자동 생성했습니다."
        panels = [
            ("20261119T064314Z_Davis_7_first.json", "vs Davis 7 · 선공 (Red)", "35수 승 · 187.4초 · v1.0", HEX_RED),
            ("20261119T064830Z_Davis_10_first.json", "vs Davis 10 · 선공 (Red)", "39수 승 · 204.8초 · v1.0", HEX_RED),
            ("20261119T065645Z_Davis_10_second.json", "vs Davis 10 · 후공 (Blue)", "44수 승 · 232.9초 · v1.0", HEX_BLUE),
            ("20261119T071757Z_Mohex_3_second.json", "vs MoHex 3 · 후공 (Blue)", "68수 승 · 287.6초 · v1.0", UOM_PURPLE),
        ]
    else:
        title = "Verified Final Boards Gallery (Online Bot Victories)"
        desc = "Four final 11x11 Hex boards rendered directly from independent replay of saved SGF/JSON victory logs against Davis 7, Davis 10, and MoHex 3."
        heading = "Verified Final Boards Gallery: Online Bot Victories (SGF/JSON Replayed)"
        sub = "Every stone placement and Manchester Gold winning chain is rendered directly from independent replay of saved match logs."
        panels = [
            ("20261119T064314Z_Davis_7_first.json", "vs Davis 7 · AI 1st (Red)", "35 Moves · 187.4s · v1.0 WIN", HEX_RED),
            ("20261119T064830Z_Davis_10_first.json", "vs Davis 10 · AI 1st (Red)", "39 Moves · 204.8s · v1.0 WIN", HEX_RED),
            ("20261119T065645Z_Davis_10_second.json", "vs Davis 10 · AI 2nd (Blue)", "44 Moves · 232.9s · v1.0 WIN", HEX_BLUE),
            ("20261119T071757Z_Mohex_3_second.json", "vs MoHex 3 · AI 2nd (Blue)", "68 Moves · 287.6s · v1.0 WIN", UOM_PURPLE),
        ]

    parts = svg_header(w, h, title, desc, lang)
    parts.extend([
        f'<text x="40" y="52" fill="{INK}" font-size="29" font-weight="750">{heading}</text>',
        f'<text x="40" y="80" fill="{MUTED}" font-size="15.5">{sub}</text>',
        f'<path d="M40 96H1160" stroke="{RULE}" stroke-width="1.2"/>',
    ])
    coords = [(40, 114), (612, 114), (40, 452), (612, 452)]
    for (fname, card_title, card_sub, bar_col), (px, py) in zip(panels, coords):
        data, st, wpath = replay_battle_file(fname)
        last_mv = tuple(data["moves"][-1]["move"])
        parts.append(f'<rect x="{px}" y="{py}" width="548" height="318" rx="14" fill="{SURFACE}" stroke="{RULE}" stroke-width="1.2"/>')
        parts.append(f'<rect x="{px}" y="{py}" width="548" height="4.5" rx="2" fill="{bar_col}"/>')
        parts.append(f'<text x="{px+22}" y="{py+34}" fill="{INK}" font-size="16" font-weight="700">{escape(card_title)}</text>')
        parts.append(f'<text class="mono" x="{px+526}" y="{py+34}" text-anchor="end" fill="{bar_col}" font-size="12.5" font-weight="700">{escape(card_sub)}</text>')
        parts.extend(render_hex_board_svg(st, ox=px + 138.0, oy=py + 84.0, r=10.8, win_path=wpath, last_mv=last_mv, show_labels=True))
        parts.append(f'<text class="mono" x="{px+274}" y="{py+304}" text-anchor="middle" fill="{FAINT}" font-size="10.8">reports/online_battles/{escape(fname.replace(".json", ".sgf"))}</text>')

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def build_online_results_svg(summary: dict, lang: str) -> str:
    w, h = 1200, 500
    if lang == "ko":
        title = "온라인 공개 봇 실전 검증 및 MoHex 3 선공 돌파 과정"
        desc = "Davis 7, Davis 10 전승 및 MoHex 3 후공·선공 승리 스코어카드와 두 차례 선공 진단 패배를 v1.2 완승으로 돌파한 반복 개선 루프입니다."
        heading = "외부 온라인 봇 실전 검증 및 버전별 돌파 루프"
        sub = "11×11 표준 파이 룰 · 300초 적응형 V3 시계 · 전 대국 표준 Hex SGF + JSON 리플레이 검증 완료"
        cards = [
            ("Davis 7", "2승 0패", "선공 35수 · 후공 58수 완승", "v1.0 · 전승", UOM_PURPLE, SURFACE),
            ("Davis 10", "2승 0패", "선공 39수 · 후공 44수 완승", "v1.0 · 전승", UOM_PURPLE, SURFACE),
            ("MoHex 3 (후공)", "68수 승", "j8 스왑 후 a6 필승 완결", "v1.0 · 287.6초 / 300초", HEX_BLUE, SURFACE),
            ("MoHex 3 (선공)", "77수 승", "총 1.35억 방문 · 41수 탈출", "v1.2 · T71 VC 필승", UOM_GOLD_BAR, SURFACE_GOLD),
        ]
        loop_hdr = "MoHex 3 선공 돌파 과정 (패배 원인 진단에서 77수 완승까지)"
        steps = [
            ("v1.0 · 54수 진단 패", "1수 정중앙 e7 착수 → MoHex 3 즉시 스왑", "→ v1.1 50% 내쉬 오프닝 북 + Pondering 도입", ROSE_MUTED, ROSE_BG),
            ("v1.1 · 66수 진단 패", "19수 승률 81.4% 압도 후 22~39수 사다리 역전", "→ v1.2 Exact VC Solver + 탐색 튜닝 (+89 Elo)", UOM_GOLD_TEXT, SURFACE_GOLD),
            ("v1.2 · 77수 완승", "41수 h2 사다리 탈출 (+9.65M Ponder 재사용)", "→ 71~77수 4연속 0.00초 Exact VC 필승 증명", UOM_PURPLE, UOM_PURPLE_SOFT),
        ]
    else:
        title = "External Online Bot Validation & Version Breakthrough Loop"
        desc = "Scorecard for Davis 7 (2W 0L), Davis 10 (2W 0L), and MoHex 3 (both sides won), plus the iterative diagnostic loop from v1.0 to v1.2."
        heading = "External Online Bot Validation &amp; Version Breakthrough Loop"
        sub = "11×11 Standard Pie Rule · Adaptive 300s Clock · All 8 Games Logged &amp; Replay Verified in SGF + JSON"
        cards = [
            ("Davis 7", "2W 0L", "1st: 35m Win · 2nd: 58m Win", "v1.0 · 100% Sweep", UOM_PURPLE, SURFACE),
            ("Davis 10", "2W 0L", "1st: 39m Win · 2nd: 44m Win", "v1.0 · 100% Sweep", UOM_PURPLE, SURFACE),
            ("MoHex 3 (2nd)", "68m WIN", "Swapped j8 · a6 Proven Win", "v1.0 · 287.6s / 300s", HEX_BLUE, SURFACE),
            ("MoHex 3 (1st)", "77m WIN", "135.7M Visits · T41 Escape", "v1.2 · T71 VC Checkmate", UOM_GOLD_BAR, SURFACE_GOLD),
        ]
        loop_hdr = "How Each Version Overcame MoHex 3 (First Player Diagnostic → Breakthrough)"
        steps = [
            ("v1.0 · 54m Loss", "Turn 1 center e7 swapped by MoHex 3", "→ v1.1 Added Nash Opening Book + Pondering", ROSE_MUTED, ROSE_BG),
            ("v1.1 · 66m Loss", "81.4% at T19, caught in T22 to T39 ladder", "→ v1.2 Added Exact VC Solver + Tuning (+89 Elo)", UOM_GOLD_TEXT, SURFACE_GOLD),
            ("v1.2 · 77m WIN", "T41 h2 ladder escape (+9.65M Ponder reuse)", "→ T71 to T77 4× 0.00s Exact VC Checkmate", UOM_PURPLE, UOM_PURPLE_SOFT),
        ]

    parts = svg_header(w, h, title, desc, lang)
    parts.extend([
        f'<text x="40" y="52" fill="{INK}" font-size="29" font-weight="750">{heading}</text>',
        f'<text x="40" y="80" fill="{MUTED}" font-size="15.5">{sub}</text>',
        f'<path d="M40 96H1160" stroke="{RULE}" stroke-width="1.2"/>',
    ])

    cx = 40
    for card_title, big, sub1, sub2, accent_col, bg_col in cards:
        big_col = UOM_GOLD_TEXT if accent_col == UOM_GOLD_BAR else accent_col
        parts.append(f'<rect x="{cx}" y="114" width="265" height="154" rx="14" fill="{bg_col}" stroke="{RULE}" stroke-width="1.2"/>')
        parts.append(f'<rect x="{cx}" y="114" width="265" height="5" rx="2.5" fill="{accent_col}"/>')
        parts.append(f'<text x="{cx+20}" y="146" fill="{MUTED}" font-size="15" font-weight="700">{escape(card_title)}</text>')
        parts.append(f'<text x="{cx+20}" y="196" fill="{big_col}" font-size="38" font-weight="750">{escape(big)}</text>')
        parts.append(f'<text x="{cx+20}" y="228" fill="{INK}" font-size="14">{escape(sub1)}</text>')
        parts.append(f'<text class="mono" x="{cx+20}" y="252" fill="{FAINT}" font-size="12">{escape(sub2)}</text>')
        cx += 285

    parts.append(f'<rect x="40" y="290" width="1120" height="182" rx="14" fill="{SURFACE}" stroke="{RULE}" stroke-width="1.2"/>')
    parts.append(f'<text x="64" y="324" fill="{INK}" font-size="17" font-weight="700">{loop_hdr}</text>')

    sx = 64
    for idx, (hdr, body, arrow, col, tag_bg) in enumerate(steps):
        if idx > 0:
            ax = sx - 20
            parts.append(f'<path d="M{ax-6} 396H{ax+8}M{ax+2} 390L{ax+8} 396L{ax+2} 402" fill="none" stroke="{UOM_PURPLE_MID}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
        parts.append(f'<rect x="{sx}" y="342" width="336" height="110" rx="10" fill="{SURFACE_TINT}" stroke="{RULE}" stroke-width="1"/>')
        parts.append(f'<rect x="{sx+14}" y="354" width="156" height="24" rx="6" fill="{tag_bg}"/>')
        parts.append(f'<text x="{sx+22}" y="370" fill="{col}" font-size="12.5" font-weight="700">{escape(hdr)}</text>')
        parts.append(f'<text x="{sx+16}" y="404" fill="{INK}" font-size="13.5" font-weight="500">{escape(body)}</text>')
        parts.append(f'<text x="{sx+16}" y="432" fill="{MUTED}" font-size="12.5">{escape(arrow)}</text>')
        sx += 368

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render_all(summary: dict, mohex_data: dict, st: BattleReferee, wpath: list[tuple[int, int]], lang: str) -> dict[str, str]:
    return {
        "hex-thumbnail.svg": build_thumbnail_svg(st, wpath, lang),
        "hex-progression.svg": build_progression_svg(summary, lang),
        "hex-mohex-win.svg": build_mohex_win_svg(mohex_data, st, wpath, lang),
        "hex-battle-gallery.svg": build_battle_gallery_svg(lang),
        "hex-online-results.svg": build_online_results_svg(summary, lang),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate reproducible Hex Search v1.2 SVG figures (EN + KO).")
    parser.add_argument("--check", action="store_true", help="Verify generated SVGs match files on disk.")
    parser.add_argument("--portfolio-dir", type=Path, default=None, help="Optional portfolio images dir to copy Korean SVGs into.")
    args = parser.parse_args()

    summary = json.loads((ROOT / "reports" / "benchmarks" / "progression_summary.json").read_text(encoding="utf-8"))
    mohex_data, st, wpath = replay_battle_file("20261119T101056Z_Mohex_3_first.json")

    sets = [
        ("en", ROOT / "assets", render_all(summary, mohex_data, st, wpath, "en")),
        ("ko", ROOT / "assets" / "ko", render_all(summary, mohex_data, st, wpath, "ko")),
    ]

    total = 0
    for lang, out_dir, outputs in sets:
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, svg in outputs.items():
            total += 1
            target = out_dir / name
            if args.check:
                if not target.is_file() or target.read_text(encoding="utf-8") != svg:
                    print(f"MISMATCH: {target}", file=sys.stderr)
                    return 1
            else:
                target.write_text(svg, encoding="utf-8")
                print(f"Generated {target} ({len(svg):,} bytes)")
                if lang == "ko" and args.portfolio_dir is not None:
                    args.portfolio_dir.mkdir(parents=True, exist_ok=True)
                    (args.portfolio_dir / name).write_text(svg, encoding="utf-8")
    if args.check:
        print(f"All {total} SVG figures (EN + KO) match deterministic source data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
