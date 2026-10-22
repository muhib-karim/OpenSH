"""Unit tests for OpenSH's local logic: classifier, history, settings, prompt, shells, clipboard, cd, running."""

import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

from support import LINUX, MACOS, WINDOWS, IsolatedTestCase, opsh


class VersionCompare(unittest.TestCase):
    def test_is_newer_version(self):
        cases = [
            ("0.4.1", "0.4.0", True), ("v1.0.0", "0.4.0", True), ("0.10.0", "0.9.0", True),
            ("0.4.0", "0.4.0", False), ("0.3.0", "0.4.0", False), ("", "0.4.0", False),
            ("1.0.0-rc1", "0.9.9", True),
        ]
        for latest, current, expected in cases:
            with self.subTest(latest=latest, current=current):
                self.assertIs(opsh.is_newer_version(latest, current), expected)

    def test_version_is_semver(self):
        self.assertRegex(opsh.__version__, r"^\d+\.\d+\.\d+$")


class Classifier(IsolatedTestCase):
    def test_shell_input_bypasses_ai_on_linux(self):
        for text in ["ls", "pwd", "git status", "cd ..", "./build.sh", "sudo apt update",
                     "cat notes.txt | grep todo", "!echo hi", "exit", "LS"]:
            with self.subTest(text=text):
                self.assertFalse(opsh.is_natural_language(text))

    def test_english_goes_to_ai(self):
        for text in ["show me large files", "what is my ip address", "compress the logs folder into a zip"]:
            with self.subTest(text=text):
                self.assertTrue(opsh.is_natural_language(text))

    def test_powershell_classifier(self):
        opsh.PLATFORM = WINDOWS
        self.assertFalse(opsh.is_natural_language("Get-ChildItem -Recurse"))
        self.assertFalse(opsh.is_natural_language("ipconfig"))
        self.assertTrue(opsh.is_natural_language("list running processes"))

    def test_platform_dict_without_shell_key_falls_back_to_os(self):
        opsh.PLATFORM = {"name": "Windows", "shell": "PowerShell"}
        self.assertFalse(opsh.is_natural_language("Get-Process"))


class ShellDetection(unittest.TestCase):
    def test_normalize_shell(self):
        cases = {"/bin/zsh": "zsh", "/usr/bin/bash": "bash", "sh": "bash", "fish": "bash",
                 "pwsh": "powershell", "PowerShell": "powershell", "pwsh.exe": "powershell"}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(opsh.normalize_shell(raw), expected)
        with self.assertRaises(ValueError):
            opsh.normalize_shell("cmd")

    def test_detect_shell(self):
        cases = [
            ("Windows", {}, "powershell"),
            ("Windows", {"OPENSH_SHELL": "bash"}, "bash"),
            ("Linux", {"SHELL": "/usr/bin/zsh"}, "zsh"),
            ("Linux", {"SHELL": "/bin/bash"}, "bash"),
            ("Linux", {}, "bash"),
            ("Darwin", {}, "zsh"),
            ("Darwin", {"SHELL": "/bin/bash"}, "bash"),
            ("Linux", {"SHELL": "/usr/bin/pwsh"}, "powershell"),
            ("Linux", {"SHELL": "/bin/tcsh-weird"}, "bash"),
            ("Linux", {"OPENSH_SHELL": "nonsense", "SHELL": "/bin/zsh"}, "zsh"),
        ]
        for system, env, expected in cases:
            with self.subTest(system=system, env=env):
                self.assertEqual(opsh.detect_shell(system, env), expected)

    def test_platform_info(self):
        self.assertEqual((MACOS["name"], MACOS["shell"]), ("macOS", "zsh"))
        self.assertEqual((WINDOWS["name"], WINDOWS["shell"], WINDOWS["path_sep"]), ("Windows", "PowerShell", "\\"))
        self.assertEqual(LINUX["shell_key"], "bash")


class History(IsolatedTestCase):
    def test_history_is_capped_and_output_truncated(self):
        for i in range(opsh.MAX_HISTORY + 5):
            opsh.add_to_history(f"cmd{i}", "x" * 1000)
        self.assertLessEqual(len(opsh.command_history), opsh.MAX_HISTORY)
        self.assertTrue(all(len(e["output"]) == 500 for e in opsh.command_history))
        self.assertLessEqual(opsh.get_context_size(), opsh.MAX_CONTEXT_CHARS)
        self.assertEqual(opsh.command_history[-1]["command"], f"cmd{opsh.MAX_HISTORY + 4}")

    def test_format_history_shows_last_five_with_two_output_lines(self):
        self.assertEqual(opsh.format_history(), "No previous commands.")
        for i in range(7):
            opsh.add_to_history(f"cmd{i}", "line1\nline2\nline3")
        text = opsh.format_history()
        self.assertNotIn("$ cmd1", text)
        self.assertIn("1. $ cmd2", text)
        self.assertIn("5. $ cmd6", text)
        self.assertIn("line2", text)
        self.assertNotIn("line3", text)


class HistoryFile(IsolatedTestCase):
    def test_round_trip_and_secret_lines_are_skipped(self):
        path = opsh.history_path()
        self.assertEqual(path, self.tmp / "history")
        self.assertTrue(opsh.append_history("list big files"))
        self.assertFalse(opsh.append_history("   "))
        self.assertFalse(opsh.append_history("export GROQ_API_KEY=abc123"))
        self.assertFalse(opsh.append_history("curl -H 'Authorization: Bearer x' api"))
        self.assertFalse(opsh.append_history("echo sk-abcdefghijklmnop"))
        self.assertTrue(opsh.append_history("git status"))
        self.assertEqual(opsh.read_history_file(), ["list big files", "git status"])

    def test_history_is_trimmed(self):
        path = opsh.history_path()
        path.write_text("".join(f"line {i} " + "x" * 300 + "\n" for i in range(opsh.HISTORY_LIMIT + 50)))
        opsh.append_history("newest")
        lines = path.read_text().splitlines()
        self.assertEqual(len(lines), opsh.HISTORY_LIMIT)
        self.assertEqual(lines[-1], "newest")

    def test_missing_file_and_unwritable_path(self):
        self.assertEqual(opsh.read_history_file(self.tmp / "nope"), [])
        self.assertFalse(opsh.append_history("x", self.tmp / "no-such-dir" / "history"))

    def test_load_into_readline_and_show(self):
        opsh.append_history("one")
        opsh.append_history("two")
        fake = mock.Mock()
        with mock.patch.object(opsh, "readline", fake):
            self.assertEqual(opsh.load_history_into_readline(), 2)
        fake.add_history.assert_has_calls([mock.call("one"), mock.call("two")])
        _, out = self.capture(opsh.show_history)
        self.assertIn("one", out)
        self.assertIn("two", out)

    def test_show_empty_history(self):
        _, out = self.capture(opsh.show_history)
        self.assertIn("No history yet", out)

    def test_history_file_is_private(self):
        opsh.append_history("ls")
        if os.name != "nt":
            self.assertEqual(opsh.history_path().stat().st_mode & 0o777, 0o600)

    def test_looks_secret(self):
        self.assertFalse(opsh.looks_secret("open the skeleton-app folder"))
        self.assertTrue(opsh.looks_secret("password=hunter2"))
        self.assertTrue(opsh.looks_secret("use key AIzaSyDUMMYDUMMY"))
        self.assertFalse(opsh.looks_secret("show me the token ring docs"))


class Settings(IsolatedTestCase):
    def test_config_round_trip(self):
        self.assertEqual(opsh.load_config(), {})
        opsh.save_config({"provider": "gemini"})
        self.assertEqual(opsh.load_config(), {"provider": "gemini"})

    def test_broken_or_non_object_config_counts_as_empty(self):
        opsh.config_path.write_text("{not json")
        self.assertEqual(opsh.load_config(), {})
        opsh.config_path.write_text("[1, 2]")
        self.assertEqual(opsh.load_config(), {})

    def test_session_overrides_win(self):
        opsh.save_config({"provider": "groq", "model": "a"})
        opsh.SESSION_OVERRIDES["model"] = "b"
        self.assertEqual(opsh.current_config(), {"provider": "groq", "model": "b"})

    def test_save_api_key_keeps_other_keys_and_load_env_reads_them(self):
        opsh.env_path.write_text("# comment\nOTHER=1\n")
        opsh.save_api_key("groq", "test-groq")
        opsh.save_api_key("gemini", "test-gemini")
        opsh.save_api_key("openai", "test-openai")
        self.assertEqual(opsh.env_path.read_text().splitlines(),
                         ["OTHER=1", "GROQ_API_KEY=test-groq", "GEMINI_API_KEY=test-gemini",
                          "OPENAI_API_KEY=test-openai"])
        if os.name != "nt":
            self.assertEqual(opsh.env_path.stat().st_mode & 0o777, 0o600)
        opsh.load_env()
        self.assertEqual(os.environ["GROQ_API_KEY"], "test-groq")
        self.assertEqual(os.environ["OPENAI_API_KEY"], "test-openai")

    def test_real_environment_wins_over_env_file_and_quotes_are_stripped(self):
        opsh.env_path.write_text('GROQ_API_KEY="from-file"\nGEMINI_API_KEY=\'quoted\'\n')
        os.environ["GROQ_API_KEY"] = "from-env"
        opsh.load_env()
        self.assertEqual(os.environ["GROQ_API_KEY"], "from-env")
        self.assertEqual(os.environ["GEMINI_API_KEY"], "quoted")

    def test_save_api_key_survives_chmod_failure(self):
        with mock.patch.object(opsh.os, "chmod", side_effect=OSError):
            opsh.save_api_key("groq", "k")
        self.assertIn("GROQ_API_KEY=k", opsh.env_path.read_text())


class Prompt(IsolatedTestCase):
    def test_prompt_includes_request_files_and_history(self):
        work = self.tmp / "work"
        (work / "Current Resume").mkdir(parents=True)
        desktop = self.tmp / "home" / "Desktop"
        desktop.mkdir()
        (desktop / "notes.txt").write_text("x")
        opsh.add_to_history("git status", "On branch main")
        seen = {}

        def fake(prompt):
            seen["prompt"] = prompt
            return "ls"

        with mock.patch.object(opsh, "get_ai_response", fake):
            self.assertEqual(opsh.get_command("open the resume folder", str(work)), "ls")
        prompt = seen["prompt"]
        self.assertIn("User request: open the resume folder", prompt)
        self.assertIn("Current Resume", prompt)
        self.assertIn("Files on Desktop", prompt)
        self.assertIn("$ git status", prompt)
        self.assertIn("bash on Linux", prompt)

    def test_powershell_prompt(self):
        opsh.PLATFORM = WINDOWS
        seen = {}
        with mock.patch.object(opsh, "get_ai_response", lambda p: seen.setdefault("p", p) and "dir"):
            opsh.get_command("list files", str(self.tmp))
        self.assertIn("PowerShell on Windows", seen["p"])

    def test_file_context_survives_unreadable_folders(self):
        with mock.patch.object(opsh.os, "listdir", side_effect=OSError):
            (self.tmp / "home" / "Desktop").mkdir()
            self.assertEqual(opsh.get_file_context(str(self.tmp)), "")

    def test_explain_command_prompt(self):
        with mock.patch.object(opsh, "get_ai_response", return_value="Lists\nfiles.  ") as ai:
            self.assertEqual(opsh.explain_command("ls -la"), "Lists files.")
        self.assertTrue(ai.call_args[0][0].startswith(opsh.EXPLAIN_PREFIX))
        self.assertIn("Command: ls -la", ai.call_args[0][0])

    def test_clean_command(self):
        cases = {
            "ls -la": "ls -la",
            "```bash\nls -la\n```": "ls -la",
            "```\nGet-ChildItem\n```": "Get-ChildItem",
            "`pwd`": "pwd",
            "$ du -sh *": "du -sh *",
            "PS> Get-Process": "Get-Process",
            "  echo hi  ": "echo hi",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(opsh.clean_command(raw), expected)


class Clipboard(IsolatedTestCase):
    def test_clipboard_commands_per_os(self):
        self.assertEqual(opsh.clipboard_commands("Windows"), [["clip"]])
        self.assertEqual(opsh.clipboard_commands("Darwin"), [["pbcopy"]])
        self.assertEqual(opsh.clipboard_commands("Linux")[0], ["wl-copy"])

    def test_first_installed_tool_wins(self):
        def which(name):
            return None if name == "wl-copy" else f"/usr/bin/{name}"

        with mock.patch.object(opsh.shutil, "which", which), mock.patch.object(opsh.subprocess, "run") as run:
            self.assertTrue(opsh.copy_to_clipboard("ls -la", "Linux"))
        argv = run.call_args[0][0]
        self.assertEqual(argv, ["/usr/bin/xclip", "-selection", "clipboard"])
        self.assertEqual(run.call_args[1]["input"], "ls -la")

    def test_falls_through_failures_and_reports_none(self):
        with mock.patch.object(opsh.shutil, "which", lambda n: f"/bin/{n}"), \
                mock.patch.object(opsh.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "x")):
            self.assertFalse(opsh.copy_to_clipboard("x", "Linux"))
        with mock.patch.object(opsh.shutil, "which", lambda n: None):
            self.assertFalse(opsh.copy_to_clipboard("x", "Darwin"))


class ChangeDirectory(IsolatedTestCase):
    def test_cd_target(self):
        cases = {
            "cd ..": "..", "cd": "~", "Set-Location C:\\Users": "C:\\Users", "chdir /tmp": "/tmp",
            "sl ~": "~", "cd build && make": None, "ls": None, "cd a; ls": None,
        }
        for cmd, expected in cases.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(opsh.cd_target(cmd), expected)

    def test_change_directory_quotes_and_errors(self):
        target = self.tmp / "My Folder"
        target.mkdir()
        self.assertTrue(opsh.change_directory(f'"{target}"'))
        self.assertEqual(pathlib.Path.cwd().resolve(), target.resolve())
        _, out = self.capture(opsh.change_directory, str(self.tmp / "missing"))
        self.assertIn("cd:", out)

    def test_set_location_path_parameter(self):
        self.assertTrue(opsh.change_directory(f"-Path '{self.tmp}'"))
        self.assertEqual(pathlib.Path.cwd().resolve(), self.tmp.resolve())

    def test_windows_env_vars(self):
        opsh.PLATFORM = WINDOWS
        os.environ["OPENSH_TEST_DIR"] = str(self.tmp)
        with mock.patch.object(opsh.os, "chdir") as chdir:
            self.assertTrue(opsh.change_directory("$env:OPENSH_TEST_DIR"))
        self.assertEqual(chdir.call_args[0][0], str(self.tmp))


class RunCommand(IsolatedTestCase):
    def test_runs_in_detected_posix_shell(self):
        with mock.patch.object(opsh.shutil, "which", lambda n: f"/usr/bin/{n}"):
            self.assertEqual(opsh.shell_argv("echo hi"), ["/usr/bin/bash", "-c", "echo hi"])
            opsh.PLATFORM = MACOS
            self.assertEqual(opsh.shell_argv("echo hi")[0], "/usr/bin/zsh")
        with mock.patch.object(opsh.shutil, "which", lambda n: None):
            self.assertEqual(opsh.shell_argv("echo hi")[0], "/bin/sh")

    def test_powershell_argv(self):
        opsh.PLATFORM = WINDOWS
        self.assertEqual(opsh.shell_argv("dir"), ["powershell", "-NoProfile", "-Command", "dir"])
        opsh.PLATFORM = opsh.get_platform_info(system="Linux", shell="powershell")
        with mock.patch.object(opsh.shutil, "which", lambda n: None):
            self.assertEqual(opsh.shell_argv("dir")[0], "pwsh")

    def test_run_command_captures_output_for_real(self):
        opsh.PLATFORM = opsh.get_platform_info()
        stdout, stderr = opsh.run_command("echo hello")
        self.assertIn("hello", stdout, stderr)

    def test_status_codes(self):
        with mock.patch.object(opsh.subprocess, "run", return_value=subprocess.CompletedProcess([], 4, "o", "e")):
            self.assertEqual(opsh.run_command_status("x"), ("o", "e", 4))
        with mock.patch.object(opsh.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertEqual(opsh.run_command_status("x")[2], 124)
        with mock.patch.object(opsh.subprocess, "run", side_effect=OSError("gone")):
            self.assertEqual(opsh.run_command_status("x")[2], 127)

    def test_timeout_and_os_errors(self):
        opsh.PLATFORM = WINDOWS
        with mock.patch.object(opsh.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 60)) as run:
            self.assertEqual(opsh.run_command("sleep"), ("", "Command timed out"))
        self.assertEqual(run.call_args[1]["timeout"], 60)
        with mock.patch.object(opsh.subprocess, "run", side_effect=FileNotFoundError("no shell")):
            self.assertEqual(opsh.run_command("x"), ("", "no shell"))


class Readline(unittest.TestCase):
    def test_load_readline_handles_missing_module(self):
        with mock.patch.object(opsh.importlib, "import_module", side_effect=ImportError):
            self.assertIsNone(opsh._load_readline())

    def test_load_readline_picks_module_per_os(self):
        with mock.patch.object(opsh.importlib, "import_module", return_value="mod") as imp:
            self.assertEqual(opsh._load_readline(), "mod")
        expected = "pyreadline3" if sys.platform == "win32" else "readline"
        imp.assert_called_once_with(expected)


if __name__ == "__main__":
    unittest.main()
