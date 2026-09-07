"""Behavior checks for live timers, frame invalidation, and stable-frame caching."""

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import sys
import unittest

LOADER = SourceFileLoader("tmuxius_test_app", str(Path(__file__).resolve().parents[1] / "tmuxius"))
SPEC = spec_from_loader(LOADER.name, LOADER)
APP = module_from_spec(SPEC)
sys.modules[SPEC.name] = APP
LOADER.exec_module(APP)


class RefreshTests(unittest.TestCase):
    def workspace(self, raw):
        return APP.Workspace(APP.Session("$0", "0", 0, 0), "%0", "Codex", "busy",
                             "Demo", 1, 1, APP.safe_preview_lines(raw),
                             APP.semantic_snapshot_signature(raw),
                             preview_signature=APP.preview_snapshot_signature(raw))

    def test_timer_tick_updates_preview_without_faking_new_activity(self):
        before = "• Working (1s · esc to interrupt)"
        after = "• Working (2s · esc to interrupt)"
        workspace = self.workspace(before)
        refreshed = APP.refresh_workspace_from_snapshot(workspace, workspace.session, after,
                                                         now=2, include_preview=True)
        self.assertIn("2s", refreshed.preview[0].text)
        self.assertEqual(refreshed.busy_seconds, 2)
        self.assertEqual(refreshed.last_activity, workspace.last_activity)

    def test_unchanged_frame_reuses_parsed_preview(self):
        raw = "• Stable content\n› Ask anything"
        workspace = self.workspace(raw)
        refreshed = APP.refresh_workspace_from_snapshot(workspace, workspace.session, raw,
                                                         now=2, include_preview=True)
        self.assertIs(refreshed.preview, workspace.preview)

    def test_changes_earlier_than_live_tail_are_not_lost(self):
        tail = "\n".join(f"line {i}" for i in range(60))
        workspace = self.workspace("Original heading\n" + tail)
        refreshed = APP.refresh_workspace_from_snapshot(workspace, workspace.session,
                                                         "Updated heading\n" + tail,
                                                         now=2, include_preview=True)
        self.assertIn("Updated heading", "\n".join(line.text for line in refreshed.preview))


if __name__ == "__main__":
    unittest.main()
