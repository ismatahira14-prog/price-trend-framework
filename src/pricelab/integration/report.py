"""Human-readable ingestion report -> data/processed/ingestion_report.md."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from pricelab.config import processed_dir
from pricelab.integration.build_master import IngestResult


def _coverage_table(master: pd.DataFrame) -> str:
    if master.empty:
        return "_no fact rows_\n"
    g = master.groupby(["source", "variable"])
    lines = [
        "| source | variable | rows | date min | date max | freq | regions | imputed |",
        "|---|---|--:|---|---|---|--:|--:|",
    ]
    for (src, var), sub in g:
        lines.append(
            f"| {src} | {var} | {len(sub)} | {sub['date'].min().date()} "
            f"| {sub['date'].max().date()} | {'/'.join(sorted(sub['freq'].unique()))} "
            f"| {sub['region'].nunique()} | {int(sub['is_imputed'].sum())} |"
        )
    return "\n".join(lines) + "\n"


def build_report(result: IngestResult, *, write: bool = True) -> str:
    m = result.master
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    parts: list[str] = [
        "# Ingestion report",
        "",
        f"_generated {now}_",
        "",
        "## Summary",
        "",
        f"- fact sources: **{len(result.facts)}**",
        f"- dimension tables: **{len(result.dimensions)}**",
        f"- master_long rows: **{len(m)}**",
        f"- duplicate rows dropped: **{result.dropped_duplicates}**",
        "",
        "## Coverage",
        "",
        _coverage_table(m),
    ]

    if not m.empty:
        parts += [
            "## Null values in `value` (post-load)",
            "",
            "| source | null values |",
            "|---|--:|",
        ]
        for src, sub in m.groupby("source"):
            parts.append(f"| {src} | {int(sub['value'].isna().sum())} |")
        parts.append("")

    parts += ["## Dimension tables", ""]
    if result.dimensions:
        parts += ["| table | rows | columns |", "|---|--:|---|"]
        for name, df in result.dimensions.items():
            parts.append(f"| {name} | {len(df)} | {', '.join(map(str, df.columns))} |")
    else:
        parts.append("_none_")
    parts.append("")

    parts += ["## Unmapped names (add aliases to config/*.yaml)", ""]
    if result.unmapped:
        for kind, values in result.unmapped.items():
            parts.append(f"**{kind}** ({len(values)}): {', '.join(values)}")
            parts.append("")
    else:
        parts.append("_all region/commodity names matched a canonical entry_")
        parts.append("")

    text = "\n".join(parts)
    if write:
        path = processed_dir() / "ingestion_report.md"
        path.write_text(text, encoding="utf-8")
    return text
