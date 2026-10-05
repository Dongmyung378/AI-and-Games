# Linux deployment and final agent

[한국어](README.ko.md) | **English** | [Portfolio home](../README.md)

This directory contains the final CPU-only C++17 agent and Python referee. The supported native board is **11 x 11** and the shipped executable targets **Linux x86_64**. Windows users can run it through x86_64 WSL; macOS users can use a Linux/amd64 container. The variable-board Python research agents are documented in [`../engine/README.md`](../engine/README.md).

## Run with the prebuilt executable

On Linux x86_64 with Python 3.10+, from this directory:

```bash
chmod +x agents/Group026/RAVE_TS
python3 Hex.py -l game.log
```

Both default players are `agents.Group026.RAVE_TS RAVE_TS`. The match uses eight native search workers per move and a five-minute budget per player; allow about 8 GiB of memory for self-play. No model, training dataset, API key, GPU, or third-party Python package is required for this path. The adapter resolves the executable beside its own source, independent of the current directory.

The log contains moves, each player's accumulated move time, and the winner/end reason. Use `-v` for detailed board logging or `-p1` and `-p2` to select compatible agents. Requests such as `python3 Hex.py -b 7` are rejected before either native process starts because the C++ arrays and heuristics are fixed at 11. Run the research engine when comparing other board sizes.

The provided binary is statically linked for `x86_64-linux-musl`. Its compiler, command, and source/artifact checksums are recorded in [`build-info.json`](agents/Group026/build-info.json). Source and adapter changes must be accompanied by a rebuilt binary.

## Rebuild from source

A Linux C++17 compiler and pthread support are sufficient:

```bash
g++ -std=c++17 -O3 -pthread agents/Group026/RAVE_TS.cpp -o agents/Group026/RAVE_TS
chmod +x agents/Group026/RAVE_TS
```

This uses your Linux compiler's runtime. The shipped static artifact was built with Zig 0.15.2 using the command in `build-info.json`. A Windows-targeted compiler produces a different executable format and cannot replace the Linux artifact.

## Native protocol

[`RAVE_TS.py`](agents/Group026/RAVE_TS.py) writes one versioned line per move:

```text
V2;current-colour;11;command;opponent;board;turn
```

`current-colour` is `R` or `B`; `command` is `START`, `CHANGE`, or `SWAP`. `CHANGE` includes opponent coordinates as `x,y`; the other commands leave that field empty. The board contains eleven comma-separated rows of eleven `0`/`R`/`B` cells. The turn is a positive integer. The native response is `x,y`, or `-1,-1` for a legal opening swap.

After the pie rule, **both participants change colour**. The initiating player next receives a `CHANGE` message, so the adapter sends its current referee colour on every request. The production parser validates all fields and applies this role before tactical checks and MCTS. Old unversioned messages fail with a protocol error instead of being interpreted as V2. The tournament entry point remains [`cmd.txt`](agents/Group026/cmd.txt).

## Tests

The Python adapter/referee checks run without additional packages. On Linux x86_64 they also exercise the shipped executable's opening swap and a fast tactical move after its role changes:

```bash
python3 -m unittest discover -s test -v
```

To include the actual production C++ parser in both swap-side traces:

```bash
g++ -std=c++17 -O2 -pthread test/native_protocol.cpp -o /tmp/hex-native-protocol
/tmp/hex-native-protocol
HEX_PROTOCOL_TEST_BINARY=/tmp/hex-native-protocol python3 -m unittest discover -s test -v
```

CI runs this coupled protocol check, the native smoke checks, and the research-engine tests. These checks validate execution and game/protocol behavior; they do not measure playing strength or recreate the historical tournament.

## Build the image

The historical coursework container is optional. From a Linux shell, macOS, or WSL with Docker:

```bash
docker build --platform linux/amd64 --build-arg UID="$(id -u)" -t hex-ai .
```

The image is based on the Ubuntu 22.04 CUDA 12.3 runtime with Python 3.11, g++, TensorFlow 2.19.0, PyTorch 2.5.1, NumPy, pandas, and scikit-learn for the wider coursework environment. The final RAVE-TS path uses only Python's standard library and CPU C++ code. Some historical environment dependencies are unpinned, so the image is not a fully frozen reconstruction of the original tournament.

## Start the container

```bash
docker run --platform linux/amd64 --cpus=8 --memory=8g \
  -v "$(pwd):/home/hex" \
  --name hex-ai --rm -it hex-ai /bin/bash
```

The working directory is mounted at `/home/hex`. When the repository was checked out on Windows, restore the executable bit inside the container:

```bash
chmod +x agents/Group026/RAVE_TS
```

Run the prebuilt match or source/test commands above inside the container. CUDA hardware is not required for the final native agent.

## Source and artifact map

| Path | Purpose |
| --- | --- |
| `agents/Group026/RAVE_TS.cpp` | C++17 source for search, heuristics, and protocol handling |
| `agents/Group026/RAVE_TS` | Prebuilt static Linux x86_64 executable |
| `agents/Group026/build-info.json` | Compiler, target, command, and artifact/source checksums |
| `agents/Group026/RAVE_TS.py` | Python adapter implementing `AgentBase` |
| `agents/Group026/cmd.txt` | Tournament discovery entry |
| `test/native_protocol.cpp` | Production parser and both pie-swap role regressions |
| `test/test_native_adapter.py` | Referee/adapter contract and shipped-native smoke checks |
| `Dockerfile` | Preserved coursework runtime with a native build toolchain |

Read the [architecture document](../docs/architecture.md) for the search design and trade-offs.
