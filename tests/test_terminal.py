"""Verify the delivered UI and reversible configuration on disposable servers."""

from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

from tmux_harness import DemoTerminal, ROOT


@unittest.skipUnless(shutil.which("tmux"), "requires tmux")
class TerminalTests(unittest.TestCase):
    def test_controls_drafts_and_live_timer(self):
        with DemoTerminal() as terminal:
            initial = terminal.text()
            self.assertIn("TOP / 0 / Build the app", initial)
            self.assertIn("BOTTOM / 1 / Write the docs", initial)
            first_timer = re.findall(r"Working \(([^·]+)", initial)[0]
            terminal.wait_for(lambda: re.findall(r"Working \(([^·]+)", terminal.text())[0] != first_timer,
                              "Working timer must advance without new transcript text", timeout=2.5)
            terminal.key("c")
            self.assertNotIn("WORKSPACES 5 /", terminal.text())
            terminal.key("\x1bOC")  # Message
            terminal.key("cC")
            self.assertNotIn("WORKSPACES 5 /", terminal.text())
            self.assertIn("cC", terminal.text())
            terminal.key("\x1b")
            terminal.key("\t")
            rows = terminal.text().splitlines()
            controls = [i for i, row in enumerate(rows) if " SELECT ID " in row and " MESSAGE " in row]
            self.assertEqual(len(controls), 1)
            self.assertGreater(controls[0], next(i for i, row in enumerate(rows) if "BOTTOM /" in row))
            terminal.key("C")
            self.assertIn("WORKSPACES 5 /", terminal.text())
            terminal.key("\t")
            terminal.key("\x1bOC")
            self.assertIn("cC", terminal.text())
            terminal.key("\r")
            terminal.wait_for(lambda: "DEMO ONLY" in terminal.text(), "demo must refuse real sending")
            self.assertIn("cC", terminal.text())

    def test_minimum_stacked_size(self):
        with DemoTerminal(52, 16, "--collapsed", "--static") as terminal:
            content = terminal.text()
            self.assertIn("TOP /", content)
            self.assertIn("BOTTOM /", content)
            self.assertEqual(sum(" SELECT ID " in row and " MESSAGE " in row
                                 for row in content.splitlines()), 1)

    def test_mouse_toggle_restores_inherited_and_explicit_settings(self):
        with DemoTerminal(70, 30, "--static") as terminal:
            def tmux(*args):
                return subprocess.check_output(terminal.command + list(args), text=True).strip()
            def toggle(action):
                return subprocess.check_output([sys.executable, str(ROOT / "tmuxius-mouse"),
                                                action, "--target", "demo", "--socket", terminal.socket], text=True)
            original_global = tmux("show-options", "-gv", "mouse")
            for previous in (None, "off", "on"):
                if previous is None:
                    tmux("set-option", "-u", "-t", "demo", "mouse")
                else:
                    tmux("set-option", "-t", "demo", "mouse", previous)
                toggle("on")
                toggle("on")
                self.assertIn("mouse=on", toggle("status"))
                toggle("off")
                self.assertEqual(tmux("show-options", "-v", "-t", "demo", "mouse"), previous or "")
                self.assertEqual(tmux("show-options", "-gv", "mouse"), original_global)
            self.assertIn("nothing changed", toggle("off"))


if __name__ == "__main__":
    unittest.main()
