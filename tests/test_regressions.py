"""One regression test per bug fixed in 0.4.0. Nothing here touches the network or a real API key."""
import io
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import urllib.error
from email.message import Message

import pytest
from conftest import MACOS, WINDOWS

import opsh

ROOT = pathlib.Path(__file__).resolve().parents[1]
posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX behaviour")


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _reply(body):
    return _FakeResponse(json.dumps(body).encode())


def _http_error(code, body):
    return urllib.error.HTTPError("https://example.invalid", code, "error", Message(), io.BytesIO(json.dumps(body).encode()))


def _capture_requests(monkeypatch, body):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req)
        return _reply(body)

    monkeypatch.setattr(opsh.urllib.request, "urlopen", fake_urlopen)
    return calls


def run_main(monkeypatch, argv, stdin_text="", ai=None):
    """Run the CLI in-process with a non-terminal stdin; returns the exit code."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    monkeypatch.setenv("OPSH_NO_UPDATE_CHECK", "1")
    if ai is not None:
        monkeypatch.setattr(opsh, "get_ai_response", ai)
    try:
        return opsh.main(argv)
    except SystemExit as e:
        return e.code


def _record_commands(monkeypatch):
    """Replace execute() with a stub that records what it was asked to run."""
    ran: list[str] = []

    def fake_execute(cmd):
        ran.append(cmd)
        return opsh.CommandResult("", "", 0)
    monkeypatch.setattr(opsh, "execute", fake_execute)
    return ran


GROQ_OK = {"choices": [{"message": {"content": "ls"}}]}
GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "ls"}]}}]}


# --- retired models (the tool could not answer any request) --------------------

def test_default_models_are_not_the_retired_ones():
    assert "llama-3.3-70b-versatile" not in opsh.DEFAULT_MODELS.values()
    assert "gemini-2.0-flash" not in opsh.DEFAULT_MODELS.values()


def test_model_comes_from_env_then_config_then_default(monkeypatch):
    assert opsh.get_model("groq") == opsh.DEFAULT_MODELS["groq"]
    opsh.save_config({"provider": "groq", "model": "from-config"})
    assert opsh.get_model("groq") == "from-config"
    monkeypatch.setenv("OPSH_MODEL", "from-env")
    assert opsh.get_model("groq") == "from-env"


def test_configured_model_is_what_gets_requested(monkeypatch):
    opsh.save_config({"provider": "groq"})
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("OPSH_MODEL", "some/other-model")
    calls = _capture_requests(monkeypatch, GROQ_OK)
    assert opsh.get_ai_response("prompt") == "ls"
    body = json.loads(calls[0].data)
    assert body["model"] == "some/other-model"
    assert "reasoning_effort" not in body  # only sent to models that accept it


def test_groq_default_request_uses_current_parameters(monkeypatch):
    calls = _capture_requests(monkeypatch, GROQ_OK)
    opsh.call_groq("prompt", "test-key")
    body = json.loads(calls[0].data)
    assert body["max_completion_tokens"] > 0 and "max_tokens" not in body
    assert body["reasoning_effort"] == "low"


@pytest.mark.parametrize("call,code,message", [
    (opsh.call_groq, 400, "The model `llama-3.3-70b-versatile` has been decommissioned and is no longer supported."),
    (opsh.call_gemini, 404, "models/gemini-2.0-flash is not found for API version v1beta, or is not supported for generateContent."),
])
def test_retired_model_error_says_how_to_change_it(monkeypatch, call, code, message):
    def retired(req, timeout):
        raise _http_error(code, {"error": {"message": message}})
    monkeypatch.setattr(opsh.urllib.request, "urlopen", retired)
    with pytest.raises(opsh.ProviderError) as caught:
        call("prompt", "test-key")
    assert caught.value.kind == "model"
    assert "OPSH_MODEL" in str(caught.value) and message[:40] in str(caught.value)


# --- where config lives (release binaries forgot the key on every launch) ------

def test_frozen_binary_keeps_config_in_home_not_the_temp_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert opsh.get_config_dir() == tmp_path / "home" / ".opsh"


def test_opsh_home_overrides_the_config_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("OPSH_HOME", str(tmp_path / "elsewhere"))
    assert opsh.get_config_dir() == tmp_path / "elsewhere"


def test_source_run_keeps_config_next_to_the_script():
    assert opsh.get_config_dir().samefile(ROOT)


def test_saving_creates_the_config_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(opsh, "config_path", tmp_path / "new" / "dir" / "config.json")
    opsh.save_config({"provider": "groq"})
    assert opsh.load_config() == {"provider": "groq"}


# --- shell used to run commands -------------------------------------------------

@posix_only
@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_commands_run_in_bash_not_plain_sh():
    stdout, stderr = opsh.run_command("echo {a,b}; [[ 1 == 1 ]] && echo ok")
    assert stdout.split() == ["a", "b", "ok"] and stderr == ""


def test_shell_falls_back_to_sh_when_bash_is_missing(monkeypatch):
    monkeypatch.setattr(opsh.shutil, "which", lambda name: None)
    assert opsh.detect_shell() == "/bin/sh"


def test_shell_choice_per_platform(monkeypatch):
    monkeypatch.setattr(opsh.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert opsh.detect_shell() == "/usr/bin/bash"
    monkeypatch.setattr(opsh, "PLATFORM", MACOS)
    assert opsh.detect_shell() == "/usr/bin/zsh"
    monkeypatch.setattr(opsh, "PLATFORM", WINDOWS)
    assert opsh.detect_shell() is None


@posix_only
def test_prompt_names_the_shell_that_will_run_the_command(monkeypatch, tmp_path):
    monkeypatch.setattr(opsh.shutil, "which", lambda name: None)
    captured: dict[str, str] = {}
    monkeypatch.setattr(opsh, "get_ai_response", lambda p: captured.setdefault("prompt", p))
    opsh.get_command("list files", str(tmp_path))
    assert "shell command for sh on Linux" in captured["prompt"]


# --- model output hygiene --------------------------------------------------------

@pytest.mark.parametrize("reply,expected", [
    ("```bash\nls -la\n```", "ls -la"),
    ("```\nls -la\n```", "ls -la"),
    ("```ls -la```", "ls -la"),
    ("Here you go:\n```sh\nls -la\n```\nHope that helps!", "ls -la"),
    ("`ls -la`", "ls -la"),
    ("$ ls -la", "ls -la"),
    ("  ls -la \n", "ls -la"),
    ("echo `date`", "echo `date`"),
    ("```powershell\nGet-ChildItem\n```", "Get-ChildItem"),
])
def test_model_reply_is_reduced_to_the_command(reply, expected):
    assert opsh.clean_model_output(reply) == expected


@pytest.mark.parametrize("reply", ["", "   \n", "```\n```", "``"])
def test_empty_model_reply_is_an_error_not_a_command(reply):
    with pytest.raises(opsh.ProviderError, match="no command"):
        opsh.clean_model_output(reply)


def test_get_command_cleans_the_reply(monkeypatch, tmp_path):
    monkeypatch.setattr(opsh, "get_ai_response", lambda p: "```bash\necho hi\n```")
    assert opsh.get_command("say hi", str(tmp_path)) == "echo hi"


# --- cd handling -----------------------------------------------------------------

@pytest.mark.parametrize("command,target", [
    ("cd", ""), ("cd ..", ".."), ("CD ..", ".."), ("cd..", ".."), ("cd ../..", "../.."), ("cd /tmp", "/tmp"),
    ('cd "My Dir"', "My Dir"), ("cd 'My Dir'", "My Dir"), ("cd My Dir", "My Dir"), ("cd -", "-"), ("cd ~/x", "~/x"),
    ("chdir sub", "sub"), ("Set-Location sub", "sub"), ('set-location -Path "C:\\Temp"', "C:\\Temp"),
])
def test_plain_directory_changes_are_recognised(command, target):
    assert opsh.parse_cd(command) == target


@pytest.mark.parametrize("command", [
    "cd /tmp && ls", "cd build; make", "cd x || exit", "cd x | cat", "cd $(pwd)", "cd x\nls",
    "cdrecord x", "cdk deploy", "echo cd", "ls", "sl", "sl x",
])
def test_compound_and_lookalike_commands_are_not_treated_as_cd(command):
    assert opsh.parse_cd(command) is None


def test_windows_cd_forms(monkeypatch):
    monkeypatch.setattr(opsh, "PLATFORM", WINDOWS)
    assert opsh.parse_cd("sl C:\\Temp") == "C:\\Temp"
    assert opsh.parse_cd("cd /d D:\\Work") == "D:\\Work"
    assert opsh.parse_cd("cd\\") == "\\"


def test_change_directory_expands_home_variables_and_dash(monkeypatch, tmp_path):
    (tmp_path / "home" / "docs").mkdir(parents=True)
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPSH_TEST_DIR", str(tmp_path / "work"))

    assert opsh.change_directory("$OPSH_TEST_DIR") is None
    assert pathlib.Path.cwd().samefile(tmp_path / "work")
    assert opsh.change_directory("$env:OPSH_TEST_DIR") is None
    assert opsh.change_directory("") is None
    assert pathlib.Path.cwd().samefile(tmp_path / "home")
    assert opsh.change_directory("-") is None
    assert pathlib.Path.cwd().samefile(tmp_path / "work")
    assert "cd:" in (opsh.change_directory("no-such-folder") or "")


def test_generated_cd_chain_reaches_the_shell_instead_of_failing_as_a_path(monkeypatch):
    ran = _record_commands(monkeypatch)
    assert opsh.handle_generated("cd /tmp && echo chained", assume_yes=False) == 0
    assert ran == ["cd /tmp && echo chained"]


def test_typed_cd_with_quotes_changes_directory(monkeypatch, tmp_path):
    (tmp_path / "My Dir").mkdir()
    monkeypatch.chdir(tmp_path)
    opsh.save_config({"provider": "groq"})
    assert run_main(monkeypatch, [], stdin_text='cd "My Dir"\nexit\n') == 0
    assert pathlib.Path.cwd().samefile(tmp_path / "My Dir")


def test_shell_survives_its_folder_being_deleted(monkeypatch, tmp_path):
    calls: list[int] = []
    moved_to: list[pathlib.Path] = []

    def getcwd():
        calls.append(1)
        if len(calls) == 1:
            raise FileNotFoundError("deleted")
        return str(tmp_path / "home")
    monkeypatch.setattr(opsh.os, "getcwd", getcwd)
    monkeypatch.setattr(opsh.os, "chdir", moved_to.append)
    assert opsh._safe_cwd() == str(tmp_path / "home")
    assert moved_to == [tmp_path / "home"]


# --- classifier ------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "open the resume folder", "make a new folder called test", "go to the downloads folder",
    "export the user list to csv", "cut the first column from data.csv", "touch up the readme for me",
    "open my documents", "source the env file in this folder",
])
def test_sentences_starting_with_a_command_word_go_to_the_model(text):
    assert opsh.is_natural_language(text)


@pytest.mark.parametrize("text", [
    "open report.pdf", "open .", "make install", "make clean all", "make -j4 all", "go build ./...", "go mod tidy",
    "export PATH=$PATH:/x", "source venv/bin/activate", "touch a b c", "cut -d, -f1 data.csv", "open -a Safari the.html",
])
def test_real_command_lines_still_run_directly(text):
    assert not opsh.is_natural_language(text)


def test_windows_sentences_and_commands(monkeypatch):
    monkeypatch.setattr(opsh, "PLATFORM", WINDOWS)
    assert opsh.is_natural_language("copy all pdf files to the backup folder")
    assert opsh.is_natural_language("move the reports into docs")
    assert opsh.is_natural_language("type out the readme")
    assert not opsh.is_natural_language("copy a.txt b.txt")
    assert not opsh.is_natural_language("copy a b")
    assert not opsh.is_natural_language("type notes.txt")


# --- exit codes and non-interactive use ------------------------------------------

def test_single_request_returns_the_commands_exit_code(monkeypatch):
    opsh.save_config({"provider": "groq"})
    assert run_main(monkeypatch, ["-c", "fail"], ai=lambda p: "exit 3") == 3
    assert run_main(monkeypatch, ["-c", "ok"], ai=lambda p: "echo ok") == 0


def test_single_request_fails_when_the_provider_fails(monkeypatch, capsys):
    opsh.save_config({"provider": "groq"})

    def broken(prompt):
        raise opsh.ProviderError("API error 500: boom")
    assert run_main(monkeypatch, ["-c", "x"], ai=broken) == 1
    assert "boom" in capsys.readouterr().err


def test_declined_destructive_command_is_not_run_and_exits_nonzero(monkeypatch):
    opsh.save_config({"provider": "groq"})
    ran = _record_commands(monkeypatch)
    assert run_main(monkeypatch, ["-c", "x"], stdin_text="n\n", ai=lambda p: "rm -rf build") == 1
    assert run_main(monkeypatch, ["-c", "x"], stdin_text="", ai=lambda p: "rm -rf build") == 1  # EOF is a no
    assert ran == []
    assert run_main(monkeypatch, ["-y", "-c", "x"], ai=lambda p: "rm -rf build") == 0
    assert ran == ["rm -rf build"]


def test_ctrl_c_during_a_single_request_exits_130(monkeypatch):
    opsh.save_config({"provider": "groq"})

    def interrupted(prompt):
        raise KeyboardInterrupt
    assert run_main(monkeypatch, ["-c", "x"], ai=interrupted) == 130


def test_bare_dash_c_is_a_usage_error(monkeypatch, capsys):
    opsh.save_config({"provider": "groq"})
    assert run_main(monkeypatch, ["-c"]) == 2
    assert "needs a request" in capsys.readouterr().err


def test_first_run_without_a_terminal_explains_instead_of_crashing(monkeypatch, capsys):
    assert run_main(monkeypatch, ["-c", "hi"], ai=lambda p: "echo hi") == 1
    assert "GROQ_API_KEY" in capsys.readouterr().err


@pytest.mark.parametrize("var,provider", [("GROQ_API_KEY", "groq"), ("GEMINI_API_KEY", "gemini")])
def test_exported_key_is_enough_without_a_config_file(monkeypatch, var, provider):
    monkeypatch.setenv(var, "test-key")
    assert opsh.get_provider() == provider
    assert run_main(monkeypatch, ["-c", "hi"], ai=lambda p: "echo hi") == 0


def test_generated_command_is_shown_with_control_characters_escaped(monkeypatch, capsys):
    monkeypatch.setattr(opsh, "execute", lambda cmd: opsh.CommandResult("", "", 0))
    opsh.handle_generated("echo safe\x1b[2K\rls", assume_yes=True)
    shown = capsys.readouterr().out
    assert "\\x1b[2K\\x0dls" in shown and "\r" not in shown


# --- config and .env ---------------------------------------------------------------

@pytest.mark.parametrize("content", ["", "{not json", "[1, 2]", "null", "\x00\x01"])
def test_broken_config_file_counts_as_empty(content):
    opsh.config_path.write_text(content)
    assert opsh.load_config() == {}


def test_corrupt_config_does_not_crash_startup(monkeypatch, capsys):
    opsh.config_path.write_text("{not json")
    assert run_main(monkeypatch, ["-c", "hi"], ai=lambda p: "echo hi") == 1
    assert "not set up" in capsys.readouterr().err


@posix_only
def test_key_and_config_files_are_private(tmp_path):
    opsh.env_path.write_text("OLD=1\n")
    os.chmod(opsh.env_path, 0o644)
    opsh.save_api_key("groq", "test-key")
    opsh.save_config({"provider": "groq"})
    assert stat.S_IMODE(os.stat(opsh.env_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(opsh.config_path).st_mode) == 0o600


def test_env_file_does_not_override_exported_variables(monkeypatch):
    opsh.env_path.write_text("GROQ_API_KEY=from-file\nGEMINI_API_KEY=from-file\n")
    monkeypatch.setenv("GROQ_API_KEY", "from-environment")
    opsh.load_env()
    assert os.environ["GROQ_API_KEY"] == "from-environment"
    assert os.environ["GEMINI_API_KEY"] == "from-file"


def test_env_file_accepts_quotes_export_and_spaces(monkeypatch):
    opsh.env_path.write_text('GROQ_API_KEY="quoted"\nexport GEMINI_API_KEY=exported\n OPSH_TEST_SPACED = spaced \nnot a pair\n')
    monkeypatch.delenv("OPSH_TEST_SPACED", raising=False)
    monkeypatch.setattr(opsh.os, "environ", dict(os.environ))
    opsh.load_env()
    assert opsh.os.environ["GROQ_API_KEY"] == "quoted"
    assert opsh.os.environ["GEMINI_API_KEY"] == "exported"
    assert opsh.os.environ["OPSH_TEST_SPACED"] == "spaced"
    assert not any(" " in name for name in opsh.os.environ)


def test_switching_provider_drops_the_old_providers_model(monkeypatch):
    opsh.save_config({"provider": "groq", "model": "groq-only-model"})
    answers = iter(["2", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(opsh, "_read_secret", lambda prompt: "test-key")
    assert opsh.setup_authentication() == {"provider": "gemini", "api_key": "test-key"}
    assert "model" not in opsh.load_config()


def test_api_key_is_read_without_echo_on_a_terminal(monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr(opsh.getpass, "getpass", lambda prompt: "typed-secretly")
    assert opsh._read_secret("key: ") == "typed-secretly"


# --- provider replies ----------------------------------------------------------------

@pytest.mark.parametrize("call,body", [
    (opsh.call_gemini, {"promptFeedback": {"blockReason": "SAFETY"}}),
    (opsh.call_gemini, {"candidates": [{"content": {"role": "model"}, "finishReason": "MAX_TOKENS"}]}),
    (opsh.call_gemini, {"candidates": [{"content": {"parts": [{"text": "  "}]}}]}),
    (opsh.call_gemini, []),
    (opsh.call_groq, {"choices": [{"message": {"content": None, "reasoning": "thinking"}}]}),
    (opsh.call_groq, {"choices": []}),
    (opsh.call_groq, {"unexpected": True}),
    (opsh.call_groq, "just a string"),
])
def test_unexpected_reply_shapes_give_a_plain_error(monkeypatch, call, body):
    monkeypatch.setattr(opsh.urllib.request, "urlopen", lambda req, timeout: _reply(body))
    with pytest.raises(opsh.ProviderError) as caught:
        call("prompt", "test-key")
    assert caught.value.kind == "response"
    assert "KeyError" not in str(caught.value) and "NoneType" not in str(caught.value)


def test_gemini_skips_thought_parts_and_joins_text(monkeypatch):
    body = {"candidates": [{"content": {"parts": [{"text": "hmm", "thought": True}, {"text": "ls "}, {"text": "-la"}]}}]}
    monkeypatch.setattr(opsh.urllib.request, "urlopen", lambda req, timeout: _reply(body))
    assert opsh.call_gemini("prompt", "test-key") == "ls -la"


def test_non_json_reply_is_reported_plainly(monkeypatch):
    monkeypatch.setattr(opsh.urllib.request, "urlopen", lambda req, timeout: _FakeResponse(b"<html>502</html>"))
    with pytest.raises(opsh.ProviderError, match="not JSON"):
        opsh.call_groq("prompt", "test-key")


@pytest.mark.parametrize("failure", [
    lambda: _http_error(503, {"error": {"message": "overloaded"}}),
    lambda: TimeoutError("The read operation timed out"),
    lambda: urllib.error.URLError("connection reset"),
])
def test_server_errors_and_timeouts_are_retried(monkeypatch, failure):
    attempts = []

    def flaky(req, timeout):
        attempts.append(req)
        if len(attempts) < 3:
            raise failure()
        return _reply(GROQ_OK)
    monkeypatch.setattr(opsh.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(opsh.time, "sleep", lambda s: None)
    assert opsh.call_groq("prompt", "test-key") == "ls"
    assert len(attempts) == 3


def test_network_failure_gives_up_with_a_network_error(monkeypatch):
    def down(req, timeout):
        raise urllib.error.URLError("no route to host")
    monkeypatch.setattr(opsh.urllib.request, "urlopen", down)
    monkeypatch.setattr(opsh.time, "sleep", lambda s: None)
    with pytest.raises(opsh.ProviderError, match="no route to host") as caught:
        opsh.call_gemini("prompt", "test-key")
    assert caught.value.kind == "network"


def test_gemini_key_travels_in_a_header_not_the_url(monkeypatch):
    calls = _capture_requests(monkeypatch, GEMINI_OK)
    opsh.call_gemini("prompt", "SENTINEL-VALUE", "models/some-model")
    assert "SENTINEL-VALUE" not in calls[0].full_url and "key=" not in calls[0].full_url
    assert calls[0].full_url.endswith("/models/some-model:generateContent")
    assert calls[0].get_header("X-goog-api-key") == "SENTINEL-VALUE"


@pytest.mark.parametrize("code,message,kind", [
    (401, "Invalid API Key", "auth"),
    (400, "API key not valid. Please pass a valid API key.", "auth"),
    (429, "slow down", "rate_limit"),
    (400, "Invalid JSON payload received by generateContent", "api"),
    (500, "internal error at integrate step", "api"),
])
def test_errors_are_classified_by_status_not_by_substring(code, message, kind):
    error = opsh._http_error(_http_error(code, {"error": {"message": message}}), "Groq")
    assert error.kind == kind
    if kind == "api":
        assert message in str(error)  # the provider's own words, not half a JSON blob


def test_auth_failure_is_not_retried(monkeypatch):
    attempts = []

    def unauthorised(req, timeout):
        attempts.append(req)
        raise _http_error(401, {"error": {"message": "Invalid API Key"}})
    monkeypatch.setattr(opsh.urllib.request, "urlopen", unauthorised)
    with pytest.raises(opsh.ProviderError, match="!auth"):
        opsh.call_groq("prompt", "test-key")
    assert len(attempts) == 1


# --- terminal handling -----------------------------------------------------------------

def test_module_imports_when_readline_is_unavailable():
    code = ("import sys; sys.modules['readline'] = None; sys.path.insert(0, sys.argv[1]); "
            "import opsh; print(opsh._HAVE_READLINE)")
    done = subprocess.run([sys.executable, "-c", code, str(ROOT)], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0 and done.stdout.strip() == "False", done.stderr


def test_windows_does_not_import_pyreadline3_as_the_package():
    # `import pyreadline3 as readline` never installs the line editor; the top-level module does.
    assert "import pyreadline3" not in (ROOT / "opsh.py").read_text(encoding="utf-8")


@posix_only
def test_prompt_marks_colour_codes_as_zero_width_for_readline(monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr(opsh, "_HAVE_READLINE", True)
    assert opsh.build_prompt("/work") == "\001\033[32m\002/work\001\033[0m\002 > "
    monkeypatch.setattr(opsh, "_HAVE_READLINE", False)
    assert opsh.build_prompt("/work") == "\033[32m/work\033[0m > "


def test_prompt_is_plain_when_colour_is_off(monkeypatch):
    monkeypatch.setattr(opsh, "_color_enabled", False)
    assert opsh.build_prompt("/work") == "/work > "


def test_output_survives_a_console_that_cannot_encode_it():
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import opsh; opsh._configure_stdio(); "
            "opsh.show_goodbye(); opsh.show_credits(); print('\\033[33m\\u2192 ls\\033[0m')")
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    done = subprocess.run([sys.executable, "-c", code, str(ROOT)], capture_output=True, timeout=60, env=env, check=False)
    assert done.returncode == 0, done.stderr
    assert b"Goodbye" in done.stdout
    assert b"\x1b" not in done.stdout  # no colour codes when output is piped


def test_errors_written_to_a_pipe_carry_no_colour_codes(monkeypatch, capfd):
    opsh.save_config({"provider": "groq"})

    def broken(prompt):
        raise opsh.ProviderError("API error 500: boom")
    assert run_main(monkeypatch, ["-c", "x"], ai=broken) == 1
    captured = capfd.readouterr()
    assert "boom" in captured.err and "\x1b" not in captured.err and "\x1b" not in captured.out


def test_no_color_is_respected_even_on_a_terminal(monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True
    stream = Terminal()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setenv("NO_COLOR", "1")
    opsh._configure_stdio()
    print("\033[31mred\033[0m")
    assert stream.getvalue() == "red\n"


def test_non_utf8_command_output_is_kept(monkeypatch):
    command = f'"{sys.executable}" -c "import sys; sys.stdout.buffer.write(bytes([255, 254, 104, 105]))"'
    stdout, stderr = opsh.run_command(command)
    assert stdout.endswith("hi") and "codec" not in stderr


@pytest.mark.parametrize("command,expected", [
    ("vim notes.txt", True), ("sudo nano /etc/hosts", True), ("top", True), ("/usr/bin/less log.txt", True),
    ("man ls", True), ("ls", False), ("cat log.txt | less", False), ("echo vim", False), ("", False),
])
def test_full_screen_programs_are_recognised(command, expected):
    assert opsh._is_interactive(command) is expected


def test_full_screen_programs_get_the_real_terminal(monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr(sys, "stdout", Terminal())
    monkeypatch.setattr(opsh.subprocess, "run", fake_run)
    monkeypatch.setattr(opsh, "PLATFORM", WINDOWS)  # where commands otherwise get a 60 s limit
    assert opsh.execute("vim notes.txt") == opsh.CommandResult("", "", 0)
    assert "stdout" not in seen and "capture_output" not in seen
    assert "timeout" not in seen  # an editor session must not be cut off


def test_timeout_default_and_override(monkeypatch):
    assert opsh._command_timeout() is None
    monkeypatch.setattr(opsh, "PLATFORM", WINDOWS)
    assert opsh._command_timeout() == 60
    monkeypatch.setenv("OPSH_TIMEOUT", "300")
    assert opsh._command_timeout() == 300
    monkeypatch.setenv("OPSH_TIMEOUT", "0")
    assert opsh._command_timeout() is None
    monkeypatch.setenv("OPSH_TIMEOUT", "soon")
    assert opsh._command_timeout() == 60


def test_timed_out_command_is_killed_and_reported(monkeypatch):
    monkeypatch.setenv("OPSH_TIMEOUT", "0.5")
    result = opsh.execute(f'"{sys.executable}" -c "import time; time.sleep(30)"')
    assert result.returncode == 124 and "timed out" in result.stderr


def test_missing_shell_is_an_error_result_not_an_exception(monkeypatch):
    monkeypatch.setattr(opsh, "PLATFORM", WINDOWS)

    def no_powershell(*args, **kwargs):
        raise FileNotFoundError("powershell")
    monkeypatch.setattr(opsh.subprocess, "Popen", no_powershell)
    assert opsh.execute("Get-Date").returncode == 127


# --- update check ------------------------------------------------------------------------

def test_update_check_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("OPSH_NO_UPDATE_CHECK", "1")
    opsh.check_for_updates()  # the autouse fixture fails the test if this touches the network


def test_update_check_runs_at_most_once_a_day(monkeypatch, capsys):
    requests = []

    def fake_urlopen(req, timeout):
        requests.append(req)
        return _reply({"tag_name": "v99.0.0"})
    monkeypatch.setattr(opsh.urllib.request, "urlopen", fake_urlopen)
    opsh.save_config({"provider": "groq"})
    opsh.check_for_updates()
    opsh.check_for_updates()
    assert len(requests) == 1
    assert "v99.0.0" in capsys.readouterr().out
    assert opsh.load_config()["provider"] == "groq"


def test_update_check_stays_quiet_when_offline(monkeypatch, capsys):
    def offline(req, timeout):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(opsh.urllib.request, "urlopen", offline)
    opsh.check_for_updates()
    assert capsys.readouterr().out == ""


# --- uninstall and privacy ------------------------------------------------------------------

def test_uninstall_reports_what_it_could_not_remove(monkeypatch, tmp_path, capsys):
    (tmp_path / "home" / ".opsh").mkdir(parents=True)

    def locked(path):
        raise PermissionError("file in use")
    monkeypatch.setattr(opsh.shutil, "rmtree", locked)
    assert opsh.uninstall() is False
    out = capsys.readouterr().out
    assert "file in use" in out and ".opsh" in out


def test_uninstall_removes_the_install(tmp_path):
    install = tmp_path / "home" / ".opsh"
    install.mkdir(parents=True)
    (install / "opsh.py").write_text("")
    assert opsh.uninstall() is True
    assert not install.exists()


def test_keys_in_command_output_are_not_sent_to_the_model():
    groq_like = "gsk_" + "a1B2" * 10          # built at runtime so no key-shaped literal sits in the repo
    google_like = "AIza" + "x9Y8" * 9
    opsh.add_to_history("cat .env", f"GROQ_API_KEY={groq_like}\nGEMINI_API_KEY={google_like}\nPATH=/usr/bin")
    opsh.add_to_history(f"curl -H 'Authorization: Bearer {groq_like}' https://example.invalid", "token: abc123")
    context = opsh.format_history()
    assert groq_like not in context and google_like not in context and "abc123" not in context
    assert "[redacted]" in context and "cat .env" in context


def test_file_names_in_the_prompt_have_control_characters_escaped(monkeypatch, tmp_path):
    monkeypatch.setattr(opsh.os, "listdir", lambda folder: ["notes.txt", "bad\x1b[2Jname", "x" * 500])
    context = opsh.get_file_context(str(tmp_path))
    assert "\x1b" not in context and "bad\\x1b[2Jname" in context
    assert "x" * 121 not in context
