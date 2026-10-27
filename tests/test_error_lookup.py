from src.error_lookup import ErrorCodeDB

db = ErrorCodeDB()


def test_sample_table_loaded():
    assert db.devices() == ["HX-ATM-500", "HX-KIOSK-300", "HX-POS-200"]


def test_lookup_normalizes_code():
    for variant in ("P-1002", "p1002", "P 1002"):
        records = db.lookup(variant)
        assert len(records) == 1 and records[0]["meaning"] == "Receipt printer paper jam"


def test_device_filter():
    assert db.lookup("A-9000", "HX-POS-200") == []
    assert db.lookup("A-9000", "HX-ATM-500")[0]["severity"] == "Critical"
    assert db.lookup("A-9000", "all")[0]["code"] == "A-9000"


def test_find_in_free_text_ignores_unknown_tokens():
    records = db.find("The HX-POS-200 shows P-1002 and also ZZ-999 and 12345")
    assert [r["code"] for r in records] == ["P-1002"]
    assert db.find("printer is making noise") == []
