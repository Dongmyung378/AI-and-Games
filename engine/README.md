# Python research environment

[한국어](README.ko.md) | **English** | [Portfolio home](../README.md)

This directory contains the supplied Hex referee and the Python agents used to compare MCTS selection policies. The portfolio's main research variants are under [`agents/Group26/`](agents/Group26/).

## Requirements

- Python 3.10 or later
- No third-party packages for the referee or `Group26` agents

The neural-network experiments under `agents/Hex/` are historical and require NumPy and PyTorch; they are not needed for the examples below.

## Run a match

From this directory:

```bash
python Hex.py
```

The default is an 11 x 11 match between two naive agents. Agent arguments use `module.path ClassName`:

```bash
python Hex.py -b 7 -v \
  -p1 "agents.Group26.Agent_RAVE_TS Agent_RAVE_TS" \
  -p2 "agents.Group26.Agent_UCB Agent_UCB"
```

On PowerShell, replace the trailing `\` characters with backticks. Run `python Hex.py --help` for every option.

## Research agents

| Module | Selection policy |
| --- | --- |
| `Agent_UCB.py` | UCB1 over direct MCTS statistics |
| `Agent_TS.py` | Thompson sampling over direct statistics |
| `Agent_RAVE_UCB.py` | UCB1 with blended RAVE evidence |
| `Agent_RAVE_TS.py` | Thompson sampling with blended RAVE evidence |
| `mcts_core.py` | Shared tree, rollout, backpropagation, and time management |

Each agent starts with a five-minute match budget and allocates 3.5% of the remaining time to a move. The blue player may return `(-1, -1)` on turn two to invoke the pie rule.

## Tests

```bash
python -m unittest discover -s test -v
```

The 18 tests cover board construction, move validation, colour handling, timeouts, illegal moves, win detection, and the swap rule.

## Tournament runner

[`HexTournament.py`](HexTournament.py) discovers configured agents, runs ordered matchups with worker processes, and writes per-game and aggregate CSV files. It follows the original coursework directory convention, so agent packages intended for tournament discovery need a valid `cmd.txt`.

## Experimental track

The curated policy comparison lives in `Group26`. The `Hex` directory preserves the separate neural-network exploration, while the final optimized native implementation lives in [`../deployment/`](../deployment/README.md). Superseded native prototypes were removed from the portfolio tree and remain recoverable from Git history.

External research sources are listed in the portfolio's [reference notes](../docs/references.md).
