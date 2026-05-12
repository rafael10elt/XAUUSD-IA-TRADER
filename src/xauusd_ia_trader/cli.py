from __future__ import annotations

import argparse
import time
from pathlib import Path

from .config import load_config
from .trader import XAUUSDAutonomousTrader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xauusd-ia-trader")
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--sleep", type=int, default=30, help="Cycle delay when running continuously")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(Path(args.config))
    trader = XAUUSDAutonomousTrader(config)

    if args.once:
        result = trader.run_once()
        print(result)
        return 0 if result.get("success") else 1

    while True:
        result = trader.run_once()
        print(result)
        time.sleep(max(5, args.sleep))


if __name__ == "__main__":
    raise SystemExit(main())

