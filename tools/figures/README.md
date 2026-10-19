# Reproduce the figures

[한국어](README.ko.md) | **English**

These optional tools render actual published measurements with Matplotlib. The pinned plotting environment requires Python 3.11 or newer; the standard-library agent runtime requires Python 3.10 or newer and a C++17 compiler.

From the repository root, use a separate environment:

```bash
python -m venv .local/figure-env
.local/figure-env/bin/python -m pip install -r tools/figures/requirements.txt
.local/figure-env/bin/python tools/figures/render_hex_deep_scientific.py --data assets/figures/deep-visual-input.json --output .local/figures --language both
.local/figure-env/bin/python tools/figures/render_hex_thumbnail.py --data assets/figures/deep-visual-input.json --output .local/figures --language both
```

On Windows, replace `.local/figure-env/bin/python` with `.local/figure-env/Scripts/python.exe`.

The published input binds repository-relative paths and raw SHA-256 guards to actual aggregates, cost mappings, worker measurements and one thumbnail game. `reports/deep/**` retains measured bytes through Git, including CRLF-bearing reports. Changed evidence fails the input guard. Rendering writes new output folders without rerunning games or altering the engine, selected policy, manifests or raw records.

Output folders `en/` and `ko/` contain `hex-shared-time.svg`, `hex-tactical-ablation.svg`, `hex-worker-positions.svg` and `hex-deep-thumbnail.svg`. Published English files are in `assets/figures/`, with Korean files in `assets/figures/ko/`. `assets/figures/deep-figure-manifest.json` records the new files and their generator, input and font hashes. The earlier seven SVGs remain separate evidence with numerical text and geometry preserved.

The fixed-iteration plot linked from the English README has a separate English derivative at `assets/figures/en/hex-final.svg`. Regenerate its labels with `python tools/figures/localize_final_policy.py`; this reads the Korean source, preserves every plotted coordinate and numerical value, and writes a separate localization receipt. The Korean original and historical receipts remain unchanged.

The shared-clock plot resolves scores from actual participant identifiers. Intervals resample complete side-reversal pairs within recorded hardware and adapter strata. A participant's 300-second setting is an allowance, not full consumption; completed games, failures and missing games retain separate denominators. Tactical 50–50% intervals reflect zero observed pair-score variation, not proven population equivalence. Worker p50, seven-repeat descriptive p95 and native-process RSS are reported separately for Windows and Kaggle and do not measure playing strength. Three fixtures replay legal Red-first histories; three are transposed, colour-exchanged static states whose Red-first reachability is not asserted.

The thumbnail uses an actual final board, verifies the recorded winning-colour path and reads its result bars from the same guarded aggregate. Its position and scores are not illustrative.

English uses DejaVu Sans. Korean requires Malgun Gothic, Noto Sans CJK or NanumGothic. If no supported Korean font is found, pass `--korean-font PATH_TO_FONT_FILE` to both renderers. Glyphs are saved as SVG paths without redistributing font files. Receipts record the exact font hash, Matplotlib version, input hashes and canvas-bound checks. Browser visual inspection is a separate check.

To recompute the shared-clock mapping and bindings from already published records, run:

```bash
python tools/figures/prepare_hex_visual_inputs.py
```

This standard-library command writes `reports/deep/analysis/shared-time-metrics.json`, `assets/figures/deep-metric-provenance.json` and `assets/figures/deep-visual-input.json`. It preserves frozen evaluation files, rejects incomplete suites and lists the 400 source-game paths and hashes. Exact figure-byte reproduction also requires the recorded font and pinned plotting library; a different supported font preserves measured values but changes glyph bytes.
