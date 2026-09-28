"""Smoke tests for the static landing page in docs/ (deployed to Vercel)."""

import fnmatch
import json
import re
from html.parser import HTMLParser

import opsh
from conftest import REPO_ROOT

DOCS = REPO_ROOT / "docs"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class TagChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.ids, self.scripts = [], [], set(), []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag not in VOID:
            self.stack.append((tag, self.getpos()))
        self._in_script = tag == "script"

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1][0] != tag:
            self.errors.append(f"unexpected </{tag}> at {self.getpos()}")
            return
        self.stack.pop()
        self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.scripts.append(data)


def parse_index():
    checker = TagChecker()
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    checker.feed(html)
    checker.close()
    return html, checker


def repo_files():
    return [p.relative_to(REPO_ROOT).as_posix() for p in REPO_ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]


def test_vercel_configs_point_at_existing_files():
    files = repo_files()
    for config_file, base in [(REPO_ROOT / "vercel.json", ""), (DOCS / "vercel.json", "docs/")]:
        config = json.loads(config_file.read_text())
        for build in config["builds"]:
            assert fnmatch.filter(files, base + build["src"].replace("/**", "/*")), build
        root_route = next(r for r in config["routes"] if r["src"] in ("/", "/(.*)"))
        assert (REPO_ROOT / (base + root_route["dest"].lstrip("/"))).is_file(), root_route


def test_index_html_is_well_formed():
    html, checker = parse_index()
    assert not checker.errors
    assert not checker.stack, f"unclosed tags: {checker.stack}"
    assert re.search(r"<title>[^<]*OpenSH[^<]*</title>", html)


def test_script_references_existing_elements():
    html, checker = parse_index()
    script = "".join(checker.scripts)
    for element_id in re.findall(r"getElementById\('([^']+)'\)", script):
        assert element_id in checker.ids
    for handler in re.findall(r'onclick="(\w+)\(', html):
        assert f"function {handler}(" in script


def test_install_commands_match_repo_scripts():
    html, _ = parse_index()
    scripts = re.findall(r"raw\.githubusercontent\.com/ai-dev-2024/OpenSH/main/([\w.]+)", html)
    assert set(scripts) == {"install.sh", "install.ps1"}
    for name in scripts:
        assert (REPO_ROOT / name).is_file()


def test_version_badge_matches_cli():
    html, _ = parse_index()
    assert f'<span class="version-badge">v{opsh.__version__}</span>' in html
