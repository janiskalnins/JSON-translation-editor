"""Core tests: translation. Culture-code conversion, the glossary prompt block, every engine with
the network patched (the request built, the response parsed, configuration and HTTP/network
errors), Google's 429 retry, TranslationThread's configuration errors and glossary hand-off, and a
translator label for every engine.

Run:  python tests/check_core_translation.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import io
import json
import subprocess
import sys
import unittest
import urllib.error
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Iterator, List
from unittest import mock
from urllib.parse import parse_qs

from deep_translator.exceptions import TooManyRequests

jte = cs.jte
G = jte.GlossaryEntry


class _Response:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@contextmanager
def fake_urlopen(payload: dict = None, error: Exception = None) -> Iterator[List]:
    """urllib.request.urlopen replaced: every Request is recorded; the answer is *payload*, or
    *error* is raised."""
    requests = []

    def fake(request, timeout=None):
        requests.append(request)
        if error is not None:
            raise error
        return _Response(payload)
    with mock.patch("urllib.request.urlopen", fake):
        yield requests


def http_error(code: int = 500, body: bytes = b"x" * 1000) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example.invalid", code, "Server Error", {}, io.BytesIO(body))


def fake_translator_class(script: list, seen: List[dict]):
    """A stand-in for a deep_translator class: the constructor's keyword arguments go into *seen*;
    each translate() takes the next *script* item and raises it when it is an exception."""
    class Fake:
        def __init__(self, **kwargs):
            seen.append(kwargs)

        def translate(self, text):
            item = script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
    return Fake


def _claude_prompt(request) -> str:
    return json.loads(request.data)["messages"][0]["content"]


class CultureTests(unittest.TestCase):
    def test_deepl_codes(self):
        cases = {"lv-LV": "LV", "en-US": "EN-US", "en-gb": "EN-GB", "pt-BR": "PT-BR",
                 "zh-Hans": "ZH", "de": "DE"}
        for culture, expected in cases.items():
            with self.subTest(culture=culture):
                self.assertEqual(jte._culture_to_deepl(culture), expected)

    def test_bcp47_language_subtags(self):
        for culture, expected in {"lv-LV": "lv", "EN-us": "en", "de": "de", "": ""}.items():
            with self.subTest(culture=culture):
                self.assertEqual(jte._culture_to_bcp47(culture), expected)


class GlossaryPromptTests(unittest.TestCase):
    def test_no_matches_add_nothing(self):
        self.assertEqual(jte._format_glossary_prompt_block([]), "")

    def test_matches_are_listed_with_their_notes(self):
        block = jte._format_glossary_prompt_block([G("Lane", "Celiņš", "bowling"), G("Ball", "Bumba")])
        self.assertTrue(block.endswith('- "Lane" → "Celiņš" (bowling)\n- "Ball" → "Bumba"'), block)


class ClaudeTests(unittest.TestCase):
    def test_returns_the_translated_text(self):
        with fake_urlopen({"content": [{"text": " Saglabāt \n"}]}):
            self.assertEqual(jte._translate_claude("Save", "lv-LV", "k", "m"), "Saglabāt")

    def test_sends_the_key_and_the_model(self):
        with fake_urlopen({"content": [{"text": "x"}]}) as requests:
            jte._translate_claude("Save", "lv-LV", "k", "m")
        self.assertEqual((requests[0].get_header("X-api-key"), json.loads(requests[0].data)["model"]),
                         ("k", "m"))

    def test_prompt_names_the_target_culture(self):
        with fake_urlopen({"content": [{"text": "x"}]}) as requests:
            jte._translate_claude("Save", "lv-LV", "k", "m")
        self.assertIn("'lv-LV'", _claude_prompt(requests[0]))

    def test_prompt_holds_the_glossary(self):
        with fake_urlopen({"content": [{"text": "x"}]}) as requests:
            jte._translate_claude("Lane", "lv-LV", "k", "m", glossary=[G("Lane", "Celiņš")])
        self.assertIn('"Lane" → "Celiņš"', _claude_prompt(requests[0]))

    def test_http_error_is_a_runtime_error(self):
        with fake_urlopen(error=http_error()), self.assertRaises(RuntimeError):
            jte._translate_claude("Save", "lv-LV", "k", "m")

    def test_http_error_message_is_truncated(self):
        with fake_urlopen(error=http_error()):
            with self.assertRaises(RuntimeError) as caught:
                jte._translate_claude("Save", "lv-LV", "k", "m")
        self.assertLess(len(str(caught.exception)), 400)

    def test_network_error_is_a_runtime_error(self):
        with fake_urlopen(error=urllib.error.URLError("offline")), self.assertRaises(RuntimeError):
            jte._translate_claude("Save", "lv-LV", "k", "m")


class DeepLTests(unittest.TestCase):
    def _request(self, key: str = "k:fx", use_free: bool = False):
        with fake_urlopen({"translations": [{"text": "x"}]}) as requests:
            jte._translate_deepl("Save", "lv-LV", key, use_free)
        return requests[0]

    def test_free_key_uses_the_free_host(self):
        self.assertEqual(self._request("k:fx").full_url, "https://api-free.deepl.com/v2/translate")

    def test_pro_key_uses_the_pro_host(self):
        self.assertEqual(self._request("k").full_url, "https://api.deepl.com/v2/translate")

    def test_sends_the_target_language(self):
        self.assertEqual(parse_qs(self._request().data.decode())["target_lang"], ["LV"])

    def test_sends_the_key_in_the_auth_header(self):
        self.assertEqual(self._request("k:fx").get_header("Authorization"), "DeepL-Auth-Key k:fx")

    def test_returns_the_translated_text(self):
        with fake_urlopen({"translations": [{"text": "Saglabāt"}]}):
            self.assertEqual(jte._translate_deepl("Save", "lv-LV", "k", True), "Saglabāt")

    def test_http_error_is_a_runtime_error(self):
        with fake_urlopen(error=http_error(403)), self.assertRaises(RuntimeError):
            jte._translate_deepl("Save", "lv-LV", "k", True)

    def test_http_error_message_is_truncated(self):
        with fake_urlopen(error=http_error(403)):
            with self.assertRaises(RuntimeError) as caught:
                jte._translate_deepl("Save", "lv-LV", "k", True)
        self.assertLess(len(str(caught.exception)), 400)

    def test_network_error_is_a_runtime_error(self):
        with fake_urlopen(error=urllib.error.URLError("offline")), self.assertRaises(RuntimeError):
            jte._translate_deepl("Save", "lv-LV", "k", True)


class LibreTranslateTests(unittest.TestCase):
    def test_posts_to_the_translate_endpoint(self):
        with fake_urlopen({"translatedText": "x"}) as requests:
            jte._translate_libretranslate("Save", "lv-LV", "https://lt.example/", "")
        self.assertEqual(requests[0].full_url, "https://lt.example/translate")

    def test_sends_the_language_subtag(self):
        with fake_urlopen({"translatedText": "x"}) as requests:
            jte._translate_libretranslate("Save", "lv-LV", "https://lt.example", "")
        self.assertEqual(json.loads(requests[0].data)["target"], "lv")

    def test_returns_the_translated_text(self):
        with fake_urlopen({"translatedText": "Saglabāt"}):
            self.assertEqual(jte._translate_libretranslate("Save", "lv-LV", "https://lt.example", ""),
                             "Saglabāt")

    def test_http_error_is_a_runtime_error(self):
        with fake_urlopen(error=http_error()), self.assertRaises(RuntimeError):
            jte._translate_libretranslate("Save", "lv-LV", "https://lt.example", "")

    def test_http_error_message_is_truncated(self):
        with fake_urlopen(error=http_error()):
            with self.assertRaises(RuntimeError) as caught:
                jte._translate_libretranslate("Save", "lv-LV", "https://lt.example", "")
        self.assertLess(len(str(caught.exception)), 400)

    def test_network_error_is_a_runtime_error(self):
        with fake_urlopen(error=urllib.error.URLError("offline")), self.assertRaises(RuntimeError):
            jte._translate_libretranslate("Save", "lv-LV", "https://lt.example", "")


class GoogleTests(unittest.TestCase):
    def _translate(self, script: list, is_cancelled=lambda: False, delay: float = 0.01) -> str:
        seen: List[dict] = []
        with mock.patch("deep_translator.GoogleTranslator", fake_translator_class(script, seen)), \
                mock.patch.object(jte, "_GOOGLE_RETRY_DELAY_S", delay):
            return jte._translate_google_dt("Save", "lv-LV", is_cancelled)

    def test_one_429_is_retried(self):
        self.assertEqual(self._translate([TooManyRequests(), "Saglabāt"]), "Saglabāt")

    def test_two_429s_give_the_rate_limit_message(self):
        with self.assertRaises(RuntimeError) as caught:
            self._translate([TooManyRequests(), TooManyRequests()])
        self.assertEqual(str(caught.exception), jte._GOOGLE_RATE_LIMIT_MSG)

    def test_cancelled_pause_sends_no_second_request(self):
        script = [TooManyRequests(), "never sent"]
        with self.assertRaises(RuntimeError):
            self._translate(script, is_cancelled=lambda: True, delay=3.0)
        self.assertEqual(script, ["never sent"])

    def test_sends_the_language_subtag(self):
        seen: List[dict] = []
        with mock.patch("deep_translator.GoogleTranslator", fake_translator_class(["x"], seen)):
            jte._translate_google_dt("Save", "lv-LV")
        self.assertEqual(seen[0]["target"], "lv")

    def test_empty_result_is_an_error(self):
        with self.assertRaises(RuntimeError):
            self._translate([""])


class MyMemoryTests(unittest.TestCase):
    def _seen(self, culture: str = "lv-lv", email: str = "") -> dict:
        seen: List[dict] = []
        with mock.patch("deep_translator.MyMemoryTranslator", fake_translator_class(["x"], seen)):
            jte._translate_mymemory_dt("Save", culture, email)
        return seen[0]

    def test_region_casing_is_normalized(self):
        self.assertEqual(self._seen("lv-lv")["target"], "lv-LV")

    def test_email_is_passed_trimmed(self):
        self.assertEqual(self._seen(email=" a@b.c ")["email"], "a@b.c")

    def test_empty_result_is_an_error(self):
        with mock.patch("deep_translator.MyMemoryTranslator", fake_translator_class([""], [])), \
                self.assertRaises(RuntimeError):
            jte._translate_mymemory_dt("Save", "lv-LV")


class MicrosoftTests(unittest.TestCase):
    def test_missing_key_is_a_value_error(self):
        with self.assertRaises(ValueError):
            jte._translate_microsoft_dt("Save", "lv-LV", "  ")

    def test_region_is_passed(self):
        seen: List[dict] = []
        with mock.patch("deep_translator.MicrosoftTranslator", fake_translator_class(["x"], seen)):
            jte._translate_microsoft_dt("Save", "lv-LV", "k", "westeurope")
        self.assertEqual(seen[0]["region"], "westeurope")

    def test_error_message_is_truncated(self):
        script = [RuntimeError("e" * 1000)]
        with mock.patch("deep_translator.MicrosoftTranslator", fake_translator_class(script, [])):
            with self.assertRaises(RuntimeError) as caught:
                jte._translate_microsoft_dt("Save", "lv-LV", "k")
        self.assertLessEqual(len(str(caught.exception)), 300)


def _run_thread(cfg: dict, mw=None) -> str:
    """TranslationThread.run() on this thread; returns what it emitted (result or error)."""
    got: List[str] = []
    thread = jte.TranslationThread("Lane", "lv-LV", cfg, mw=mw)
    thread.finished.connect(got.append)
    thread.errored.connect(got.append)
    thread.run()
    return got[0]


class TranslationThreadTests(unittest.TestCase):
    def test_missing_configuration_is_reported(self):
        cases = {"claude": "No Claude API key configured.",
                 "deepl": "No DeepL API key configured.",
                 "microsoft_dt": "No Microsoft Translator API key configured."}
        for engine, message in cases.items():
            with self.subTest(engine=engine):
                self.assertEqual(_run_thread({"engine": engine}), message)

    def test_no_engine_is_reported(self):
        self.assertTrue(_run_thread({"engine": "none"}).startswith("No translation engine configured"))

    def test_matched_glossary_reaches_the_claude_prompt(self):
        mw = SimpleNamespace(glossary=[G("Lane", "Celiņš"), G("Ball", "Bumba")])
        with fake_urlopen({"content": [{"text": "x"}]}) as requests:
            _run_thread({"engine": "claude", "claude_api_key": "k"}, mw=mw)
        self.assertEqual(('"Lane" → "Celiņš"' in _claude_prompt(requests[0]),
                          '"Ball"' in _claude_prompt(requests[0])), (True, False))

    def test_disabled_glossary_stays_out_of_the_prompt(self):
        mw = SimpleNamespace(glossary=[G("Lane", "Celiņš")])
        with fake_urlopen({"content": [{"text": "x"}]}) as requests:
            _run_thread({"engine": "claude", "claude_api_key": "k", "glossary_enabled": False}, mw=mw)
        self.assertNotIn("Glossary", _claude_prompt(requests[0]))


class EngineLabelTests(unittest.TestCase):
    def test_every_engine_has_a_translator_label(self):
        engines = {key for key, _ in jte._TRANSLATION_ENGINES} - {"none"}
        self.assertEqual(set(jte._ENGINE_LABELS), engines)


@contextmanager
def recorded_open_process() -> Iterator[List[int]]:
    """anyio.open_process replaced by one that records each call's creationflags and fails, so
    no real process starts; the no-window wrapper, if installed inside, wraps this fake."""
    import anyio
    flags: List[int] = []

    async def fake(command, **kwargs):
        flags.append(kwargs.get("creationflags", 0))
        raise FileNotFoundError("no process in tests")
    with mock.patch.object(anyio, "open_process", fake):
        yield flags


@unittest.skipUnless(sys.platform == "win32", "console windows exist only on Windows")
class NoConsoleWindowTests(unittest.TestCase):
    """The windowed exe has no console, so every console program it starts (the claude CLI)
    would open a console window of its own unless started with CREATE_NO_WINDOW."""

    def _open(self, **kwargs) -> List[int]:
        import anyio
        with recorded_open_process() as flags:
            jte._install_no_window_process_spawn()
            with self.assertRaises(FileNotFoundError):
                anyio.run(lambda: anyio.open_process(["x"], **kwargs))
        return flags

    def test_sdk_process_starts_without_a_window(self):
        self.assertEqual(self._open(), [subprocess.CREATE_NO_WINDOW])

    def test_flags_the_caller_set_are_kept(self):
        self.assertEqual(self._open(creationflags=subprocess.CREATE_NEW_CONSOLE),
                         [subprocess.CREATE_NEW_CONSOLE])

    def test_installing_twice_wraps_once(self):
        import anyio
        with recorded_open_process():
            jte._install_no_window_process_spawn()
            first = anyio.open_process
            jte._install_no_window_process_spawn()
            self.assertIs(anyio.open_process, first)

    def test_subscription_session_starts_the_cli_without_a_window(self):
        session = jte.ClaudeSubscriptionSession("token", "claude-haiku-4-5")
        with recorded_open_process() as flags:
            with self.assertRaises(RuntimeError):
                session.start()
        self.assertEqual(set(flags), {subprocess.CREATE_NO_WINDOW})

    def test_sign_in_starts_the_cli_without_a_window(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(kwargs.get("creationflags", 0))
            return subprocess.CompletedProcess(args, 0, stdout="Token: sk-ant-abc", stderr="")
        with mock.patch("shutil.which", return_value="claude"), \
                mock.patch("subprocess.run", fake_run):
            jte.ClaudeSetupTokenThread().run()
        self.assertEqual(calls, [subprocess.CREATE_NO_WINDOW])


class PlaceholderPromptTests(unittest.TestCase):
    def test_claude_prompt_asks_to_keep_placeholders(self):
        sent = {}

        def fake_urlopen(req, timeout=None):
            sent["body"] = json.loads(req.data)
            return _Response({"content": [{"text": "x"}]})

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            jte._translate_claude("{name} saved", "es", "key", "model")
        self.assertIn(jte._PLACEHOLDER_PROMPT, sent["body"]["messages"][0]["content"])


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
