"""Installed shell resources and real zsh startup; run under Xvfb."""
from pathlib import Path
import shlex
import shutil
import unittest

import test_ghostty_integration as integration


@unittest.skipUnless(shutil.which("zsh"), "shell integration tests require zsh")
class ZshIntegrationTests(integration.GhosttyTestCase):
    custom_zdotdir = False
    shell_command = "zsh -l"

    def prepare(self):
        self.env.pop("ZDOTDIR", None)
        self.env.pop("GHOSTTY_RESOURCES_DIR", None)
        # Keep startup errors readable if zsh exits before reaching its prompt.
        with (self.root / "config" / "ghostty" / "config").open("a") as config:
            config.write("wait-after-command = true\n")
        self.dotdir = self.root / "zsh config" if self.custom_zdotdir else self.root / "home"
        self.dotdir.mkdir(exist_ok=True)
        if self.custom_zdotdir:
            self.env["ZDOTDIR"] = str(self.dotdir)
        (self.dotdir / ".zshenv").write_text(
            # Ubuntu's global zshrc otherwise runs compinit and can prompt about
            # permissions on the runner's completion directories. This fixture
            # checks startup and prompt hooks, so it does not need completions.
            "skip_global_compinit=1\n"
            "typeset -gi USER_ZSHENV_COUNT=$((USER_ZSHENV_COUNT + 1))\n")
        (self.dotdir / ".zprofile").write_text("typeset -gi USER_ZPROFILE_COUNT=$((USER_ZPROFILE_COUNT + 1))\n")
        (self.dotdir / ".zshrc").write_text("typeset -gi USER_ZSHRC_COUNT=$((USER_ZSHRC_COUNT + 1))\nPROMPT='READY> '\n")

    def test_user_config_and_both_integrations_load(self):
        self.wait(lambda: "READY>" in self.call("surface.read_screen")["text"], "user zsh prompt")
        output = self.root / "shell-state"
        script = self.root / "check.zsh"
        script.write_text(
            "print -r -- $USER_ZSHENV_COUNT $USER_ZPROFILE_COUNT $USER_ZSHRC_COUNT\n"
            "print -r -- ${ZDOTDIR-$HOME}\n"
            "print -r -- $+functions[_ghostty_precmd] $+functions[_seance_precmd]\n"
            "print -r -- ${precmd_functions[(I)_ghostty_precmd]} ${precmd_functions[(I)_seance_precmd]}\n"
            "print -r -- $SEANCE_SHELL_INTEGRATION_DIR\n"
            "print -r -- $SEANCE_BIN_DIR\n"
            "whence -p claude\n"
        )
        self.call("surface.send_text", {"text": "source " + shlex.quote(str(script)) +
                                       " > " + shlex.quote(str(output)) + "\n"})
        self.wait(lambda: output.exists() and len(output.read_text().splitlines()) == 7,
                  "shell integration state")
        lines = output.read_text().splitlines()
        self.assertEqual(lines[0], "1 1 1", "each user startup file must run exactly once")
        self.assertEqual(lines[1], str(self.dotdir))
        self.assertEqual(lines[2], "1 1", "Ghostty and Seance functions must both be installed")
        self.assertTrue(all(int(index) > 0 for index in lines[3].split()),
                        "both integrations must register their prompt hooks")
        resources = Path(self.binary).parent.parent / "share" / "seance"
        self.assertEqual(lines[4], str(resources / "shell-integration"))
        self.assertTrue((Path(lines[4]) / "zsh-integration.sh").is_file())
        self.assertEqual(lines[5], str(resources / "bin"))
        self.assertEqual(lines[6], str(resources / "bin" / "claude"))


class CustomZdotdirTests(ZshIntegrationTests):
    custom_zdotdir = True


class BashIntegrationTests(integration.GhosttyTestCase):
    shell_command = "/bin/bash"

    def prepare(self):
        self.env.pop("GHOSTTY_RESOURCES_DIR", None)
        (self.root / "home" / ".bashrc").write_text("PS1='BASH_READY> '\n")

    def test_namespaced_resources_load_and_wrapper_is_on_path(self):
        self.wait(lambda: "BASH_READY>" in self.call("surface.read_screen")["text"], "user bash prompt")
        output = self.root / "bash-state"
        self.call("surface.send_text", {"text":
            "{ type -t _seance_prompt_command; printf '%s\\n' \"$SEANCE_SHELL_INTEGRATION_DIR\"; "
            "command -v claude; } > " + shlex.quote(str(output)) + "\n"})
        self.wait(lambda: output.exists() and len(output.read_text().splitlines()) == 3,
                  "bash integration state")
        resources = Path(self.binary).parent.parent / "share" / "seance"
        self.assertEqual(output.read_text().splitlines(), [
            "function", str(resources / "shell-integration"), str(resources / "bin" / "claude")])
        self.assertTrue((resources / "shell-integration" / "bash-integration.sh").is_file())
