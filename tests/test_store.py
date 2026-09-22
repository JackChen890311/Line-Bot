import json

from line_bot.store import HistoryLog, PendingStore, READY, THINKING


def test_history_append_writes_jsonl(tmp_path):
    log = HistoryLog(tmp_path)
    log.append("U123", "user", "hi")
    log.append("U123", "bot", "你說：hi")

    lines = (tmp_path / "history" / "U123.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert (first["role"], first["text"]) == ("user", "hi")
    assert (second["role"], second["text"]) == ("bot", "你說：hi")
    assert "ts" in first


def test_pending_full_cycle(tmp_path):
    store = PendingStore(tmp_path)
    assert store.read("U1") is None

    store.save_thinking("U1", "Q?")
    pend = store.read("U1")
    assert pend["status"] == THINKING and pend["answer"] is None

    assert store.save_ready("U1", "Q?", "A!") is True
    pend = store.read("U1")
    assert pend["status"] == READY and pend["answer"] == "A!"

    store.clear("U1")
    assert store.read("U1") is None


def test_pending_save_ready_guards_stale_question(tmp_path):
    store = PendingStore(tmp_path)
    store.save_thinking("U1", "Q-new")

    # Stale worker for an older question must not clobber the slot.
    assert store.save_ready("U1", "Q-old", "stale") is False
    pend = store.read("U1")
    assert pend["question"] == "Q-new" and pend["status"] == THINKING


def test_pending_clear_missing_file_no_raise(tmp_path):
    PendingStore(tmp_path).clear("nobody")
