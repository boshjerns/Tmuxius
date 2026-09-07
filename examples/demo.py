#!/usr/bin/env python3
"""Exercise the real dashboard with fictional data and all process access blocked."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_app():
    loader = SourceFileLoader("tmuxius_demo_app", str(ROOT / "tmuxius"))
    spec = spec_from_loader(loader.name, loader)
    app = module_from_spec(spec)
    sys.modules[spec.name] = app
    loader.exec_module(app)
    return app


SUBJECTS = ("Build the app", "Write the docs", "Review tests", "Plan the release", "Explore an idea")
TRANSCRIPTS = (
    """› Build a small reading list app. Keep it comfortable on a tablet.

• The basic flow is in place. You can add a book, move it between
  lists, and come back to exactly where you were reading.

  I am keeping the layout quiet: clear labels, a small set of
  actions, and room for the content to breathe.

• The first checks cover opening a list, changing the selection,
  and returning from the detail view. The selected item stays
  visible as you move through a longer reading list.

  Next I am checking the same flow with a narrow viewport and
  keyboard input, including an empty list and a long book title.

• I have the first version running. Books are grouped by Reading, Next,
  and Finished, with a clear title and a short note for each one.

  I am checking the narrow layout now. The list keeps its place when
  you open a book, and every action is reachable from the keyboard.

• The changes so far:

  - A simple list with large, readable controls.
  - Search that keeps the current selection visible.
  - A detail view that fits a portrait terminal.
  - Separate saved positions for each list.

• I will finish the interaction checks and report the result here.

{working}
2 background terminals running · /ps to view

› Ask anything
""",
    """> Write the getting-started guide while the app is being built.

• I have a first outline for someone opening the app for the
  first time. It starts with a short example and introduces
  controls at the point where you need them.

  The examples use a fictional reading list. You can follow the
  whole guide without needing an account or any existing data.

• I am checking that the wording matches the current screen,
  including what happens when a list is empty and how to return
  to your place after opening a book.

  Each instruction should fit comfortably on a small display.

• The guide now walks through opening your first reading list,
  adding a book, and moving between the list and its details.

  I kept the examples short so the whole flow is easy to follow
  on a small screen. Each step explains the visible control and
  what happens after you use it.

• The navigation reference covers:

  - Arrow keys to move through the current list.
  - Enter to open the selected item.
  - Escape to return with your place preserved.
  - Search and scrolling without losing the active selection.

• I am reviewing the examples against the current interface.

{working}
1 background terminal running · /ps to view

> What would you like to do next?
""",
)


def frame(index: int, seconds: int) -> str:
    if index < 2:
        elapsed = seconds + (135 if index == 0 else 72)
        working = f"\033[2m◦ Working ({elapsed // 60}m {elapsed % 60}s · esc to interrupt)\033[0m"
        return TRANSCRIPTS[index].format(working=working)
    return (
        f"› {SUBJECTS[index]}.\n\n"
        "• This is a fictional workspace for trying the controls.\n"
        "  Use arrows to select a workspace, Tab to switch panels,\n"
        "  and C outside Message to hide or restore the list.\n\n"
        "• Ready for the next step.\n\n› Ask anything\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single", action="store_true")
    parser.add_argument("--collapsed", action="store_true")
    parser.add_argument("--static", action="store_true", help="freeze fictional activity timers")
    args = parser.parse_args()
    app = load_app()
    started = time.monotonic()
    now = time.time()
    sessions = [app.Session(f"demo-{i}", str(i), 0, int(now)) for i in range(5)]
    panes = {
        session.session_id: app.Pane("0", "0", f"%demo-{i}", "codex" if i != 1 else "claude", 0,
                                    window_name=SUBJECTS[i], automatic_rename=False)
        for i, session in enumerate(sessions)
    }

    def snapshots(_socket, selected, _history_lines):
        seconds = 0 if args.static else int(time.monotonic() - started)
        return {pane.pane_id: frame(int(pane.pane_id.split("-")[-1]), seconds) for pane in selected}

    def collect(*_args, **_kwargs):
        captured = snapshots(None, list(panes.values()), 0)
        result = []
        for i, session in enumerate(sessions):
            pane = panes[session.session_id]
            raw = captured[pane.pane_id]
            result.append(app.Workspace(
                session, pane.pane_id, "Claude" if i == 1 else "Codex",
                "busy" if i < 2 else "ready", SUBJECTS[i], now - i * 120,
                135 if i == 0 else 72 if i == 1 else None,
                app.safe_preview_lines(raw), app.semantic_snapshot_signature(raw),
                SUBJECTS[i], app.preview_snapshot_signature(raw),
            ))
        return result

    def reject_message(_socket, workspace, _message, results):
        results.put(app.SendResult(False, workspace.session.session_id, "DEMO ONLY: no message was sent"))

    state = app.DashboardState(demo_mode=True, split_view=not args.single,
                              workspaces_collapsed=args.collapsed, focus="nav",
                              selected_session_ids=[sessions[0].session_id, sessions[1].session_id])
    with ExitStack() as stack:
        # Fail closed if the renderer ever reaches a real process or tmux call.
        stack.enter_context(patch.object(app.subprocess, "run", side_effect=AssertionError("Demo cannot start processes")))
        for name, value in {
            "list_sessions": lambda _socket: sessions,
            "list_active_panes": lambda _socket: panes,
            "collect_workspaces": collect,
            "capture_snapshots": snapshots,
            "refresh_workspace_details": lambda workspaces, *_: workspaces,
            "submit_dashboard_message": reject_message,
            "DashboardState": lambda: state,
        }.items():
            stack.enter_context(patch.object(app, name, value))
        return app.run_dashboard(None, 0, 0.5, "NO_COLOR" not in os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
