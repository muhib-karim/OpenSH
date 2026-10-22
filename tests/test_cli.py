"""CLI behaviour: flags, explain/dry-run/copy flow, first-run setup, the REPL and its built-ins."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from support import LINUX, ROOT, WINDOWS, IsolatedTestCase, opsh


def answers(*items):
    """An input() replacement that returns items in order, then raises EOFError (Ctrl+D)."""
    queue = list(items)

    def ask(_prompt=""):
        if not queue:
            raise EOFError
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return ask


class HandleGenerated(IsolatedTestCase):
    def run_handle(self, command, ask=None, **opts):
        with mock.patch.object(opsh, "run_command", return_value=("out\n", "err\n")) as run:
            ran, out = self.capture(opsh.handle_generated, command, opsh.RunOptions(**opts), ask or answers())
        return ran, out, run

    def test_safe_command_runs_and_is_remembered(self):
        ran, out, run = self.run_handle("ls -la")
        self.assertTrue(ran)
        run.assert_called_once_with("ls -la")
        self.assertIn("→ ls -la", out)
        self.assertEqual(opsh.command_history[-1]["command"], "ls -la")

    def test_destructive_command_skipped_without_yes(self):
        ran, out, run = self.run_handle("rm -rf build", answers("n"))
        self.assertFalse(ran)
        run.assert_not_called()
        self.assertIn("Skipped", out)

    def test_destructive_command_runs_with_yes_flag(self):
        ran, _, run = self.run_handle("rm -rf build", yes=True)
        self.assertTrue(ran)

    def test_dry_run_never_runs(self):
        ran, out, run = self.run_handle("rm -rf build", dry_run=True)
        self.assertFalse(ran)
        run.assert_not_called()
        self.assertIn("dry run", out)

    def test_explain_shows_explanation_and_reasons_then_asks(self):
        self.use_mock_provider()
        ran, out, run = self.run_handle("rm -rf build", answers("y"), explain=True)
        self.assertTrue(ran)
        self.assertIn("Mock explanation", out)
        self.assertIn("⚠ Deletes files recursively", out)

    def test_explain_asks_even_for_safe_commands(self):
        self.use_mock_provider()
        ran, out, run = self.run_handle("ls", answers("n"), explain=True)
        self.assertFalse(ran)
        self.assertIn("Skipped", out)
        ran, _, _ = self.run_handle("ls", answers(""), explain=True)
        self.assertTrue(ran)
        ran, _, _ = self.run_handle("ls", answers(), explain=True)  # Ctrl+D means no
        self.assertFalse(ran)
        ran, _, _ = self.run_handle("ls", answers(), explain=True, yes=True)
        self.assertTrue(ran)

    def test_explain_survives_provider_errors(self):
        with mock.patch.object(opsh, "explain_command", side_effect=opsh.ProviderError("offline")):
            _, out, _ = self.run_handle("ls", answers("y"), explain=True)
        self.assertIn("no explanation: offline", out)

    def test_copy(self):
        with mock.patch.object(opsh, "copy_to_clipboard", return_value=True) as copy:
            _, out, _ = self.run_handle("ls", dry_run=True, copy=True)
        copy.assert_called_once_with("ls")
        self.assertIn("Copied", out)
        with mock.patch.object(opsh, "copy_to_clipboard", return_value=False):
            _, out, _ = self.run_handle("ls", dry_run=True, copy=True)
        self.assertIn("No clipboard tool", out)

    def test_cd_is_handled_in_process(self):
        ran, _, run = self.run_handle(f"cd {self.tmp}")
        self.assertTrue(ran)
        run.assert_not_called()
        self.assertEqual(os.path.realpath(os.getcwd()), os.path.realpath(self.tmp))


class RunOnce(IsolatedTestCase):
    def test_success_empty_and_error(self):
        self.use_mock_provider("ls")
        with mock.patch.object(opsh, "handle_generated") as handle:
            code, _ = self.capture(opsh.run_once, "list", opsh.RunOptions())
        self.assertEqual(code, 0)
        handle.assert_called_once()
        self.use_mock_provider("   ")
        code, out = self.capture(opsh.run_once, "list", opsh.RunOptions())
        self.assertEqual(code, 1)
        self.assertIn("empty command", out)
        os.environ["OPENSH_PROVIDER"] = "groq"
        code, out = self.capture(opsh.run_once, "list", opsh.RunOptions())
        self.assertEqual(code, 1)
        self.assertIn("No Groq API key", out)


class SetupAuthentication(IsolatedTestCase):
    def setup(self, *items, secret="test-key"):
        opened = []
        result, out = self.capture(opsh.setup_authentication, answers(*items), lambda _p: secret, opened.append)
        return result, out, opened

    def test_groq_default(self):
        result, out, opened = self.setup("", "")
        self.assertEqual(result, {"provider": "groq", "api_key": "test-key"})
        self.assertEqual(len(opened), 1)
        self.assertEqual(opsh.load_config()["provider"], "groq")
        self.assertIn("GROQ_API_KEY=test-key", opsh.env_path.read_text())
        self.assertNotIn("test-key", out)

    def test_gemini_without_browser(self):
        result, _, opened = self.setup("2", "n")
        self.assertEqual(result["provider"], "gemini")
        self.assertEqual(opened, [])
        self.assertEqual(os.environ["GEMINI_API_KEY"], "test-key")

    def test_empty_key_is_rejected(self):
        result, out, _ = self.setup("1", "n", secret="")
        self.assertIsNone(result)
        self.assertIn("No API key", out)

    def test_openai_compatible(self):
        opsh.save_config({"provider": "groq", "model": "old"})
        result, _, opened = self.setup("3", "https://llm.example/v1", "my-model")
        self.assertEqual(result["provider"], "openai")
        self.assertEqual(opened, [])
        config = opsh.load_config()
        self.assertEqual((config["base_url"], config["model"]), ("https://llm.example/v1", "my-model"))
        self.assertIn("OPENAI_API_KEY=test-key", opsh.env_path.read_text())

    def test_openai_compatible_without_key_and_defaults(self):
        result, _, _ = self.setup("3", "", "", secret="")
        self.assertEqual(result, {"provider": "openai", "api_key": ""})
        self.assertEqual(opsh.load_config()["base_url"], "https://api.openai.com/v1")
        self.assertFalse(opsh.env_path.exists())

    def test_openai_compatible_rejects_bad_url(self):
        result, out, _ = self.setup("3", "ftp://x")
        self.assertIsNone(result)
        self.assertIn("must start with http", out)

    def test_ollama(self):
        result, out, _ = self.setup("4", "")
        self.assertEqual(result, {"provider": "ollama", "api_key": None})
        self.assertEqual(opsh.load_config()["model"], "llama3.2")
        self.assertIn("ollama serve", out)


class InfoScreens(IsolatedTestCase):
    def test_help_lists_the_right_exit_key(self):
        for platform_info, exit_key in [(LINUX, "Ctrl+D"), (WINDOWS, "Ctrl+C")]:
            opsh.PLATFORM = platform_info
            _, out = self.capture(opsh.show_help)
            with self.subTest(platform=platform_info["name"]):
                self.assertTrue(any(exit_key in line and "Exit OpenSH" in line for line in out.splitlines()))
                self.assertIn("!explain", out)

    def test_version_shows_provider_and_model_but_no_key(self):
        _, out = self.capture(opsh.show_version)
        self.assertIn("Provider: not configured", out)
        os.environ["GROQ_API_KEY"] = "test-key"
        opsh.save_config({"provider": "groq"})
        _, out = self.capture(opsh.show_version)
        self.assertIn("Provider: groq (llama-3.3-70b-versatile)", out)
        self.assertIn(f"v{opsh.__version__}", out)
        self.assertNotIn("test-key", out)

    def test_credits_and_goodbye(self):
        _, out = self.capture(opsh.show_credits)
        self.assertIn("nlsh", out)
        _, out = self.capture(opsh.show_goodbye)
        self.assertIn("Goodbye", out)

    def test_exit_handler_raises_interrupted(self):
        with self.assertRaises(InterruptedError):
            self.capture(opsh.exit_handler, 2, None)


class UpdateCheck(IsolatedTestCase):
    def check(self, tag):
        os.environ.pop("OPENSH_NO_UPDATE_CHECK", None)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"tag_name": tag}).encode()
        with mock.patch.object(opsh.urllib.request, "urlopen", return_value=response):
            _, out = self.capture(opsh.check_for_updates)
        return out

    def test_reports_only_newer_releases(self):
        self.assertIn("New version available: v9.9.9", self.check("v9.9.9"))
        self.assertEqual(self.check(f"v{opsh.__version__}"), "")

    def test_network_failure_is_silent_and_check_can_be_disabled(self):
        del os.environ["OPENSH_NO_UPDATE_CHECK"]
        with mock.patch.object(opsh.urllib.request, "urlopen", side_effect=OSError):
            _, out = self.capture(opsh.check_for_updates)
        self.assertEqual(out, "")
        os.environ["OPENSH_NO_UPDATE_CHECK"] = "1"
        _, out = self.capture(opsh.check_for_updates)  # urlopen would raise AssertionError if used
        self.assertEqual(out, "")


class Uninstall(IsolatedTestCase):
    def test_uninstall_removes_install_dir_and_launcher(self):
        home = self.tmp / "home"
        (home / ".opsh").mkdir()
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".local" / "bin" / "opsh").write_text("#!/bin/sh")
        removed, _ = self.capture(opsh.uninstall, answers("y"))
        self.assertTrue(removed)
        self.assertFalse((home / ".opsh").exists())
        self.assertFalse((home / ".local" / "bin" / "opsh").exists())

    def test_uninstall_on_windows_and_cancel(self):
        opsh.PLATFORM = WINDOWS
        self.assertFalse(self.capture(opsh.uninstall, answers("n"))[0])
        self.assertTrue(self.capture(opsh.uninstall, answers("y"))[0])


class Repl(IsolatedTestCase):
    def repl(self, *inputs, **opts):
        with mock.patch("builtins.input", answers(*inputs)):
            return self.capture(opsh.repl, opsh.RunOptions(**opts))

    def test_exit_and_ctrl_d(self):
        code, out = self.repl("", "exit")
        self.assertEqual(code, 0)
        self.assertIn("Goodbye", out)
        code, out = self.repl()
        self.assertEqual(code, 0)

    def test_builtins(self):
        with mock.patch.object(opsh, "setup_authentication", return_value={"provider": "groq"}), \
                mock.patch.object(opsh, "copy_to_clipboard", return_value=True):
            code, out = self.repl("!help", "!version", "!credits", "!history", "!auth",
                                  "!explain", "!explain", "!dry-run", "!copy", "!", "quit")
        self.assertEqual(code, 0)
        for text in ["!explain", "OpenSH", "nlsh", "Authentication updated", "Explain-before-run on",
                     "Explain-before-run off", "Dry run on", "Nothing to copy"]:
            self.assertIn(text, out)
        self.assertIn("!help", opsh.read_history_file())

    def test_shell_input_runs_directly_and_cd_moves(self):
        with mock.patch.object(opsh, "run_command", return_value=("hi\n", "")) as run:
            _, out = self.repl("!echo hi", "git status", f"cd {self.tmp}", "exit")
        self.assertEqual([c.args[0] for c in run.call_args_list], ["echo hi", "git status"])
        self.assertEqual(os.path.realpath(os.getcwd()), os.path.realpath(self.tmp))

    def test_english_goes_through_the_model_and_can_be_copied(self):
        self.use_mock_provider("ls -la")
        with mock.patch.object(opsh, "run_command", return_value=("", "")) as run, \
                mock.patch.object(opsh, "copy_to_clipboard", side_effect=[True, False]):
            _, out = self.repl("list my files", "!copy", "!copy", "exit")
        run.assert_called_once_with("ls -la")
        self.assertIn("Copied", out)
        self.assertIn("No clipboard tool", out)

    def test_empty_model_answer_and_errors_keep_the_loop_alive(self):
        self.use_mock_provider("  ")
        _, out = self.repl("list my files", "exit")
        self.assertIn("empty command", out)
        os.environ["OPENSH_PROVIDER"] = "groq"
        _, out = self.repl("list my files", "exit")
        self.assertIn("No Groq API key", out)
        with mock.patch.object(opsh, "get_command", side_effect=[RuntimeError("boom"), InterruptedError()]):
            _, out = self.repl("list my files", "list my files", "exit")
        self.assertIn("Error: boom", out)

    def test_uninstall_from_repl(self):
        with mock.patch.object(opsh, "uninstall", side_effect=[False, True]):
            code, _ = self.repl("!uninstall", "!uninstall")
        self.assertEqual(code, 0)

    def test_history_disabled(self):
        with mock.patch("builtins.input", answers("hello there", "exit")), \
                mock.patch.object(opsh, "get_command", return_value=""):
            self.capture(opsh.repl, opsh.RunOptions(), False)
        self.assertEqual(opsh.read_history_file(), [])


class Main(IsolatedTestCase):
    def test_first_run_without_answers_exits_1(self):
        with mock.patch("builtins.input", answers()):
            code, out = self.capture(opsh.main, [])
        self.assertEqual(code, 1)
        self.assertIn("Authentication required", out)

    def test_first_run_setup_then_repl(self):
        with mock.patch.object(opsh, "setup_authentication", return_value={"provider": "groq"}), \
                mock.patch.object(opsh, "repl", return_value=0) as repl:
            code, out = self.capture(opsh.main, [])
        self.assertEqual(code, 0)
        self.assertIn("Welcome", out)
        repl.assert_called_once()

    def test_flags_reach_run_once(self):
        with mock.patch.object(opsh, "run_once", return_value=0) as run_once:
            code, _ = self.capture(opsh.main, ["--provider", "mock", "--model", "m", "--shell", "zsh",
                                               "-n", "-e", "--copy", "-y", "-c", "list", "files"])
        self.assertEqual(code, 0)
        query, opts = run_once.call_args[0]
        self.assertEqual(query, "list files")
        self.assertEqual(opts, opsh.RunOptions(yes=True, dry_run=True, explain=True, copy=True))
        self.assertEqual(opsh.SESSION_OVERRIDES, {"provider": "mock", "model": "m"})
        self.assertEqual(opsh.PLATFORM["shell"], "zsh")

    def test_history_setting(self):
        opsh.save_config({"provider": "mock", "history": False})
        with mock.patch.object(opsh, "repl", return_value=0) as repl:
            self.capture(opsh.main, [])
        self.assertEqual(repl.call_args[0][1], False)
        opsh.save_config({"provider": "mock"})
        with mock.patch.object(opsh, "repl", return_value=0) as repl:
            self.capture(opsh.main, ["--no-history"])
        self.assertEqual(repl.call_args[0][1], False)

    def test_help_has_examples(self):
        help_text = opsh.build_parser().format_help()
        for flag in ["--dry-run", "--explain", "--copy", "--shell", "--provider", "examples:"]:
            self.assertIn(flag, help_text)


class EndToEnd(unittest.TestCase):
    """Run the real script in a subprocess with the offline provider."""

    def run_opsh(self, *args, env_extra=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("OPENSH_")}
        env.update({"OPENSH_PROVIDER": "mock", "OPENSH_NO_UPDATE_CHECK": "1", "PYTHONIOENCODING": "utf-8"})
        env.update(env_extra or {})
        return subprocess.run([sys.executable, str(ROOT / "opsh.py"), *args], capture_output=True, text=True,
                              encoding="utf-8", env=env, timeout=60, stdin=subprocess.DEVNULL)

    def test_help_and_version(self):
        help_run = self.run_opsh("--help")
        self.assertEqual(help_run.returncode, 0)
        self.assertIn("examples:", help_run.stdout)
        version_run = self.run_opsh("--version")
        self.assertEqual(version_run.stdout.strip(), f"OpenSH v{opsh.__version__}")

    def test_dry_run_with_mock_provider(self):
        result = self.run_opsh("-n", "-c", "list", "files")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mock: list files", result.stdout)
        self.assertIn("dry run", result.stdout)

    def test_guard_blocks_destructive_command_without_tty(self):
        result = self.run_opsh("-c", "clean", env_extra={"OPENSH_MOCK_RESPONSE": "rm -rf /tmp/opensh-never"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Skipped", result.stdout)


if __name__ == "__main__":
    unittest.main()
