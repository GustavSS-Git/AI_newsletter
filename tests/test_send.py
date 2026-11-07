import pytest

from newsletter.send import SendError, send_edition
from tests.conftest import make_edition

CFG = {"publication": {"name": "AI Daily", "tagline": "T.", "footer": "F", "base_url": "https://news.example.com"}}


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, str(data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, existing=None, post_status=201):
        self.existing, self.post_status, self.posts, self.gets = existing or [], post_status, [], []

    def get(self, url, headers=None, params=None, timeout=None):
        self.gets.append((url, headers, params))
        return FakeResp(200, {"results": self.existing, "count": len(self.existing)})

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json, headers))
        return FakeResp(self.post_status, {"id": "em_1", "status": json["status"]} if self.post_status < 400 else {"detail": "bad"})


def test_draft_mode_creates_draft_with_headers_and_metadata():
    s = FakeSession()
    out = send_edition(make_edition(), CFG, mode="draft", key="k", session=s)
    assert out["id"] == "em_1"
    url, payload, headers = s.posts[0]
    assert url.endswith("/v1/emails") and payload["status"] == "draft"
    assert payload["metadata"]["edition"] == "2026-11-04" and payload["archival_mode"] == "disabled"
    assert payload["body"].startswith("<!-- buttondown-editor-mode: fancy -->")
    assert headers["Authorization"] == "Token k" and headers["X-Idempotency-Key"].startswith("ai-daily-2026-11-04-draft-")
    assert payload["canonical_url"] == "https://news.example.com/archive/2026-11-04"


def test_send_mode_uses_about_to_send():
    s = FakeSession()
    send_edition(make_edition(), CFG, mode="send", key="k", session=s)
    assert s.posts[0][1]["status"] == "about_to_send"
    assert s.posts[0][2]["X-Buttondown-Live-Dangerously"] == "true"


def test_draft_mode_omits_live_header():
    s = FakeSession()
    send_edition(make_edition(), CFG, mode="draft", key="k", session=s)
    assert "X-Buttondown-Live-Dangerously" not in s.posts[0][2]


def test_existing_email_for_edition_is_not_recreated():
    s = FakeSession(existing=[{"id": "em_0", "status": "sent", "metadata": {"edition": "2026-11-04"}}])
    out = send_edition(make_edition(), CFG, mode="send", key="k", session=s)
    assert out["id"] == "em_0" and s.posts == []


def test_other_editions_emails_do_not_block():
    s = FakeSession(existing=[{"id": "em_0", "status": "sent", "metadata": {"edition": "2026-11-03"}}])
    send_edition(make_edition(), CFG, mode="draft", key="k", session=s)
    assert len(s.posts) == 1


def test_api_error_raises():
    with pytest.raises(SendError):
        send_edition(make_edition(), CFG, mode="draft", key="k", session=FakeSession(post_status=400))


def test_missing_key_and_bad_mode(monkeypatch):
    monkeypatch.delenv("BUTTONDOWN_API_KEY", raising=False)
    with pytest.raises(SendError):
        send_edition(make_edition(), CFG, mode="draft", session=FakeSession())
    with pytest.raises(ValueError):
        send_edition(make_edition(), CFG, mode="blast", key="k", session=FakeSession())


def test_idempotency_key_differs_per_run(monkeypatch):
    keys = []
    for run in ("111", "222"):
        monkeypatch.setenv("GITHUB_RUN_ID", run)
        s = FakeSession()
        send_edition(make_edition(), CFG, mode="send", key="k", session=s)
        keys.append(s.posts[0][2]["X-Idempotency-Key"])
    assert keys[0] != keys[1] and keys[0].startswith("ai-daily-2026-11-04-send-111")
