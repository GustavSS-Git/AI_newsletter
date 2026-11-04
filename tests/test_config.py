import pytest

from newsletter.config import api_key_problem


@pytest.mark.parametrize("value,ok", [
    ("sk-ant-api03-abcDEF_123", True),
    ("  sk-ant-api03-abc\n", True),                       # surrounding whitespace is stripped
    ("", False),
    ("curl https://api.anthropic.com/v1/messages \\\n  -H 'x-api-key: sk-ant-x'", False),
    ("ANTHROPIC_API_KEY=sk-ant-abc", False),
    ('"sk-ant-abc"', False),
    ("abc123", False),
])
def test_api_key_problem(monkeypatch, value, ok):
    monkeypatch.setenv("ANTHROPIC_API_KEY", value)
    problem = api_key_problem()
    assert (problem is None) == ok
    if problem:
        assert "sk-ant-x" not in problem and "abc" not in problem   # never echoes the key


def test_api_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "not set" in api_key_problem()
