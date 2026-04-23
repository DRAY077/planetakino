"""CLI entry point: python -m planetakino <command>."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import DEFAULT_CINEMA, EXPORT_PATH
from .pipeline import export_json, fetch_cinema


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="planetakino")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="Fetch both sections and store in DB")
    p_fetch.add_argument("--cinema", default=DEFAULT_CINEMA)
    p_fetch.add_argument("--cache-days", type=int, default=7)
    p_fetch.add_argument("--export", action="store_true",
                         help="Also write movies.json after fetching")

    p_export = sub.add_parser("export", help="Write movies.json from DB")
    p_export.add_argument("--cinema", default=DEFAULT_CINEMA)
    p_export.add_argument("--out", default=str(EXPORT_PATH))

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.cmd == "fetch":
        report = fetch_cinema(args.cinema, detail_cache_days=args.cache_days)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.export:
            out = export_json(args.cinema)
            print(f"exported → {out}")
        return 0 if not report.get("errors") else 1

    if args.cmd == "export":
        from pathlib import Path
        out = export_json(args.cinema, path=Path(args.out))
        print(f"exported → {out}")
        return 0

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
