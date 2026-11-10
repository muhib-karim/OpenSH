"""Checks on the files around opsh.py: installers, changelog, workflows."""
import os
import pathlib
import re
import shutil
import subprocess

import pytest

import opsh

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["install.ps1", "uninstall.ps1"])
def test_powershell_scripts_are_pure_ascii(name):
    # Windows PowerShell 5.1 reads a BOM-less script as ANSI. A UTF-8 check mark then
    # decodes to a smart quote, which PowerShell treats as a string delimiter: parse error.
    data = (ROOT / name).read_bytes()
    bad = sorted({byte for byte in data if byte > 127})
    assert not bad, f"{name} contains non-ASCII bytes: {bad[:5]}"


def test_version_matches_the_top_changelog_entry():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    released = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", changelog, flags=re.MULTILINE)
    assert released and released[0] == opsh.__version__


def test_windows_installer_installs_only_what_requirements_lists():
    script = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "google-genai" not in script
    assert "requirements.txt" in script


def test_windows_installer_survives_being_piped_into_iex():
    script = (ROOT / "install.ps1").read_text(encoding="utf-8")
    # Under `irm | iex` there is no script path; using it unguarded aborts the install.
    assert "Split-Path -Parent $MyInvocation.MyCommand.Path" not in script
    assert not re.search(r"^\s*exit\b", script, flags=re.MULTILINE), "exit would close the user's window under iex"


def test_windows_autostart_is_opt_in():
    script = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "[y/N]" in script and "[Y/n]" not in script


def test_unix_installer_never_creates_bash_profile_and_has_no_venv():
    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert not re.search(r"^\s*touch\b", script, flags=re.MULTILINE)
    assert "-m venv" not in script and "pip install" not in script


@pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None, reason="needs a real bash")
@pytest.mark.parametrize("name", ["install.sh", "uninstall.sh"])
def test_shell_scripts_parse(name):
    done = subprocess.run(["bash", "-n", str(ROOT / name)], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr


def test_ci_does_not_pair_python_39_with_ubuntu_latest():
    # setup-python has no 3.9 build for the newest Ubuntu image; that leg must stay on 24.04.
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"exclude:\s*\n\s*- os: ubuntu-latest\s*\n\s*python-version: '3\.9'", workflow)
    assert re.search(r"include:\s*\n\s*- os: ubuntu-24\.04\s*\n\s*python-version: '3\.9'", workflow)


def test_runtime_has_no_third_party_requirements():
    lines = [line.strip() for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()]
    packages = [line for line in lines if line and not line.startswith("#")]
    assert packages == ["pyreadline3; sys_platform == 'win32'"]
