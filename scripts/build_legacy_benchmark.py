"""Generate an auditable runtime adapter around the unchanged historical Hex algorithm.

This is a controlled historical-algorithm benchmark, not a source-exact original
executable. The source-exact original remains separately available via --legacy.
Only protocol/runtime scheduling, seed injection and telemetry are adapted. Every
replacement is guarded by an exact source match and written to a patch receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hexai.native import environment, resolve_compiler, sha256

ORIGINAL = ROOT / "deployment/agents/Group026/RAVE_TS.cpp"
ORIGINAL_LF_SHA256 = "3bcf831944b86847b2384ab4d85e451bf12e7890b3a17492e8ed617266287244"

RUNTIME = r'''
// Benchmark-only runtime adapter. Original selection, expansion, rollout,
// reward and zero-AMAF code below are preserved byte-for-byte (canonical LF).
#include <cstdint>
#include <iomanip>
struct BenchmarkRuntime {
    std::uint64_t seed = 378, iterations = 0, completed = 0, nodes = 0, rave_updates = 0;
    unsigned int workers = 1;
    int request_turn = 1;
    double seconds = 0, game_seconds = 300, allocated = -1, external_remaining = -1;
    bool iteration_mode = false, original_iteration_cap_reached = false;
    std::chrono::steady_clock::time_point deadline;
    std::vector<std::uint64_t> worker_iterations, worker_nodes, worker_amaf;
} benchmark;
'''

MAIN = r'''
double benchmark_number(const std::string& value) {
    std::size_t end = 0;
    double number = std::stod(value, &end);
    if (end != value.size() || !std::isfinite(number) || number < 0)
        throw std::invalid_argument("Expected a finite nonnegative number.");
    return number;
}
std::uint64_t benchmark_integer(const std::string& value) {
    if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos)
        throw std::invalid_argument("Expected an unsigned decimal integer.");
    return std::stoull(value);
}
int main(int argc, char* argv[]) {
    try {
        int first = 1;
        if (argc >= 3 && (std::string(argv[1]) == "R" || std::string(argv[1]) == "B")) {
            if (protocol_integer(argv[2]) != BOARD_SIZE) throw std::invalid_argument("Only 11x11 is supported.");
            first = 3;
        }
        for (int i = first; i < argc; ++i) {
            std::string key = argv[i];
            if (key == "--version") { std::cout << "hex-legacy-controlled-benchmark 1.0.0\n"; return 0; }
            if (i + 1 >= argc) throw std::invalid_argument("Missing option value.");
            std::string value = argv[++i];
            if (key == "--seed") benchmark.seed = benchmark_integer(value);
            else if (key == "--workers") {
                auto count = benchmark_integer(value);
                if (count < 1 || count > 64) throw std::invalid_argument("Workers must be 1 through 64.");
                benchmark.workers = static_cast<unsigned int>(count);
            } else if (key == "--iterations") {
                benchmark.iterations = benchmark_integer(value);
                if (benchmark.iterations < 1 || benchmark.iterations > 1000000000ULL)
                    throw std::invalid_argument("Iteration total must be 1 through 1000000000.");
                benchmark.iteration_mode = true;
            } else if (key == "--seconds") benchmark.seconds = benchmark_number(value);
            else if (key == "--game-seconds") benchmark.game_seconds = benchmark_number(value);
            else throw std::invalid_argument("Unknown benchmark option: " + key);
        }
        init_centrality();
        Agent agent(RED);
        double cumulative_used = 0;
        int previous_turn = 0;
        std::string line;
        while (std::getline(std::cin, line)) {
            if (line.empty()) continue;
            const auto started = std::chrono::steady_clock::now();
            if (line.back() == '\r') line.pop_back();
            std::vector<std::string> parts;
            std::stringstream input(line);
            std::string field;
            while (std::getline(input, field, ';')) parts.push_back(field);
            bool v3 = parts.size() == 9 && parts[0] == "V3";
            if (!v3 && !(parts.size() == 7 && parts[0] == "V2"))
                throw std::invalid_argument("Expected seven V2 or nine V3 fields.");
            std::string original_line = "V2";
            for (int i = 1; i < 7; ++i) original_line += ";" + parts[i];
            NativeRequest request = parse_request(original_line);
            if (parts[3] == "START" || request.turn <= previous_turn) cumulative_used = 0;
            benchmark.request_turn = request.turn;
            benchmark.completed = benchmark.nodes = benchmark.rave_updates = 0;
            benchmark.original_iteration_cap_reached = false;
            benchmark.worker_iterations.assign(benchmark.workers, 0);
            benchmark.worker_nodes.assign(benchmark.workers, 0);
            benchmark.worker_amaf.assign(benchmark.workers, 0);
            benchmark.external_remaining = v3 ? benchmark_number(parts[8]) : -1;
            double remaining = std::max(0.0, benchmark.game_seconds - cumulative_used);
            if (v3) remaining = std::min(benchmark.game_seconds, benchmark.external_remaining);
            benchmark.allocated = v3 ? std::min(benchmark_number(parts[7]), remaining) :
                (benchmark.iteration_mode ? remaining : std::min(agent.get_time_budget(request.turn), remaining));
            if (benchmark.seconds > 0) benchmark.allocated = std::min(benchmark.allocated, benchmark.seconds);
            // End the search before the outer response deadline. No selection math changes.
            const double margin = std::min(.010, benchmark.allocated * .05);
            benchmark.deadline = started + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                std::chrono::duration<double>(std::max(0.0, benchmark.allocated - margin)));
            apply_request(agent, request);
            if (agent.root_board.check_win(RED) || agent.root_board.check_win(BLUE))
                throw std::invalid_argument("Terminal board: no move is legal.");
            Point move = agent.get_best_move(request.turn, request.opponent);
            double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
            cumulative_used += seconds;
            previous_turn = request.turn;
            std::cout << move.x << ',' << move.y << std::endl;
            std::cerr << std::setprecision(10) << "{\"kind\":\"hex_search_move\",\"version\":\"controlled-legacy-1.0.0\","
                "\"policy\":\"controlled_historical_rave_ts\",\"protocol\":\"" << (v3 ? "V3" : "V2")
                << "\",\"seed\":" << benchmark.seed << ",\"turn\":" << request.turn
                << ",\"colour\":\"" << (request.colour == RED ? 'R' : 'B') << "\",\"move\":[" << move.x << ',' << move.y
                << "],\"reason\":\"" << (move.x < 0 ? "pie_rule_swap" : (benchmark.completed ? "search" : "tactic_or_budget_fallback"))
                << "\",\"iterations\":" << benchmark.completed << ",\"nodes\":" << benchmark.nodes
                << ",\"rave_updates\":" << benchmark.rave_updates << ",\"seconds\":" << seconds
                << ",\"game_seconds_used\":" << cumulative_used << ",\"effective_search_allowance_seconds\":" << benchmark.allocated
                << ",\"external_remaining_seconds\":" << benchmark.external_remaining
                << ",\"original_iteration_cap_reached\":" << (benchmark.original_iteration_cap_reached ? "true" : "false")
                << ",\"workers\":[";
            for (unsigned int w = 0; w < benchmark.workers; ++w) {
                if (w) std::cerr << ',';
                std::cerr << "{\"id\":" << w << ",\"iterations\":" << benchmark.worker_iterations[w]
                    << ",\"nodes\":" << benchmark.worker_nodes[w] << ",\"rave_updates\":" << benchmark.worker_amaf[w] << '}';
            }
            std::cerr << "]}" << std::endl;
            // Prevent the historical scheduler's synthetic swap charge from affecting fairness.
            agent.total_time_used = cumulative_used;
            benchmark.allocated = -1;
        }
        return 0;
    } catch (const std::exception& error) {
        // Error strings here are fixed source text or option names, never document contents.
        std::cerr << "Controlled legacy Hex error: " << error.what() << std::endl;
        return 2;
    }
}
'''


def canonical_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generate(source: Path, output: Path) -> dict:
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or any(output.is_relative_to((ROOT / part).resolve()) for part in ("engine", "deployment")):
        raise ValueError("Generated files must never overwrite historical directories.")
    original = source.read_text(encoding="utf-8")
    if canonical_hash(original) != ORIGINAL_LF_SHA256:
        raise ValueError("Historical source hash differs from the frozen source; adapter generation refused.")
    text = original
    patches = []

    def replace(label: str, before: str, after: str, count: int = 1):
        nonlocal text
        if text.count(before) != count:
            raise ValueError(f"Guarded patch {label}: expected {count} exact matches.")
        text = text.replace(before, after)
        patches.append({"label": label, "matches": count, "before_sha256": canonical_hash(before),
                        "after_sha256": canonical_hash(after), "before": before, "after": after})

    replace("runtime_instrumentation_globals", "const int BOARD_SIZE = 11;", RUNTIME + "\nconst int BOARD_SIZE = 11;")
    replace("seed_injection_not_selection_math", "thread_local std::mt19937 rng(std::random_device{}());",
            "thread_local std::mt19937 rng(378); // Seeded separately per controlled worker below.")
    replace("externally_controlled_move_allowance", "    double get_time_budget(int turn) {\n",
            "    double get_time_budget(int turn) {\n        if (benchmark.allocated >= 0) return benchmark.allocated;\n")
    replace("worker_telemetry_fields", "        int iterations;\n        std::map<Point, std::pair<double, double>> child_stats;",
            "        int iterations;\n        std::uint64_t nodes = 0, rave_updates = 0;\n        bool original_cap = false;\n        std::map<Point, std::pair<double, double>> child_stats;")
    replace("worker_id_and_seed", "double time_limit) {\n        auto start_time = std::chrono::high_resolution_clock::now();",
            "double time_limit, unsigned int worker_id) {\n"
            "        std::uint64_t position = 1469598103934665603ULL;\n"
            "        for (int m = 0; m < NUM_TILES; ++m) position = (position ^ (board.tile_colours[m] + 1)) * 1099511628211ULL;\n"
            "        std::seed_seq seeds{static_cast<unsigned int>(benchmark.seed), static_cast<unsigned int>(benchmark.seed >> 32),\n"
            "            static_cast<unsigned int>(position), static_cast<unsigned int>(position >> 32),\n"
            "            static_cast<unsigned int>(benchmark.request_turn), worker_id, static_cast<unsigned int>(turn)};\n"
            "        rng.seed(seeds);\n        (void)time_limit;\n        std::uint64_t rave_updates = 0;\n")
    replace("shared_deadline_and_total_iteration_runtime", "            if (iterations > 1500000) break;\n\n"
            "            if (iterations % 1000 == 0) {\n"
            "                auto now = std::chrono::high_resolution_clock::now();\n"
            "                std::chrono::duration<double> elapsed = now - start_time;\n"
            "                if (elapsed.count() > time_limit - 0.1) break;\n            }",
            "            if (iterations > 1500000) break; // Original algorithm safety limit retained.\n"
            "            if (benchmark.iteration_mode && static_cast<std::uint64_t>(iterations) >=\n"
            "                benchmark.iterations / benchmark.workers + (worker_id < benchmark.iterations % benchmark.workers ? 1 : 0)) break;\n"
            "            if (std::chrono::steady_clock::now() >= benchmark.deadline) break;")
    replace("observe_original_zero_amaf", "                        node->rave_visits++;", "                        node->rave_visits++;\n                        ++rave_updates;")
    replace("worker_telemetry_no_tree_change", "        result.iterations = iterations;",
            "        result.iterations = iterations;\n        result.nodes = node_pool.size();\n"
            "        result.rave_updates = rave_updates;\n        result.original_cap = iterations > 1500000;")
    replace("controlled_worker_count", "        const unsigned int num_threads = 8;", "        const unsigned int num_threads = benchmark.workers;")
    replace("pass_controlled_worker_id", "this, root_board, my_colour, opp_move, time_budget));",
            "this, root_board, my_colour, opp_move, time_budget, i));")
    replace("aggregate_runtime_telemetry", "        for (auto& f : futures) {\n            ThreadResult res = f.get();",
            "        unsigned int worker_id = 0;\n        for (auto& f : futures) {\n            ThreadResult res = f.get();\n"
            "            benchmark.completed += res.iterations; benchmark.nodes += res.nodes; benchmark.rave_updates += res.rave_updates;\n"
            "            benchmark.original_iteration_cap_reached = benchmark.original_iteration_cap_reached || res.original_cap;\n"
            "            benchmark.worker_iterations[worker_id] = res.iterations; benchmark.worker_nodes[worker_id] = res.nodes;\n"
            "            benchmark.worker_amaf[worker_id++] = res.rave_updates;")
    main_start = text.index("int main(int argc, char* argv[]) {")
    replace("protocol_and_runtime_main", text[main_start:], MAIN)
    # These complete algorithmic regions must remain exactly the historical bytes.
    unchanged = []
    for label, start, stop in (
        ("board_and_expansion", "class FastBoard {", "// ==========================================\n// 4. Agent Class"),
        ("selection_rollout_bridge_tactics", "    Node* select_child(Node* node) {", "    double get_time_budget(int turn) {"),
        ("tree_selection_and_expansion", "            Node* node = root;", "            Colour winner = simulate(node, sim_board, red_moves, blue_moves);"),
    ):
        prior = original[original.index(start):original.index(stop)]
        current = text[text.index(start):text.index(stop)]
        if current != prior:
            raise ValueError("Algorithm preservation assertion failed: " + label)
        unchanged.append({"region": label, "canonical_sha256": canonical_hash(prior), "unchanged": True})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    receipt = {"schema_version": 1, "kind": "controlled_historical_algorithm_runtime_adapter",
               "original_source": "deployment/agents/Group026/RAVE_TS.cpp",
               "original_source_sha256": sha256(source), "original_canonical_sha256": canonical_hash(original),
               "generated_source_sha256": sha256(output), "patches": patches,
               "unchanged_algorithm_regions": unchanged,
               "scope": "Protocol, seeded streams, workers, deadline polling, external budgets and telemetry only. Not a source-exact historical executable. The historical 1500001-iteration per-worker cap remains. No board, selection, expansion, rollout, reward, swap or tactical algorithm is repaired."}
    return receipt


def compiler_output_path(output: Path, windows: bool | None = None) -> Path:
    """MinGW may append .exe; compile explicitly, then install the exact pathname."""
    windows = os.name == "nt" if windows is None else windows
    if windows and output.suffix.lower() != ".exe":
        return output.with_name(output.name + ".compiler-output.exe")
    return output


def default_output_path(root: Path = ROOT) -> Path:
    """The same extensionless participant path is used in every frozen manifest."""
    return root / ".local/bin/legacy_benchmark"


def build_adapter(output: Path | None = None, compiler: str | None = None, generate_only: bool = False,
                  sanitizer: bool = False) -> dict:
    output = Path(output or default_output_path()).resolve()
    if any(output.is_relative_to((ROOT / part).resolve()) for part in ("engine", "deployment")):
        raise ValueError("Controlled adapter builds must not overwrite historical directories.")
    generated = output.with_name(output.name + ".cpp")
    patch_receipt = generate(ORIGINAL, generated)
    patch_path = output.with_name(output.name + ".patch.json")
    patch_path.write_text(json.dumps(patch_receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    if generate_only:
        return {"generated_source": str(generated), "patch_receipt": str(patch_path), **patch_receipt}
    command = resolve_compiler(compiler)
    version = subprocess.run(command + ["--version"], capture_output=True, text=True, timeout=20, check=True).stdout.strip()
    flags = ["-std=c++17", "-O3", "-pthread"]
    if sanitizer:
        if os.name == "nt":
            raise ValueError("Sanitizer verification requires a compatible Linux compiler/runtime.")
        flags = ["-std=c++17", "-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined", "-pthread"]
    if os.name == "nt" and "mingw" in (str(command[0]) + version).lower():
        flags += ["-static", "-static-libgcc", "-static-libstdc++"]
    compiled_output = compiler_output_path(output)
    full_command = command + flags + [str(generated), "-o", str(compiled_output)]
    compiled = subprocess.run(full_command, capture_output=True, text=True, timeout=180)
    if compiled.returncode:
        raise RuntimeError("Controlled legacy build failed:\n" + compiled.stderr[-12000:])
    if not compiled_output.is_file():
        raise RuntimeError("Compiler did not produce its explicitly requested executable: " + str(compiled_output))
    if compiled_output != output:
        # Both absolute paths share the explicitly requested parent directory.
        # Windows CreateProcess executes this PE file at the extensionless name.
        compiled_output.replace(output)
    receipt = {"schema_version": 1, "kind": "benchmark_legacy", "original_source_sha256": sha256(ORIGINAL),
               "original_canonical_sha256": ORIGINAL_LF_SHA256, "generated_source_sha256": sha256(generated),
               "patch_receipt": patch_path.name, "patch_receipt_sha256": sha256(patch_path),
               "compiler": command, "compiler_version": version, "command": full_command,
               "executable": str(output), "executable_sha256": sha256(output), "environment": environment(),
               "compiler_output": str(compiled_output),
               "installed_exact_requested_path": output.is_file(),
               "sanitizers": sanitizer, "unchanged_algorithm_regions": patch_receipt["unchanged_algorithm_regions"]}
    output.with_name(output.name + ".build.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compiler")
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--sanitizer", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build_adapter(args.output, args.compiler, args.generate_only, args.sanitizer), indent=2))
