"""Shared fixtures. No test in this suite talks to a real LLM API or needs an API key."""

import io
import json
import signal
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import opsh  # noqa: E402

# Kept before the autouse fixture stubs it out, so it can be tested directly
REAL_CHECK_FOR_UPDATES = opsh.check_for_updates

LINUX = {"name": "Linux", "shell": "bash", "home": Path.home(), "path_sep": "/"}


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeLLM:
    """Stands in for urllib.request.urlopen and records every request."""

    def __init__(self):
        self.requests = []
        self.replies = []

    def reply_groq(self, text):
        self.replies.append({"choices": [{"message": {"content": text}}]})

    def reply_gemini(self, text):
        self.replies.append({"candidates": [{"content": {"parts": [{"text": text}]}}]})

    def fail(self, code, body=b'{"error": {"message": "bad"}}'):
        self.replies.append(("http_error", code, body))

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if not self.replies:
            raise AssertionError(f"unexpected network call to {req.full_url}")
        reply = self.replies.pop(0)
        if isinstance(reply, tuple) and reply[0] == "http_error":
            _, code, body = reply
            raise urllib.error.HTTPError(req.full_url, code, "error", {}, io.BytesIO(body))
        return FakeResponse(reply)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point config/.env at a temp dir, clear API keys and block real network access."""
    monkeypatch.setattr(opsh, "config_path", tmp_path / "config.json")
    monkeypatch.setattr(opsh, "env_path", tmp_path / ".env")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(opsh, "command_history", [])
    monkeypatch.setattr(opsh, "commands_run", 0)
    monkeypatch.setattr(opsh, "_keys_from_shell", set())
    monkeypatch.setattr(opsh, "check_for_updates", lambda: None)
    monkeypatch.setattr(opsh.time, "sleep", lambda seconds: None)

    def no_network(req, timeout=None):
        raise AssertionError("tests must not make real network calls")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    previous_sigint = signal.getsignal(signal.SIGINT)
    yield tmp_path
    signal.signal(signal.SIGINT, previous_sigint)


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(urllib.request, "urlopen", llm)
    return llm


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(opsh, "PLATFORM", LINUX)


@pytest.fixture
def run_main(monkeypatch):
    """Run opsh.main() with the given argv and scripted answers to input()."""

    def run(*argv, answers=()):
        pending = list(answers)

        def fake_input(prompt=""):
            if not pending:
                raise EOFError
            return pending.pop(0)

        monkeypatch.setattr("builtins.input", fake_input)
        monkeypatch.setattr(sys, "argv", ["opsh", *argv])
        try:
            opsh.main()
        except SystemExit as e:
            return e.code
        return 0

    return run
