"""Shared test helpers: load opsh.py as a module without installing it."""

import contextlib
import importlib.util
import io
import os
import pathlib
import sys
import tempfile
import unittest
import unittest.mock as mock

ROOT = pathlib.Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("opsh", ROOT / "opsh.py")
assert _spec is not None and _spec.loader is not None
opsh = importlib.util.module_from_spec(_spec)
sys.modules["opsh"] = opsh  # dataclasses look the module up while it loads
_spec.loader.exec_module(opsh)

LINUX = opsh.get_platform_info(system="Linux", shell="bash")
MACOS = opsh.get_platform_info(system="Darwin", shell="zsh")
WINDOWS = opsh.get_platform_info(system="Windows", shell="powershell")

_ENV_KEYS = [k for k in os.environ if k.startswith("OPENSH_")] + [
    "GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "MY_KEY", "OLLAMA_HOST",
]


class IsolatedTestCase(unittest.TestCase):
    """Keeps every test away from the real config, .env, history, home folder and network."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        (self.tmp / "home").mkdir()
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)

        env = {k: v for k, v in os.environ.items() if k not in _ENV_KEYS}
        env.update({"OPENSH_NO_UPDATE_CHECK": "1", "OPENSH_HISTORY": str(self.tmp / "history")})
        self._patch(mock.patch.dict(os.environ, env, clear=True))
        self._patch(mock.patch.object(opsh, "config_path", self.tmp / "config.json"))
        self._patch(mock.patch.object(opsh, "env_path", self.tmp / ".env"))
        self._patch(mock.patch.object(opsh, "command_history", []))
        self._patch(mock.patch.object(opsh, "SESSION_OVERRIDES", {}))
        self._patch(mock.patch.object(opsh, "PLATFORM", LINUX))
        self._patch(mock.patch.object(opsh, "readline", None))
        home = self.tmp / "home"
        self._patch(mock.patch.object(opsh.Path, "home", classmethod(lambda cls: home)))
        self._patch(mock.patch.object(opsh.urllib.request, "urlopen", side_effect=AssertionError("network used")))
        self._patch(mock.patch.object(opsh.signal, "signal"))

    def _patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def capture(self, fn, *args, **kwargs):
        """Run fn and return (result, stdout text)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = fn(*args, **kwargs)
        return result, out.getvalue()

    def use_mock_provider(self, response=None):
        os.environ["OPENSH_PROVIDER"] = "mock"
        if response is not None:
            os.environ["OPENSH_MOCK_RESPONSE"] = response
