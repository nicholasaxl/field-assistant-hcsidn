from src import policy
from src.citations import answer_strength

RULES = {
    "escalation_contact": "Desk 123",
    "critical_severities": ["Critical"],
    "keyword_rules": [
        {"id": "tamper", "level": "critical", "keywords": ["skimmer"], "title": "Tampering", "message": "Stop."},
        {"id": "two", "level": "warning", "keywords": ["safe door"], "title": "Two people", "message": "Never alone."},
    ],
}


def test_critical_code_alert_includes_contact():
    records = [{"code": "A-2002", "meaning": "Skimmer suspected", "severity": "Critical"}]
    alerts = policy.evaluate("A-2002", records, "", RULES)
    assert alerts[0]["id"] == "code-A-2002" and alerts[0]["level"] == "critical"
    assert "Desk 123" in alerts[0]["message"]


def test_non_critical_code_has_no_alert():
    records = [{"code": "P-1001", "meaning": "Out of paper", "severity": "Low"}]
    assert policy.evaluate("P-1001", records, "", RULES) == []


def test_keywords_match_whole_words_in_question_or_answer():
    assert [a["id"] for a in policy.evaluate("is this a skimmer?", [], "", RULES)] == ["tamper"]
    assert [a["id"] for a in policy.evaluate("jam", [], "Open the safe door first.", RULES)] == ["two"]
    assert policy.evaluate("skimmers are fine", [], "", RULES) == []  # whole word only
    assert policy.evaluate("keyboard problem", [], "", {**RULES, "keyword_rules": [
        {"id": "k", "level": "critical", "keywords": ["key"], "title": "K", "message": "M"}]}) == []


def test_alerts_sorted_most_severe_first_and_deduplicated():
    alerts = policy.evaluate("skimmer", [], "open the safe door, skimmer, skimmer", RULES)
    assert [a["id"] for a in alerts] == ["tamper", "two"]


def test_missing_policy_file_means_no_alerts(tmp_path):
    assert policy.evaluate("skimmer", [], "", policy.load_policies(tmp_path / "nope.json")) == []


def test_shipped_policy_file_is_valid_and_has_rules():
    shipped = policy.load_policies()
    assert shipped["critical_severities"] == ["Critical"]
    assert {r["id"] for r in shipped["keyword_rules"]} >= {"tampering", "two-person-control"}
    assert all({"id", "level", "keywords", "title", "message"} <= rule.keys() for rule in shipped["keyword_rules"])


def test_answer_strength_levels():
    close = [{"distance": 0.5}]
    far = [{"distance": 0.8}]
    assert answer_strength(close, 3, 0, False)["level"] == "strong"
    assert answer_strength(far, 3, 0, False)["level"] == "good"
    assert answer_strength(far, 3, 0, True)["level"] == "strong"  # exact error-code match
    assert answer_strength(close, 2, 1, False)["level"] == "check"
    assert answer_strength(close, 0, 0, False)["level"] == "check"
