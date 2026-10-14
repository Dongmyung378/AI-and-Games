#!/usr/bin/env python3
"""Prepare a private CPU-only Kaggle verification script; never submit a job."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
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
}


def selected_files(root):
    names = set(REQUIRED)
    for folder in ("hexai", "tests", "engine/src", "engine/test", "engine/agents/Group26", "engine/agents/DefaultAgents",
                   "engine/agents/TestAgents", "deployment/src", "deployment/test", "deployment/agents/Group026"):
        for path in (root / folder).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".cpp"} and "__pycache__" not in path.parts:
                names.add(path.relative_to(root).as_posix())
    for name in names:
        if not (root / name).is_file():
            raise ValueError("Required source file missing: " + name)
    return sorted(names)


KERNEL_TEMPLATE = r'''"""CPU-only saved-source Hex verification. No model training or network access."""
import base64, hashlib, io, json, os, shutil, subprocess, sys, time, zipfile
from pathlib import Path

ARCHIVE_B85 = __ARCHIVE_B85__
EXPECTED_ARCHIVE_SHA256 = __ARCHIVE_SHA__
SOURCE_FILES = __SOURCE_FILES__
FROZEN_MANIFEST_SHA256 = __MANIFEST_SHA__
SHARD_INDEX = __SHARD_INDEX__
SHARD_COUNT = __SHARD_COUNT__

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
        path = Path(info.filename)
        if path.is_absolute() or '..' in path.parts or '\\' in info.filename:
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
manifest = load_manifest(source / 'configs/frozen.json')
if manifest_hash(manifest) != FROZEN_MANIFEST_SHA256:
    raise RuntimeError('Frozen evaluation manifest mismatch.')

def run(label, command, cwd=source, env=None):
    started = time.perf_counter()
    with (result / (label + '.log')).open('w', encoding='utf-8') as handle:
        completed = subprocess.run(command, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT, env=env)
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
shutil.copy2(rebuilt_legacy, adapter_legacy)
legacy_receipt = json.loads(rebuilt_legacy.with_name(rebuilt_legacy.name + '.build.json').read_text())
legacy_receipt['executable'] = str(adapter_legacy)
adapter_legacy.with_name(adapter_legacy.name + '.build.json').write_text(json.dumps(legacy_receipt, indent=2) + '\n')
adapter_environment = dict(os.environ, HEX_PROTOCOL_TEST_BINARY=str(protocol))
run('original-adapter-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'test', '-v'], source / 'deployment', adapter_environment)

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
    built = source / '.local/bin' / ('legacy_hex' if participant.get('kind') == 'legacy' else 'hex_search')
    if destination != built:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, destination)
        receipt = json.loads(built.with_name(built.name + '.build.json').read_text())
        receipt['executable'] = str(destination)
        destination.with_name(destination.name + '.build.json').write_text(json.dumps(receipt, indent=2) + '\n')

(result / 'source-inventory.json').write_text(json.dumps(SOURCE_FILES, indent=2) + '\n')
(result / 'runtime.json').write_text(json.dumps({'environment': environment(), 'gpu_requested': False,
    'source_archive_sha256': EXPECTED_ARCHIVE_SHA256, 'manifest_sha256': FROZEN_MANIFEST_SHA256,
    'shard_index': SHARD_INDEX, 'shard_count': SHARD_COUNT}, indent=2) + '\n')
run('evaluate', [sys.executable, '-m', 'hexai', 'evaluate', '--config', 'configs/frozen.json',
    '--output', str(result / 'evaluation'), '--shard-index', str(SHARD_INDEX), '--shard-count', str(SHARD_COUNT)])
(result / 'completion.json').write_text(json.dumps({'status': 'complete', 'gpu_requested': False,
    'manifest_sha256': FROZEN_MANIFEST_SHA256, 'shard_index': SHARD_INDEX, 'shard_count': SHARD_COUNT}, indent=2) + '\n')
print('HEX_CPU_VERIFICATION_COMPLETE', flush=True)
'''


def package(owner, slug, config, output, shard_index=0, shard_count=1, root=ROOT):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        raise ValueError("Owner and slug may contain only letters, digits, hyphens and underscores.")
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("Require shard_count>=1 and 0<=shard_index<shard_count.")
    root = Path(root).resolve()
    config = Path(config).resolve()
    manifest = load_manifest(config)
    for value in manifest["participants"].values():
        configured = value.get("legacy_executable", value.get("executable"))
        if configured is not None:
            path = Path(configured)
            if "\\" in configured or (path.is_absolute() and not path.is_relative_to(Path(KAGGLE_SOURCE_ROOT))):
                raise ValueError("Frozen executable path is not portable to Kaggle: " + configured)
            if ".." in path.parts:
                raise ValueError("Executable paths may not escape the disposable source tree.")
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory is not empty; choose a new destination.")
    output.mkdir(parents=True, exist_ok=True)
    payloads = {}
    for relative in selected_files(root):
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
    compile(text, "kernel.py", "exec")
    (output / "kernel.py").write_text(text, encoding="utf-8", newline="\n")
    metadata = {"id": owner + "/" + slug, "title": slug.replace("-", " ").title(), "code_file": "kernel.py",
                "language": "python", "kernel_type": "script", "is_private": True,
                "enable_gpu": False, "enable_tpu": False, "enable_internet": False,
                "dataset_sources": [], "competition_sources": [], "kernel_sources": []}
    (output / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n")
    (output / "source-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8", newline="\n")
    receipt = {"schema_version": 1, "status": "prepared_not_submitted", "kernel_id": metadata["id"],
               "gpu_requested": False, "private": True, "internet_requested": False,
               "source_files": len(inventory), "archive_bytes": len(archive_bytes), "archive_sha256": digest,
               "manifest_sha256": manifest_hash(manifest), "manifest_games": len(manifest["games"]),
               "shard_index": shard_index, "shard_count": shard_count,
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
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        receipt = package(args.owner, args.slug, args.config, args.output, args.shard_index, args.shard_count)
    except (ValueError, OSError, SyntaxError, TypeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
