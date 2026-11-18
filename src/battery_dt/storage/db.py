"""SQLite storage layer with a narrow measurement table."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from battery_dt.common.config import resolve_path


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    config_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    payload TEXT NOT NULL,
    ts_ingest TEXT NOT NULL,
    qos INTEGER,
    run_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_raw_ingest ON raw_messages(ts_ingest);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    variable TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL,
    ts_source TEXT NOT NULL,
    ts_ingest TEXT NOT NULL,
    seq INTEGER NOT NULL,
    quality TEXT NOT NULL,
    run_id INTEGER,
    UNIQUE(asset_id, run_id, seq, variable)
);
CREATE INDEX IF NOT EXISTS idx_meas_lookup
    ON measurements(asset_id, variable, ts_source);
CREATE INDEX IF NOT EXISTS idx_meas_ingest ON measurements(ts_ingest);

CREATE TABLE IF NOT EXISTS data_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    from_seq INTEGER NOT NULL,
    to_seq INTEGER NOT NULL,
    missed INTEGER NOT NULL,
    detected_at TEXT NOT NULL,
    run_id INTEGER
);

CREATE TABLE IF NOT EXISTS twin_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts_source TEXT NOT NULL,
    ts_ingest TEXT NOT NULL,
    soc REAL,
    soh_pct REAL,
    r0_ohm REAL,
    r0_ratio REAL,
    t_core_C REAL,
    surface_temp_est_C REAL,
    v_pred_V REAL,
    v_meas_V REAL,
    v_residual_mV REAL,
    t_residual_C REAL,
    remaining_s REAL,
    active_alarms TEXT,
    quality TEXT,
    raw_json TEXT NOT NULL,
    run_id INTEGER,
    UNIQUE(asset_id, run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_twin_source ON twin_outputs(asset_id, ts_source);

CREATE TABLE IF NOT EXISTS alarms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    code TEXT NOT NULL,
    severity TEXT,
    ts_source TEXT NOT NULL,
    ts_ingest TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    reason TEXT,
    recommendation TEXT,
    evidence_json TEXT,
    raw_json TEXT NOT NULL,
    run_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_alarm_time ON alarms(ts_ingest);

CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    payload TEXT NOT NULL,
    ts_ingest TEXT NOT NULL,
    run_id INTEGER
);

CREATE TABLE IF NOT EXISTS asset_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    ts_ingest TEXT NOT NULL,
    payload TEXT NOT NULL,
    run_id INTEGER
);

CREATE TABLE IF NOT EXISTS asset_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    ts_ingest TEXT NOT NULL,
    payload TEXT NOT NULL,
    run_id INTEGER
);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = resolve_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._held: sqlite3.Connection | None = None

    def _configure(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def open_persistent(self) -> None:
        """Keep one connection open so writes can be committed in batches."""
        if self._held is None:
            self._held = self._configure(
                sqlite3.connect(self.path, timeout=15, check_same_thread=False)
            )

    def commit(self) -> None:
        if self._held is not None:
            self._held.commit()

    def close(self) -> None:
        if self._held is not None:
            try:
                self._held.commit()
            finally:
                self._held.close()
                self._held = None

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if self._held is not None:
            yield self._held
            return
        conn = self._configure(sqlite3.connect(self.path, timeout=15))
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    def create_run(self, started_at: str, config_snapshot: dict[str, Any]) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                "INSERT INTO runs(started_at, config_json) VALUES (?, ?)",
                (started_at, json.dumps(config_snapshot, ensure_ascii=False)),
            )
            return int(cur.lastrowid)

    def insert_raw(
        self,
        *,
        topic: str,
        payload: str,
        ts_ingest: str,
        qos: int,
        run_id: int,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO raw_messages(topic, payload, ts_ingest, qos, run_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (topic, payload, ts_ingest, qos, run_id),
            )

    def insert_measurement(
        self,
        *,
        asset_id: str,
        variable: str,
        value: float,
        unit: str,
        ts_source: str,
        ts_ingest: str,
        seq: int,
        quality: str,
        run_id: int,
    ) -> bool:
        with self.connection() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO measurements("
                "asset_id, variable, value, unit, ts_source, ts_ingest, seq, quality, run_id"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    asset_id,
                    variable,
                    value,
                    unit,
                    ts_source,
                    ts_ingest,
                    seq,
                    quality,
                    run_id,
                ),
            )
            return cur.rowcount > 0

    def insert_gap(
        self,
        *,
        asset_id: str,
        from_seq: int,
        to_seq: int,
        missed: int,
        detected_at: str,
        run_id: int,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO data_gaps(asset_id, from_seq, to_seq, missed, detected_at, run_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (asset_id, from_seq, to_seq, missed, detected_at, run_id),
            )

    def insert_twin_output(
        self,
        *,
        payload: dict[str, Any],
        ts_ingest: str,
        run_id: int,
    ) -> bool:
        with self.connection() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO twin_outputs("
                "asset_id, seq, ts_source, ts_ingest, soc, soh_pct, r0_ohm, r0_ratio, "
                "t_core_C, surface_temp_est_C, v_pred_V, v_meas_V, v_residual_mV, "
                "t_residual_C, remaining_s, active_alarms, quality, raw_json, run_id"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    payload.get("asset_id", "pack01"),
                    int(payload["seq"]),
                    payload["ts"],
                    ts_ingest,
                    payload.get("soc"),
                    payload.get("soh_pct"),
                    payload.get("r0_ohm"),
                    payload.get("r0_ratio"),
                    payload.get("t_core_C"),
                    payload.get("surface_temp_est_C"),
                    payload.get("v_pred_V"),
                    payload.get("v_meas_V"),
                    payload.get("v_residual_mV"),
                    payload.get("t_residual_C"),
                    payload.get("remaining_s"),
                    json.dumps(payload.get("active_alarms", [])),
                    payload.get("quality"),
                    json.dumps(payload, ensure_ascii=False),
                    run_id,
                ),
            )
            return cur.rowcount > 0

    def insert_alarm(
        self,
        *,
        payload: dict[str, Any],
        ts_source: str,
        ts_ingest: str,
        run_id: int,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO alarms("
                "asset_id, code, severity, ts_source, ts_ingest, active, reason, "
                "recommendation, evidence_json, raw_json, run_id"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    payload.get("asset_id", "pack01"),
                    payload.get("code", "UNKNOWN"),
                    payload.get("severity"),
                    ts_source,
                    ts_ingest,
                    1 if payload.get("active", True) else 0,
                    payload.get("reason"),
                    payload.get("recommendation"),
                    json.dumps(payload.get("evidence", {}), ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False),
                    run_id,
                ),
            )

    def insert_command(
        self,
        *,
        asset_id: str,
        topic: str,
        payload: str,
        ts_ingest: str,
        run_id: int,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO commands(asset_id, topic, payload, ts_ingest, run_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (asset_id, topic, payload, ts_ingest, run_id),
            )

    def insert_meta(
        self,
        *,
        asset_id: str,
        ts_ingest: str,
        payload: str,
        run_id: int,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO asset_meta(asset_id, ts_ingest, payload, run_id) "
                "VALUES (?, ?, ?, ?)",
                (asset_id, ts_ingest, payload, run_id),
            )

    def insert_status(
        self,
        *,
        asset_id: str,
        status: str,
        ts_ingest: str,
        payload: str,
        run_id: int,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO asset_status(asset_id, status, ts_ingest, payload, run_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (asset_id, status, ts_ingest, payload, run_id),
            )

    def max_seq(self, asset_id: str) -> int | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT MAX(seq) AS max_seq FROM measurements WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
        return None if row is None or row["max_seq"] is None else int(row["max_seq"])

    def get_series(
        self,
        variable: str,
        asset_id: str = "pack01",
        *,
        limit: int = 5000,
        t0: str | None = None,
        t1: str | None = None,
    ) -> pd.DataFrame:
        clauses = ["asset_id = ?", "variable = ?", "quality = 'good'"]
        params: list[Any] = [asset_id, variable]
        if t0:
            clauses.append("ts_source >= ?")
            params.append(t0)
        if t1:
            clauses.append("ts_source <= ?")
            params.append(t1)
        params.append(int(limit))
        sql = (
            "SELECT ts_source, value, unit, seq, quality FROM measurements "
            f"WHERE {' AND '.join(clauses)} ORDER BY ts_source DESC LIMIT ?"
        )
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        frame = pd.DataFrame([dict(row) for row in rows])
        if frame.empty:
            return frame
        frame["ts_source"] = pd.to_datetime(frame["ts_source"], utc=True)
        return frame.sort_values("ts_source").reset_index(drop=True)

    def get_twin_history(self, asset_id: str = "pack01", limit: int = 5000) -> pd.DataFrame:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM twin_outputs WHERE asset_id = ? "
                "ORDER BY ts_source DESC LIMIT ?",
                (asset_id, int(limit)),
            ).fetchall()
        frame = pd.DataFrame([dict(row) for row in rows])
        if frame.empty:
            return frame
        frame["ts_source"] = pd.to_datetime(frame["ts_source"], utc=True)
        return frame.sort_values("ts_source").reset_index(drop=True)

    def get_alarms(self, asset_id: str = "pack01", limit: int = 50) -> pd.DataFrame:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM alarms WHERE asset_id = ? ORDER BY ts_ingest DESC LIMIT ?",
                (asset_id, int(limit)),
            ).fetchall()
        return pd.DataFrame([dict(row) for row in rows])

    def get_active_alarms(self, asset_id: str = "pack01") -> pd.DataFrame:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM alarms WHERE asset_id = ? AND active = 1 "
                "AND id IN (SELECT MAX(id) FROM alarms WHERE asset_id = ? GROUP BY code) "
                "ORDER BY ts_ingest DESC",
                (asset_id, asset_id),
            ).fetchall()
        return pd.DataFrame([dict(row) for row in rows])

    def latest(self, table: str, order_column: str = "ts_ingest") -> dict[str, Any] | None:
        allowed = {"measurements", "twin_outputs", "alarms", "asset_status", "raw_messages"}
        if table not in allowed:
            raise ValueError(f"unsupported table {table}")
        with self.connection() as conn:
            row = conn.execute(
                f"SELECT * FROM {table} ORDER BY {order_column} DESC LIMIT 1"
            ).fetchone()
        return None if row is None else dict(row)

    def counts(self) -> dict[str, int]:
        names = [
            "raw_messages",
            "measurements",
            "twin_outputs",
            "alarms",
            "data_gaps",
            "commands",
        ]
        result: dict[str, int] = {}
        with self.connection() as conn:
            for name in names:
                row = conn.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()
                result[name] = int(row["n"])
        return result

    def latest_twin(self, asset_id: str = "pack01") -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM twin_outputs WHERE asset_id = ? "
                "ORDER BY ts_source DESC LIMIT 1",
                (asset_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def latest_measurement_ingest(self, asset_id: str = "pack01") -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT MAX(ts_ingest) AS t FROM measurements WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
        return None if row is None else row["t"]

    def latest_status(self, asset_id: str = "pack01") -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM asset_status WHERE asset_id = ? ORDER BY ts_ingest DESC LIMIT 1",
                (asset_id,),
            ).fetchone()
        return None if row is None else dict(row)
