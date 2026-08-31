"""Write master_long + dimension tables to your local SQL Server instance.

This is a LOCAL convenience (browse the data in SSMS, write real SQL queries).
It is intentionally separate from the deployed dashboard's data source
(``duckdb_export``) - a dashboard deployed to the internet cannot reach a SQL
Server sitting on a personal machine without exposing it to the internet,
which this project deliberately does not do.

Requires the optional ``sqlserver`` extra: ``pip install -e ".[sqlserver]"``.
"""

from __future__ import annotations

import logging

import pandas as pd

from pricelab.config import load_config

log = logging.getLogger("pricelab.integration.sql")


class SqlServerUnavailable(RuntimeError):
    """Raised when the sqlserver extra isn't installed or the server can't be reached."""


def _engine():
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.engine import URL
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise SqlServerUnavailable(
            "sqlalchemy/pyodbc not installed. Run: pip install -e \".[sqlserver]\""
        ) from e

    cfg = (load_config()["database"] or {}).get("sql_server", {})
    if not cfg.get("enabled", True):
        raise SqlServerUnavailable("sql_server.enabled is false in config/database.yaml")

    query = {"driver": cfg.get("driver", "ODBC Driver 17 for SQL Server")}
    if cfg.get("trusted_connection", True):
        query["Trusted_Connection"] = "yes"

    url = URL.create(
        "mssql+pyodbc",
        username=cfg.get("username") or None,
        password=cfg.get("password") or None,
        host=cfg.get("server", "localhost"),
        database=cfg.get("database", "PriceTrendFramework"),
        query=query,
    )
    # fast_executemany speeds up bulk inserts of thousands of rows a lot.
    return create_engine(url, fast_executemany=True)


def _ensure_database(cfg: dict) -> None:
    """CREATE DATABASE if it doesn't exist yet (connects to `master` to do so)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL

    dbname = cfg.get("database", "PriceTrendFramework")
    query = {"driver": cfg.get("driver", "ODBC Driver 17 for SQL Server")}
    if cfg.get("trusted_connection", True):
        query["Trusted_Connection"] = "yes"
    master_url = URL.create(
        "mssql+pyodbc",
        username=cfg.get("username") or None,
        password=cfg.get("password") or None,
        host=cfg.get("server", "localhost"),
        database="master",
        query=query,
    )
    engine = create_engine(master_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM sys.databases WHERE name = :name"), {"name": dbname}
        ).first()
        if not exists:
            log.info("creating database %s", dbname)
            conn.execute(text(f"CREATE DATABASE [{dbname}]"))
    engine.dispose()


def write_sql_server(
    master: pd.DataFrame, dimensions: dict[str, pd.DataFrame]
) -> dict[str, int]:
    """Write master_long + every dimension table as SQL Server tables (replace).

    Returns {table_name: row_count}. Raises SqlServerUnavailable if the
    extra isn't installed or the server can't be reached - callers should
    catch that and continue (this is a local convenience, not a hard
    dependency of the pipeline).
    """
    cfg = (load_config()["database"] or {}).get("sql_server", {})
    _ensure_database(cfg)
    engine = _engine()

    written: dict[str, int] = {}
    try:
        out = master.copy()
        out["is_imputed"] = out["is_imputed"].astype(bool)
        out.to_sql("master_long", engine, if_exists="replace", index=False, chunksize=1000)
        written["master_long"] = len(out)

        for name, df in dimensions.items():
            df.to_sql(f"dim_{name}", engine, if_exists="replace", index=False, chunksize=1000)
            written[f"dim_{name}"] = len(df)
    finally:
        engine.dispose()

    return written
