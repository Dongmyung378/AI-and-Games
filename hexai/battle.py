"""Interactive online Hex battle assistant (for Davis 7/10, MoHex, HexGui, etc.) with SGF & JSON logging."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .evaluation import move_budget
from .native import NativeProcess, environment, executable_default, sha256
from .referee import Colour, Referee


def format_algebraic(move: tuple[int, int]) -> str:
    if move == (-1, -1):
        return "swap"
    row, col = move
    return f"{chr(ord('a') + col)}{row + 1}"


def parse_user_move(text: str, size: int) -> tuple[int, int]:
    s = text.strip().lower()
    if s in {"swap", "swap-pieces", "swap-sides"}:
        return (-1, -1)
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) != 2:
            raise ValueError("Use algebraic (e.g. f6) or row,col (e.g. 5,5).")
        r, c = int(parts[0]), int(parts[1])
        if not (0 <= r < size and 0 <= c < size):
            raise ValueError("Coordinate out of bounds.")
        return (r, c)
    if len(s) >= 2 and s[0].isalpha() and s[1:].isdigit():
        c = ord(s[0]) - ord("a")
        r = int(s[1:]) - 1
        if not (0 <= r < size and 0 <= c < size):
            raise ValueError("Coordinate out of bounds.")
        return (r, c)
    raise ValueError("Unrecognized move. Enter algebraic (e.g. f6), row,col (e.g. 5,5), swap, undo, or quit.")


def render_board(state: Referee, last_move: tuple[int, int] | None = None) -> str:
    n = state.board.size
    lines = []
    header = "    " + " ".join(chr(ord("a") + c) for c in range(n))
    lines.append("    === RED / BLACK: TOP (1) <-> BOTTOM (" + str(n) + ") ===")
    lines.append("    === BLUE / WHITE: LEFT (a) <-> RIGHT (" + chr(ord("a") + n - 1) + ") ===")
    lines.append(header)
    for r in range(n):
        indent = " " * r
        cells = []
        for c in range(n):
            col = state.board.tiles[r][c].colour
            ch = "R" if col == Colour.RED else ("B" if col == Colour.BLUE else ".")
            if last_move == (r, c):
                ch = ch.lower() if ch != "." else "*"
            cells.append(ch)
        lines.append(f"{indent}{r + 1:2d}  " + " ".join(cells) + f"  {r + 1}")
    return "\n".join(lines)


class BattleReferee(Referee):
    """Referee supporting both online swap-pieces (BGA/Little Golem/HexGui) and swap-sides."""

    def __init__(self, size: int, red: str, blue: str, swap_rule: str = "swap_pieces"):
        super().__init__(size, red, blue)
        if swap_rule not in {"swap_pieces", "swap_sides"}:
            raise ValueError("swap_rule must be 'swap_pieces' or 'swap_sides'.")
        self.swap_rule = swap_rule
        self.swapped_stone: tuple[int, int] | None = None

    def play(self, move):
        if move == (-1, -1) and self.swap_rule == "swap_pieces":
            if self.winner is not None:
                raise ValueError("Cannot play after a connecting path has won.")
            if self.turn != 2:
                raise ValueError("Swap is legal only at turn two.")
            first = self.previous_move
            if first is None or first == (-1, -1):
                raise ValueError("Cannot swap pieces without an opening stone.")
            r0, c0 = first
            self.board.set_tile_colour(r0, c0, None)
            self.board.set_tile_colour(c0, r0, Colour.BLUE)
            self.swapped_stone = (c0, r0)
            self.colour = Colour.RED
            self.previous_move = (-1, -1)
            self.turn += 1
            return
        super().play(move)


def export_sgf(
    size: int,
    red_name: str,
    blue_name: str,
    moves: list[dict],
    winner: str | None,
    swap_rule: str = "swap_sides",
) -> str:
    res = "B+" if winner == red_name else ("W+" if winner == blue_name else "?")
    swap_token = "swap-pieces" if swap_rule == "swap_pieces" else "swap-sides"
    tokens = [f"(;FF[4]GM[11]SZ[{size}]PB[{red_name}]PW[{blue_name}]RE[{res}]"]
    for ev in moves:
        c = "B" if ev["colour"] == "R" else "W"
        mv = tuple(ev["move"])
        coord = swap_token if mv == (-1, -1) else format_algebraic(mv)
        tokens.append(f";{c}[{coord}]")
    tokens.append(")\n")
    return "".join(tokens)


def run_battle(args) -> dict:
    size = args.board_size
    ai_side = args.side.lower()
    if ai_side not in {"first", "second", "red", "blue", "black", "white"}:
        raise ValueError("--side must be first|second|red|blue|black|white.")
    ai_is_first = ai_side in {"first", "red", "black"}

    ai_label = "hex-search-v1.2"
    opp_label = args.opponent
    red_name = ai_label if ai_is_first else opp_label
    blue_name = opp_label if ai_is_first else ai_label

    exe = Path(args.executable or executable_default()).resolve()
    use_fixed_seconds = args.seconds is not None
    budget_cfg = {
        "mode": "time" if use_fixed_seconds else "game_time",
        "game_seconds": args.game_seconds,
        "expected_actor_moves": args.expected_moves,
        "minimum_future_actor_moves": 8,
        "io_reserve_seconds": 0.05,
        "response_margin_seconds": 5.0,
        "response_timeout": max(30.0, (args.seconds or 30.0) + 15.0),
    }
    cmd = [
        str(exe),
        "--policy", args.policy,
        "--workers", str(args.workers),
        "--game-seconds", str(args.game_seconds),
        "--node-cap", str(args.node_cap),
        "--memory-mb", str(args.memory_mb),
        "--shared-tree", str(1 if args.workers > 1 else 0),
        "--solver", "1",
        "--two-dist", "1",
        "--pat-prior", "1",
        "--pat-rollout", "1",
        "--pat-temp", str(args.pat_temp),
        "--opening-book", "1",
        "--swap", str(args.swap),
        "--seed", str(args.seed),
    ]
    if use_fixed_seconds:
        cmd += ["--seconds", str(args.seconds)]

    budget_desc = (
        f"Fixed {args.seconds:.1f}s/move"
        if use_fixed_seconds
        else f"Adaptive V3 {args.game_seconds:.0f}s/game (~{args.game_seconds / args.expected_moves:.1f}s/move)"
    )
    print(f"\n[hex-search v1.2 Online Battle Assistant]")
    print(f"  Board     : {size}x{size}")
    print(f"  First (R) : {red_name}  (Top 1 <-> Bottom {size})")
    print(f"  Second(B) : {blue_name} (Left a <-> Right {chr(ord('a') + size - 1)})")
    print(f"  AI Budget : {budget_desc} | {args.workers} threads (Lock-Free Shared Tree) | RAM cap {args.memory_mb} MiB")
    print("  Commands  : algebraic (f6), row,col (5,5), swap, undo, quit\n")

    history: list[dict] = []
    ai_spent = 0.0
    ai_requests = 0
    swap_rule = getattr(args, "swap_rule", "swap_pieces")

    def rebuild_state() -> BattleReferee:
        st = BattleReferee(size, red_name, blue_name, swap_rule=swap_rule)
        for ev in history:
            st.play(tuple(ev["move"]))
        return st

    state = rebuild_state()
    with NativeProcess(cmd) as engine:
        while state.winner is None and state.turn <= size * size + 1:
            last_mv = tuple(history[-1]["move"]) if history else None
            print(render_board(state, last_mv if last_mv != (-1, -1) else None))
            actor = state.actor
            col_char = Colour.get_char(state.colour)
            print(f"\nTurn {state.turn} | To play: {actor} ({'RED/BLACK' if col_char == 'R' else 'BLUE/WHITE'})")

            if actor == ai_label:
                alloc = move_budget(budget_cfg, ai_spent, ai_requests)
                msg = state.message()
                if not use_fixed_seconds:
                    msg = (
                        "V3" + msg[2:] + ";"
                        + format(alloc["assigned_search_seconds"], ".17g") + ";"
                        + format(alloc["remaining_seconds"], ".17g")
                    )
                    print(
                        f"  [Thinking] V3 clock: {alloc['assigned_search_seconds']:.2f}s allocated "
                        f"({alloc['remaining_seconds']:.1f}s remaining of {args.game_seconds:.0f}s)...",
                        flush=True,
                    )
                else:
                    print(f"  [Thinking] Fixed {args.seconds:.2f}s...", flush=True)
                timeout = max(30.0, alloc["timeout_seconds"] + 10.0)
                move, elapsed = engine.request(msg, timeout)
                ai_spent += elapsed
                ai_requests += 1
                tel = engine.telemetry[-1] if engine.telemetry else {}
                iters = tel.get("iterations", 0)
                cv = tel.get("chosen_visits", 0)
                cw = tel.get("chosen_wins", 0)
                wr = (100.0 * cw / cv) if cv > 0 else 0.0
                solver_st = tel.get("solver_status", "none")
                reused_v = tel.get("reused_visits", 0)
                alg = format_algebraic(move)
                rem_after = max(0.0, args.game_seconds - ai_spent)
                rem_info = f"spent {ai_spent:.1f}s" if use_fixed_seconds else f"left {rem_after:.1f}s"
                print(
                    f"  >>> AI PLAYS: {alg.upper()}  (row,col={move[0]},{move[1]}) | "
                    f"winrate={wr:.1f}% | iters={iters:,} (+{reused_v:,} reused) | "
                    f"solver={solver_st} | {elapsed:.2f}s ({rem_info})"
                )
                state.play(move)
                history.append({
                    "turn": len(history) + 1, "actor": actor, "colour": col_char,
                    "move": list(move), "algebraic": alg, "response_seconds": round(elapsed, 4),
                    "winrate_pct": round(wr, 2), "iterations": iters, "solver_status": solver_st,
                })
            else:
                raw = input(f"  Enter {opp_label}'s move (e.g. f6 / swap / undo / quit): ").strip()
                if raw.lower() in {"q", "quit", "exit"}:
                    print("Battle aborted by user.")
                    break
                if raw.lower() == "undo":
                    if len(history) >= 2:
                        history.pop()
                        history.pop()
                        state = rebuild_state()
                        ai_spent = sum(ev["response_seconds"] for ev in history if ev["actor"] == ai_label)
                        ai_requests = sum(1 for ev in history if ev["actor"] == ai_label)
                        print("Undid last full turn pair.")
                    elif len(history) == 1:
                        history.pop()
                        state = rebuild_state()
                        ai_spent = sum(ev["response_seconds"] for ev in history if ev["actor"] == ai_label)
                        ai_requests = sum(1 for ev in history if ev["actor"] == ai_label)
                        print("Undid last move.")
                    else:
                        print("Nothing to undo.")
                    continue
                try:
                    mv = parse_user_move(raw, size)
                    state.play(mv)
                except ValueError as err:
                    print(f"  [Invalid move] {err}")
                    continue
                history.append({
                    "turn": len(history) + 1, "actor": actor, "colour": col_char,
                    "move": list(mv), "algebraic": format_algebraic(mv), "response_seconds": 0.0,
                })

    print("\n" + render_board(state, tuple(history[-1]["move"]) if history else None))
    winner = state.winner
    print(f"\n=== GAME OVER | Winner: {winner or 'unfinished'} | Turns: {len(history)} ===")

    out_dir = Path(args.save_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_opp = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in opp_label).strip("_") or "opponent"
    stem = f"{ts}_{safe_opp}_{'first' if ai_is_first else 'second'}"
    record = {
        "schema_version": 1,
        "timestamp_utc": ts,
        "board_size": size,
        "red": red_name,
        "blue": blue_name,
        "ai_side": "first" if ai_is_first else "second",
        "opponent": opp_label,
        "status": "completed" if winner else "aborted",
        "winner": winner,
        "winning_colour": Colour.get_char(state.board.get_winner()) if winner else None,
        "turns": len(history),
        "moves": history,
        "final_board": state.board_text(),
        "engine_command": cmd,
        "executable_sha256": sha256(exe),
        "environment": environment(),
    }
    json_path = out_dir / f"{stem}.json"
    sgf_path = out_dir / f"{stem}.sgf"
    json_path.write_text(json.dumps(record, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    sgf_path.write_text(export_sgf(size, red_name, blue_name, history, winner, swap_rule=swap_rule), encoding="utf-8")
    print(f"Saved match record: {json_path}")
    print(f"Saved SGF record  : {sgf_path}")
    return record
