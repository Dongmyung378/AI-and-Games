#!/usr/bin/env python3
"""Prepare a private CPU-only Kaggle verification script; never submit a job."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from hexai.evaluation import load_manifest, manifest_hash

KAGGLE_SOURCE_ROOT = "/kaggle/working/hex-source"
REQUIRED = {
    "hexai/__init__.py", "hexai/__main__.py", "hexai/cli.py", "hexai/evaluation.py", "hexai/native.py", "hexai/reference.py", "hexai/referee.py",
    "native/hex_search.cpp", "tests/test_evaluation.py", "tests/test_reference.py",
    "engine/Hex.py", "engine/HexTournament.py", "engine/src/Board.py", "engine/src/Game.py", "engine/test/test_Board.py",
    "deployment/Hex.py", "deployment/HexTournament.py", "deployment/src/Board.py", "deployment/src/Game.py",
    "deployment/test/test_native_adapter.py", "deployment/test/native_protocol.cpp", "deployment/agents/Group026/RAVE_TS.cpp", "deployment/agents/Group026/RAVE_TS.py",
    "deployment/agents/Group026/build-info.json", "scripts/package_kaggle_cpu.py", "scripts/verify_release.py",
}


def selected_files(root):
    names = set(REQUIRED)
    for folder in ("hexai", "native", "scripts", "tests", "engine/src", "engine/test", "engine/agents/Group26", "engine/agents/DefaultAgents",
                   "engine/agents/TestAgents", "deployment/src", "deployment/test", "deployment/agents/Group026"):
        for path in (root / folder).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".cpp", ".h", ".hpp", ".sh", ".ps1", ".bat"} and "__pycache__" not in path.parts:
                names.add(path.relative_to(root).as_posix())
    for name in names:
        if not (root / name).is_file():
            raise ValueError("Required source file missing: " + name)
    return sorted(names)


def assigned_game_ids(manifest, shard_index=0, shard_count=1):
    """Use the evaluator's whole-pair grouping, never split sides across shards."""
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("Require shard_count>=1 and 0<=shard_index<shard_count.")
    groups, selected = {}, []
    for game in manifest["games"]:
        group = "pair:" + game["pair_id"] if game.get("pair_id") else "game:" + game["game_id"]
        if group not in groups:
            groups[group] = len(groups)
        if groups[group] % shard_count == shard_index:
            selected.append(game["game_id"])
    return selected


def completion_record(manifest, records, summary, shard_index=0, shard_count=1):
    """Completion describes assigned work, not the entire multi-shard manifest."""
    assigned = set(assigned_game_ids(manifest, shard_index, shard_count))
    by_id = {}
    for record in records:
        ident = record.get("game_id")
        if ident not in assigned or ident in by_id:
            raise ValueError("Unexpected or duplicate game in the assigned shard: " + str(ident))
        by_id[ident] = record
    if summary.get("manifest_sha256") != manifest_hash(manifest):
        raise ValueError("Saved summary uses a different frozen manifest.")
    if summary.get("recorded_games") != len(by_id):
        raise ValueError("Saved summary count differs from the shard's game files.")
    missing = sorted(assigned - set(by_id))
    failed = sorted(ident for ident, record in by_id.items() if record.get("status") != "completed")
    checkpoint = summary.get("checkpoint_stop")
    status = ("checkpointed" if checkpoint else "incomplete") if missing else (
        "completed_with_failures" if failed else "complete")
    pairs = {}
    for game in manifest["games"]:
        if game["game_id"] in assigned and game.get("pair_id"):
            pairs.setdefault(game["pair_id"], set()).add(game["game_id"])
    partial = sorted(pair for pair, ids in pairs.items() if 0 < len(ids & set(by_id)) < len(ids))
    completed_pairs = sum(all(ident in by_id and by_id[ident].get("status") == "completed"
                              for ident in ids) for ids in pairs.values())
    return {"schema_version": 3, "status": status, "scope": "assigned_shard",
            "gpu_requested": False, "manifest_sha256": manifest_hash(manifest),
            "shard_index": shard_index, "shard_count": shard_count,
            "assigned_games": len(assigned), "recorded_assigned_games": len(by_id),
            "completed_assigned_games": len(by_id) - len(failed),
            "failed_assigned_game_ids": failed, "missing_assigned_game_ids": missing,
            "assigned_pairs": len(pairs), "completed_assigned_pairs": completed_pairs,
            "partial_recorded_pair_ids": partial, "checkpoint_stop": checkpoint,
            "global_manifest_games": len(manifest["games"]),
            "global_manifest_records_complete_from_this_run": len(by_id) == len(manifest["games"]),
            "interpretation": "Status covers assigned shard only. A checkpointed or failed run is not complete successful evaluation. Partial pairs must retain original run provenance."}


def write_flat_outputs(work, result, completion):
    """Save all finished records and a top-level receipt even after a checkpoint."""
    work, result = Path(work), Path(result)
    (result / "completion.json").write_text(json.dumps(completion, indent=2) + "\n",
                                          encoding="utf-8", newline="\n")
    archive_path = work / "hex-public-cpu-results.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(result.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(result).as_posix())
    digest = hashlib.sha256()
    with archive_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    published = {**completion, "result_archive": archive_path.name,
                 "result_archive_sha256": digest.hexdigest(),
                 "result_archive_bytes": archive_path.stat().st_size}
    (work / "hex-public-cpu-completion.json").write_text(json.dumps(published, indent=2) + "\n",
                                                       encoding="utf-8", newline="\n")
    return published


KERNEL_TEMPLATE = r'''"""CPU-only saved-source Hex verification. No model training or network access."""
import base64, hashlib, io, json, os, shutil, subprocess, sys, time, zipfile
from pathlib import Path, PurePosixPath

ARCHIVE_B85 = __ARCHIVE_B85__
EXPECTED_ARCHIVE_SHA256 = __ARCHIVE_SHA__
SOURCE_FILES = __SOURCE_FILES__
FROZEN_MANIFEST_SHA256 = __MANIFEST_SHA__
SHARD_INDEX = __SHARD_INDEX__
SHARD_COUNT = __SHARD_COUNT__
VERIFY_SANITIZERS = __VERIFY_SANITIZERS__
MAX_WALL_SECONDS = __MAX_WALL_SECONDS__
CHECKPOINT_MARGIN_SECONDS = __CHECKPOINT_MARGIN_SECONDS__
kernel_started = time.perf_counter()

work = Path('/kaggle/working')
source = work / 'hex-source'
result = work / 'hex-results'
source.mkdir(parents=True, exist_ok=False)
result.mkdir(parents=True, exist_ok=False)
payload = base64.b85decode(ARCHIVE_B85)
if hashlib.sha256(payload).hexdigest() != EXPECTED_ARCHIVE_SHA256:
    raise RuntimeError('Embedded source archive SHA-256 mismatch.')
with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or '..' in path.parts or '\\' in info.filename or ':' in info.filename:
            raise RuntimeError('Unsafe source archive member.')
    archive.extractall(source)
for name, spec in SOURCE_FILES.items():
    path = source / name
    if len(path.read_bytes()) != spec['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != spec['sha256']:
        raise RuntimeError('Source file integrity mismatch: ' + name)
    if path.suffix == '.py':
        compile(path.read_text(encoding='utf-8'), name, 'exec')

sys.path.insert(0, str(source))
from hexai.evaluation import load_manifest, manifest_hash
from hexai.native import environment
from scripts.package_kaggle_cpu import completion_record, write_flat_outputs
manifest = load_manifest(source / 'configs/frozen.json')
if manifest_hash(manifest) != FROZEN_MANIFEST_SHA256:
    raise RuntimeError('Frozen evaluation manifest mismatch.')

def run(label, command, cwd=source, env=None, stdin=None, timeout=None):
    started = time.perf_counter()
    with (result / (label + '.log')).open('w', encoding='utf-8') as handle:
        completed = subprocess.run(command, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT,
            env=env, input=stdin, text=True, timeout=timeout)
    print(json.dumps({'step': label, 'returncode': completed.returncode, 'seconds': time.perf_counter() - started}), flush=True)
    if completed.returncode:
        raise RuntimeError(label + ' failed. Inspect its saved log.')

run('build', [sys.executable, '-m', 'hexai', 'build'])
run('maintained-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'])
run('original-referee-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'test', '-v'], source / 'engine')
protocol = source / '.local/bin/original-protocol-test'
run('original-protocol-build', ['g++', '-std=c++17', '-O2', '-pthread', 'test/native_protocol.cpp', '-o', str(protocol)], source / 'deployment')
run('original-protocol-tests', [str(protocol)])
# The preserved adapter's Linux tests expect this fixed executable location.
# Rebuild from included source inside this disposable tree rather than bundling
# an existing binary or modifying the user's original deployment directory.
run('legacy-build', [sys.executable, '-m', 'hexai', 'build', '--legacy'])
rebuilt_legacy = source / '.local/bin/legacy_hex'
adapter_legacy = source / 'deployment/agents/Group026/RAVE_TS'
original_build_info = json.loads((source / 'deployment/agents/Group026/build-info.json').read_text())
legacy_source = source / 'deployment/agents/Group026/RAVE_TS.cpp'
legacy_canonical = legacy_source.read_bytes().replace(b'\r\n', b'\n').replace(b'\r', b'\n')
if hashlib.sha256(legacy_canonical).hexdigest() != original_build_info['source_sha256']:
    raise RuntimeError('Preserved adapter source differs from its historical build-info source checksum.')
shutil.copy2(rebuilt_legacy, adapter_legacy)
legacy_receipt = json.loads(rebuilt_legacy.with_name(rebuilt_legacy.name + '.build.json').read_text())
legacy_receipt['executable'] = str(adapter_legacy)
adapter_legacy.with_name(adapter_legacy.name + '.build.json').write_text(json.dumps(legacy_receipt, indent=2) + '\n')
(result / 'adapter-fixture-build.json').write_text(json.dumps({
    'fixture': 'rebuilt_from_preserved_source_for_disposable_adapter_tests',
    'historical_build_info': original_build_info,
    'historical_source_checksum_matches': True,
    'fixture_build_receipt': legacy_receipt,
    'fixture_executable_sha256': hashlib.sha256(adapter_legacy.read_bytes()).hexdigest(),
    'original_shipped_binary_embedded': False,
    'scope': 'This fixture rebuild is not the original shipped binary and does not validate that original binary.'
}, indent=2) + '\n')
adapter_environment = dict(os.environ, HEX_PROTOCOL_TEST_BINARY=str(protocol))
run('original-adapter-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'test', '-v'], source / 'deployment', adapter_environment)
if any(participant.get('kind') == 'benchmark_legacy' for participant in manifest['participants'].values()):
    run('controlled-legacy-build', [sys.executable, 'scripts/build_legacy_benchmark.py'])
if VERIFY_SANITIZERS:
    run('native-controlled-legacy-sanitizer-tests', [sys.executable,
        'scripts/check_native_sanitizers.py', '--output', str(result / 'sanitizers')],
        timeout=600)
build_evidence = result / 'build-evidence'
build_evidence.mkdir()
for path in sorted((source / '.local/bin').glob('*')):
    if path.is_file() and path.suffix in {'.json', '.cpp'}:
        shutil.copy2(path, build_evidence / path.name)

# Custom executable destinations must remain inside this disposable source tree.
# The preserved C++ source is rebuilt here; no shipped binary is embedded.
for participant in manifest['participants'].values():
    configured = participant.get('legacy_executable', participant.get('executable'))
    if configured is None:
        continue
    destination = Path(configured)
    if not destination.is_absolute():
        destination = source / destination
    destination = destination.resolve()
    if not destination.is_relative_to(source.resolve()):
        raise RuntimeError('Executable path escapes the disposable source tree.')
    name = {'legacy': 'legacy_hex', 'benchmark_legacy': 'legacy_benchmark'}.get(participant.get('kind'), 'hex_search')
    built = source / '.local/bin' / name
    if destination != built:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, destination)
        receipt = json.loads(built.with_name(built.name + '.build.json').read_text())
        receipt['executable'] = str(destination)
        destination.with_name(destination.name + '.build.json').write_text(json.dumps(receipt, indent=2) + '\n')

(result / 'source-inventory.json').write_text(json.dumps(SOURCE_FILES, indent=2) + '\n')
(result / 'runtime.json').write_text(json.dumps({'environment': environment(), 'gpu_requested': False,
    'source_archive_sha256': EXPECTED_ARCHIVE_SHA256, 'manifest_sha256': FROZEN_MANIFEST_SHA256,
    'shard_index': SHARD_INDEX, 'shard_count': SHARD_COUNT,
    'sanitizers_requested': VERIFY_SANITIZERS, 'max_wall_seconds': MAX_WALL_SECONDS,
    'checkpoint_margin_seconds': CHECKPOINT_MARGIN_SECONDS}, indent=2) + '\n')
remaining_wall_seconds = max(.001, MAX_WALL_SECONDS - (time.perf_counter() - kernel_started))
run('evaluate', [sys.executable, '-m', 'hexai', 'evaluate', '--config', 'configs/frozen.json',
    '--output', str(result / 'evaluation'), '--shard-index', str(SHARD_INDEX), '--shard-count', str(SHARD_COUNT),
    '--max-wall-seconds', str(remaining_wall_seconds),
    '--checkpoint-margin-seconds', str(CHECKPOINT_MARGIN_SECONDS)])
summary = json.loads((result / 'evaluation/summary.json').read_text())
records = [json.loads(path.read_text()) for path in sorted((result / 'evaluation/games').glob('*.json'))]
completion = completion_record(manifest, records, summary, SHARD_INDEX, SHARD_COUNT)
completion.update({'source_archive_sha256': EXPECTED_ARCHIVE_SHA256,
    'max_wall_seconds': MAX_WALL_SECONDS, 'evaluation_wall_allowance_seconds': remaining_wall_seconds,
    'checkpoint_margin_seconds': CHECKPOINT_MARGIN_SECONDS})
write_flat_outputs(work, result, completion)
print('HEX_CPU_VERIFICATION_' + completion['status'].upper(), flush=True)
'''


def package(owner, slug, config, output, shard_index=0, shard_count=1, root=ROOT, sanitizers=False,
            max_wall_seconds=33000, checkpoint_margin_seconds=120):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        raise ValueError("Owner and slug may contain only letters, digits, hyphens and underscores.")
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("Require shard_count>=1 and 0<=shard_index<shard_count.")
    if (not math.isfinite(max_wall_seconds) or max_wall_seconds <= 0 or
            not math.isfinite(checkpoint_margin_seconds) or checkpoint_margin_seconds < 0 or
            checkpoint_margin_seconds >= max_wall_seconds):
        raise ValueError("Require finite max_wall_seconds>checkpoint_margin_seconds>=0.")
    root = Path(root).resolve()
    config = Path(config).resolve()
    manifest = load_manifest(config)
    assigned = assigned_game_ids(manifest, shard_index, shard_count)
    if not assigned:
        raise ValueError("Selected shard has no assigned games; reduce shard_count or choose a nonempty shard.")
    source_names = set(selected_files(root)) | {'configs/frozen.json'}
    if any(value.get('kind') == 'benchmark_legacy' for value in manifest['participants'].values()):
        if 'scripts/build_legacy_benchmark.py' not in source_names:
            raise ValueError("Controlled legacy evaluation requires scripts/build_legacy_benchmark.py.")
    if sanitizers:
        for required in ('scripts/check_native_sanitizers.py', 'scripts/build_legacy_benchmark.py',
                         'tests/test_native_budget.py'):
            if required not in source_names:
                raise ValueError("Sanitizer verification source is missing: " + required)
    destinations = {}
    for value in manifest["participants"].values():
        configured = value.get("legacy_executable", value.get("executable"))
        if configured is not None:
            path = PurePosixPath(configured)
            if "\\" in configured or ":" in configured or (path.is_absolute() and not path.is_relative_to(PurePosixPath(KAGGLE_SOURCE_ROOT))):
                raise ValueError("Frozen executable path is not portable to Kaggle: " + configured)
            if ".." in path.parts:
                raise ValueError("Executable paths may not escape the disposable source tree.")
            relative = path.relative_to(PurePosixPath(KAGGLE_SOURCE_ROOT)) if path.is_absolute() else path
            if relative.as_posix() in source_names or relative.as_posix().endswith('.build.json'):
                raise ValueError("Executable destination would overwrite a packaged source or build receipt: " + configured)
            kind = value.get('kind', 'native')
            if relative in destinations and destinations[relative] != kind:
                raise ValueError("Native and legacy participants may not share an executable destination.")
            destinations[relative] = kind
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory is not empty; choose a new destination.")
    output.mkdir(parents=True, exist_ok=True)
    payloads = {}
    for relative in sorted(source_names - {'configs/frozen.json'}):
        payload = (root / relative).read_bytes().replace(b"\r\n", b"\n")
        if relative.endswith(".py"):
            compile(payload.decode("utf-8"), relative, "exec")
        payloads[relative] = payload
    payloads["configs/frozen.json"] = config.read_bytes().replace(b"\r\n", b"\n")
    inventory = {name: {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)} for name, payload in sorted(payloads.items())}
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in sorted(payloads.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload)
    archive_bytes = archive_buffer.getvalue()
    digest = hashlib.sha256(archive_bytes).hexdigest()
    text = KERNEL_TEMPLATE.replace("__ARCHIVE_B85__", repr(base64.b85encode(archive_bytes).decode("ascii")))
    text = text.replace("__ARCHIVE_SHA__", repr(digest)).replace("__SOURCE_FILES__", repr(inventory))
    text = text.replace("__MANIFEST_SHA__", repr(manifest_hash(manifest)))
    text = text.replace("__SHARD_INDEX__", str(shard_index)).replace("__SHARD_COUNT__", str(shard_count))
    text = text.replace("__VERIFY_SANITIZERS__", repr(bool(sanitizers)))
    text = text.replace("__MAX_WALL_SECONDS__", repr(float(max_wall_seconds)))
    text = text.replace("__CHECKPOINT_MARGIN_SECONDS__", repr(float(checkpoint_margin_seconds)))
    compile(text, "kernel.py", "exec")
    (output / "kernel.py").write_text(text, encoding="utf-8", newline="\n")
    metadata = {"id": owner + "/" + slug, "title": slug.replace("-", " ").title(), "code_file": "kernel.py",
                "language": "python", "kernel_type": "script", "is_private": True,
                "enable_gpu": False, "enable_tpu": False, "enable_internet": False,
                "dataset_sources": [], "competition_sources": [], "kernel_sources": []}
    (output / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n")
    (output / "source-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8", newline="\n")
    receipt = {"schema_version": 3, "status": "prepared_not_submitted", "kernel_id": metadata["id"],
               "gpu_requested": False, "private": True, "internet_requested": False,
               "source_files": len(inventory), "archive_bytes": len(archive_bytes), "archive_sha256": digest,
               "manifest_sha256": manifest_hash(manifest), "manifest_games": len(manifest["games"]),
               "shard_index": shard_index, "shard_count": shard_count,
               "assigned_games": len(assigned), "max_wall_seconds": max_wall_seconds,
               "checkpoint_margin_seconds": checkpoint_margin_seconds,
               "assigned_external_decision_cap_seconds": len(assigned) * 2 * manifest["budget"].get("game_seconds", 300),
               "sanitizers_requested": bool(sanitizers),
               "kernel_script_sha256": hashlib.sha256((output / "kernel.py").read_bytes()).hexdigest(),
               "validation": {"source_python_syntax": "passed", "kernel_python_syntax": "passed", "required_entrypoints": "passed"},
               "contents": "Reviewed Python/C++ source, tests and one frozen config only. No weights, datasets, credentials, private notes or existing native executables."}
    (output / "package-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--slug", default="hex-cpu-verification")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT,
                        help="Source checkout to package (defaults to this repository).")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--max-wall-seconds", type=float, default=33000,
                        help="Bound notebook work and checkpoint between games (default 33,000 seconds).")
    parser.add_argument("--checkpoint-margin-seconds", type=float, default=120,
                        help="Reserve time before starting the next game (default 120 seconds).")
    parser.add_argument("--sanitizers", action="store_true",
                        help="Also run Linux g++ AddressSanitizer and UndefinedBehaviorSanitizer checks.")
    args = parser.parse_args(argv)
    try:
        receipt = package(args.owner, args.slug, args.config, args.output, args.shard_index, args.shard_count,
                          root=args.source_root, sanitizers=args.sanitizers,
                          max_wall_seconds=args.max_wall_seconds,
                          checkpoint_margin_seconds=args.checkpoint_margin_seconds)
    except (ValueError, OSError, SyntaxError, TypeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
