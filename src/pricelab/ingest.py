"""Command-line entry point for the ingestion pipeline.

    python -m pricelab.ingest --all
    python -m pricelab.ingest --source inflation_cpi_groups --source crop_production
    python -m pricelab.ingest --all --no-write
"""

from __future__ import annotations

import argparse
import logging
import sys

import pricelab.ingestion  # noqa: F401  -- registers loaders
from pricelab.config import data_dir, load_config
from pricelab.integration.build_master import IngestResult, build_master
from pricelab.integration.report import build_report


def run(*, all: bool = True, sources: list[str] | None = None, write: bool = True) -> IngestResult:
    """Programmatic entry point (used by notebooks)."""
    only = None if all and not sources else (sources or [])
    result = build_master(only=only, write=write)
    build_report(result, write=write)
    return result


def _print_summary(result: IngestResult) -> None:
    m = result.master
    print(f"\ndata dir            : {data_dir()}")
    print(f"fact sources        : {len(result.facts)}  ({', '.join(result.facts) or '-'})")
    print(f"dimension tables    : {len(result.dimensions)}  ({', '.join(result.dimensions) or '-'})")
    print(f"master_long rows    : {len(m)}")
    print(f"duplicates dropped  : {result.dropped_duplicates}")
    if not m.empty:
        print("\nrows by source / variable:")
        print(m.groupby(["source", "variable"]).size().to_string())
        print(f"\ndate range          : {m['date'].min().date()} -> {m['date'].max().date()}")
    if result.unmapped:
        print("\nunmapped names (see config/*.yaml):")
        for kind, values in result.unmapped.items():
            print(f"  {kind}: {', '.join(values)}")
    if result.paths:
        print("\nwritten:")
        for name, path in result.paths.items():
            print(f"  {name}: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pricelab-ingest", description=__doc__)
    parser.add_argument("--all", action="store_true", help="run every source in sources.yaml")
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        metavar="KEY",
        help="run only this source (repeatable)",
    )
    parser.add_argument("--no-write", action="store_true", help="do not write output files")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.all and not args.sources:
        known = ", ".join(load_config()["sources"] or {})
        parser.error(f"pass --all or --source KEY. Known sources: {known}")

    result = run(all=args.all, sources=args.sources, write=not args.no_write)
    _print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
