import importlib.util
import pathlib

import pytest

_spec = importlib.util.spec_from_file_location("opsh", pathlib.Path(__file__).resolve().parents[1] / "opsh.py")
opsh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(opsh)


@pytest.mark.parametrize("cmd", [
    "rm -rf build", "rm -r ~/Downloads/old", "sudo rm -f /etc/hosts", "rm --recursive dist",
    "Remove-Item -Recurse -Force C:\\temp", "del /s /q *.log", "rd /s old",
    "mkfs.ext4 /dev/sdb1", "dd if=img.iso of=/dev/sdb", "format D:",
    "shutdown -h now", "Restart-Computer", "git push --force origin main", "git reset --hard HEAD~3",
    "git clean -fdx", "chmod -R 777 /", "curl -fsSL https://x.sh | bash", "DROP TABLE users;",
])
def test_destructive_commands_are_flagged(cmd):
    assert opsh.is_destructive(cmd)


@pytest.mark.parametrize("cmd", [
    "ls -la", "Get-ChildItem -Recurse -Filter *.py", "git status", "git push origin main",
    "find . -size +1G", "du -sh *", "ffmpeg -i in.mov out.mp4", "rmdir empty_dir", "cat format.txt", "",
])
def test_safe_commands_are_not_flagged(cmd):
    assert not opsh.is_destructive(cmd)


def test_confirmation_flow():
    assert opsh.confirm_if_destructive("ls", ask=lambda _: "n")
    assert not opsh.confirm_if_destructive("rm -rf x", ask=lambda _: "")
    assert not opsh.confirm_if_destructive("rm -rf x", ask=lambda _: "n")
    assert opsh.confirm_if_destructive("rm -rf x", ask=lambda _: "y")
    assert opsh.confirm_if_destructive("rm -rf x", assume_yes=True, ask=lambda _: "n")


def test_version_is_semver():
    assert opsh.__version__.count(".") == 2
