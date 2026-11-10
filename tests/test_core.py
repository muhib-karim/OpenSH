"""Unit tests for OpenSH's non-network logic: classifier, history, config, prompt, providers, CLI."""
import io
import json
import pathlib
import subprocess
import sys
import urllib.error
from email.message import Message

import pytest
from conftest import LINUX, WINDOWS

import opsh

ROOT = pathlib.Path(__file__).resolve().parents[1]


# --- version comparison ------------------------------------------------------

@pytest.mark.parametrize("latest,current,expected", [
    ("0.3.1", "0.3.0", True), ("v1.0.0", "0.3.0", True), ("0.10.0", "0.9.0", True),
    ("0.3.0", "0.3.0", False), ("0.2.0", "0.3.0", False), ("", "0.3.0", False),
])
def test_is_newer_version(latest, current, expected):
    assert opsh.is_newer_version(latest, current) is expected


# --- shell-vs-English classifier ---------------------------------------------

@pytest.mark.parametrize("text", ["ls", "pwd", "git status", "cd ..", "./build.sh", "sudo apt update",
                                  "cat notes.txt | grep todo", "!echo hi", "exit"])
def test_shell_input_bypasses_ai_on_linux(text):
    assert not opsh.is_natural_language(text)


@pytest.mark.parametrize("text", ["show me large files", "what is my ip address",
                                  "compress the logs folder into a zip"])
def test_english_goes_to_ai(text):
    assert opsh.is_natural_language(text)


def test_windows_classifier_knows_powershell(monkeypatch):
    monkeypatch.setattr(opsh, "PLATFORM", WINDOWS)
    assert not opsh.is_natural_language("Get-ChildItem -Recurse")
    assert not opsh.is_natural_language("ipconfig")
    assert opsh.is_natural_language("list running processes")


# --- history -----------------------------------------------------------------

def test_history_is_capped_and_output_truncated():
    for i in range(opsh.MAX_HISTORY + 5):
        opsh.add_to_history(f"cmd{i}", "x" * 1000)
    assert len(opsh.command_history) <= opsh.MAX_HISTORY
    assert all(len(e["output"]) == 500 for e in opsh.command_history)
    assert opsh.get_context_size() <= opsh.MAX_CONTEXT_CHARS
    assert opsh.command_history[-1]["command"] == f"cmd{opsh.MAX_HISTORY + 4}"


def test_format_history_shows_last_five_with_two_output_lines():
    assert opsh.format_history() == "No previous commands."
    for i in range(7):
        opsh.add_to_history(f"cmd{i}", "line1\nline2\nline3")
    text = opsh.format_history()
    assert "$ cmd0" not in text and "$ cmd1" not in text
    assert "1. $ cmd2" in text and "5. $ cmd6" in text
    assert "line2" in text and "line3" not in text


# --- safety confirmation -----------------------------------------------------

def test_safe_command_never_prompts():
    def ask(_):
        raise AssertionError("should not prompt")
    assert opsh.confirm_if_destructive("ls -la", ask=ask)


@pytest.mark.parametrize("answer,expected", [("y", True), ("YES", True), ("n", False), ("", False)])
def test_destructive_command_needs_explicit_yes(answer, expected):
    assert opsh.confirm_if_destructive("rm -rf build", ask=lambda _: answer) is expected


def test_destructive_command_skipped_on_eof_and_allowed_with_assume_yes():
    def eof(_):
        raise EOFError
    assert not opsh.confirm_if_destructive("rm -rf build", ask=eof)
    assert opsh.confirm_if_destructive("rm -rf build", assume_yes=True, ask=eof)


# --- config and .env ---------------------------------------------------------

def test_config_round_trip():
    assert opsh.load_config() == {}
    opsh.save_config({"provider": "gemini"})
    assert opsh.load_config() == {"provider": "gemini"}


def test_save_api_key_keeps_other_keys_and_load_env_reads_them(monkeypatch):
    opsh.env_path.write_text("# comment\nOTHER=1\n")
    opsh.save_api_key("groq", "test-groq")
    opsh.save_api_key("gemini", "test-gemini")
    assert opsh.env_path.read_text().splitlines() == ["OTHER=1", "GROQ_API_KEY=test-groq", "GEMINI_API_KEY=test-gemini"]

    for key in ("OTHER", "GROQ_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)  # exported variables win over the file, so start clean
    opsh.load_env()
    assert opsh.os.environ["GROQ_API_KEY"] == "test-groq"
    assert opsh.os.environ["GEMINI_API_KEY"] == "test-gemini"


@pytest.mark.parametrize("provider,var", [("groq", "GROQ_API_KEY"), ("gemini", "GEMINI_API_KEY")])
def test_missing_key_points_user_to_auth(monkeypatch, provider, var):
    opsh.save_config({"provider": provider})
    monkeypatch.delenv(var, raising=False)
    with pytest.raises(Exception, match="!auth"):
        opsh.get_ai_response("anything")


# --- prompt building ---------------------------------------------------------

def test_prompt_includes_request_files_and_history(monkeypatch, tmp_path):
    work = tmp_path / "work"
    (work / "Current Resume").mkdir(parents=True)
    opsh.add_to_history("git status", "On branch main")
    captured: dict[str, str] = {}
    monkeypatch.setattr(opsh, "get_ai_response", lambda p: captured.setdefault("prompt", p) and "ls")

    assert opsh.get_command("open the resume folder", str(work)) == "ls"
    prompt = captured["prompt"]
    assert "User request: open the resume folder" in prompt
    assert "Current Resume" in prompt
    assert "$ git status" in prompt
    assert "bash on Linux" in prompt


def test_windows_prompt_asks_for_powershell(monkeypatch, tmp_path):
    monkeypatch.setattr(opsh, "PLATFORM", WINDOWS)
    captured: dict[str, str] = {}
    monkeypatch.setattr(opsh, "get_ai_response", lambda p: captured.setdefault("prompt", p))
    opsh.get_command("list files", str(tmp_path))
    assert "PowerShell command for Windows" in captured["prompt"]


# --- provider calls (network mocked) -----------------------------------------

class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_groq_parses_response_and_retries_on_429(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", Message(), None)
        body = {"choices": [{"message": {"content": "  ls -la\n"}}]}
        return _FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr(opsh.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(opsh.time, "sleep", lambda s: None)
    assert opsh.call_groq("prompt", "test-key") == "ls -la"
    assert len(calls) == 2
    assert calls[0].get_header("Authorization") == "Bearer test-key"
    assert json.loads(calls[0].data)["model"] == opsh.DEFAULT_MODELS["groq"]


def test_gemini_parses_response(monkeypatch):
    body = {"candidates": [{"content": {"parts": [{"text": "pwd\n"}]}}]}
    monkeypatch.setattr(opsh.urllib.request, "urlopen", lambda req, timeout: _FakeResponse(json.dumps(body).encode()))
    assert opsh.call_gemini("prompt", "test-key") == "pwd"


def test_provider_gives_up_after_repeated_429(monkeypatch):
    def always_429(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", Message(), None)
    monkeypatch.setattr(opsh.urllib.request, "urlopen", always_429)
    monkeypatch.setattr(opsh.time, "sleep", lambda s: None)
    with pytest.raises(Exception, match="Rate limit"):
        opsh.call_groq("prompt", "test-key")


# --- command runner and CLI --------------------------------------------------

def test_run_command_captures_output():
    stdout, _ = opsh.run_command("echo hello")
    assert "hello" in stdout


def test_cli_help_and_version():
    help_run = subprocess.run([sys.executable, str(ROOT / "opsh.py"), "--help"],
                              capture_output=True, text=True, timeout=60)
    assert help_run.returncode == 0
    assert "--command" in help_run.stdout and "--yes" in help_run.stdout

    version_run = subprocess.run([sys.executable, str(ROOT / "opsh.py"), "--version"],
                                 capture_output=True, text=True, timeout=60)
    assert version_run.returncode == 0
    assert version_run.stdout.strip() == f"OpenSH v{opsh.__version__}"


@pytest.mark.parametrize("platform_info,exit_key", [(LINUX, "Ctrl+D"), (WINDOWS, "Ctrl+C")])
def test_help_lists_the_right_exit_key(monkeypatch, capsys, platform_info, exit_key):
    monkeypatch.setattr(opsh, "PLATFORM", platform_info)
    opsh.show_help()
    out = capsys.readouterr().out
    assert any(exit_key in line and "Exit OpenSH" in line for line in out.splitlines())
