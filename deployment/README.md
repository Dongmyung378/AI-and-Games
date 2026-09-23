# Reproducible deployment and final agent

[한국어](README.ko.md) | **English** | [Portfolio home](../README.md)

This directory preserves the Linux tournament environment and the optimized final agent. [`agents/Group026/RAVE_TS.py`](agents/Group026/RAVE_TS.py) implements the referee interface and launches [`RAVE_TS`](agents/Group026/RAVE_TS), the compiled C++17 search engine.

## Build the image

From Linux, macOS, or WSL:

```bash
docker build --build-arg UID="$(id -u)" -t hex-ai .
```

The image is based on Ubuntu 22.04 with Python 3.11. It installs the CPU versions of TensorFlow 2.19.0, PyTorch 2.5.1, NumPy, pandas, and scikit-learn to reproduce the supplied coursework environment. The final RAVE-TS agent itself is CPU-only.

## Start the container

```bash
docker run --cpus=8 --memory=8g \
  -v "$(pwd):/home/hex" \
  --name hex-ai --rm -it hex-ai /bin/bash
```

The working directory is mounted at `/home/hex`. When the repository was checked out on Windows, restore the executable bit inside the container:

```bash
chmod +x agents/Group026/RAVE_TS
```

## Run the final agent

```bash
python3 Hex.py \
  -p1 "agents.Group026.RAVE_TS RAVE_TS" \
  -p2 "agents.Group026.RAVE_TS RAVE_TS"
```

The adapter sends `START`, `CHANGE`, or `SWAP` messages to the native process and reads an `x,y` response. The tournament entry point is recorded in [`agents/Group026/cmd.txt`](agents/Group026/cmd.txt).

## Tests

```bash
python3 -m unittest discover -s test -v
```

## Source and artifact map

| Path | Purpose |
| --- | --- |
| `agents/Group026/RAVE_TS.cpp` | C++17 source for search, heuristics, and protocol handling |
| `agents/Group026/RAVE_TS` | Prebuilt Linux tournament executable |
| `agents/Group026/RAVE_TS.py` | Python adapter implementing `AgentBase` |
| `agents/Group026/cmd.txt` | Tournament discovery entry |
| `Dockerfile` | Reproducible coursework runtime |

Read the [architecture document](../docs/architecture.md) for the search design and trade-offs.
