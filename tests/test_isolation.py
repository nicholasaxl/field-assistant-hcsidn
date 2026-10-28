import config
from src import api


def test_feedback_db_is_redirected_away_from_the_real_one(tmp_path):
    assert config.FEEDBACK_DB.parent == tmp_path
    store = api.get_feedback_store()  # the cached default used when a test forgets to override it
    store.log_interaction(question="q", device="all")
    assert (tmp_path / "guard-feedback.db").exists()
