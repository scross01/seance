"""Fullscreen through physical keys, GTK and Openbox on isolated X servers."""
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

import test_keyboard_remaps as keyboard


class FullscreenTests(keyboard.PhysicalKeyboardTestCase):
    config_extra = '\n[window]\ndecoration-mode = "csd"\n'

    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = tempfile.TemporaryDirectory(prefix="seance-fullscreen-")
        cls.addClassCleanup(cls.fixture_dir.cleanup)
        cls.module = str(Path(cls.fixture_dir.name) / "window-probe.so")
        flags = subprocess.check_output(["pkg-config", "--cflags", "--libs", "libadwaita-1"], text=True)
        subprocess.run(["cc", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                        str(Path(__file__).with_name("window_probe.c")), "-o", cls.module,
                        *shlex.split(flags)], check=True)

    def setUp(self):
        if not shutil.which("openbox"):
            self.skipTest("fullscreen tests require openbox")
        self.state_file = Path(self.fixture_dir.name) / "windows.json"
        self.state_file.write_text("{}")
        self.env_extra = {"LD_PRELOAD": self.module,
                          "SEANCE_TEST_WINDOW_STATE": str(self.state_file),
                          "XDG_CURRENT_DESKTOP": ""}
        super().setUp()
        # No desktop configuration or WM keybindings may intercept our keys.
        config = self.app.root / "openbox.xml"
        config.write_text('<openbox_config xmlns="http://openbox.org/3.4/rc"/>')
        wm_env = self.app.env.copy()
        wm_env.pop("LD_PRELOAD", None)
        wm = subprocess.Popen(["openbox", "--sm-disable", "--config-file", str(config)],
                              env=wm_env, stdout=subprocess.PIPE, stderr=self.app.log)
        self.addCleanup(self.stop_server, wm)
        self.window = self.run_x("xdotool", "search", "--onlyvisible", "--pid",
                                 str(self.app.process.pid)).strip().splitlines()[0]
        self.app.wait(lambda: subprocess.run(
            ["xdotool", "windowactivate", self.window], env=self.app.env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode == 0,
            "window manager startup")
        self.run_x("xdotool", "windowactivate", "--sync", self.window)
        self.app.wait(lambda: self.state().get("header_height", 0) > 0, "initial CSD header")

    def state(self, window=None):
        return json.loads(self.state_file.read_text()).get(window or self.window, {})

    def expect_state(self, fullscreen, header):
        self.app.wait(lambda: self.state().get("fullscreen") == int(fullscreen) and
                      (self.state().get("header_height", -2) == header if header <= 0 else
                       self.state().get("header_height", 0) > 0),
                      f"fullscreen={fullscreen}, header={header}; last state={self.state()}")

    def palette_toggle(self):
        self.run_x("xdotool", "key", "ctrl+shift+p")
        self.app.wait(lambda: self.state().get("search_focused"), "command palette focus")
        self.run_x("xdotool", "type", "Toggle Fullscreen")
        # GtkSearchEntry debounces search-changed; Enter must use the new results.
        self.app.wait(lambda: self.state().get("fullscreen_selected"), "fullscreen search result")
        self.run_x("xdotool", "key", "Return")

    def test_f11_and_palette_restore_header_and_terminal_input(self):
        self.capture()
        self.run_x("xdotool", "key", "F11")
        self.expect_state(True, 0)
        self.run_x("xdotool", "key", "a")
        self.palette_toggle()
        self.expect_state(False, 1)
        self.palette_toggle()
        self.expect_state(True, 0)
        self.run_x("xdotool", "key", "F11")
        self.expect_state(False, 1)
        self.run_x("xdotool", "key", "b")
        self.app.wait(lambda: self.received().endswith(b"b"), "typing after fullscreen")
        self.assertEqual(self.received(), b"ab", "fullscreen shortcuts must not reach the terminal")

    def test_decoration_reload_keeps_fullscreen_header_hidden(self):
        self.run_x("xdotool", "key", "F11")
        self.expect_state(True, 0)
        config = self.app.root / "config" / "seance" / "config.toml"
        original = config.read_text()
        config.write_text(original.replace('decoration-mode = "csd"', 'decoration-mode = "ssd"'))
        self.run_x("xdotool", "key", "ctrl+shift+comma")
        self.expect_state(True, -1)
        self.run_x("xdotool", "key", "F11")
        self.expect_state(False, -1)
        self.run_x("xdotool", "key", "F11")
        self.expect_state(True, -1)
        config.write_text(original)
        self.run_x("xdotool", "key", "ctrl+shift+comma")
        self.expect_state(True, 0)
        self.run_x("xdotool", "key", "F11")
        self.expect_state(False, 1)

    def test_fullscreen_binding_can_be_reassigned(self):
        config = self.app.root / "config" / "seance" / "config.toml"
        with config.open("a") as output:
            output.write('\n[keybinds]\ntoggle-fullscreen = "F12"\n')
        self.run_x("xdotool", "key", "ctrl+shift+comma")
        self.capture()
        self.run_x("xdotool", "key", "F11", "a")
        self.app.wait(lambda: self.received().endswith(b"a"), "unbound F11 delivered to terminal")
        self.assertEqual(self.received(), b"\x1b[23~a")
        self.expect_state(False, 1)
        self.run_x("xdotool", "key", "F12")
        self.expect_state(True, 0)
        self.run_x("xdotool", "key", "F12")
        self.expect_state(False, 1)
