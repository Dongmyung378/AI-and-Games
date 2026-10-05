import argparse
import importlib
import sys

from src.Colour import Colour
from src.Game import Game
from src.Player import Player

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="Hex",
        description="Run Hex. By default, two native RAVE-TS agents play on an 11x11 board.",
    )
    parser.add_argument(
        "-p1",
        "--player1",
        default="agents.Group026.RAVE_TS RAVE_TS",
        type=str,
        help="Specify player 1 as module and class, e.g. agents.Group026.RAVE_TS RAVE_TS",
    )
    parser.add_argument(
        "-p1Name",
        "--player1Name",
        default="Alice",
        type=str,
        help="Specify the player 1 name",
    )
    parser.add_argument(
        "-p2",
        "--player2",
        default="agents.Group026.RAVE_TS RAVE_TS",
        type=str,
        help="Specify player 2 as module and class, e.g. agents.Group026.RAVE_TS RAVE_TS",
    )
    parser.add_argument(
        "-p2Name",
        "--player2Name",
        default="Bob",
        type=str,
        help="Specify the player 2 name",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "-b",
        "--board_size",
        type=int,
        default=11,
        help="Specify the board size",
    )
    parser.add_argument(
        "-l",
        "--log",
        nargs="?",
        type=str,
        default=sys.stderr,
        const="game.log",
        help=(
            "Save moves history to a log file,"
            "if the flag is present, the result will be saved to game.log."
            "If a filename is provided, the result will be saved to the provided file."
            "If the flag is not present, the result will be printed to the console, via stderr."
        ),
    )

    args = parser.parse_args(argv)
    if args.board_size < 1:
        parser.error("board size must be positive")
    try:
        classes = []
        for specification in (args.player1, args.player2):
            module, name = specification.split()
            classes.append(getattr(importlib.import_module(module), name))
    except (ValueError, ImportError, AttributeError) as exc:
        parser.error(f"cannot load the requested agent: {exc}")
    for agent_class in classes:
        supported = getattr(agent_class, "fixed_board_size", None)
        if supported is not None and args.board_size != supported:
            parser.error(f"{agent_class.__name__} supports only {supported}x{supported} boards; use -b {supported}")

    agents = []
    try:
        agents = [classes[0](Colour.RED)]
        agents.append(classes[1](Colour.BLUE))
        g = Game(
            player1=Player(name=args.player1Name, agent=agents[0]),
            player2=Player(name=args.player2Name, agent=agents[1]),
            board_size=args.board_size,
            logDest=args.log,
            verbose=args.verbose,
        )
        g.run()
    except OSError as exc:
        parser.error(f"cannot start the native agent: {exc}; use the Linux runtime and executable permissions")
    finally:
        for agent in agents:
            if hasattr(agent, "close"):
                agent.close()


if __name__ == "__main__":
    main()
