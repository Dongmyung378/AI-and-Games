#!/usr/bin/env python3
"""Verify a saved Hex release without compilation, training or new matches."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from hexai.evaluation import canonical, load_manifest, manifest_hash, replay, summarize


def safe_path(root, relative):
    if not isinstance(relative, str):
        raise ValueError("Manifest paths must be strings.")
    if "\\" in relative or ":" in relative or ".." in PurePosixPath(relative).parts:
        raise ValueError("Manifest paths must be relative POSIX paths inside the repository.")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or Path(relative).is_absolute():
        raise ValueError("Manifest path escapes the repository: " + relative)
    return path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def file_check(root, relative, spec):
    path = safe_path(root, relative)
    payload = path.read_bytes()
    digest = spec.get("sha256", spec.get("canonical_sha256"))
    if not isinstance(digest, str):
        raise ValueError("Missing SHA-256 for " + relative)
    normalize = spec.get("canonical_lf", False) or spec.get("hash_mode") in {"lf", "canonical_lf"}
    if "canonical_sha256" in spec and "sha256" not in spec:
        # The original inventory records Git blobs with LF. Binary files retain
        # their original bytes even if their payload happens to include CRLF.
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError:
            normalize = False
        else:
            normalize = True
    if normalize:
        payload = payload.replace(b"\r\n", b"\n")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != digest.lower():
        raise ValueError("SHA-256 mismatch: " + relative)
    if "bytes" in spec and len(payload) != spec["bytes"]:
        raise ValueError("Byte count mismatch: " + relative)
    return {"path": relative, "sha256": actual, "bytes": len(payload), "canonical_lf": normalize}


def source_bytes(root, suite, group, name, default):
    """Resolve an evaluated source version, optionally from a preserved ZIP."""
    relative = suite.get("source_paths", {}).get(group, {}).get(name, default)
    safe_path(root, relative)
    archived = suite.get("source_archive")
    if archived is None:
        return safe_path(root, relative).read_bytes()
    prefix = suite.get("source_archive_prefix", "")
    if prefix:
        safe_path(root, prefix)
        relative = prefix.rstrip("/") + "/" + relative
    with zipfile.ZipFile(safe_path(root, archived)) as archive:
        try:
            return archive.read(relative)
        except KeyError as error:
            raise ValueError("Evaluated source missing from preserved archive: " + relative) from error


def source_fingerprints(payload):
    """Equivalent UTF-8 checkout line endings do not define a new source version."""
    candidates = {hashlib.sha256(payload).hexdigest()}
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        return candidates
    normalized = payload.replace(b"\r\n", b"\n")
    candidates.add(hashlib.sha256(normalized).hexdigest())
    candidates.add(hashlib.sha256(normalized.replace(b"\n", b"\r\n")).hexdigest())
    return candidates


def verify_suite(root, suite):
    manifest = load_manifest(safe_path(root, suite["manifest"]))
    fingerprint = manifest_hash(manifest)
    declared = suite.get("manifest_sha256")
    if declared is not None and fingerprint != declared:
        raise ValueError("Suite manifest SHA-256 differs from the release declaration.")
    expected_games = {game["game_id"]: game for game in manifest["games"]}
    results, runs, source_hashes, runner_hashes = {}, [], {}, None
    recorded_runner_hashes, recorded_source_hashes = [], {}
    pair_run_map = {}
    modern_suite = False
    for relative in suite["run_dirs"]:
        directory = safe_path(root, relative)
        frozen = load_manifest(directory / "manifest.json")
        if manifest_hash(frozen) != fingerprint:
            raise ValueError("Run uses a different manifest: " + relative)
        metadata = read_json(directory / "metadata.json")
        modern_run = metadata.get("schema_version", 1) >= 2
        modern_suite = modern_suite or modern_run
        if modern_run and not isinstance(metadata.get("execution_signature"), dict):
            raise ValueError("Version-two run metadata must record its execution signature: " + relative)
        if metadata.get("manifest_sha256") != fingerprint:
            raise ValueError("Run metadata manifest SHA-256 differs: " + relative)
        hashes = metadata.get("runner_sha256")
        required_runner_files = {"native.py", "referee.py", "evaluation.py", "cli.py"}
        if not isinstance(hashes, dict) or set(hashes) != required_runner_files:
            raise ValueError("Run must pin all four evaluation runner source files: " + relative)
        normalized_hashes = {}
        for name, digest in hashes.items():
            payload = source_bytes(root, suite, "runner", name, "hexai/" + name)
            if digest not in source_fingerprints(payload):
                raise ValueError("Pinned runner source differs from evaluated code: " + name)
            normalized_hashes[name] = hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()
        if runner_hashes is None:
            runner_hashes = normalized_hashes
        elif normalized_hashes != runner_hashes:
            raise ValueError("Pinned runner source versions differ within one suite.")
        recorded_runner_hashes.append({"directory": relative, "hashes": hashes})
        for label, binary in metadata["binaries"].items():
            receipt = binary.get("build_receipt")
            if not receipt:
                # A historical shipped binary can be recorded without a rebuild.
                if manifest["participants"][label].get("kind") == "legacy":
                    continue
                raise ValueError("Maintained engine is missing its source-build receipt: " + label)
            controlled_legacy = manifest["participants"][label].get("kind") == "benchmark_legacy"
            digest = receipt.get("generated_source_sha256") if controlled_legacy else receipt.get("source_sha256")
            if not digest:
                raise ValueError("Build receipt has no source hash: " + label)
            default = "deployment/agents/Group026/RAVE_TS.cpp" if manifest["participants"][label].get("kind") == "legacy" else "native/hex_search.cpp"
            payload = source_bytes(root, suite, "native", label, default)
            if digest not in source_fingerprints(payload):
                raise ValueError("Pinned native source differs from evaluated source for " + label)
            if controlled_legacy:
                original = safe_path(root, "deployment/agents/Group026/RAVE_TS.cpp").read_bytes()
                if receipt.get("original_canonical_sha256") not in source_fingerprints(original):
                    raise ValueError("Controlled historical adapter no longer identifies the preserved original source.")
            normalized = hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()
            if label in source_hashes and source_hashes[label] != normalized:
                raise ValueError("Native source versions differ within one suite for " + label)
            source_hashes[label] = normalized
            recorded_source_hashes.setdefault(label, set()).add(digest)
            if receipt.get("executable_sha256") != binary.get("sha256"):
                raise ValueError("Recorded executable hash differs from its build receipt: " + label)
        if set(metadata["binaries"]) != set(manifest["participants"]):
            raise ValueError("Recorded executables do not cover all configured participants: " + relative)
        run_results = []
        for path in sorted((directory / "games").glob("*.json")):
            item = read_json(path)
            ident = item.get("game_id")
            if ident not in expected_games or ident in results:
                raise ValueError("Unexpected or duplicate saved game_id: " + str(ident))
            if item.get("manifest_sha256") != fingerprint:
                raise ValueError("Saved game has a different manifest hash: " + ident)
            if modern_run and item.get("execution_signature") != metadata["execution_signature"]:
                raise ValueError("Saved game execution signature differs from its run metadata: " + ident)
            for key, value in expected_games[ident].items():
                if item.get(key) != value:
                    raise ValueError("Saved game differs from its frozen config: " + ident + "/" + key)
            pair_id = item.get("pair_id")
            if pair_id:
                if pair_id in pair_run_map and pair_run_map[pair_id] != relative:
                    raise ValueError("Side-reversal pair spans different recorded run directories: " + pair_id)
                pair_run_map[pair_id] = relative
            replay(item)
            results[ident] = item
            run_results.append(item)
        if not run_results:
            raise ValueError("Release run has no saved games: " + relative)
        runs.append({"directory": relative, "games": len(run_results), "environment": metadata["environment"]})
    if set(results) != set(expected_games):
        raise ValueError("Release suite is incomplete: " + str(len(set(expected_games) - set(results))) + " missing games.")
    expected_count = suite.get("expected_games", len(expected_games))
    if len(results) != expected_count:
        raise ValueError("Declared release game count differs from the saved suite.")
    computed = summarize(manifest, list(results.values()))
    stored = read_json(safe_path(root, suite["aggregate"]))
    for key in ("manifest_sha256", "suite_id", "split", "budget", "scheduled_games", "recorded_games", "completed_games", "missing_game_ids"):
        if stored.get(key) != computed[key]:
            raise ValueError("Aggregate does not match saved games: " + key)
    if suite.get("expected_completed", computed["completed_games"]) != computed["completed_games"]:
        raise ValueError("Completed-game count differs from the release declaration.")
    # Verify counts, rates and pair membership. Bootstrap endpoints are already
    # pinned by the aggregate file hash; resampling order can differ by run order.
    fields = ("left", "right", "scheduled_games", "recorded_games", "completed_games", "left_wins", "right_wins",
              "left_win_rate_completed_games", "complete_side_pairs", "paired_mean_win_rate", "failures", "failures_by_actor",
              "failure_rate_recorded", "left_first_wins", "left_second_wins")
    modern_fields = ("left_verified_wins_per_scheduled_game", "missing_games",
                     "failure_rate_scheduled", "pair_strata")
    saved = stored.get("comparisons", [])
    # Old aggregates did not contain these fields. Preserve their historical
    # schema rather than rewriting old evidence to look like a newer run.
    fields += tuple(key for key in modern_fields if modern_suite or any(key in item for item in saved))
    expected_comparisons = [{key: comparison[key] for key in fields} for comparison in computed["comparisons"]]
    saved_comparisons = [{key: comparison.get(key) for key in fields} for comparison in saved]
    if expected_comparisons != saved_comparisons:
        raise ValueError("Aggregate comparison metrics differ from replayed saved games.")
    return {"suite_id": manifest["suite_id"], "split": manifest["split"], "manifest_sha256": fingerprint,
            "games": len(results), "completed_games": computed["completed_games"],
            "failed_games": len(results) - computed["completed_games"],
            "replayed_moves": sum(len(item["moves"]) for item in results.values()),
            "runs": runs, "native_source_hashes": source_hashes, "runner_hashes": runner_hashes,
            "recorded_runner_hashes": recorded_runner_hashes,
            "recorded_native_source_hashes": {key: sorted(values) for key, values in recorded_source_hashes.items()},
            "pair_run_dirs": pair_run_map,
            "source_archive": suite.get("source_archive")}


def verify(root=ROOT, manifest_path=None):
    root = Path(root).resolve()
    if manifest_path is None:
        manifest_path = "reports/release-manifest-v2.json" if (root / "reports/release-manifest-v2.json").is_file() else "reports/release-manifest.json"
    manifest = read_json(safe_path(root, manifest_path))
    if manifest.get("schema_version") not in {1, 2}:
        raise ValueError("Unknown release-manifest schema version.")
    if not isinstance(manifest.get("files"), dict) or not manifest["files"]:
        raise ValueError("Release manifest must pin at least one file.")
    verified = [file_check(root, relative, spec) for relative, spec in manifest["files"].items()]
    original = read_json(safe_path(root, manifest["original_inventory"]))
    originals = [file_check(root, relative, spec) for relative, spec in original["files"].items()]
    for suite in manifest.get("evaluation_suites", []):
        archive = suite.get("source_archive")
        if archive is not None and archive not in manifest["files"]:
            raise ValueError("Historical source archive is not pinned by the release inventory: " + archive)
    suites = [verify_suite(root, suite) for suite in manifest.get("evaluation_suites", [])]
    return {"schema_version": 2, "status": "passed", "release_manifest": manifest_path, "release_files_verified": len(verified),
            "original_files_unchanged": len(originals), "original_commit": original.get("original_commit"),
            "evaluation_suites_verified": len(suites), "saved_games_replayed": sum(item["games"] for item in suites),
            "saved_moves_replayed": sum(item["replayed_moves"] for item in suites), "suites": suites,
            "scope": "Saved-release integrity and referee replay only. No new matches, model training or independent external-opponent evaluation."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", help="Release inventory; defaults to v2 when present, otherwise v1.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(args.root, args.manifest)
    except (KeyError, ValueError, OSError, TypeError) as error:
        result = {"schema_version": 1, "status": "failed", "error": str(error)}
        code = 1
    else:
        code = 0
    text = json.dumps(result, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8", newline="\n")
    print(text, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
