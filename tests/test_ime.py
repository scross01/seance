"""GTK composition regressions using physical keys on an isolated X server."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from unittest.mock import patch

import test_keyboard_remaps as keyboard


class SimpleIMETests(keyboard.PhysicalKeyboardTestCase):
    # The app normally reserves Ctrl+Shift+U for notification navigation.
    config_extra = '\n[keybinds]\njump-to-unread = "unset"\n'

    def setUp(self):
        # Exercise GTK's real compose engine without the desktop's IME daemon.
        with patch.dict(os.environ, {"GTK_IM_MODULE": "simple"}):
            super().setUp()

    def unicode_input(self, codepoint, terminator="Return"):
        self.key(37, True)
        self.key(50, True)
        self.tap(30)  # Physical U while Ctrl+Shift are held.
        self.key(50, False)
        self.key(37, False)
        self.run_x("xdotool", "type", codepoint)
        self.run_x("xdotool", "key", terminator)

    def test_korean_commit_is_sent_once_without_enter_or_paste_markers(self):
        self.capture(bracketed_paste=True)
        self.unicode_input("d55c")  # 한
        self.unicode_input("ae00", "space")  # 글
        self.tap(38)
        self.app.wait(lambda: self.received().endswith(b"a"), "typing after composition")
        self.assertEqual(self.received(), "한글a".encode())

    def test_composition_can_commit_on_modifier_release(self):
        self.capture()
        self.key(37, True)
        self.key(50, True)
        self.tap(30)  # Ctrl+Shift+U
        for keycode in (10, 10, 19):  # 110, keeping the modifiers held.
            self.tap(keycode)
        self.key(50, False)  # Releasing Shift commits U+0110.
        self.key(37, False)
        self.tap(38)
        self.app.wait(lambda: self.received().endswith(b"a"), "commit on modifier release")
        self.assertEqual(self.received(), "Đa".encode())

    def test_dead_key_commit_and_cancel_preserve_plain_keys_and_shortcuts(self):
        self.capture(variant="intl")
        self.tap(48)  # dead acute
        self.tap(26)  # e -> é
        self.tap(48)
        self.tap(9)   # Escape cancels the second composition.
        self.tap(38)
        self.key(37, True)
        self.tap(26)  # Ctrl+E must keep its physical key/modifier metadata.
        self.key(37, False)
        self.app.wait(lambda: self.received().endswith(b"\x05"), "shortcut after composition")
        self.assertEqual(self.received(), "éa".encode() + b"\x05")

    def test_cjk_commit_in_middle_of_existing_text(self):
        self.app.call("surface.send_text", {"text": "printf '<%s>\\n' AB"})
        self.app.wait(lambda: "AB" in self.app.call("surface.read_screen")["text"], "existing text")
        self.run_x("xdotool", "key", "Left")
        self.unicode_input("d55c")
        self.run_x("xdotool", "key", "End", "Return")
        self.app.wait(lambda: "<A한B>" in self.app.call("surface.read_screen")["text"],
                      "CJK insertion at the shell cursor")

    def test_closing_composing_panes_detaches_the_input_context(self):
        other = self.app.call("surface.split")["surface_id"]
        self.app.wait(lambda: self.app.call("surface.read_screen", {"surface_id": other}).get("text"),
                      "split startup")
        self.run_x("setxkbmap", "-layout", "us", "-variant", "intl", "-option", "")
        self.tap(48)  # Leave a dead-key composition pending while closing.
        self.app.call("surface.close", {"surface_id": other})
        self.app.stop()
        self.app.log.seek(0)
        self.assertNotIn("CRITICAL", self.app.log.read())


class IMESignalTests(keyboard.PhysicalKeyboardTestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = tempfile.TemporaryDirectory(prefix="seance-ime-")
        cls.addClassCleanup(cls.fixture_dir.cleanup)
        cls.module = str(Path(cls.fixture_dir.name) / "ime.so")
        flags = subprocess.check_output(["pkg-config", "--cflags", "--libs", "gtk4"], text=True)
        subprocess.run(["cc", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                        str(Path(__file__).with_name("ime_context.c")), "-o", cls.module,
                        *shlex.split(flags)], check=True)

    def setUp(self):
        self.ime_log = Path(self.fixture_dir.name) / "cursor.log"
        self.ime_log.write_text("")
        with patch.dict(os.environ, {"LD_PRELOAD": self.module,
                                     "SEANCE_TEST_IME_LOG": str(self.ime_log)}):
            super().setUp()

    def test_commit_then_preedit_change_keeps_next_korean_syllable(self):
        self.capture()
        self.run_x("xdotool", "key", "F6", "F8", "F7", "q", "a")
        self.app.wait(lambda: self.received().endswith(b"a"), "Hangul syllables and key translation")
        self.assertEqual(self.received(), "안녕λa".encode())

    def test_async_commit_is_complete_and_does_not_use_bracketed_paste(self):
        self.capture(bracketed_paste=True)
        self.run_x("xdotool", "key", "F9")
        expected = ("한글" * 128).encode()
        self.app.wait(lambda: len(self.received()) >= len(expected), "asynchronous IME commit")
        self.assertEqual(self.received(), expected)

    def cursor(self):
        count = len(self.ime_log.read_text().splitlines())
        self.run_x("xdotool", "key", "F10")
        self.app.wait(lambda: len(self.ime_log.read_text().splitlines()) > count, "IME cursor location")
        return tuple(map(int, self.ime_log.read_text().splitlines()[-1].split()))

    def test_candidate_anchor_tracks_cursor_and_focus_returns_after_pane_switch(self):
        original = self.app.call("system.identify")["surface_id"]
        self.app.call("surface.send_text", {"text": "AB"})
        self.app.wait(lambda: "AB" in self.app.call("surface.read_screen")["text"], "existing text")
        focused, x, y, width, height = self.cursor()
        self.assertEqual(focused, 1)
        self.assertGreater(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertGreaterEqual(width, 1)
        self.assertGreater(height, 1)
        self.run_x("xdotool", "key", "Left")
        # Readline updates the terminal cursor asynchronously after the key.
        self.app.wait(lambda: self.cursor()[1] < x, "candidate anchor after cursor movement")
        self.run_x("xdotool", "key", "F6")
        other = self.app.call("surface.split")["surface_id"]
        self.app.wait(lambda: self.app.call("surface.read_screen", {"surface_id": other}).get("text"),
                      "split startup")
        self.assertEqual(self.cursor()[0], 1)
        self.app.call("surface.focus", {"surface_id": original})
        self.assertEqual(self.cursor()[0], 1)
        self.run_x("xdotool", "key", "q")
        self.app.wait(lambda: "AλB" in self.app.call("surface.read_screen")["text"],
                      "plain translation after focus reset")
