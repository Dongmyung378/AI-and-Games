"""Interactive local Hex GUI for playing directly against Hex-Search v1.2 or online bots."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .battle import BattleReferee, export_sgf, format_algebraic
from .evaluation import move_budget
from .native import NativeProcess, environment, executable_default, sha256
from .referee import Colour


# ---------------------------------------------------------------------------
# Pure geometry helpers (unit-testable without a display)
# ---------------------------------------------------------------------------

def hex_center(row: int, col: int, radius: float, origin_x: float, origin_y: float, transpose: bool = False) -> tuple[float, float]:
    """Return pixel center (x, y) of pointy-top hex cell (row, col)."""
    dr, dc = (col, row) if transpose else (row, col)
    dx = math.sqrt(3.0) * radius
    dy = 1.5 * radius
    x = origin_x + dc * dx + dr * (dx * 0.5)
    y = origin_y + dr * dy
    return (x, y)


def hex_vertices(cx: float, cy: float, radius: float) -> list[float]:
    """Return flat list [x0, y0, ..., x5, y5] of pointy-top hexagon vertices."""
    pts: list[float] = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        pts.append(cx + radius * math.cos(angle))
        pts.append(cy + radius * math.sin(angle))
    return pts


def hit_test_hex(
    px: float,
    py: float,
    size: int,
    radius: float,
    origin_x: float,
    origin_y: float,
    transpose: bool = False,
) -> tuple[int, int] | None:
    """Return nearest (row, col) if (px, py) falls inside a hex cell, else None."""
    best: tuple[int, int] | None = None
    best_d2 = (radius * 0.94) ** 2
    for r in range(size):
        for c in range(size):
            cx, cy = hex_center(r, c, radius, origin_x, origin_y, transpose=transpose)
            d2 = (px - cx) ** 2 + (py - cy) ** 2
            if d2 <= best_d2:
                best_d2 = d2
                best = (r, c)
    return best


def compute_board_layout(width: float, height: float, size: int, padding: float = 48.0) -> tuple[float, float, float]:
    """Compute (radius, origin_x, origin_y) to fit an NxN hex rhombus cleanly in (width, height)."""
    usable_w = max(120.0, width - 2.0 * padding)
    usable_h = max(120.0, height - 2.0 * padding)
    cols_span = math.sqrt(3.0) * (1.5 * size - 0.5)
    rows_span = 1.5 * size + 0.5
    radius = max(10.0, min(usable_w / cols_span, usable_h / rows_span))
    total_w = cols_span * radius
    total_h = rows_span * radius
    origin_x = (width - total_w) * 0.5 + math.sqrt(3.0) * 0.5 * radius
    origin_y = (height - total_h) * 0.5 + radius
    return (radius, origin_x, origin_y)


# ---------------------------------------------------------------------------
# Color palette & Difficulty presets
# ---------------------------------------------------------------------------

BG_ROOT = "#0f172a"
BG_PANEL = "#162033"
BG_CARD = "#1e293b"
FG_TEXT = "#f1f5f9"
FG_MUTED = "#94a3b8"
ACCENT_GOLD = "#fbbf24"
ACCENT_GREEN = "#34d399"
ACCENT_RED = "#ef4444"
ACCENT_RED_LIGHT = "#f87171"
ACCENT_BLUE = "#3b82f6"
ACCENT_BLUE_LIGHT = "#60a5fa"
CELL_EMPTY = "#243247"
CELL_HOVER = "#354966"
CELL_BORDER = "#475569"

DIFFICULTY_PRESETS_SPEC: list[tuple[str, dict]] = [
    ("beginner", {"clock_mode": "fixed", "fixed_seconds": "0.5", "game_seconds": "120", "workers": "2", "ponder": False}),
    ("intermediate", {"clock_mode": "fixed", "fixed_seconds": "2.0", "game_seconds": "180", "workers": "4", "ponder": False}),
    ("strong", {"clock_mode": "fixed", "fixed_seconds": "5.0", "game_seconds": "300", "workers": "8", "ponder": True}),
    ("grandmaster", {"clock_mode": "v3", "fixed_seconds": "5.0", "game_seconds": "300", "workers": "12", "ponder": True}),
]

PRESET_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "beginner": "Beginner (0.5s · 2 threads)",
        "intermediate": "Intermediate (2s · 4 threads)",
        "strong": "Strong (5s · 8 threads)",
        "grandmaster": "Grandmaster (300s · 12 threads)",
    },
    "ko": {
        "beginner": "입문 (0.5s·2스레드)",
        "intermediate": "중급 (2s·4스레드)",
        "strong": "강함 (5s·8스레드)",
        "grandmaster": "최강 (300s·12스레드)",
    },
}

DIFFICULTY_PRESETS: dict[str, dict] = {
    PRESET_LABELS["ko"][key]: cfg for key, cfg in DIFFICULTY_PRESETS_SPEC
}
for _lang_map in PRESET_LABELS.values():
    for _k, _cfg in DIFFICULTY_PRESETS_SPEC:
        DIFFICULTY_PRESETS[_lang_map[_k]] = _cfg

UI_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "title": "Hex-Search v1.2 · Play vs AI & Online Battle Board",
        "waiting": "Ready...",
        "winrate_empty": "AI Winrate: -",
        "winrate_fmt": "AI Winrate: {wr:.1f}%",
        "btn_swap": "Swap (Pie Rule)",
        "btn_undo": "Undo",
        "btn_save": "Save SGF",
        "chk_coords": "Coords (f6)",
        "chk_nums": "Move #",
        "chk_transpose": "Swap Axes",
        "chk_ponder": "Pondering (Search on Opponent Turn)",
        "cfg_frame": " Match Mode & Engine Settings ",
        "lbl_mode": "Mode:",
        "rad_human": "Human vs AI",
        "rad_online": "Online Bot Bridge",
        "lbl_preset": "Preset:",
        "lbl_board": "Board:",
        "lbl_threads": "Threads:",
        "lbl_opponent": "Opp:",
        "lbl_side": "AI Side:",
        "rad_first": "AI 1st (Red)",
        "rad_second": "AI 2nd (Blue · You 1st)",
        "rad_v3": "V3 Clock (s):",
        "rad_fixed": "Fixed (s/mv):",
        "lbl_swap": "Swap:",
        "rad_pieces": "swap-pieces",
        "rad_sides": "swap-sides",
        "btn_new": "Start New Match (Apply Settings)",
        "lbl_history": "Move History",
        "orient_tb": "Top↔Bottom",
        "orient_lr": "Left↔Right",
        "tag_me": "You",
        "tag_opp": "Opp",
        "new_game": "New Match Started",
        "your_turn_human": "Your turn! Click any empty hex cell.",
        "your_turn_online": "Click the opponent's move on the board.",
        "ai_first_think": "AI is computing the opening move...",
        "game_over": "Game Over ({n} moves)",
        "human_win": "Congratulations! You won!",
        "ai_win": "AI (Hex-Search v1.2) Wins!",
        "winner_fmt": "Winner: {w}",
        "win_chain_note": "Gold winning connection highlighted. Match log auto-saved.",
        "turn_fmt": "Turn {t}  •  To Move: {actor} ({col})",
        "ai_thinking": "AI Thinking...",
        "target_time": "Target budget: {sec:.1f}s ({w} threads)",
        "searching": "Searching... {el:.1f}s / {alloc:.1f}s ({w} threads)",
        "engine_err": "Engine Error",
        "unknown_err": "Unknown error",
        "swap_dest": "AI Play: SWAP → {dest} (Blue)",
        "swap_plain": "AI Play: SWAP",
        "ai_move_human": "AI Move:",
        "ai_move_online": "AI Suggestion:",
        "wait_human": "Your turn! Click an empty cell.",
        "wait_online": "Play on online board, then click opponent move.",
        "elapsed_fmt": "{el:.2f}s · {wait}",
        "ponder_suffix": " (Pondering active)",
        "clock_fixed_start": "Fixed {sec:.1f}s/move",
        "clock_v3_start": "V3 Clock {sec:.0f}s left",
        "clock_fixed_run": "Total {spent:.1f}s (Fixed mode)",
        "clock_v3_run": "Clock: {rem:.1f}s / {tot:.0f}s left",
        "tel_start": "Solver: -  |  {w} threads\n{clock}",
        "tel_run": "Solver: {solver}  |  {iters:,} (+{reused:,} reused)\n{clock}",
        "undo_done": "Move Undone",
        "undo_note": "Click a cell to continue or let AI search.",
        "saved_note": "Saved: {name}",
        "err_title": "Engine Launch Error",
        "err_body": "Failed to launch hex_search:\n{err}\nRun 'python -m hexai build' first.",
        "illegal_title": "Illegal Move",
        "save_title": "Match Saved",
        "save_body": "Saved to:\n{p0}\n{p1}",
    },
    "ko": {
        "title": "Hex-Search v1.2 · 사람 vs AI & 온라인 대국 보드",
        "waiting": "대기 중...",
        "winrate_empty": "AI 예상 승률: -",
        "winrate_fmt": "AI 예상 승률: {wr:.1f}%",
        "btn_swap": "Swap (파이 룰)",
        "btn_undo": "되돌리기 (Undo)",
        "btn_save": "기보 저장",
        "chk_coords": "좌표(f6)",
        "chk_nums": "수순(#)",
        "chk_transpose": "상하↔좌우 반전",
        "chk_ponder": "상대 턴 미리 탐색 (Pondering)",
        "cfg_frame": " 대결 모드 & 사용자 설정 ",
        "lbl_mode": "모드:",
        "rad_human": "사람 vs AI",
        "rad_online": "온라인 봇 어시스턴트",
        "lbl_preset": "난이도:",
        "lbl_board": "보드:",
        "lbl_threads": "스레드:",
        "lbl_opponent": "상대명:",
        "lbl_side": "AI 진영:",
        "rad_first": "AI 선공(Red)",
        "rad_second": "AI 후공(Blue·내가 선공)",
        "rad_v3": "V3 시계(초):",
        "rad_fixed": "수당 고정(초):",
        "lbl_swap": "Swap:",
        "rad_pieces": "돌 반전(pieces)",
        "rad_sides": "진영 교대(sides)",
        "btn_new": "새 대국 시작 (설정 적용)",
        "lbl_history": "수순 기록",
        "orient_tb": "상↔하",
        "orient_lr": "좌↔우",
        "tag_me": "나",
        "tag_opp": "상대",
        "new_game": "새 대국 시작!",
        "your_turn_human": "당신 차례입니다! 원하는 빈 칸을 클릭하세요.",
        "your_turn_online": "상대 수를 보드에서 클릭하세요.",
        "ai_first_think": "AI가 첫 수를 계산합니다...",
        "game_over": "대국 종료 ({n}수)",
        "human_win": "축하합니다! 승리했습니다!",
        "ai_win": "AI (Hex-Search v1.2) 승리!",
        "winner_fmt": "승자: {w}",
        "win_chain_note": "황금 연결 경로가 표시되었습니다. 기보 자동 저장 완료.",
        "turn_fmt": "Turn {t}  •  차례: {actor} ({col})",
        "ai_thinking": "AI 생각 중...",
        "target_time": "목표 시간: {sec:.1f}s ({w}스레드)",
        "searching": "탐색 중... {el:.1f}s / {alloc:.1f}s ({w}스레드)",
        "engine_err": "엔진 오류",
        "unknown_err": "알 수 없는 오류",
        "swap_dest": "AI 선택: SWAP → {dest} (Blue)",
        "swap_plain": "AI 선택: SWAP (스왑!)",
        "ai_move_human": "AI 착수:",
        "ai_move_online": "AI 추천 수:",
        "wait_human": "당신 차례입니다! 빈 칸을 클릭하세요.",
        "wait_online": "온라인 보드에 둔 뒤 상대 수를 클릭하세요.",
        "elapsed_fmt": "{el:.2f}초 소요 · {wait}",
        "ponder_suffix": " · Pondering",
        "clock_fixed_start": "고정 {sec:.1f}s/수",
        "clock_v3_start": "V3 시계 {sec:.0f}s 남음",
        "clock_fixed_run": "누적 {spent:.1f}s (고정 모드)",
        "clock_v3_run": "시계: {rem:.1f}s / {tot:.0f}s 남음",
        "tel_start": "Solver: -  |  {w}스레드\n{clock}",
        "tel_run": "Solver: {solver}  |  {iters:,} (+{reused:,} 재사용)\n{clock}",
        "undo_done": "되돌리기 완료",
        "undo_note": "다시 수를 클릭하거나 AI가 탐색합니다.",
        "saved_note": "저장됨: {name}",
        "err_title": "엔진 실행 오류",
        "err_body": "hex_search 실행 실패:\n{err}\n먼저 'python -m hexai build'를 실행하세요.",
        "illegal_title": "불가능한 수",
        "save_title": "기보 저장 완료",
        "save_body": "저장 위치:\n{p0}\n{p1}",
    },
}


class HexBattleGUI:
    def __init__(self, root: tk.Tk, args) -> None:
        self.root = root
        self.args = args
        self.lang = getattr(args, "lang", "en")
        if self.lang not in UI_TEXT:
            self.lang = "en"
        self.size = int(args.board_size)
        self.exe = Path(args.executable or executable_default()).resolve()

        self.root.title(self._t("title"))
        self.root.configure(bg=BG_ROOT)
        dpi_scale = max(1.0, min(1.5, float(self.root.winfo_fpixels("1i")) / 96.0))
        scr_w = self.root.winfo_screenwidth()
        scr_h = self.root.winfo_screenheight()
        win_w = min(max(1320, int(1320 * dpi_scale)), max(1080, scr_w - 60))
        win_h = min(max(880, int(880 * dpi_scale)), max(740, scr_h - 90))
        self._sidebar_width = max(415, int(415 * dpi_scale))
        self.root.geometry(f"{win_w}x{win_h}")
        self.root.minsize(1060, 720)

        # Match / engine runtime state
        self.ai_label = "hex-search-v1.2"
        self.engine: NativeProcess | None = None
        self.engine_cmd: list[str] = []
        self.state: BattleReferee | None = None
        self.history: list[dict] = []
        self.ai_spent = 0.0
        self.ai_requests = 0
        self.ai_is_first = str(args.side).lower() in {"first", "red", "black"}
        self.swap_rule = getattr(args, "swap_rule", "swap_pieces")
        self.thinking = False
        self.pondering = False
        self.think_start = 0.0
        self.think_alloc = 0.0
        self.session_token = 0
        self.hover_cell: tuple[int, int] | None = None
        self.saved_for_game = False
        self.last_ai_event: dict | None = None
        self._result_queue: queue.Queue = queue.Queue()

        default_mode = getattr(args, "mode", "human")
        if default_mode not in {"human", "online"}:
            default_mode = "human"
        default_opp = "Human" if (default_mode == "human" and args.opponent in {"Human", "Davis 10"}) else args.opponent
        self._preset_key = "strong" if default_mode == "human" and args.seconds is not None else "grandmaster"

        # Tk variables for setup & toggles
        self.var_mode = tk.StringVar(value=default_mode)
        self.var_board_size = tk.StringVar(value=str(self.size))
        self.var_preset = tk.StringVar(value=PRESET_LABELS[self.lang][self._preset_key])
        self.var_opponent = tk.StringVar(value=default_opp)
        self.var_side = tk.StringVar(value="first" if self.ai_is_first else "second")
        self.var_swap_rule = tk.StringVar(value=self.swap_rule)
        self.var_clock_mode = tk.StringVar(value="fixed" if args.seconds is not None else "v3")
        self.var_game_seconds = tk.StringVar(value=str(int(args.game_seconds)))
        self.var_fixed_seconds = tk.StringVar(value=str(args.seconds if args.seconds is not None else 2.0))
        self.var_workers = tk.StringVar(value=str(args.workers))
        self.var_show_coords = tk.BooleanVar(value=True)
        self.var_show_numbers = tk.BooleanVar(value=True)
        self.var_transpose = tk.BooleanVar(value=False)
        self.var_ponder = tk.BooleanVar(value=True)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.start_new_game()

    def _t(self, key: str, **kwargs) -> str:
        text = UI_TEXT[self.lang].get(key, key)
        return text.format(**kwargs) if kwargs else text

    def set_language(self, lang: str) -> None:
        if lang not in UI_TEXT or lang == self.lang:
            return
        self.lang = lang
        self.root.title(self._t("title"))
        self.btn_lang_en.configure(
            bg=ACCENT_BLUE if lang == "en" else BG_CARD,
            fg="#ffffff" if lang == "en" else FG_MUTED,
        )
        self.btn_lang_ko.configure(
            bg=ACCENT_BLUE if lang == "ko" else BG_CARD,
            fg="#ffffff" if lang == "ko" else FG_MUTED,
        )
        self.btn_swap.configure(text=self._t("btn_swap"))
        self.btn_undo.configure(text=self._t("btn_undo"))
        self.btn_save.configure(text=self._t("btn_save"))
        self.chk_coords.configure(text=self._t("chk_coords"))
        self.chk_nums.configure(text=self._t("chk_nums"))
        self.chk_transpose.configure(text=self._t("chk_transpose"))
        self.chk_ponder.configure(text=self._t("chk_ponder"))
        self.cfg_frame.configure(text=self._t("cfg_frame"))
        self.lbl_mode.configure(text=self._t("lbl_mode"))
        self.rad_human.configure(text=self._t("rad_human"))
        self.rad_online.configure(text=self._t("rad_online"))
        self.lbl_preset.configure(text=self._t("lbl_preset"))
        self.preset_box.configure(values=[PRESET_LABELS[lang][k] for k, _ in DIFFICULTY_PRESETS_SPEC])
        self.var_preset.set(PRESET_LABELS[lang][self._preset_key])
        self.lbl_board.configure(text=self._t("lbl_board"))
        self.lbl_threads.configure(text=self._t("lbl_threads"))
        self.lbl_opponent.configure(text=self._t("lbl_opponent"))
        self.lbl_side.configure(text=self._t("lbl_side"))
        self.rad_first.configure(text=self._t("rad_first"))
        self.rad_second.configure(text=self._t("rad_second"))
        self.rad_v3.configure(text=self._t("rad_v3"))
        self.rad_fixed.configure(text=self._t("rad_fixed"))
        self.lbl_swap.configure(text=self._t("lbl_swap"))
        self.rad_pieces.configure(text=self._t("rad_pieces"))
        self.rad_sides.configure(text=self._t("rad_sides"))
        self.btn_new.configure(text=self._t("btn_new"))
        self.lbl_history.configure(text=self._t("lbl_history"))
        self._refresh_telemetry_labels()
        self.hist_list.delete(0, tk.END)
        for ev in self.history:
            self._append_history_row(ev)
        self._refresh_ui_state()

    def _refresh_telemetry_labels(self) -> None:
        ev = self.last_ai_event
        if ev is None:
            self.lbl_winrate.configure(text=self._t("winrate_empty"))
            clock_desc = (
                self._t("clock_fixed_start", sec=getattr(self, "fixed_seconds", 2.0))
                if getattr(self, "use_fixed_seconds", False)
                else self._t("clock_v3_start", sec=getattr(self, "game_seconds", 300.0))
            )
            self.lbl_tel_detail.configure(
                text=self._t("tel_start", w=getattr(self, "workers", 4), clock=clock_desc)
            )
            if self.state is not None and self.state.winner is None and not self.history:
                is_human = self.var_mode.get() == "human"
                self.lbl_ai_move.configure(text=self._t("new_game"), fg=ACCENT_GOLD)
                if not self.ai_is_first:
                    self.lbl_think_status.configure(
                        text=self._t("your_turn_human") if is_human else self._t("your_turn_online")
                    )
                else:
                    self.lbl_think_status.configure(text=self._t("ai_first_think"))
            return
        wr = float(ev.get("winrate_pct", 50.0))
        iters = int(ev.get("iterations", 0))
        reused_v = int(ev.get("reused_visits", 0))
        solver_st = str(ev.get("solver_status", "none"))
        elapsed = float(ev.get("response_seconds", 0.0))
        move = tuple(ev["move"])
        alg = ev["algebraic"]
        self.lbl_winrate.configure(text=self._t("winrate_fmt", wr=wr))
        self._draw_winrate_bar(wr)
        rem = max(0.0, self.game_seconds - self.ai_spent)
        clock_str = (
            self._t("clock_fixed_run", spent=self.ai_spent)
            if self.use_fixed_seconds
            else self._t("clock_v3_run", rem=rem, tot=self.game_seconds)
        )
        solver_badge = solver_st.upper() if solver_st != "none" else "normal"
        self.lbl_tel_detail.configure(
            text=self._t("tel_run", solver=solver_badge, iters=iters, reused=reused_v, clock=clock_str)
        )
        if self.state is not None and self.state.winner is None:
            if move == (-1, -1):
                if self.swap_rule == "swap_pieces" and self.state.swapped_stone is not None:
                    dest = format_algebraic(self.state.swapped_stone).upper()
                    self.lbl_ai_move.configure(text=self._t("swap_dest", dest=dest), fg=ACCENT_GOLD)
                else:
                    self.lbl_ai_move.configure(text=self._t("swap_plain"), fg=ACCENT_GOLD)
            else:
                prefix = self._t("ai_move_human") if self.var_mode.get() == "human" else self._t("ai_move_online")
                self.lbl_ai_move.configure(text=f"{prefix} {alg.upper()}  ({move[0]}, {move[1]})", fg=ACCENT_GOLD)
            wait_msg = self._t("wait_human") if self.var_mode.get() == "human" else self._t("wait_online")
            suffix = self._t("ponder_suffix") if self.pondering else ""
            self.lbl_think_status.configure(text=self._t("elapsed_fmt", el=elapsed, wait=wait_msg) + suffix)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TProgressbar", troughcolor=BG_ROOT, background=ACCENT_GOLD, thickness=9)

        main = tk.Frame(self.root, bg=BG_ROOT)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left = tk.Frame(main, bg=BG_ROOT)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        top_bar = tk.Frame(left, bg=BG_PANEL)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        self.lbl_players = tk.Label(
            top_bar,
            text="",
            bg=BG_PANEL,
            fg=FG_TEXT,
            font=("Segoe UI", 11, "bold"),
            padx=12,
            pady=8,
            anchor="w",
        )
        self.lbl_players.pack(side=tk.LEFT, fill=tk.X, expand=True)

        lang_box = tk.Frame(top_bar, bg=BG_PANEL, padx=8)
        lang_box.pack(side=tk.RIGHT)
        self.btn_lang_en = tk.Button(
            lang_box,
            text="EN",
            command=lambda: self.set_language("en"),
            bg=ACCENT_BLUE if self.lang == "en" else BG_CARD,
            fg="#ffffff" if self.lang == "en" else FG_MUTED,
            activebackground="#2563eb",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=9,
            pady=3,
        )
        self.btn_lang_en.pack(side=tk.LEFT, padx=(0, 3))
        self.btn_lang_ko = tk.Button(
            lang_box,
            text="한국어",
            command=lambda: self.set_language("ko"),
            bg=ACCENT_BLUE if self.lang == "ko" else BG_CARD,
            fg="#ffffff" if self.lang == "ko" else FG_MUTED,
            activebackground="#2563eb",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=9,
            pady=3,
        )
        self.btn_lang_ko.pack(side=tk.LEFT)

        self.canvas = tk.Canvas(left, bg="#131c2e", highlightthickness=1, highlightbackground="#334155")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.redraw_board())
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Leave>", self._on_mouse_leave)
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # Right sidebar
        right = tk.Frame(main, bg=BG_PANEL, width=self._sidebar_width)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        right.pack_propagate(False)

        # --- Big Status / AI Move Banner ---
        banner = tk.Frame(right, bg=BG_CARD, padx=12, pady=10, highlightbackground=ACCENT_GOLD, highlightthickness=1)
        banner.pack(fill=tk.X, padx=10, pady=(10, 6))

        self.lbl_turn_banner = tk.Label(banner, text="Turn 1", bg=BG_CARD, fg=FG_MUTED, font=("Segoe UI", 10, "bold"), anchor="w")
        self.lbl_turn_banner.pack(fill=tk.X)

        self.lbl_ai_move = tk.Label(
            banner,
            text=self._t("waiting"),
            bg=BG_CARD,
            fg=ACCENT_GOLD,
            font=("Segoe UI", 17, "bold"),
            anchor="w",
            pady=3,
        )
        self.lbl_ai_move.pack(fill=tk.X)

        self.lbl_think_status = tk.Label(banner, text="", bg=BG_CARD, fg=FG_TEXT, font=("Segoe UI", 9), anchor="w")
        self.lbl_think_status.pack(fill=tk.X)

        self.progress = ttk.Progressbar(banner, mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X, pady=(6, 0))

        # --- Telemetry Card ---
        tel_card = tk.Frame(right, bg=BG_CARD, padx=12, pady=7)
        tel_card.pack(fill=tk.X, padx=10, pady=(0, 6))

        self.lbl_winrate = tk.Label(tel_card, text=self._t("winrate_empty"), bg=BG_CARD, fg=FG_TEXT, font=("Segoe UI", 10, "bold"), anchor="w")
        self.lbl_winrate.pack(fill=tk.X)

        self.wr_canvas = tk.Canvas(tel_card, height=11, bg="#0f172a", highlightthickness=0)
        self.wr_canvas.pack(fill=tk.X, pady=(3, 5))

        self.lbl_tel_detail = tk.Label(
            tel_card,
            text="",
            bg=BG_CARD,
            fg=FG_MUTED,
            font=("Consolas", 9),
            justify="left",
            anchor="w",
        )
        self.lbl_tel_detail.pack(fill=tk.X)

        # --- Action Buttons ---
        act_frame = tk.Frame(right, bg=BG_PANEL)
        act_frame.pack(fill=tk.X, padx=10, pady=(0, 6))

        self.btn_swap = tk.Button(
            act_frame, text=self._t("btn_swap"), command=self._on_swap_click,
            bg="#475569", fg=FG_TEXT, activebackground="#64748b", activeforeground=FG_TEXT,
            relief=tk.FLAT, font=("Segoe UI", 9, "bold"), pady=5, state=tk.DISABLED,
        )
        self.btn_swap.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))

        self.btn_undo = tk.Button(
            act_frame, text=self._t("btn_undo"), command=self._on_undo_click,
            bg="#475569", fg=FG_TEXT, activebackground="#64748b", activeforeground=FG_TEXT,
            relief=tk.FLAT, font=("Segoe UI", 9, "bold"), pady=5,
        )
        self.btn_undo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3)

        self.btn_save = tk.Button(
            act_frame, text=self._t("btn_save"), command=self._on_manual_save,
            bg="#2563eb", fg=FG_TEXT, activebackground="#3b82f6", activeforeground=FG_TEXT,
            relief=tk.FLAT, font=("Segoe UI", 9, "bold"), pady=5,
        )
        self.btn_save.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

        # --- View & Pondering Options ---
        opt_frame = tk.Frame(right, bg=BG_CARD, padx=10, pady=5)
        opt_frame.pack(fill=tk.X, padx=10, pady=(0, 6))

        opt_row1 = tk.Frame(opt_frame, bg=BG_CARD)
        opt_row1.pack(fill=tk.X)
        self.chk_coords = tk.Checkbutton(
            opt_row1, text=self._t("chk_coords"), variable=self.var_show_coords,
            command=lambda: (self._refresh_ui_state(), self.redraw_board()),
            bg=BG_CARD, fg=FG_TEXT, selectcolor=BG_ROOT,
            activebackground=BG_CARD, activeforeground=FG_TEXT, font=("Segoe UI", 9),
        )
        self.chk_coords.pack(side=tk.LEFT, padx=(0, 6))
        self.chk_nums = tk.Checkbutton(
            opt_row1, text=self._t("chk_nums"), variable=self.var_show_numbers,
            command=lambda: (self._refresh_ui_state(), self.redraw_board()),
            bg=BG_CARD, fg=FG_TEXT, selectcolor=BG_ROOT,
            activebackground=BG_CARD, activeforeground=FG_TEXT, font=("Segoe UI", 9),
        )
        self.chk_nums.pack(side=tk.LEFT, padx=(0, 6))
        self.chk_transpose = tk.Checkbutton(
            opt_row1, text=self._t("chk_transpose"), variable=self.var_transpose,
            command=lambda: (self._refresh_ui_state(), self.redraw_board()),
            bg=BG_CARD, fg=FG_TEXT, selectcolor=BG_ROOT,
            activebackground=BG_CARD, activeforeground=FG_TEXT, font=("Segoe UI", 9),
        )
        self.chk_transpose.pack(side=tk.LEFT, padx=(0, 6))

        self.chk_ponder = tk.Checkbutton(
            opt_frame, text=self._t("chk_ponder"), variable=self.var_ponder,
            command=self._on_ponder_toggle, bg=BG_CARD, fg=ACCENT_GOLD, selectcolor=BG_ROOT,
            activebackground=BG_CARD, activeforeground=ACCENT_GOLD, font=("Segoe UI", 9, "bold"), anchor="w",
        )
        self.chk_ponder.pack(fill=tk.X, pady=(2, 0))

        # --- Interactive Game & User Custom Settings Card ---
        self.cfg_frame = tk.LabelFrame(right, text=self._t("cfg_frame"), bg=BG_PANEL, fg=FG_MUTED, font=("Segoe UI", 9, "bold"), padx=8, pady=6)
        cfg = self.cfg_frame
        cfg.pack(fill=tk.X, padx=10, pady=(0, 6))

        # Mode switch
        rm = tk.Frame(cfg, bg=BG_PANEL)
        rm.pack(fill=tk.X, pady=2)
        self.lbl_mode = tk.Label(rm, text=self._t("lbl_mode"), bg=BG_PANEL, fg=FG_TEXT, width=6, anchor="w", font=("Segoe UI", 9))
        self.lbl_mode.pack(side=tk.LEFT)
        self.rad_human = tk.Radiobutton(
            rm, text=self._t("rad_human"), variable=self.var_mode, value="human", command=self._on_mode_change,
            bg=BG_PANEL, fg=ACCENT_GREEN, selectcolor=BG_ROOT, activebackground=BG_PANEL, font=("Segoe UI", 9, "bold"),
        )
        self.rad_human.pack(side=tk.LEFT)
        self.rad_online = tk.Radiobutton(
            rm, text=self._t("rad_online"), variable=self.var_mode, value="online", command=self._on_mode_change,
            bg=BG_PANEL, fg=FG_TEXT, selectcolor=BG_ROOT, activebackground=BG_PANEL, font=("Segoe UI", 9),
        )
        self.rad_online.pack(side=tk.LEFT, padx=(6, 0))

        # Difficulty presets (quick apply)
        rp = tk.Frame(cfg, bg=BG_PANEL)
        rp.pack(fill=tk.X, pady=2)
        self.lbl_preset = tk.Label(rp, text=self._t("lbl_preset"), bg=BG_PANEL, fg=FG_TEXT, width=6, anchor="w", font=("Segoe UI", 9))
        self.lbl_preset.pack(side=tk.LEFT)
        self.preset_box = ttk.Combobox(
            rp,
            textvariable=self.var_preset,
            values=[PRESET_LABELS[self.lang][k] for k, _ in DIFFICULTY_PRESETS_SPEC],
            state="readonly",
            width=22,
        )
        self.preset_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.preset_box.bind("<<ComboboxSelected>>", self._on_preset_selected)

        # Board size + Opponent name + Threads
        r1 = tk.Frame(cfg, bg=BG_PANEL)
        r1.pack(fill=tk.X, pady=2)
        self.lbl_board = tk.Label(r1, text=self._t("lbl_board"), bg=BG_PANEL, fg=FG_TEXT, width=6, anchor="w", font=("Segoe UI", 9))
        self.lbl_board.pack(side=tk.LEFT)
        for sz in ("7", "9", "11"):
            tk.Radiobutton(
                r1, text=f"{sz}×{sz}", variable=self.var_board_size, value=sz,
                bg=BG_PANEL, fg=FG_TEXT, selectcolor=BG_ROOT, activebackground=BG_PANEL, font=("Segoe UI", 9),
            ).pack(side=tk.LEFT)
        self.lbl_threads = tk.Label(r1, text=self._t("lbl_threads"), bg=BG_PANEL, fg=FG_TEXT, font=("Segoe UI", 9))
        self.lbl_threads.pack(side=tk.LEFT, padx=(8, 2))
        tk.Entry(r1, textvariable=self.var_workers, bg=BG_CARD, fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT, width=4).pack(side=tk.LEFT)

        r1b = tk.Frame(cfg, bg=BG_PANEL)
        r1b.pack(fill=tk.X, pady=2)
        self.lbl_opponent = tk.Label(r1b, text=self._t("lbl_opponent"), bg=BG_PANEL, fg=FG_TEXT, width=6, anchor="w", font=("Segoe UI", 9))
        self.lbl_opponent.pack(side=tk.LEFT)
        tk.Entry(r1b, textvariable=self.var_opponent, bg=BG_CARD, fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # AI Side
        r2 = tk.Frame(cfg, bg=BG_PANEL)
        r2.pack(fill=tk.X, pady=2)
        self.lbl_side = tk.Label(r2, text=self._t("lbl_side"), bg=BG_PANEL, fg=FG_TEXT, width=6, anchor="w", font=("Segoe UI", 9))
        self.lbl_side.pack(side=tk.LEFT)
        self.rad_first = tk.Radiobutton(
            r2, text=self._t("rad_first"), variable=self.var_side, value="first",
            bg=BG_PANEL, fg=ACCENT_RED_LIGHT, selectcolor=BG_ROOT, activebackground=BG_PANEL, font=("Segoe UI", 9),
        )
        self.rad_first.pack(side=tk.LEFT)
        self.rad_second = tk.Radiobutton(
            r2, text=self._t("rad_second"), variable=self.var_side, value="second",
            bg=BG_PANEL, fg=ACCENT_BLUE_LIGHT, selectcolor=BG_ROOT, activebackground=BG_PANEL, font=("Segoe UI", 9),
        )
        self.rad_second.pack(side=tk.LEFT, padx=(6, 0))

        # Custom clock
        r3 = tk.Frame(cfg, bg=BG_PANEL)
        r3.pack(fill=tk.X, pady=2)
        self.rad_v3 = tk.Radiobutton(
            r3, text=self._t("rad_v3"), variable=self.var_clock_mode, value="v3",
            bg=BG_PANEL, fg=FG_TEXT, selectcolor=BG_ROOT, activebackground=BG_PANEL, font=("Segoe UI", 9),
        )
        self.rad_v3.pack(side=tk.LEFT)
        tk.Entry(r3, textvariable=self.var_game_seconds, bg=BG_CARD, fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT, width=5).pack(side=tk.LEFT, padx=(2, 8))
        self.rad_fixed = tk.Radiobutton(
            r3, text=self._t("rad_fixed"), variable=self.var_clock_mode, value="fixed",
            bg=BG_PANEL, fg=FG_TEXT, selectcolor=BG_ROOT, activebackground=BG_PANEL, font=("Segoe UI", 9),
        )
        self.rad_fixed.pack(side=tk.LEFT)
        tk.Entry(r3, textvariable=self.var_fixed_seconds, bg=BG_CARD, fg=FG_TEXT, insertbackground=FG_TEXT, relief=tk.FLAT, width=4).pack(side=tk.LEFT, padx=(2, 0))

        # Swap rule
        r4 = tk.Frame(cfg, bg=BG_PANEL)
        r4.pack(fill=tk.X, pady=2)
        self.lbl_swap = tk.Label(r4, text=self._t("lbl_swap"), bg=BG_PANEL, fg=FG_TEXT, width=6, anchor="w", font=("Segoe UI", 9))
        self.lbl_swap.pack(side=tk.LEFT)
        self.rad_pieces = tk.Radiobutton(
            r4, text=self._t("rad_pieces"), variable=self.var_swap_rule, value="swap_pieces",
            bg=BG_PANEL, fg=FG_TEXT, selectcolor=BG_ROOT, activebackground=BG_PANEL, font=("Segoe UI", 9),
        )
        self.rad_pieces.pack(side=tk.LEFT)
        self.rad_sides = tk.Radiobutton(
            r4, text=self._t("rad_sides"), variable=self.var_swap_rule, value="swap_sides",
            bg=BG_PANEL, fg=FG_TEXT, selectcolor=BG_ROOT, activebackground=BG_PANEL, font=("Segoe UI", 9),
        )
        self.rad_sides.pack(side=tk.LEFT, padx=(4, 0))

        self.btn_new = tk.Button(
            cfg, text=self._t("btn_new"), command=self.start_new_game,
            bg="#059669", fg=FG_TEXT, activebackground="#10b981", activeforeground=FG_TEXT,
            relief=tk.FLAT, font=("Segoe UI", 10, "bold"), pady=6,
        )
        self.btn_new.pack(fill=tk.X, pady=(6, 0))

        # --- Move History Log ---
        hist_frame = tk.Frame(right, bg=BG_PANEL)
        hist_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))
        self.lbl_history = tk.Label(hist_frame, text=self._t("lbl_history"), bg=BG_PANEL, fg=FG_MUTED, font=("Segoe UI", 9, "bold"), anchor="w")
        self.lbl_history.pack(fill=tk.X)

        self.hist_list = tk.Listbox(
            hist_frame, bg=BG_CARD, fg=FG_TEXT, selectbackground="#354966",
            relief=tk.FLAT, font=("Consolas", 9), activestyle="none",
        )
        sb = tk.Scrollbar(hist_frame, orient=tk.VERTICAL, command=self.hist_list.yview)
        self.hist_list.configure(yscrollcommand=sb.set)
        self.hist_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    # ------------------------------------------------------------------
    # Presets & Mode Handlers
    # ------------------------------------------------------------------

    def _on_mode_change(self) -> None:
        if self.var_mode.get() == "human":
            if self.var_opponent.get() in {"", "Davis 10", "MoHex 3", "OnlineOpponent"}:
                self.var_opponent.set("Human")
        else:
            if self.var_opponent.get() in {"", "Human"}:
                self.var_opponent.set("MoHex 3")

    def _on_preset_selected(self, _event=None) -> None:
        selected = self.var_preset.get()
        for key, _ in DIFFICULTY_PRESETS_SPEC:
            if selected in {PRESET_LABELS["en"][key], PRESET_LABELS["ko"][key]}:
                self._preset_key = key
                break
        preset = DIFFICULTY_PRESETS.get(selected)
        if not preset:
            return
        self.var_clock_mode.set(preset["clock_mode"])
        self.var_fixed_seconds.set(preset["fixed_seconds"])
        self.var_game_seconds.set(preset["game_seconds"])
        self.var_workers.set(preset["workers"])
        self.var_ponder.set(preset["ponder"])

    # ------------------------------------------------------------------
    # Engine Lifecycle & Pondering
    # ------------------------------------------------------------------

    def _close_engine(self) -> None:
        self._stop_ponder()
        if self.engine is not None:
            try:
                self.engine.close()
            except Exception:
                pass
            self.engine = None

    def _start_ponder(self) -> None:
        if (
            not self.var_ponder.get()
            or self.thinking
            or self.engine is None
            or self.state is None
            or self.state.winner is not None
            or self.state.actor == self.ai_label
        ):
            return
        if self.engine.process.poll() is not None or self.engine.process.stdin is None:
            return
        try:
            pmsg = "PONDER" + self.state.message()[2:]
            self.engine.process.stdin.write(pmsg + "\n")
            self.engine.process.stdin.flush()
            self.pondering = True
        except OSError:
            self.pondering = False

    def _stop_ponder(self) -> None:
        if not self.pondering:
            return
        self.pondering = False
        if self.engine is None or self.engine.process.poll() is not None or self.engine.process.stdin is None:
            return
        try:
            self.engine.process.stdin.write("STOP_PONDER\n")
            self.engine.process.stdin.flush()
        except OSError:
            pass

    def _on_ponder_toggle(self) -> None:
        if self.var_ponder.get():
            self._start_ponder()
        else:
            self._stop_ponder()

    def _current_budget_cfg(self) -> tuple[bool, float, float, int, dict]:
        use_fixed = self.var_clock_mode.get() == "fixed"
        try:
            game_secs = max(10.0, float(self.var_game_seconds.get()))
        except ValueError:
            game_secs = 300.0
        try:
            fixed_secs = max(0.1, float(self.var_fixed_seconds.get()))
        except ValueError:
            fixed_secs = 2.0
        try:
            workers = max(1, min(32, int(self.var_workers.get())))
        except ValueError:
            workers = int(self.args.workers)
        budget_cfg = {
            "mode": "time" if use_fixed else "game_time",
            "game_seconds": game_secs,
            "expected_actor_moves": int(self.args.expected_moves),
            "minimum_future_actor_moves": 8,
            "io_reserve_seconds": 0.05,
            "response_margin_seconds": 5.0,
            "response_timeout": max(30.0, (fixed_secs if use_fixed else 30.0) + 15.0),
        }
        return (use_fixed, game_secs, fixed_secs, workers, budget_cfg)

    def start_new_game(self) -> None:
        self.session_token += 1
        self.thinking = False
        self._close_engine()

        try:
            self.size = max(5, min(15, int(self.var_board_size.get())))
        except ValueError:
            self.size = 11
        self.opp_label = self.var_opponent.get().strip() or ("Human" if self.var_mode.get() == "human" else "Opponent")
        self.ai_is_first = self.var_side.get() == "first"
        self.swap_rule = self.var_swap_rule.get()
        self.red_name = self.ai_label if self.ai_is_first else self.opp_label
        self.blue_name = self.opp_label if self.ai_is_first else self.ai_label

        use_fixed, game_secs, fixed_secs, workers, budget_cfg = self._current_budget_cfg()
        self.use_fixed_seconds = use_fixed
        self.game_seconds = game_secs
        self.fixed_seconds = fixed_secs
        self.workers = workers
        self.budget_cfg = budget_cfg

        cmd = [
            str(self.exe),
            "--policy", self.args.policy,
            "--workers", str(workers),
            "--game-seconds", str(game_secs),
            "--node-cap", str(self.args.node_cap),
            "--memory-mb", str(self.args.memory_mb),
            "--shared-tree", str(1 if workers > 1 else 0),
            "--solver", "1",
            "--two-dist", "1",
            "--pat-prior", "1",
            "--pat-rollout", "1",
            "--pat-temp", str(self.args.pat_temp),
            "--opening-book", "1",
            "--swap", str(self.args.swap),
            "--seed", str(self.args.seed),
        ]
        if use_fixed:
            cmd += ["--seconds", str(fixed_secs)]
        self.engine_cmd = cmd
        try:
            self.engine = NativeProcess(cmd)
        except Exception as err:
            messagebox.showerror(self._t("err_title"), self._t("err_body", err=err))
            return

        self.history = []
        self.last_ai_event = None
        self.ai_spent = 0.0
        self.ai_requests = 0
        self.saved_for_game = False
        self.hover_cell = None
        self.state = BattleReferee(self.size, self.red_name, self.blue_name, swap_rule=self.swap_rule)

        self.hist_list.delete(0, tk.END)
        self.progress["value"] = 0
        self._draw_winrate_bar(None)
        self._refresh_telemetry_labels()

        self._refresh_ui_state()
        self.redraw_board()
        self._maybe_trigger_ai()

    def _rebuild_state(self) -> None:
        st = BattleReferee(self.size, self.red_name, self.blue_name, swap_rule=self.swap_rule)
        for ev in self.history:
            st.play(tuple(ev["move"]))
        self.state = st
        self.ai_spent = sum(ev["response_seconds"] for ev in self.history if ev["actor"] == self.ai_label)
        self.ai_requests = sum(1 for ev in self.history if ev["actor"] == self.ai_label)
        ai_evs = [ev for ev in self.history if ev["actor"] == self.ai_label]
        self.last_ai_event = ai_evs[-1] if ai_evs else None
        self.hist_list.delete(0, tk.END)
        for ev in self.history:
            self._append_history_row(ev)

    def _append_history_row(self, ev: dict) -> None:
        tag = "AI" if ev["actor"] == self.ai_label else (self._t("tag_me") if self.var_mode.get() == "human" else self._t("tag_opp"))
        extra = ""
        if "winrate_pct" in ev:
            extra = f" | {ev['winrate_pct']:.1f}% ({ev['response_seconds']:.1f}s)"
        self.hist_list.insert(tk.END, f"#{ev['turn']:2d} [{ev['colour']}] {tag:3s}: {ev['algebraic'].upper():4s}{extra}")
        self.hist_list.see(tk.END)

    def _refresh_ui_state(self) -> None:
        if self.state is None:
            return
        red_p = self.state.players[Colour.RED]
        blue_p = self.state.players[Colour.BLUE]
        orient_r = self._t("orient_lr") if self.var_transpose.get() else self._t("orient_tb")
        orient_b = self._t("orient_tb") if self.var_transpose.get() else self._t("orient_lr")
        self.lbl_players.configure(
            text=f"  ● RED ({orient_r}): {red_p}    |    ● BLUE ({orient_b}): {blue_p}"
        )

        if self.state.winner is not None:
            self.lbl_turn_banner.configure(text=self._t("game_over", n=len(self.history)), fg=ACCENT_GREEN)
            if self.var_mode.get() == "human":
                win_msg = self._t("human_win") if self.state.winner != self.ai_label else self._t("ai_win")
            else:
                win_msg = self._t("winner_fmt", w=self.state.winner)
            self.lbl_ai_move.configure(text=win_msg, fg=ACCENT_GREEN)
            self.lbl_think_status.configure(text=self._t("win_chain_note"))
            self.btn_swap.configure(state=tk.DISABLED)
            self.btn_undo.configure(state=tk.NORMAL)
            if not self.saved_for_game:
                self._save_record(silent=True)
                self.saved_for_game = True
            return

        actor = self.state.actor
        col_name = "RED" if self.state.colour == Colour.RED else "BLUE"
        is_ai_turn = actor == self.ai_label
        self.lbl_turn_banner.configure(
            text=self._t("turn_fmt", t=self.state.turn, actor=actor, col=col_name),
            fg=ACCENT_RED_LIGHT if self.state.colour == Colour.RED else ACCENT_BLUE_LIGHT,
        )
        can_swap = (not self.thinking) and (not is_ai_turn) and (self.state.turn == 2) and (int(self.args.swap) == 1)
        self.btn_swap.configure(state=tk.NORMAL if can_swap else tk.DISABLED)
        self.btn_undo.configure(state=tk.DISABLED if self.thinking or not self.history else tk.NORMAL)

    # ------------------------------------------------------------------
    # AI Background Thinking
    # ------------------------------------------------------------------

    def _maybe_trigger_ai(self) -> None:
        if self.state is None or self.state.winner is not None or self.thinking:
            return
        if self.state.actor != self.ai_label or self.engine is None:
            return

        self.thinking = True
        self.pondering = False
        token = self.session_token
        alloc = move_budget(self.budget_cfg, self.ai_spent, self.ai_requests)
        msg = self.state.message()
        if not self.use_fixed_seconds:
            msg = (
                "V3" + msg[2:] + ";"
                + format(alloc["assigned_search_seconds"], ".17g") + ";"
                + format(alloc["remaining_seconds"], ".17g")
            )
            self.think_alloc = float(alloc["assigned_search_seconds"])
        else:
            self.think_alloc = float(self.fixed_seconds)

        timeout = max(30.0, float(alloc["timeout_seconds"]) + 10.0)
        self.think_start = time.perf_counter()
        self.progress["value"] = 0
        self.lbl_ai_move.configure(text=self._t("ai_thinking"), fg=ACCENT_GOLD)
        self.lbl_think_status.configure(text=self._t("target_time", sec=self.think_alloc, w=self.workers))
        self._refresh_ui_state()
        self._tick_thinking(token)

        engine = self.engine
        q = self._result_queue

        def worker() -> None:
            try:
                prev_moves = sum(1 for t in engine.telemetry if t.get("kind") == "hex_search_move")
                move, elapsed = engine.request(msg, timeout)
                tel = {}
                for _ in range(15):
                    with engine._lock:
                        mv_tels = [t for t in engine.telemetry if t.get("kind") == "hex_search_move"]
                    if len(mv_tels) > prev_moves:
                        tel = mv_tels[-1]
                        break
                    time.sleep(0.002)
                q.put((token, move, elapsed, tel, None))
            except Exception as err:
                q.put((token, None, 0.0, {}, str(err)))

        threading.Thread(target=worker, daemon=True).start()

    def _tick_thinking(self, token: int) -> None:
        if not self.thinking or token != self.session_token:
            return
        while True:
            try:
                res_token, move, elapsed, tel, error = self._result_queue.get_nowait()
            except queue.Empty:
                break
            if res_token == self.session_token:
                self._on_ai_result(res_token, move, elapsed, tel, error)
                return
        el = time.perf_counter() - self.think_start
        pct = min(98.0, (el / max(0.2, self.think_alloc)) * 100.0)
        self.progress["value"] = pct
        self.lbl_think_status.configure(text=self._t("searching", el=el, alloc=self.think_alloc, w=self.workers))
        self.root.after(50, lambda: self._tick_thinking(token))

    def _on_ai_result(
        self,
        token: int,
        move: tuple[int, int] | None,
        elapsed: float,
        tel: dict,
        error: str | None,
    ) -> None:
        if token != self.session_token or self.state is None:
            return
        self.thinking = False
        self.progress["value"] = 100

        if error or move is None:
            self.lbl_ai_move.configure(text=self._t("engine_err"), fg=ACCENT_RED_LIGHT)
            self.lbl_think_status.configure(text=error or self._t("unknown_err"))
            self._refresh_ui_state()
            return

        self.ai_spent += elapsed
        self.ai_requests += 1

        col_char = Colour.get_char(self.state.colour)
        self.state.play(move)

        iters = int(tel.get("iterations", 0))
        cv = int(tel.get("chosen_visits", 0))
        cw = int(tel.get("chosen_wins", 0))
        solver_st = str(tel.get("solver_status", "none"))
        if cv > 0:
            wr = 100.0 * cw / cv
        elif "win" in solver_st.lower():
            wr = 100.0
        elif "loss" in solver_st.lower():
            wr = 0.0
        else:
            wr = 50.0
        reused_v = int(tel.get("reused_visits", 0))
        alg = format_algebraic(move)

        ev = {
            "turn": len(self.history) + 1,
            "actor": self.ai_label,
            "colour": col_char,
            "move": list(move),
            "algebraic": alg,
            "response_seconds": round(elapsed, 4),
            "winrate_pct": round(wr, 2),
            "iterations": iters,
            "reused_visits": reused_v,
            "solver_status": solver_st,
            "reason": str(tel.get("reason", "")),
        }
        self.history.append(ev)
        self.last_ai_event = ev
        self._append_history_row(ev)

        if self.state.winner is None and self.var_ponder.get():
            self._start_ponder()
        self._refresh_telemetry_labels()
        self._refresh_ui_state()
        self.redraw_board()

    # ------------------------------------------------------------------
    # User Mouse / Button Events
    # ------------------------------------------------------------------

    def _on_mouse_move(self, event) -> None:
        if self.state is None or self.state.winner is not None or self.thinking:
            return
        if self.state.actor == self.ai_label:
            return
        cell = self._pixel_to_cell(event.x, event.y)
        if cell is not None:
            r, c = cell
            if self.state.board.tiles[r][c].colour is not None:
                cell = None
        if cell != self.hover_cell:
            self.hover_cell = cell
            self.redraw_board()

    def _on_mouse_leave(self, _event) -> None:
        if self.hover_cell is not None:
            self.hover_cell = None
            self.redraw_board()

    def _on_canvas_click(self, event) -> None:
        if self.state is None or self.state.winner is not None or self.thinking:
            return
        if self.state.actor == self.ai_label:
            return
        cell = self._pixel_to_cell(event.x, event.y)
        if cell is None:
            return
        r, c = cell
        if self.state.board.tiles[r][c].colour is not None:
            return
        self._apply_opponent_move((r, c))

    def _on_swap_click(self) -> None:
        if self.state is None or self.state.winner is not None or self.thinking:
            return
        if self.state.actor == self.ai_label or self.state.turn != 2:
            return
        self._apply_opponent_move((-1, -1))

    def _apply_opponent_move(self, mv: tuple[int, int]) -> None:
        if self.state is None:
            return
        col_char = Colour.get_char(self.state.colour)
        actor = self.state.actor
        try:
            self.state.play(mv)
        except ValueError as err:
            messagebox.showwarning(self._t("illegal_title"), str(err))
            return
        ev = {
            "turn": len(self.history) + 1,
            "actor": actor,
            "colour": col_char,
            "move": list(mv),
            "algebraic": format_algebraic(mv),
            "response_seconds": 0.0,
        }
        self.history.append(ev)
        self._append_history_row(ev)
        self.hover_cell = None
        self._refresh_ui_state()
        self.redraw_board()
        self._maybe_trigger_ai()

    def _on_undo_click(self) -> None:
        if self.thinking or not self.history:
            return
        self._stop_ponder()
        if len(self.history) >= 2 and self.history[-1]["actor"] == self.ai_label:
            self.history.pop()
            self.history.pop()
        else:
            self.history.pop()
        self.saved_for_game = False
        self._rebuild_state()
        self.hover_cell = None
        self.lbl_ai_move.configure(text=self._t("undo_done"), fg=FG_TEXT)
        self.lbl_think_status.configure(text=self._t("undo_note"))
        self._refresh_ui_state()
        self.redraw_board()
        self._maybe_trigger_ai()

    def _on_manual_save(self) -> None:
        paths = self._save_record(silent=False)
        if paths:
            messagebox.showinfo(self._t("save_title"), self._t("save_body", p0=paths[0], p1=paths[1]))

    def _save_record(self, silent: bool = True) -> tuple[Path, Path] | None:
        if self.state is None:
            return None
        out_dir = Path(self.args.save_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_opp = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in self.opp_label).strip("_") or "opponent"
        stem = f"{ts}_{safe_opp}_{'first' if self.ai_is_first else 'second'}"
        winner = self.state.winner
        record = {
            "schema_version": 1,
            "timestamp_utc": ts,
            "board_size": self.size,
            "red": self.red_name,
            "blue": self.blue_name,
            "ai_side": "first" if self.ai_is_first else "second",
            "opponent": self.opp_label,
            "status": "completed" if winner else "in_progress",
            "winner": winner,
            "winning_colour": Colour.get_char(self.state.board.get_winner()) if winner else None,
            "turns": len(self.history),
            "moves": self.history,
            "final_board": self.state.board_text(),
            "engine_command": self.engine_cmd,
            "executable_sha256": sha256(self.exe),
            "environment": environment(),
        }
        json_path = out_dir / f"{stem}.json"
        sgf_path = out_dir / f"{stem}.sgf"
        json_path.write_text(json.dumps(record, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        sgf_path.write_text(
            export_sgf(self.size, self.red_name, self.blue_name, self.history, winner, swap_rule=self.swap_rule),
            encoding="utf-8",
        )
        if not silent:
            self.lbl_think_status.configure(text=self._t("saved_note", name=sgf_path.name))
        return (json_path, sgf_path)

    def _on_close(self) -> None:
        self.session_token += 1
        self.thinking = False
        self._close_engine()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Canvas Rendering
    # ------------------------------------------------------------------

    def _layout(self) -> tuple[float, float, float]:
        w = max(300.0, float(self.canvas.winfo_width()))
        h = max(300.0, float(self.canvas.winfo_height()))
        return compute_board_layout(w, h, self.size, padding=46.0)

    def _pixel_to_cell(self, px: float, py: float) -> tuple[int, int] | None:
        r, ox, oy = self._layout()
        return hit_test_hex(px, py, self.size, r, ox, oy, transpose=self.var_transpose.get())

    def _draw_winrate_bar(self, wr: float | None) -> None:
        c = self.wr_canvas
        c.delete("all")
        w = max(200, c.winfo_width() or 300)
        h = 11
        c.create_rectangle(0, 0, w, h, fill="#334155", outline="")
        if wr is None:
            return
        frac = max(0.0, min(1.0, wr / 100.0))
        color = ACCENT_GREEN if wr >= 55.0 else (ACCENT_GOLD if wr >= 45.0 else ACCENT_RED_LIGHT)
        c.create_rectangle(0, 0, int(w * frac), h, fill=color, outline="")
        c.create_line(w * 0.5, 0, w * 0.5, h, fill=FG_TEXT, width=1)

    def redraw_board(self) -> None:
        if self.state is None:
            return
        c = self.canvas
        c.delete("all")
        radius, ox, oy = self._layout()
        tr = self.var_transpose.get()
        n = self.size

        def edge_line(p0, p1, color: str) -> None:
            c.create_line(p0[0], p0[1], p1[0], p1[1], fill=color, width=max(6, int(radius * 0.36)), capstyle=tk.ROUND)

        tl = hex_center(0, 0, radius, ox, oy, tr)
        tr_pt = hex_center(0, n - 1, radius, ox, oy, tr)
        bl = hex_center(n - 1, 0, radius, ox, oy, tr)
        br = hex_center(n - 1, n - 1, radius, ox, oy, tr)
        off = radius * 1.05
        if not tr:
            edge_line((tl[0] - off * 0.4, tl[1] - off), (tr_pt[0] + off * 0.4, tr_pt[1] - off), ACCENT_RED)
            edge_line((bl[0] - off * 0.4, bl[1] + off), (br[0] + off * 0.4, br[1] + off), ACCENT_RED)
            edge_line((tl[0] - off, tl[1] - off * 0.2), (bl[0] - off, bl[1] + off * 0.2), ACCENT_BLUE)
            edge_line((tr_pt[0] + off, tr_pt[1] - off * 0.2), (br[0] + off, br[1] + off * 0.2), ACCENT_BLUE)
        else:
            edge_line((tl[0] - off, tl[1] - off * 0.2), (tr_pt[0] - off, tr_pt[1] + off * 0.2), ACCENT_RED)
            edge_line((bl[0] + off, bl[1] - off * 0.2), (br[0] + off, br[1] + off * 0.2), ACCENT_RED)
            edge_line((tl[0] - off * 0.4, tl[1] - off), (bl[0] + off * 0.4, bl[1] - off), ACCENT_BLUE)
            edge_line((tr_pt[0] - off * 0.4, tr_pt[1] + off), (br[0] + off * 0.4, br[1] + off), ACCENT_BLUE)

        move_num: dict[tuple[int, int], int] = {}
        last_pos: tuple[int, int] | None = None
        last_is_ai = False
        for ev in self.history:
            mv = tuple(ev["move"])
            if mv == (-1, -1):
                if self.swap_rule == "swap_pieces" and last_pos is not None:
                    r0, c0 = last_pos
                    move_num.pop((r0, c0), None)
                    swapped = (c0, r0)
                    move_num[swapped] = ev["turn"]
                    last_pos = swapped
                    last_is_ai = ev["actor"] == self.ai_label
            else:
                move_num[mv] = ev["turn"]
                last_pos = mv
                last_is_ai = ev["actor"] == self.ai_label

        win_cells: set[tuple[int, int]] = set()
        if self.state.winner is not None:
            wc = self.state.board.get_winner()
            if wc is not None:
                win_cells = set(self.state.board.winning_path(wc))

        show_coords = self.var_show_coords.get()
        show_nums = self.var_show_numbers.get()
        font_coord = ("Consolas", max(7, int(radius * 0.34)))
        font_num = ("Segoe UI", max(8, int(radius * 0.42)), "bold")
        font_axis = ("Segoe UI", max(9, int(radius * 0.42)), "bold")

        for col in range(n):
            lbl = chr(ord("a") + col)
            p_top = hex_center(0, col, radius, ox, oy, tr)
            p_bot = hex_center(n - 1, col, radius, ox, oy, tr)
            if not tr:
                c.create_text(p_top[0], p_top[1] - radius * 1.55, text=lbl, fill=ACCENT_RED_LIGHT, font=font_axis)
                c.create_text(p_bot[0], p_bot[1] + radius * 1.55, text=lbl, fill=ACCENT_RED_LIGHT, font=font_axis)
            else:
                c.create_text(p_top[0] - radius * 1.55, p_top[1], text=lbl, fill=ACCENT_RED_LIGHT, font=font_axis)
                c.create_text(p_bot[0] + radius * 1.55, p_bot[1], text=lbl, fill=ACCENT_RED_LIGHT, font=font_axis)

        for row in range(n):
            lbl = str(row + 1)
            p_left = hex_center(row, 0, radius, ox, oy, tr)
            p_right = hex_center(row, n - 1, radius, ox, oy, tr)
            if not tr:
                c.create_text(p_left[0] - radius * 1.55, p_left[1], text=lbl, fill=ACCENT_BLUE_LIGHT, font=font_axis)
                c.create_text(p_right[0] + radius * 1.55, p_right[1], text=lbl, fill=ACCENT_BLUE_LIGHT, font=font_axis)
            else:
                c.create_text(p_left[0], p_left[1] - radius * 1.55, text=lbl, fill=ACCENT_BLUE_LIGHT, font=font_axis)
                c.create_text(p_right[0], p_right[1] + radius * 1.55, text=lbl, fill=ACCENT_BLUE_LIGHT, font=font_axis)

        for r in range(n):
            for col in range(n):
                cx, cy = hex_center(r, col, radius, ox, oy, tr)
                tile_col = self.state.board.tiles[r][col].colour
                is_hover = self.hover_cell == (r, col)
                is_last = last_pos == (r, col)
                is_win = (r, col) in win_cells

                if tile_col == Colour.RED:
                    fill = ACCENT_RED
                elif tile_col == Colour.BLUE:
                    fill = ACCENT_BLUE
                else:
                    fill = CELL_HOVER if is_hover else CELL_EMPTY

                outline = ACCENT_GOLD if (is_win or is_last) else CELL_BORDER
                width = 3 if (is_win or is_last) else 1
                verts = hex_vertices(cx, cy, radius * 0.96)
                c.create_polygon(verts, fill=fill, outline=outline, width=width)

                if is_win:
                    ring_r = radius * 0.66
                    c.create_oval(cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r, outline=ACCENT_GOLD, width=2.5)
                elif is_last:
                    ring_r = radius * 0.68
                    ring_col = ACCENT_GOLD if last_is_ai else "#ffffff"
                    c.create_oval(cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r, outline=ring_col, width=2)

                if tile_col is not None and show_nums and (r, col) in move_num:
                    c.create_text(cx, cy, text=str(move_num[(r, col)]), fill="#ffffff", font=font_num)
                elif tile_col is None and show_coords:
                    c.create_text(cx, cy, text=format_algebraic((r, col)), fill="#718096" if not is_hover else FG_TEXT, font=font_coord)


def run_battle_gui(args) -> None:
    root = tk.Tk()
    HexBattleGUI(root, args)
    root.mainloop()
