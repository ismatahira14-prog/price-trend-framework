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
import os

import pandas as pd

from pricelab.config import load_config

log = logging.getLogger("pricelab.integration.sql")
REQUIRED_DATABASE = "IMIS"


class SqlServerUnavailable(RuntimeError):
    """Raised when the sqlserver extra isn't installed or the server can't be reached."""


def _as_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def connection_config() -> dict:
    """Return SQL Server settings, with secrets sourced only from the environment."""
    base = dict((load_config()["database"] or {}).get("sql_server", {}))
    base.update(
        server=os.getenv("PRICELAB_SQL_SERVER", ""),
        port=os.getenv("PRICELAB_SQL_PORT", "1433"),
        database=os.getenv("PRICELAB_SQL_DATABASE", "master"),
        username=os.getenv("PRICELAB_SQL_USERNAME", ""),
        password=os.getenv("PRICELAB_SQL_PASSWORD", ""),
        trusted_connection=_as_bool(
            os.getenv("PRICELAB_SQL_TRUSTED_CONNECTION"),
            base.get("trusted_connection", False),
        ),
        encrypt=_as_bool(os.getenv("PRICELAB_SQL_ENCRYPT"), base.get("encrypt", True)),
        trust_server_certificate=_as_bool(
            os.getenv("PRICELAB_SQL_TRUST_SERVER_CERTIFICATE"),
            base.get("trust_server_certificate", False),
        ),
    )
    missing = [name for name in ("server", "database") if not base.get(name)]
    if not base["trusted_connection"]:
        missing += [name for name in ("username", "password") if not base.get(name)]
    if missing:
        names = ", ".join(f"PRICELAB_SQL_{name.upper()}" for name in missing)
        raise SqlServerUnavailable(f"Missing SQL Server settings in .env: {names}")
    if str(base["database"]).casefold() != REQUIRED_DATABASE.casefold():
        raise SqlServerUnavailable(
            f"Refusing SQL Server access: PRICELAB_SQL_DATABASE must be "
            f"{REQUIRED_DATABASE!r}, got {base['database']!r}"
        )
    return base


def _engine():
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.engine import URL
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise SqlServerUnavailable(
            "sqlalchemy/pyodbc not installed. Run: pip install -e \".[sqlserver]\""
        ) from e

    cfg = connection_config()
    if not cfg.get("enabled", True):
        raise SqlServerUnavailable("sql_server.enabled is false in config/database.yaml")

    query = {
        "driver": cfg.get("driver", "ODBC Driver 18 for SQL Server"),
        "Encrypt": "yes" if cfg["encrypt"] else "no",
        "TrustServerCertificate": "yes" if cfg["trust_server_certificate"] else "no",
    }
    if cfg.get("trusted_connection", True):
        query["Trusted_Connection"] = "yes"

    url = URL.create(
        "mssql+pyodbc",
        username=cfg.get("username") or None,
        password=cfg.get("password") or None,
        host=cfg.get("server", "localhost"),
        port=int(cfg["port"]) if cfg.get("port") else None,
        database=cfg.get("database", "PriceTrendFramework"),
        query=query,
    )
    # fast_executemany speeds up bulk inserts of thousands of rows a lot.
    return create_engine(url, fast_executemany=True)


def _ensure_database(cfg: dict) -> None:
    """Validate the sole permitted database; never connect through ``master``."""
    dbname = str(cfg.get("database", ""))
    if dbname.casefold() != REQUIRED_DATABASE.casefold():
        raise SqlServerUnavailable(
            f"Refusing database creation/access outside {REQUIRED_DATABASE!r}: {dbname!r}"
        )


def write_sql_server(
    master: pd.DataFrame, dimensions: dict[str, pd.DataFrame]
) -> dict[str, int]:
    """Write master_long + every dimension table as SQL Server tables (replace).

    Returns {table_name: row_count}. Raises SqlServerUnavailable if the
    extra isn't installed or the server can't be reached - callers should
    catch that and continue (this is a local convenience, not a hard
    dependency of the pipeline).
    """
    cfg = connection_config()
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
