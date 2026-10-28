"""Safety rules that no model decides: critical error codes and risky topics always raise an alert.

Rules live in data/policies.json so the customer can edit wording, keywords and the escalation contact
without touching code.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import config

LEVEL_ORDER = {"critical": 0, "warning": 1}
EMPTY = {"escalation_contact": "", "critical_severities": [], "keyword_rules": []}


@lru_cache(maxsize=4)
def _read(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_policies(path: str | Path | None = None) -> dict:
    path = Path(path or config.POLICIES_JSON)
    if not path.exists():
        return EMPTY
    return _read(str(path), path.stat().st_mtime)  # re-read when the file is edited


def _mentions(text: str, keyword: str) -> bool:
    return re.search(rf"\b{re.escape(keyword.lower())}\b", text) is not None


def evaluate(question: str, code_records: list[dict], answer_text: str, policies: dict | None = None) -> list[dict]:
    """Alerts for this question and answer, most severe first. Each is {id, level, title, message}."""
    policies = policies if policies is not None else load_policies()
    contact = policies.get("escalation_contact", "")
    suffix = f" Contact: {contact}" if contact else ""
    critical_severities = set(policies.get("critical_severities", []))

    alerts: dict[str, dict] = {}
    for record in code_records:
        if record.get("severity") in critical_severities:
            alerts.setdefault(
                f"code-{record['code']}",
                {
                    "id": f"code-{record['code']}",
                    "level": "critical",
                    "title": f"Critical fault {record['code']}",
                    "message": f"{record['meaning']}. Stop and escalate before doing anything else.{suffix}",
                },
            )

    haystack = f"{question} {answer_text}".lower()
    for rule in policies.get("keyword_rules", []):
        if any(_mentions(haystack, keyword) for keyword in rule["keywords"]):
            level = rule.get("level", "warning")
            alerts.setdefault(
                rule["id"],
                {
                    "id": rule["id"],
                    "level": level,
                    "title": rule["title"],
                    "message": rule["message"] + (suffix if level == "critical" else ""),
                },
            )
    return sorted(alerts.values(), key=lambda a: LEVEL_ORDER.get(a["level"], 9))
