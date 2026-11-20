"""Read-only SQL Server connectivity check.

Run after filling `.env`:
    python -m pricelab.integration.sql_connection
"""

from __future__ import annotations

from sqlalchemy import text

from pricelab.integration.sql_export import SqlServerUnavailable, _engine


def test_connection() -> dict[str, str]:
    engine = _engine()
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT "
                    "CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) AS server_name, "
                    "DB_NAME() AS database_name, "
                    "SYSTEM_USER AS login_name"
                )
            ).mappings().one()
            return dict(row)
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        info = test_connection()
    except SqlServerUnavailable as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Connected to {info['server_name']} / {info['database_name']} as {info['login_name']}")
