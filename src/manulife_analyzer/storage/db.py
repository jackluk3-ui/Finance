"""SQLite persistence for prices, macro series and computed metrics."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol      TEXT NOT NULL,
    source      TEXT NOT NULL,
    asof        DATE NOT NULL,
    nav         REAL NOT NULL,
    currency    TEXT,
    PRIMARY KEY (symbol, source, asof)
);
CREATE INDEX IF NOT EXISTS ix_prices_asof ON prices(asof);

CREATE TABLE IF NOT EXISTS macro (
    series_id   TEXT NOT NULL,
    asof        DATE NOT NULL,
    value       REAL NOT NULL,
    PRIMARY KEY (series_id, asof)
);
CREATE INDEX IF NOT EXISTS ix_macro_asof ON macro(asof);

CREATE TABLE IF NOT EXISTS metrics (
    symbol      TEXT NOT NULL,
    metric      TEXT NOT NULL,
    asof        DATE NOT NULL,
    value       REAL NOT NULL,
    PRIMARY KEY (symbol, metric, asof)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    source      TEXT NOT NULL,
    ran_at      TIMESTAMP NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT
);
"""


@dataclass(frozen=True)
class PricePoint:
    symbol: str
    source: str
    asof: date
    nav: float
    currency: str | None = None


@dataclass(frozen=True)
class MacroPoint:
    series_id: str
    asof: date
    value: float


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(
            self.path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_prices(self, points: Iterable[PricePoint]) -> int:
        rows = [
            (p.symbol, p.source, p.asof.isoformat(), float(p.nav), p.currency)
            for p in points
        ]
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO prices(symbol, source, asof, nav, currency)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(symbol, source, asof) DO UPDATE SET
                     nav = excluded.nav,
                     currency = excluded.currency""",
                rows,
            )
        return len(rows)

    def upsert_macro(self, points: Iterable[MacroPoint]) -> int:
        rows = [(p.series_id, p.asof.isoformat(), float(p.value)) for p in points]
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO macro(series_id, asof, value)
                   VALUES (?, ?, ?)
                   ON CONFLICT(series_id, asof) DO UPDATE SET value = excluded.value""",
                rows,
            )
        return len(rows)

    def upsert_metrics(self, rows: Iterable[tuple[str, str, date, float]]) -> int:
        prepared = [(s, m, d.isoformat(), float(v)) for s, m, d, v in rows]
        if not prepared:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO metrics(symbol, metric, asof, value)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(symbol, metric, asof) DO UPDATE SET value = excluded.value""",
                prepared,
            )
        return len(prepared)

    def log_fetch(self, source: str, status: str, detail: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO fetch_log(source, ran_at, status, detail) VALUES (?, ?, ?, ?)",
                (source, datetime.utcnow().isoformat(), status, detail),
            )

    def prices_df(self, symbol: str | None = None) -> pd.DataFrame:
        query = "SELECT symbol, source, asof, nav, currency FROM prices"
        params: tuple = ()
        if symbol:
            query += " WHERE symbol = ?"
            params = (symbol,)
        query += " ORDER BY asof"
        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params, parse_dates=["asof"])
        return df

    def macro_df(self, series_id: str | None = None) -> pd.DataFrame:
        query = "SELECT series_id, asof, value FROM macro"
        params: tuple = ()
        if series_id:
            query += " WHERE series_id = ?"
            params = (series_id,)
        query += " ORDER BY asof"
        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params, parse_dates=["asof"])
        return df

    def metrics_df(self, metric: str | None = None) -> pd.DataFrame:
        query = "SELECT symbol, metric, asof, value FROM metrics"
        params: tuple = ()
        if metric:
            query += " WHERE metric = ?"
            params = (metric,)
        query += " ORDER BY asof"
        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params, parse_dates=["asof"])
        return df

    def latest_metric(self, metric: str) -> pd.DataFrame:
        with self._connect() as conn:
            df = pd.read_sql_query(
                """
                SELECT symbol, asof, value
                FROM metrics
                WHERE metric = ?
                  AND asof = (SELECT MAX(asof) FROM metrics m2
                              WHERE m2.symbol = metrics.symbol AND m2.metric = ?)
                """,
                conn,
                params=(metric, metric),
                parse_dates=["asof"],
            )
        return df
