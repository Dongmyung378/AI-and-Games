#!/usr/bin/env python3
"""Verify a saved Hex release without compilation, training or new matches."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from hexai.evaluation import canonical, load_manifest, manifest_hash, replay, summarize


def safe_path(root, relative):
    if not isinstance(relative, str):
        raise ValueError("Manifest paths must be strings.")
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


def verify_suite(root, suite):
    manifest = load_manifest(safe_path(root, suite["manifest"]))
    fingerprint = manifest_hash(manifest)
    declared = suite.get("manifest_sha256")
    if declared is not None and fingerprint != declared:
        raise ValueError("Suite manifest SHA-256 differs from the release declaration.")
    expected_games = {game["game_id"]: game for game in manifest["games"]}
    results, runs, source_hashes, runner_hashes = {}, [], {}, None
    for relative in suite["run_dirs"]:
        directory = safe_path(root, relative)
        frozen = load_manifest(directory / "manifest.json")
        if manifest_hash(frozen) != fingerprint:
            raise ValueError("Run uses a different manifest: " + relative)
        metadata = read_json(directory / "metadata.json")
        if metadata.get("manifest_sha256") != fingerprint:
            raise ValueError("Run metadata manifest SHA-256 differs: " + relative)
        hashes = metadata.get("runner_sha256")
        if not hashes:
            raise ValueError("Run is missing runner source hashes: " + relative)
        if runner_hashes is None:
            runner_hashes = hashes
        elif hashes != runner_hashes:
            raise ValueError("Runner source hashes differ across hosts.")
        for name, digest in hashes.items():
            if hashlib.sha256((root / "hexai" / name).read_bytes()).hexdigest() != digest:
                raise ValueError("Release runner no longer matches evaluated code: " + name)
        for label, binary in metadata["binaries"].items():
            receipt = binary.get("build_receipt")
            if not receipt:
                # A historical shipped binary can be recorded without a rebuild.
                if manifest["participants"][label].get("kind") == "legacy":
                    continue
                raise ValueError("Maintained engine is missing its source-build receipt: " + label)
            digest = receipt.get("source_sha256")
            if not digest:
                raise ValueError("Build receipt has no source hash: " + label)
            if label in source_hashes and source_hashes[label] != digest:
                raise ValueError("Native source differs across hosts for " + label)
            source_hashes[label] = digest
            current = root / ("deployment/agents/Group026/RAVE_TS.cpp" if manifest["participants"][label].get("kind") == "legacy" else "native/hex_search.cpp")
            payload = current.read_bytes().replace(b"\r\n", b"\n")
            if hashlib.sha256(payload).hexdigest() != digest:
                # Receipts made from Windows historical CRLF sources hash raw
                # bytes, while Linux source packaging can canonicalize LF.
                if hashlib.sha256(current.read_bytes()).hexdigest() != digest:
                    raise ValueError("Released native source differs from evaluated source for " + label)
        run_results = []
        for path in sorted((directory / "games").glob("*.json")):
            item = read_json(path)
            ident = item.get("game_id")
            if ident not in expected_games or ident in results:
                raise ValueError("Unexpected or duplicate saved game_id: " + str(ident))
            if item.get("manifest_sha256") != fingerprint:
                raise ValueError("Saved game has a different manifest hash: " + ident)
            for key, value in expected_games[ident].items():
                if item.get(key) != value:
                    raise ValueError("Saved game differs from its frozen config: " + ident + "/" + key)
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
    expected_comparisons = [{key: comparison[key] for key in fields} for comparison in computed["comparisons"]]
    saved_comparisons = [{key: comparison.get(key) for key in fields} for comparison in stored.get("comparisons", [])]
    if expected_comparisons != saved_comparisons:
        raise ValueError("Aggregate comparison metrics differ from replayed saved games.")
    return {"suite_id": manifest["suite_id"], "split": manifest["split"], "manifest_sha256": fingerprint,
            "games": len(results), "completed_games": computed["completed_games"],
            "failed_games": len(results) - computed["completed_games"],
            "replayed_moves": sum(len(item["moves"]) for item in results.values()),
            "runs": runs, "native_source_hashes": source_hashes, "runner_hashes": runner_hashes}


def verify(root=ROOT, manifest_path="reports/release-manifest.json"):
    root = Path(root).resolve()
    manifest = read_json(safe_path(root, manifest_path))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unknown release-manifest schema version.")
    if not isinstance(manifest.get("files"), dict) or not manifest["files"]:
        raise ValueError("Release manifest must pin at least one file.")
    verified = [file_check(root, relative, spec) for relative, spec in manifest["files"].items()]
    original = read_json(safe_path(root, manifest["original_inventory"]))
    originals = [file_check(root, relative, spec) for relative, spec in original["files"].items()]
    suites = [verify_suite(root, suite) for suite in manifest.get("evaluation_suites", [])]
    return {"schema_version": 1, "status": "passed", "release_files_verified": len(verified),
            "original_files_unchanged": len(originals), "original_commit": original.get("original_commit"),
            "evaluation_suites_verified": len(suites), "saved_games_replayed": sum(item["games"] for item in suites),
            "saved_moves_replayed": sum(item["replayed_moves"] for item in suites), "suites": suites,
            "scope": "Saved-release integrity and referee replay only. No new matches, model training or independent external-opponent evaluation."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", default="reports/release-manifest.json")
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
