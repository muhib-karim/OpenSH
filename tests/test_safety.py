"""Table-driven tests for the destructive-command guard.

Every row pairs a command the guard must flag with a similar everyday command it must
leave alone, so a pattern that is too broad fails just as loudly as one that is too narrow.
"""

import time
import unittest

from support import opsh

# (shell, destructive, benign)
PAIRS = [
    # --- recursive / forced deletes: bash + zsh ---------------------------------------
    ("bash", "rm -rf build", "rm build.log"),
    ("bash", "rm -r ~/Downloads/old", "ls -r ~/Downloads/old"),
    ("bash", "rm -fr node_modules", "rm notes.txt"),
    ("bash", "rm -Rf /var/tmp/cache", "ls -Rf /var/tmp/cache"),
    ("bash", "rm -r -f dist", "rm -i dist.tar"),
    ("bash", "rm --recursive dist", "rm --interactive dist.tar"),
    ("bash", "rm --force old.db", "rm -v old.db"),
    ("bash", "rm dist -rf", "rm dist.txt"),
    ("bash", "sudo rm -rf /", "sudo ls -la /"),
    ("bash", "sudo -E rm -rf /opt/app", "sudo -E ls /opt/app"),
    ("bash", "/bin/rm -rf ~/projects", "/bin/ls ~/projects"),
    ("bash", "\\rm -rf tmp", "\\ls tmp"),
    ("bash", "command rm -rf tmp", "command -v rm"),
    ("bash", "cd /tmp && rm -rf *", "cd /tmp && ls *"),
    ("bash", "find . -name '*.pyc' | xargs rm -rf", "find . -name '*.pyc' | xargs ls -l"),
    ("bash", "find . -type d -name __pycache__ -exec rm -rf {} +", "find . -type d -name __pycache__ -print"),
    ("bash", "find /var/log -name '*.gz' -delete", "find /var/log -name '*.gz'"),
    ("bash", "shred -u secrets.txt", "sha256sum secrets.txt"),
    ("bash", "mv ~/Documents /dev/null", "mv ~/Documents/a.txt ~/Desktop/"),
    ("bash", "truncate -s 0 /var/log/syslog", "tail -n 50 /var/log/syslog"),
    ("zsh", "rm -rf ~/Library/Caches/*", "du -sh ~/Library/Caches/*"),
    ("zsh", "rm -rf -- *(.)", "print -l -- *(.)"),
    ("zsh", "sudo rm -rf /Applications/Old.app", "open /Applications/Safari.app"),
    ("zsh", "noglob rm -rf build/*", "noglob ls build/*"),
    ("zsh", "nohup rm -rf /data &", "nohup python server.py &"),
    # --- recursive / forced deletes: PowerShell + cmd -----------------------------------
    ("powershell", "Remove-Item -Recurse -Force C:\\temp", "Remove-Item C:\\temp\\a.txt"),
    ("powershell", "Remove-Item C:\\temp -Recurse", "Get-ChildItem C:\\temp -Recurse"),
    ("powershell", "remove-item .\\dist -force", "remove-item .\\dist\\old.log"),
    ("powershell", "Remove-Item -Path $env:USERPROFILE\\Downloads\\* -Recurse", "Copy-Item -Path .\\a -Destination .\\b -Recurse"),
    ("powershell", "ri .\\build -r -fo", "ri .\\build.log"),
    ("powershell", "rm -r .\\node_modules", "rm .\\debug.log"),
    ("powershell", "del .\\cache -Recurse", "del .\\cache.txt"),
    ("powershell", "Get-ChildItem *.log -Recurse | Remove-Item -Force", "Get-ChildItem *.log -Recurse | Measure-Object"),
    ("powershell", "Remove-Item 'C:\\Program Files\\App' -Recurse -Force", "Get-Item 'C:\\Program Files\\App'"),
    ("cmd", "rmdir /s /q C:\\old", "rmdir C:\\empty"),
    ("cmd", "rd /s build", "rd build"),
    ("cmd", "del /s /q *.log", "del old.log"),
    ("cmd", "del /f /q C:\\data\\*", "dir /s C:\\data"),
    ("cmd", "erase /s /q *.tmp", "echo /s /q"),
    # --- disks and filesystems ---------------------------------------------------------
    ("bash", "mkfs.ext4 /dev/sdb1", "lsblk /dev/sdb1"),
    ("bash", "mkfs -t vfat /dev/sdc", "blkid /dev/sdc"),
    ("bash", "mke2fs /dev/sda2", "e2fsck -n /dev/sda2"),
    ("bash", "mkswap /dev/sda3", "swapon --show"),
    ("bash", "wipefs -a /dev/sdb", "lsblk -f /dev/sdb"),
    ("bash", "dd if=img.iso of=/dev/sdb bs=4M", "dd if=/dev/zero of=test.img bs=1M count=10"),
    ("bash", "sudo dd if=/dev/zero of=/dev/nvme0n1", "dd if=/dev/sda of=backup.img"),
    ("bash", "dd if=/dev/urandom of=/dev/disk2", "dd if=/dev/urandom of=/dev/null count=1"),
    ("bash", "cat image.bin > /dev/sda", "cat image.bin > image.copy"),
    ("bash", "echo 1 >/dev/nvme0n1", "echo 1 >/dev/null"),
    ("bash", "fdisk /dev/sda", "fdisk -l"),
    ("bash", "sfdisk /dev/sdb < layout.txt", "sfdisk -l /dev/sdb"),
    ("bash", "parted /dev/sdb mklabel gpt", "parted -l"),
    ("zsh", "diskutil eraseDisk APFS Blank disk2", "diskutil list"),
    ("zsh", "sudo diskutil partitionDisk disk3 GPT JHFS+ New 100%", "diskutil info disk3"),
    ("powershell", "Format-Volume -DriveLetter D", "Get-Volume -DriveLetter D"),
    ("powershell", "Clear-Disk -Number 1 -RemoveData", "Get-Disk -Number 1"),
    ("powershell", "Initialize-Disk -Number 2", "Get-Disk"),
    ("powershell", "Remove-Partition -DriveLetter E", "Get-Partition -DriveLetter E"),
    ("powershell", "Remove-Item -Recurse -Force $HOME", "Get-Process | Format-Table"),
    ("cmd", "format D:", "type format.txt"),
    ("cmd", "format C: /q", "echo format"),
    ("cmd", "diskpart", "chkdsk C:"),
    ("cmd", "cipher /w:C:\\", "cipher /?"),
    ("cmd", "vssadmin delete shadows /all", "vssadmin list shadows"),
    ("cmd", "bcdedit /delete {current}", "bcdedit /enum"),
    # --- permissions ------------------------------------------------------------------
    ("bash", "chmod -R 777 /", "chmod -R 755 ./dist"),
    ("bash", "sudo chmod -R 777 /etc", "chmod 644 ./etc/app.conf"),
    ("bash", "chmod 777 -R /usr", "chmod 777 /tmp/test.sock"),
    ("bash", "chmod --recursive a+rwx /", "chmod +x ./run.sh"),
    ("bash", "chmod 777 /", "chmod 700 ~/.ssh"),
    ("bash", "chown -R nobody /", "chown -R $USER ./build"),
    ("bash", "sudo chown -R me:me /usr", "chown me:me notes.txt"),
    ("zsh", "sudo chmod -R 000 /System", "chmod -R u+w ./System"),
    ("powershell", "icacls C:\\ /grant Everyone:F /T", "icacls C:\\project\\file.txt"),
    ("powershell", "takeown /f C:\\Windows /r", "whoami /groups"),
    # --- fork bombs and runaway processes ----------------------------------------------
    ("bash", ":(){ :|:& };:", "echo ':)'"),
    ("bash", ":() { : | : & } ; :", "true; :"),
    ("zsh", "bomb(){ bomb|bomb& };bomb", "greet(){ echo hi; };greet"),
    ("powershell", "while($true){Start-Process powershell}", "while($i -lt 3){$i++}"),
    ("cmd", "%0|%0", "echo %0"),
    ("bash", "kill -9 -1", "kill -9 12345"),
    ("bash", "killall node", "pgrep node"),
    ("bash", "pkill -9 python", "pkill -f my_script.py"),
    ("powershell", "Stop-Process -Name chrome -Force", "Get-Process -Name chrome"),
    ("cmd", "taskkill /f /im explorer.exe", "tasklist /fi \"imagename eq explorer.exe\""),
    # --- power ------------------------------------------------------------------------
    ("bash", "shutdown -h now", "cat shutdown.log"),
    ("bash", "sudo reboot", "echo reboot"),
    ("bash", "poweroff", "uptime"),
    ("bash", "halt -p", "grep halt notes.txt"),
    ("bash", "sudo systemctl poweroff", "systemctl status nginx"),
    ("bash", "init 0", "echo init 0"),
    ("zsh", "sudo shutdown -r +5", "last reboot"),
    ("powershell", "Restart-Computer -Force", "Get-ComputerInfo"),
    ("powershell", "Stop-Computer", "Get-Command Stop-Computer -Syntax"),
    ("cmd", "shutdown /s /t 0", "type shutdown.txt"),
    # --- git history ------------------------------------------------------------------
    ("bash", "git push --force origin main", "git push origin main"),
    ("bash", "git push -f", "git push -u origin feature"),
    ("bash", "git push origin +main", "git push origin main:main"),
    ("bash", "git push --force-with-lease", "git push --tags"),
    ("bash", "git reset --hard HEAD~3", "git reset --soft HEAD~1"),
    ("bash", "git clean -fdx", "git clean -n"),
    ("bash", "git branch -D feature", "git branch -d feature"),
    ("bash", "git filter-branch --tree-filter 'rm x' HEAD", "git log --oneline"),
    ("bash", "git checkout -- .", "git checkout -b feature"),
    ("powershell", "git reset --hard origin/main", "git fetch origin main"),
    # --- download and execute ---------------------------------------------------------
    ("bash", "curl -fsSL https://example.com/x.sh | bash", "curl -fsSL https://example.com/x.json | jq ."),
    ("bash", "curl -s https://example.com/i.sh | sudo sh", "curl -s https://example.com/i.sh -o i.sh"),
    ("bash", "wget -qO- https://example.com/i.sh | sh", "wget -q https://example.com/file.zip"),
    ("bash", "curl https://example.com/a.py | python3", "curl https://example.com/a.txt | grep foo"),
    ("bash", "bash <(curl -s https://example.com/i.sh)", "diff <(ls a) <(ls b)"),
    ("bash", "sh -c \"$(curl -fsSL https://example.com/i.sh)\"", "sh -c 'echo hi'"),
    ("zsh", "zsh -c \"$(wget -qO- https://example.com/i.sh)\"", "zsh -c 'print hi'"),
    ("zsh", "curl -sL https://example.com/i.sh | zsh", "curl -sL https://example.com/i.sh | less"),
    ("powershell", "iwr https://example.com/i.ps1 | iex", "iwr https://example.com/i.ps1 -OutFile i.ps1"),
    ("powershell", "irm https://example.com/i.ps1 | Invoke-Expression", "irm https://example.com/api | ConvertTo-Json"),
    ("powershell", "iex (New-Object Net.WebClient).DownloadString('https://example.com/a')", "(New-Object Net.WebClient).DownloadFile('https://example.com/a', 'a')"),
    ("powershell", "Invoke-WebRequest https://example.com/x.ps1 | Invoke-Expression", "Invoke-WebRequest https://example.com/x.ps1 -OutFile x.ps1"),
    # --- system files, registry, security ---------------------------------------------
    ("bash", "echo '' > /etc/passwd", "cat /etc/passwd"),
    ("bash", "sudo tee /etc/hosts < /dev/null", "tee notes.txt < /dev/null"),
    ("bash", "crontab -r", "crontab -l"),
    ("bash", "history -c && rm ~/.bash_history", "history 20"),
    ("powershell", "reg delete HKLM\\Software\\App /f", "reg query HKLM\\Software\\App"),
    ("powershell", "Remove-Item HKLM:\\Software\\App -Recurse", "Get-Item HKLM:\\Software\\App"),
    ("powershell", "Set-ExecutionPolicy Unrestricted -Force", "Get-ExecutionPolicy"),
    ("powershell", "Set-MpPreference -DisableRealtimeMonitoring $true", "Get-MpPreference"),
    # --- databases and infrastructure -------------------------------------------------
    ("bash", "psql -c 'DROP TABLE users;'", "psql -c 'SELECT * FROM users;'"),
    ("bash", "mysql -e 'DROP DATABASE shop'", "mysql -e 'SHOW DATABASES'"),
    ("bash", "psql -c 'TRUNCATE TABLE orders'", "psql -c 'SELECT count(*) FROM orders'"),
    ("bash", "redis-cli FLUSHALL", "redis-cli PING"),
    ("bash", "docker system prune -a -f", "docker system df"),
    ("bash", "docker volume prune -f", "docker volume ls"),
    ("bash", "docker rm -f $(docker ps -aq)", "docker ps -a"),
    ("bash", "kubectl delete namespace prod", "kubectl get namespace prod"),
    ("bash", "terraform destroy -auto-approve", "terraform plan"),
    ("powershell", "docker image prune -a --force", "docker image ls"),
    # --- wrapped commands: sudo/env options, assignments, nested and remote shells ---------
    ("bash", "sudo -u root rm -rf /var/www", "sudo -u root ls /var/www"),
    ("bash", "sudo -u www-data git reset --hard", "sudo -u www-data git status"),
    ("bash", "env FOO=1 rm -rf build", "env FOO=1 make build"),
    ("bash", "FOO=1 rm -rf build", "FOO=1 make build"),
    ("bash", "GIT_DIR=x git push --force", "GIT_DIR=x git push"),
    ("bash", "nice -n 10 rm -rf /srv/cache", "nice -n 10 tar czf a.tgz src"),
    ("bash", "timeout 5 rm -rf ~", "timeout 5 ping -c 1 example.com"),
    ("bash", "bash -c 'rm -rf ~'", "bash -c 'ls ~'"),
    ("zsh", 'zsh -c "sudo reboot"', 'zsh -c "uptime"'),
    ("bash", "ssh host 'rm -rf /var/www'", "ssh host 'ls /var/www'"),
    ("bash", "ssh -i key.pem prod sudo reboot", "ssh -i key.pem prod uptime"),
    ("bash", "docker exec c rm -rf /data", "docker exec c ls /data"),
    ("bash", "kubectl exec -it pod -- rm -rf /tmp/x", "kubectl exec -it pod -- ls /tmp"),
    ("bash", "git -C repo push -f", "git -C repo push"),
    ("bash", "git checkout .", "git checkout main"),
    ("bash", "find . -name '*.log' | xargs rm", "find . -name '*.log' | xargs wc -l"),
    ("cmd", "cmd /c rd /s /q C:\\temp", "cmd /c dir C:\\temp"),
    ("powershell", 'powershell -Command "Remove-Item -Recurse -Force C:\\x"', 'powershell -Command "Get-ChildItem C:\\x"'),
    ("powershell", "Get-ChildItem *.tmp | Remove-Item", "Get-ChildItem *.tmp | Select-Object Name"),
    ("powershell", "Clear-RecycleBin -Force", "Get-PSDrive"),
]


class GuardTable(unittest.TestCase):
    def test_table_has_at_least_100_pairs(self):
        self.assertGreaterEqual(len(PAIRS), 100)

    def test_table_covers_every_shell(self):
        self.assertEqual({shell for shell, _, _ in PAIRS}, {"bash", "zsh", "powershell", "cmd"})

    def test_destructive_commands_are_flagged(self):
        for shell, bad, _ in PAIRS:
            with self.subTest(shell=shell, cmd=bad):
                self.assertTrue(opsh.is_destructive(bad), f"not flagged: {bad}")

    def test_benign_twins_are_not_flagged(self):
        for shell, _, good in PAIRS:
            with self.subTest(shell=shell, cmd=good):
                self.assertFalse(opsh.is_destructive(good), f"flagged: {good} -> {opsh.explain_risk(good)}")

    def test_every_flag_comes_with_a_reason(self):
        for _, bad, _ in PAIRS:
            for reason in opsh.explain_risk(bad):
                with self.subTest(cmd=bad):
                    self.assertTrue(reason and reason[0].isupper(), reason)

    def test_empty_and_whitespace_are_safe(self):
        for cmd in ("", "   ", "\n"):
            self.assertFalse(opsh.is_destructive(cmd))
            self.assertEqual(opsh.explain_risk(cmd), [])

    def test_long_input_is_checked_quickly(self):
        cmd = "sudo " + "-x y " * 400 + "ls " + "a " * 2000
        start = time.perf_counter()
        opsh.explain_risk(cmd)
        self.assertLess(time.perf_counter() - start, 1.0)

    def test_reasons_are_deduplicated(self):
        reasons = opsh.explain_risk("rm -rf a; rm -rf b")
        self.assertEqual(len(reasons), len(set(reasons)))


class Confirmation(unittest.TestCase):
    def test_safe_commands_never_prompt(self):
        def ask(_prompt):
            raise AssertionError("should not prompt")

        self.assertTrue(opsh.confirm_if_destructive("ls", ask=ask))

    def test_destructive_needs_explicit_yes(self):
        for answer, allowed in [("", False), ("n", False), ("no", False), ("y", True), ("YES", True)]:
            with self.subTest(answer=answer):
                self.assertIs(opsh.confirm_if_destructive("rm -rf x", ask=lambda _p, a=answer: a), allowed)

    def test_assume_yes_skips_prompt(self):
        self.assertTrue(opsh.confirm_if_destructive("rm -rf x", assume_yes=True, ask=lambda _p: "n"))

    def test_eof_and_ctrl_c_mean_no(self):
        for exc in (EOFError, KeyboardInterrupt):

            def ask(_prompt, exc=exc):
                raise exc

            with self.subTest(exc=exc.__name__):
                self.assertFalse(opsh.confirm_if_destructive("rm -rf x", ask=ask))

    def test_prompt_lists_the_reasons(self):
        seen = []
        opsh.confirm_if_destructive("rm -rf x", ask=lambda p: seen.append(p) or "n")
        self.assertIn("delete", seen[0].lower())


if __name__ == "__main__":
    unittest.main()
