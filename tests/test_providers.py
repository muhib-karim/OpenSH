"""Provider layer: HTTP retries and timeouts, key handling, each provider's request/response shape."""

import email.message
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from support import WINDOWS, IsolatedTestCase, opsh


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok(payload):
    return FakeResponse(json.dumps(payload).encode())


def http_error(code, body=b"", headers=None):
    msg = email.message.Message()
    for key, value in (headers or {}).items():
        msg[key] = value
    return urllib.error.HTTPError("https://api.example.test", code, "err", msg, io.BytesIO(body))


class Http(IsolatedTestCase):
    def post(self, *responses, retries=2, secrets=()):
        """Call http_post_json with urlopen returning/raising the given responses in order."""
        calls = []

        def urlopen(req, timeout):
            calls.append((req, timeout))
            item = responses[len(calls) - 1]
            if isinstance(item, BaseException):
                raise item
            return item

        sleeps = []
        with mock.patch.object(opsh.urllib.request, "urlopen", urlopen):
            result, out = self.capture(
                opsh.http_post_json, "https://api.example.test/x", {"a": 1}, {"H": "v"},
                timeout=7, retries=retries, secrets=secrets, sleep=sleeps.append,
            )
        return result, calls, sleeps, out

    def test_success_sends_json_with_timeout(self):
        result, calls, sleeps, _ = self.post(ok({"ok": True}))
        self.assertEqual(result, {"ok": True})
        req, timeout = calls[0]
        self.assertEqual((req.get_method(), timeout, json.loads(req.data)), ("POST", 7, {"a": 1}))
        self.assertEqual(sleeps, [])

    def test_retries_429_and_5xx_with_backoff_and_retry_after(self):
        result, calls, sleeps, out = self.post(
            http_error(429, headers={"Retry-After": "3"}), http_error(503), ok({"ok": 1}),
        )
        self.assertEqual(result, {"ok": 1})
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [3.0, 4.0])
        self.assertIn("Rate limit", out)
        self.assertIn("Server error 503", out)

    def test_bad_retry_after_falls_back_to_backoff(self):
        _, _, sleeps, _ = self.post(http_error(429, headers={"Retry-After": "soon"}), ok({}))
        self.assertEqual(sleeps, [2.0])

    def test_gives_up_on_repeated_429(self):
        with self.assertRaisesRegex(opsh.ProviderError, "Rate limit"):
            self.post(http_error(429), http_error(429), http_error(429))

    def test_auth_errors_are_not_retried(self):
        with self.assertRaisesRegex(opsh.ProviderError, "Authentication failed \\(401\\)"):
            self.post(http_error(401), ok({}))

    def test_other_errors_show_body_with_key_redacted(self):
        with self.assertRaises(opsh.ProviderError) as ctx:
            self.post(http_error(400, b'{"error": "bad key secret-key-123"}'), secrets=["secret-key-123"])
        self.assertIn("API error 400", str(ctx.exception))
        self.assertNotIn("secret-key-123", str(ctx.exception))
        self.assertIn("***", str(ctx.exception))

    def test_unreadable_error_body(self):
        err = http_error(418)
        err.read = mock.Mock(side_effect=OSError)
        with self.assertRaisesRegex(opsh.ProviderError, "API error 418"):
            self.post(err)

    def test_network_errors_retry_then_fail(self):
        result, calls, sleeps, _ = self.post(TimeoutError("slow"), ok({"ok": 1}))
        self.assertEqual((result, len(calls), sleeps), ({"ok": 1}, 2, [2.0]))
        with self.assertRaisesRegex(opsh.ProviderError, "Network error: down"):
            self.post(urllib.error.URLError("down"), retries=0)

    def test_invalid_json_and_non_object(self):
        with self.assertRaisesRegex(opsh.ProviderError, "Invalid JSON"):
            self.post(FakeResponse(b"<html>"))
        with self.assertRaisesRegex(opsh.ProviderError, "Unexpected response"):
            self.post(ok([1, 2]))

    def test_redact(self):
        self.assertEqual(opsh.redact("key=abcd1234 again abcd1234", ["abcd1234", None, "ab"]), "key=*** again ***")


class Providers(IsolatedTestCase):
    def capture_request(self, provider, payload):
        seen = {}

        def urlopen(req, timeout):
            seen.update(req=req, timeout=timeout)
            return ok(payload)

        with mock.patch.object(opsh.urllib.request, "urlopen", urlopen):
            text = provider.complete("prompt")
        return text, seen["req"], seen["timeout"]

    def test_groq_request_and_response(self):
        provider = opsh.GroqProvider("llama", api_key="test-key", base_url="https://g.example/v1/", timeout=9)
        text, req, timeout = self.capture_request(provider, {"choices": [{"message": {"content": " ls -la\n"}}]})
        self.assertEqual(text, "ls -la")
        self.assertEqual(req.full_url, "https://g.example/v1/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(req.get_header("User-agent"), f"OpenSH/{opsh.__version__}")
        self.assertEqual(json.loads(req.data)["model"], "llama")
        self.assertEqual(timeout, 9)

    def test_openai_compatible_without_key_sends_no_auth_header(self):
        provider = opsh.OllamaProvider("llama3.2", base_url="http://localhost:11434/v1")
        _, req, _ = self.capture_request(provider, {"choices": [{"message": {"content": "pwd"}}]})
        self.assertIsNone(req.get_header("Authorization"))

    def test_gemini_key_goes_in_header_not_url(self):
        provider = opsh.GeminiProvider("gemini-x", api_key="test-key", base_url="https://gem.example/v1beta")
        text, req, _ = self.capture_request(provider, {"candidates": [{"content": {"parts": [{"text": "pwd"}]}}]})
        self.assertEqual(text, "pwd")
        self.assertEqual(req.full_url, "https://gem.example/v1beta/models/gemini-x:generateContent")
        self.assertNotIn("test-key", req.full_url)
        self.assertEqual(req.get_header("X-goog-api-key"), "test-key")

    def test_unexpected_shapes_raise_provider_error(self):
        with self.assertRaisesRegex(opsh.ProviderError, "Unexpected response from openai"):
            self.capture_request(opsh.OpenAICompatibleProvider("m", base_url="https://x.example"), {"choices": []})
        with self.assertRaisesRegex(opsh.ProviderError, "Unexpected response from gemini"):
            self.capture_request(opsh.GeminiProvider("m", base_url="https://x.example"), {"oops": 1})

    def test_repr_never_shows_key(self):
        self.assertNotIn("test-key", repr(opsh.GroqProvider("m", api_key="test-key")))

    def test_base_provider_is_abstract(self):
        with self.assertRaises(NotImplementedError):
            opsh.Provider("m").complete("x")

    def test_mock_provider(self):
        provider = opsh.MockProvider("mock")
        self.assertEqual(provider.complete('...User request: say "hi"'), "echo \"mock: say 'hi'\"")
        self.assertEqual(provider.complete("for PowerShell ...User request: x"), 'Write-Output "mock: x"')
        self.assertIn("Mock explanation", provider.complete(f"{opsh.EXPLAIN_PREFIX} ...\n\nCommand: ls"))
        os.environ["OPENSH_MOCK_RESPONSE"] = "rm -rf build"
        self.assertEqual(provider.complete("User request: clean"), "rm -rf build")


class BuildProvider(IsolatedTestCase):
    def test_defaults_per_provider(self):
        env = {"GROQ_API_KEY": "g", "GEMINI_API_KEY": "m"}
        cases = [
            ({}, opsh.GroqProvider, "llama-3.3-70b-versatile"),
            ({"provider": "gemini"}, opsh.GeminiProvider, "gemini-2.5-flash"),
            ({"provider": "openai"}, opsh.OpenAICompatibleProvider, "gpt-4o-mini"),
            ({"provider": "ollama"}, opsh.OllamaProvider, "llama3.2"),
            ({"provider": "local"}, opsh.OllamaProvider, "llama3.2"),
            ({"provider": "mock"}, opsh.MockProvider, "mock"),
        ]
        for config, cls, model in cases:
            with self.subTest(config=config):
                provider = opsh.build_provider(config, env)
                self.assertIs(type(provider), cls)
                self.assertEqual(provider.model, model)

    def test_custom_openai_compatible_endpoint(self):
        config = {"provider": "openai-compatible", "base_url": "https://llm.example/v1", "model": "my-model",
                  "api_key_env": "MY_KEY", "timeout": 5, "retries": 0}
        provider = opsh.build_provider(config, {"MY_KEY": "k"})
        self.assertEqual((provider.base_url, provider.model, provider.api_key), ("https://llm.example/v1", "my-model", "k"))
        self.assertEqual((provider.timeout, provider.retries), (5.0, 0))

    def test_environment_overrides(self):
        env = {"OPENSH_PROVIDER": "ollama", "OPENSH_MODEL": "qwen", "OPENSH_TIMEOUT": "12"}
        provider = opsh.build_provider({"provider": "groq"}, env)
        self.assertEqual((provider.name, provider.model, provider.timeout), ("ollama", "qwen", 12.0))
        provider = opsh.build_provider({"provider": "ollama"}, {"OLLAMA_HOST": "127.0.0.1:11500"})
        self.assertEqual(provider.base_url, "http://127.0.0.1:11500/v1")
        provider = opsh.build_provider({"provider": "openai"}, {"OPENSH_BASE_URL": "http://box.example:8000/v1"})
        self.assertEqual(provider.base_url, "http://box.example:8000/v1")

    def test_errors(self):
        with self.assertRaisesRegex(opsh.ProviderError, "No Groq API key - set GROQ_API_KEY or run !auth"):
            opsh.build_provider({}, {})
        with self.assertRaisesRegex(opsh.ProviderError, "No Gemini API key"):
            opsh.build_provider({"provider": "gemini"}, {})
        with self.assertRaisesRegex(opsh.ProviderError, "Unknown provider 'nope'"):
            opsh.build_provider({"provider": "nope"}, {})
        with self.assertRaisesRegex(opsh.ProviderError, "must start with http"):
            opsh.build_provider({"provider": "openai", "base_url": "file:///etc/passwd"}, {})
        with self.assertRaisesRegex(opsh.ProviderError, "must be numbers"):
            opsh.build_provider({"provider": "mock", "retries": "lots"}, {})

    def test_get_ai_response_uses_config_and_session_overrides(self):
        opsh.save_config({"provider": "groq"})
        opsh.SESSION_OVERRIDES["provider"] = "mock"
        self.assertEqual(opsh.get_ai_response("User request: hi"), 'echo "mock: hi"')

    def test_get_command_uses_powershell_with_mock(self):
        self.use_mock_provider()
        opsh.PLATFORM = WINDOWS
        self.assertEqual(opsh.get_command("list files", str(self.tmp)), 'Write-Output "mock: list files"')


if __name__ == "__main__":
    unittest.main()
