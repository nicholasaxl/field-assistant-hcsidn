"""Local SQLite store: every answer, the engineer's outcome and per-step results.

It powers the "Fixed it / Didn't fix it" loop, escalation handoffs and the Insights page. Nothing here
calls a model; everything is plain counting so the numbers can be trusted and explained.
"""
from __future__ import annotations

import csv
import io
import json
import random
import sqlite3
import statistics
import threading
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import config

OUTCOMES = ("fixed", "not_fixed", "escalated")
REASONS = {
    "step_failed": "A step didn't work",
    "different_problem": "It's a different problem",
    "doc_wrong": "The document is wrong or outdated",
    "need_person": "Needs a person",
}
STEP_RESULTS = ("done", "failed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    question TEXT NOT NULL,
    device TEXT NOT NULL,
    intent TEXT,
    fallback INTEGER NOT NULL DEFAULT 0,
    cached INTEGER NOT NULL DEFAULT 0,
    elapsed REAL,
    stages TEXT,
    steps TEXT,
    sources TEXT,
    codes TEXT,
    alerts TEXT,
    is_sample INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS feedback (
    interaction_id TEXT PRIMARY KEY REFERENCES interactions(id) ON DELETE CASCADE,
    outcome TEXT NOT NULL,
    reason TEXT,
    note TEXT,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS step_results (
    interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    result TEXT NOT NULL,
    ts REAL NOT NULL,
    PRIMARY KEY (interaction_id, step_index)
);
CREATE INDEX IF NOT EXISTS idx_interactions_ts ON interactions(ts);
"""


def _dump(value) -> str:
    return json.dumps(value if value is not None else [])


def _doc_name(label: str) -> str:
    """'atm_runbook.md, Clearing a note jam' -> 'atm_runbook.md'; error-table labels stay whole."""
    return label.split(",")[0].strip()


class FeedbackStore:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        # A database created before models were recorded gains the column in place; nothing is lost.
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(interactions)")}
        if "model" not in columns:
            self._db.execute("ALTER TABLE interactions ADD COLUMN model TEXT")
            self._db.commit()

    # ---------- writes ----------
    def log_interaction(
        self,
        *,
        question: str,
        device: str,
        intent: str | None = None,
        fallback: bool = False,
        cached: bool = False,
        elapsed: float | None = None,
        stages: list | None = None,
        steps: list | None = None,
        sources: list | None = None,
        codes: list | None = None,
        alerts: list | None = None,
        is_sample: bool = False,
        ts: float | None = None,
        interaction_id: str | None = None,
        model: str | None = None,
    ) -> str:
        interaction_id = interaction_id or uuid.uuid4().hex
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO interactions (id, ts, question, device, intent, fallback, cached, elapsed,"
                " stages, steps, sources, codes, alerts, is_sample, model) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    interaction_id,
                    ts if ts is not None else datetime.now().timestamp(),
                    question,
                    device,
                    intent,
                    int(fallback),
                    int(cached),
                    elapsed,
                    _dump(stages),
                    _dump(steps),
                    _dump(sources),
                    _dump(codes),
                    _dump(alerts),
                    int(is_sample),
                    model,
                ),
            )
        return interaction_id

    def _require(self, interaction_id: str) -> None:
        if not self._db.execute("SELECT 1 FROM interactions WHERE id = ?", (interaction_id,)).fetchone():
            raise KeyError(interaction_id)

    def set_outcome(
        self, interaction_id: str, outcome: str, reason: str | None = None, note: str | None = None
    ) -> None:
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}")
        if reason is not None and reason not in REASONS:
            raise ValueError(f"reason must be one of {tuple(REASONS)}")
        with self._lock, self._db:
            self._require(interaction_id)
            self._db.execute(
                "INSERT INTO feedback (interaction_id, outcome, reason, note, ts) VALUES (?,?,?,?,?)"
                " ON CONFLICT(interaction_id) DO UPDATE SET outcome=excluded.outcome, reason=excluded.reason,"
                " note=excluded.note, ts=excluded.ts",
                (interaction_id, outcome, reason, (note or "").strip()[:1000] or None, datetime.now().timestamp()),
            )

    def clear_outcome(self, interaction_id: str) -> None:
        with self._lock, self._db:
            self._require(interaction_id)
            self._db.execute("DELETE FROM feedback WHERE interaction_id = ?", (interaction_id,))

    def set_step_result(self, interaction_id: str, step_index: int, result: str | None) -> None:
        if result is not None and result not in STEP_RESULTS:
            raise ValueError(f"result must be one of {STEP_RESULTS} or None")
        with self._lock, self._db:
            self._require(interaction_id)
            if result is None:
                self._db.execute(
                    "DELETE FROM step_results WHERE interaction_id = ? AND step_index = ?",
                    (interaction_id, step_index),
                )
            else:
                self._db.execute(
                    "INSERT INTO step_results (interaction_id, step_index, result, ts) VALUES (?,?,?,?)"
                    " ON CONFLICT(interaction_id, step_index) DO UPDATE SET result=excluded.result, ts=excluded.ts",
                    (interaction_id, step_index, result, datetime.now().timestamp()),
                )

    # ---------- reads ----------
    def get_interaction(self, interaction_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT i.*, f.outcome, f.reason, f.note, f.ts AS feedback_ts FROM interactions i"
                " LEFT JOIN feedback f ON f.interaction_id = i.id WHERE i.id = ?",
                (interaction_id,),
            ).fetchone()
            if row is None:
                return None
            results = {
                r["step_index"]: r["result"]
                for r in self._db.execute(
                    "SELECT step_index, result FROM step_results WHERE interaction_id = ?", (interaction_id,)
                )
            }
        item = dict(row)
        for key in ("stages", "steps", "sources", "codes", "alerts"):
            item[key] = json.loads(item[key] or "[]")
        item["step_results"] = results
        return item

    def handoff_summary(self, interaction_id: str) -> str:
        """A plain-text escalation note: what was asked, what was tried, what failed. No model involved."""
        item = self.get_interaction(interaction_id)
        if item is None:
            raise KeyError(interaction_id)
        when = datetime.fromtimestamp(item["ts"]).strftime("%Y-%m-%d %H:%M")
        device = "All devices" if item["device"] == config.ALL_DEVICES else item["device"]
        lines = [
            "FIELD ASSIST HANDOFF",
            f"Date: {when}",
            f"Device: {device}",
            f"Problem reported: {item['question']}",
        ]
        if item["codes"]:
            lines.append(f"Error codes: {', '.join(item['codes'])}")
        if item["steps"]:
            lines.append("")
            lines.append("Documented procedure suggested:")
            for index, text in enumerate(item["steps"]):
                status = {"done": "done", "failed": "DID NOT WORK"}.get(item["step_results"].get(index), "")
                lines.append(f"  {index + 1}. {text}" + (f"  [{status}]" if status else ""))
        elif item["fallback"]:
            lines.append("")
            lines.append("No matching procedure was found in the documents.")
        outcome = item.get("outcome")
        if outcome:
            label = {"fixed": "Fixed", "not_fixed": "Not fixed", "escalated": "Escalated"}[outcome]
            reason = REASONS.get(item.get("reason") or "")
            lines.append("")
            lines.append(f"Outcome: {label}" + (f" ({reason})" if reason else ""))
        if item.get("note"):
            lines.append(f"Engineer note: {item['note']}")
        if item["sources"]:
            lines.append("")
            lines.append("Sources consulted:")
            lines.extend(f"  - {label}" for label in item["sources"])
        if item["alerts"]:
            lines.append("")
            lines.append("Safety alerts shown:")
            lines.extend(f"  - {a.get('title', '')}: {a.get('message', '')}" for a in item["alerts"])
        return "\n".join(lines)

    def has_rows(self, sample: bool) -> bool:
        with self._lock:
            return bool(
                self._db.execute("SELECT 1 FROM interactions WHERE is_sample = ? LIMIT 1", (int(sample),)).fetchone()
            )

    def _rows(self, sample: bool, since: float) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT i.*, f.outcome, f.reason, f.note FROM interactions i"
                " LEFT JOIN feedback f ON f.interaction_id = i.id"
                " WHERE i.is_sample = ? AND i.ts >= ? ORDER BY i.ts DESC",
                (int(sample), since),
            ).fetchall()
            failed = self._db.execute(
                "SELECT s.interaction_id, s.step_index FROM step_results s"
                " JOIN interactions i ON i.id = s.interaction_id WHERE s.result = 'failed' AND i.is_sample = ?",
                (int(sample),),
            ).fetchall()
        failed_by = defaultdict(list)
        for r in failed:
            failed_by[r["interaction_id"]].append(r["step_index"])
        out = []
        for row in rows:
            item = dict(row)
            for key in ("stages", "steps", "sources", "codes", "alerts"):
                item[key] = json.loads(item[key] or "[]")
            item["failed_steps"] = failed_by.get(item["id"], [])
            out.append(item)
        return out

    def insights(self, days: int = 30, minutes_per_escalation: int | None = None, now: datetime | None = None) -> dict:
        """Counts and rates for the Insights page. Shows sample data only while sample rows exist."""
        now = now or datetime.now()
        minutes = config.MINUTES_PER_ESCALATION if minutes_per_escalation is None else minutes_per_escalation
        sample_mode = self.has_rows(True)
        rows = self._rows(sample_mode, (now - timedelta(days=days)).timestamp())

        answered = [r for r in rows if not r["fallback"]]
        with_feedback = [r for r in rows if r["outcome"]]
        fixed = [r for r in with_feedback if r["outcome"] == "fixed"]
        not_fixed = [r for r in with_feedback if r["outcome"] == "not_fixed"]
        escalated = [r for r in with_feedback if r["outcome"] == "escalated"]
        elapsed = [r["elapsed"] for r in rows if r["elapsed"] is not None]

        by_day = Counter(datetime.fromtimestamp(r["ts"]).date() for r in rows)
        today = now.date()
        volume = [
            {"date": (today - timedelta(days=offset)).isoformat(), "count": by_day.get(today - timedelta(days=offset), 0)}
            for offset in range(days - 1, -1, -1)
        ]

        topics = Counter(
            (r["codes"][0] if r["codes"] else _doc_name(r["sources"][0]) if r["sources"] else "No matching document")
            for r in rows
        )

        gap_counts: Counter = Counter()
        for r in rows:
            if r["fallback"]:
                gap_counts[(r["question"], r["device"], "no_answer", None)] += 1
            elif r["outcome"] == "not_fixed" and r["reason"] in ("different_problem", "doc_wrong", "need_person"):
                gap_counts[(r["question"], r["device"], "not_fixed", r["reason"])] += 1
        # The same unanswered question asked repeatedly is one gap with a count, not many rows.
        gaps = [
            {"question": q, "device": d, "kind": kind, "reason": reason, "count": count}
            for (q, d, kind, reason), count in gap_counts.most_common()
        ]

        docs: dict[str, dict] = defaultdict(lambda: {"answers": 0, "fixed": 0, "not_fixed": 0})
        for r in answered:
            for name in dict.fromkeys(_doc_name(s) for s in r["sources"]):
                docs[name]["answers"] += 1
                docs[name]["fixed"] += r["outcome"] == "fixed"
                docs[name]["not_fixed"] += r["outcome"] == "not_fixed"
        documents = []
        for name, d in docs.items():
            judged = d["fixed"] + d["not_fixed"]
            documents.append({"document": name, **d, "fix_rate": (d["fixed"] / judged) if judged else None})
        documents.sort(key=lambda d: d["answers"], reverse=True)

        failing = Counter()
        for r in rows:
            for index in r["failed_steps"]:
                if index < len(r["steps"]):
                    failing[r["steps"][index]] += 1

        feedback_total = len(with_feedback)
        return {
            "sample": sample_mode,
            "has_real": self.has_rows(False),
            "days": days,
            "minutes_per_escalation": minutes,
            "questions": len(rows),
            "answered": len(answered),
            "no_answer": len(rows) - len(answered),
            "feedback_count": feedback_total,
            "feedback_coverage": (feedback_total / len(answered)) if answered else None,
            "fixed": len(fixed),
            "not_fixed": len(not_fixed),
            "escalated": len(escalated),
            "fixed_rate": (len(fixed) / feedback_total) if feedback_total else None,
            "escalation_rate": (len(escalated) / feedback_total) if feedback_total else None,
            "median_seconds": round(statistics.median(elapsed), 1) if elapsed else None,
            "estimated_hours_saved": round(len(fixed) * minutes / 60, 1),
            "volume": volume,
            "topics": [{"topic": t, "count": c} for t, c in topics.most_common(6)],
            "gaps": gaps[:8],
            "documents": documents[:8],
            "failing_steps": [{"step": s, "count": c} for s, c in failing.most_common(5)],
            "recent": [
                {
                    "question": r["question"],
                    "device": r["device"],
                    "outcome": r["outcome"],
                    "reason": r["reason"],
                    "ts": datetime.fromtimestamp(r["ts"]).isoformat(timespec="minutes"),
                }
                for r in with_feedback[:8]
            ],
        }

    def export_csv(self) -> str:
        sample_mode = self.has_rows(True)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(
            ["time", "device", "question", "intent", "answered", "outcome", "reason", "seconds", "top_source", "model", "sample_data"]
        )
        for r in self._rows(sample_mode, 0):
            writer.writerow(
                [
                    datetime.fromtimestamp(r["ts"]).isoformat(timespec="seconds"),
                    r["device"],
                    r["question"],
                    r["intent"] or "",
                    "no" if r["fallback"] else "yes",
                    r["outcome"] or "",
                    r["reason"] or "",
                    r["elapsed"] if r["elapsed"] is not None else "",
                    _doc_name(r["sources"][0]) if r["sources"] else "",
                    r["model"] or "",
                    "yes" if r["is_sample"] else "no",
                ]
            )
        return out.getvalue()

    # ---------- sample data and clearing ----------
    def load_sample(self, now: datetime | None = None) -> int:
        """Fill Insights with clearly flagged SAMPLE rows for demos. Never touches real rows."""
        if self.has_rows(True):
            return 0
        now = now or datetime.now()
        rng = random.Random(7)
        count = 0
        for day in range(29, -1, -1):
            for _ in range(rng.choice([2, 3, 3, 4, 5, 6]) if day < 24 else rng.choice([1, 2, 2, 3])):
                case = rng.choice(_SAMPLE_CASES)
                if not case["steps"] and rng.random() > 0.3:
                    case = rng.choice(_SAMPLE_ANSWERED)  # unanswered questions are the minority
                stamp = (now - timedelta(days=day, hours=rng.randint(0, 9), minutes=rng.randint(0, 59))).timestamp()
                no_answer = case["steps"] == []
                fast = not no_answer and rng.random() < 0.45
                interaction_id = self.log_interaction(
                    question=case["question"],
                    device=case["device"],
                    intent="error_code" if case["codes"] else "troubleshooting",
                    fallback=no_answer,
                    elapsed=round(rng.uniform(2.1, 4.8) if fast else rng.uniform(11, 27), 1),
                    steps=case["steps"],
                    sources=[case["source"]] if case["source"] else [],
                    codes=case["codes"],
                    is_sample=True,
                    ts=stamp,
                )
                if no_answer or rng.random() > 0.78:
                    continue  # not every answer gets feedback, like real life
                roll = rng.random()
                if roll < 0.7:
                    self._seed_outcome(interaction_id, stamp, "fixed", None)
                elif roll < 0.88:
                    reason = rng.choice(["step_failed", "step_failed", "different_problem", "doc_wrong"])
                    self._seed_outcome(interaction_id, stamp, "not_fixed", reason)
                    if reason == "step_failed" and case["steps"]:
                        self.set_step_result(interaction_id, rng.randrange(len(case["steps"])), "failed")
                else:
                    self._seed_outcome(interaction_id, stamp, "escalated", "need_person")
                count += 1
        return count

    def _seed_outcome(self, interaction_id: str, stamp: float, outcome: str, reason: str | None) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO feedback (interaction_id, outcome, reason, note, ts) VALUES (?,?,?,?,?)",
                (interaction_id, outcome, reason, None, stamp + 600),
            )

    def clear(self, scope: str = "sample") -> int:
        """Delete sample rows only, or everything. Returns how many interactions were removed."""
        if scope not in ("sample", "all"):
            raise ValueError("scope must be 'sample' or 'all'")
        with self._lock, self._db:
            cursor = (
                self._db.execute("DELETE FROM interactions WHERE is_sample = 1")
                if scope == "sample"
                else self._db.execute("DELETE FROM interactions")
            )
            return cursor.rowcount


_SAMPLE_CASES = [
    {
        "question": "How do I clear a note jam?",
        "device": "HX-ATM-500",
        "codes": [],
        "source": "atm_cash_dispenser_jam_runbook.md, Clearing a note jam",
        "steps": [
            "Take the ATM out of service and open the front door, then the safe door.",
            "Remove the affected cassette and check the pick area for torn or folded notes.",
            "Open the transport path cover and remove any notes.",
            "Check the rollers for dust or residue and clean them.",
            "Run the dispense test and return the ATM to service.",
        ],
    },
    {
        "question": "Getting P-1002 on the terminal",
        "device": "HX-POS-200",
        "codes": ["P-1002"],
        "source": "pos_receipt_printer_runbook.md, Paper out or paper jam",
        "steps": [
            "Open the printer cover and remove any jammed paper.",
            "Wipe the platen roller with a lint-free cloth.",
            "Reload the paper and run a test print from the service menu.",
        ],
    },
    {
        "question": "Card reader is not detected",
        "device": "HX-KIOSK-300",
        "codes": ["K-1001"],
        "source": "kiosk_card_reader_runbook.md, Reader not detected",
        "steps": [
            "Open the Service Menu and check whether the reader is listed.",
            "Reseat the USB cable at both ends and power on again.",
            "Run the reader self test, and replace the reader if it still fails.",
        ],
    },
    {
        "question": "Receipts are printing blank",
        "device": "HX-POS-200",
        "codes": [],
        "source": "pos_receipt_printer_runbook.md, Faint or blank receipts",
        "steps": [
            "Flip the roll of paper and retry printing.",
            "Clean the print head with an alcohol swab.",
            "Check the print density setting.",
        ],
    },
    {
        "question": "Payment host timeouts but ping works",
        "device": "HX-POS-200",
        "codes": ["P-2002"],
        "source": "network_connectivity_runbook.md, Connectivity tests",
        "steps": [
            "Ping the payment host by IP address.",
            "Check the firewall rule for the payment port.",
            "Restart the network service from the service menu.",
        ],
    },
    {
        "question": "How do I reset the cassette counters after refilling?",
        "device": "HX-ATM-500",
        "codes": [],
        "source": "hx-atm-500_cash_cassette_replenishment.docx, Replenishment steps",
        "steps": [
            "Close both doors after loading the cassette.",
            "Choose Counters, then Reset cassette counters, and enter the loaded count.",
            "Run the dispense test and return the ATM to service.",
        ],
    },
    {
        "question": "Kiosk firmware update stuck at 40 percent",
        "device": "HX-KIOSK-300",
        "codes": ["K-7002"],
        "source": "hx-kiosk-300_firmware_update_guide.pdf, p.3",
        "steps": [
            "Check the network link and the free disk space.",
            "Choose Download again so it resumes from the last verified block.",
            "Roll back to the previous version if it fails twice.",
        ],
    },
    {
        "question": "Cash drawer will not open after a sale",
        "device": "HX-POS-200",
        "codes": ["P-3001"],
        "source": "pos_receipt_printer_runbook.md, Cash drawer does not open",
        "steps": [
            "Check that the RJ12 drawer cable is seated at the printer.",
            "Confirm the drawer-kick setting is enabled.",
            "Use the manual key release so the customer is not delayed.",
        ],
    },
    {"question": "Printer will not pair after firmware 4.1", "device": "HX-POS-200", "codes": [], "source": None, "steps": []},
    {"question": "How do I replace the ATM router?", "device": "HX-ATM-500", "codes": [], "source": None, "steps": []},
    {"question": "Scheduling the A-7001 patch window", "device": "HX-ATM-500", "codes": ["A-7001"], "source": None, "steps": []},
]
_SAMPLE_ANSWERED = [case for case in _SAMPLE_CASES if case["steps"]]
