"""Exact error-code lookup (CSV loaded into in-memory SQLite). Deterministic, no LLM."""
from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

import config

_CODE_PATTERN = re.compile(r"\b[A-Za-z]{1,3}-?\d{3,5}\b")


class ErrorCodeDB:
    def __init__(self, csv_path: str | Path | None = None):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE errors (device_model TEXT, code TEXT, code_norm TEXT,"
            " meaning TEXT, fix TEXT, severity TEXT)"
        )
        path = Path(csv_path or config.ERROR_CODES_CSV)
        if path.exists():
            self._load(path)

    @staticmethod
    def normalize(code: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", code.upper())

    def _load(self, path: Path) -> None:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = [
                (r["device_model"], r["code"], self.normalize(r["code"]), r["meaning"], r["fix"], r["severity"])
                for r in csv.DictReader(fh)
            ]
        self._conn.executemany("INSERT INTO errors VALUES (?,?,?,?,?,?)", rows)

    def devices(self) -> list[str]:
        rows = self._conn.execute("SELECT DISTINCT device_model FROM errors ORDER BY 1").fetchall()
        return [r[0] for r in rows]

    def lookup(self, code: str, device_model: str | None = None) -> list[dict]:
        sql = "SELECT device_model, code, meaning, fix, severity FROM errors WHERE code_norm = ?"
        args: list[str] = [self.normalize(code)]
        if device_model and device_model != config.ALL_DEVICES:
            sql += " AND device_model = ?"
            args.append(device_model)
        return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def find(self, text: str, device_model: str | None = None) -> list[dict]:
        """All known error records for codes mentioned in free text."""
        seen: set[str] = set()
        records: list[dict] = []
        for candidate in _CODE_PATTERN.findall(text):
            norm = self.normalize(candidate)
            if norm in seen:
                continue
            seen.add(norm)
            records.extend(self.lookup(candidate, device_model))
        return records
