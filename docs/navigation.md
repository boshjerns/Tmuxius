# Navigating Tmuxius

## Panels, workspaces, and focus

A workspace is a tmux session's active pane. Its displayed ID is its session
name; numeric names such as `0`, `1`, and `2` enable direct digit selection.
Named sessions work through arrows and scrolling. If you change the active pane
inside a session, Tmuxius follows it.

The one-panel view has **Select ID** and **Message** modes. Stacked view adds
**Window**, which chooses TOP or BOTTOM. The panel colors identify position;
the visible control row, highlighted mode chip, and text cursor identify focus.
The two panels cannot show the same workspace simultaneously: choosing the
other panel's workspace swaps the selections.

Use **Left / Right** outside Message to step between modes. **Tab / Shift-Tab**
switch panels in stacked view. In one-panel view, Tab advances toward Message;
from Message, Tab returns to Select ID. **Esc** leaves Message for Select ID.

In Window mode, **Up / Down** and scrolling select the panel. In Select ID,
they change its workspace. Digits build a numeric session name; the selection
commits after approximately 0.7 seconds or immediately with **Enter**.
**Backspace** edits the pending ID. Enter with no pending ID opens Message.

**C** hides/restores the entire workspace list. **S** changes the number of
panels, **R / Ctrl-L** refresh, and **Q** quits. These shortcuts work only outside
Message; uppercase works too. Collapsing the list and switching layouts do not
discard drafts. Layout and drafts live only for the current dashboard process.

## Scrolling and touch

In Message, **Up / Down** scroll the transcript one line and **Page Up / Page
Down** scroll larger chunks. Scroll events move several lines. `LIVE` means
you are at the newest output; `+N` means you are looking N wrapped rows back.
Scroll down to return to live output. Each workspace keeps its own position.

Scroll events follow the selected mode: Window changes panels, Select ID changes
workspaces, and Message scrolls chat. A scroll over a panel activates that panel
first. Clicking a mode chip changes mode; clicking inside a transcript activates
that panel in Select ID mode. Use the mode chip to tell what scrolling will do.

Tmuxius runs on your host, inside a terminal. A tablet terminal can map touch
gestures to mouse scrolling or arrow keys. Horizontal gestures must be mapped
by your terminal app; there is no built-in raw-touch swipe recognizer. Client
apps differ, so use the mode controls and arrows if gestures are unavailable.

If you run the dashboard inside tmux, mouse forwarding may require mouse support.
The optional session-scoped toggle saves and restores your prior setting:

```sh
tmuxius-mouse on --target monitor
tmuxius-mouse off --target monitor
```

See tmux's [mouse documentation](https://github.com/tmux/tmux/wiki/Getting-Started#using-the-mouse).
Tmuxius requests mouse and bracketed-paste support while running, and releases
them when it exits normally. It does not change global tmux key bindings.

## Messages and editing

In Message, type or paste a draft, then press **Enter** to submit to the selected
workspace. This can steer a busy Codex or Claude session. The dashboard checks
the recognized composer and attempts to verify submission; an existing different
unsent draft in the agent pane causes it to stop. Unknown interfaces and modal
dialogs may need direct interaction in the original pane.

| Key | Message editing |
| --- | --- |
| Left / Right | Move the cursor; Left at the start returns to Select ID |
| Home / Ctrl-A | Start of draft |
| End / Ctrl-E | End of draft |
| Backspace / Delete | Delete before / at cursor |
| Ctrl-U / Ctrl-K | Delete before / after cursor |
| Ctrl-W | Delete previous word |
| Ctrl-C | Clear the dashboard draft |
| Esc | Return to Select ID while retaining the draft |

Drafts follow workspaces, including when you switch panels. Pasted multiline
text stays one message. Larger pastes display as a compact content block; the
original text is retained for submission. The maximum message is 1,048,576
characters. Bracketed paste is the most reliable way to distinguish pasted
newlines from an intentional Enter key. An incomplete bracketed paste is rejected.

Bare slash commands such as `/new` and `/fast` are entered as paced literal
keystrokes for Codex's command menu. Ordinary messages and commands with arguments
use bracketed paste. Tmuxius does not add instructions or receipt text to your
message. When submission is uncertain, it restores the dashboard draft and
shows an error. Inspect the original agent before retrying; a restored draft
does not prove that the first attempt was never received.

## Subjects and activity

Subjects update from the current workspace. A manually named tmux window with
automatic renaming disabled takes precedence:

```sh
tmux rename-window -t 0:0 'Build the app'
tmux set-window-option -t 0:0 automatic-rename off
```

Otherwise, Tmuxius looks for the current Codex thread title on Linux, then falls
back to a filtered transcript summary. Codex title enrichment depends on its
local process and database layout, which may change between versions. Retained
titles are cached by thread ID in the pane's `@tmuxius_codex_name_cache` option;
this is separate from your tmux status-bar configuration.

`BUSY` is inferred from recognized agent activity output. Other colors describe
time since observed activity: green within 10 minutes, yellow at 10–30 minutes,
orange at 30–60 minutes, and dark after an hour. **READY, FINISHING, and COMPLETE
are display hints, not proof that a task succeeded or an agent is idle.** The
Working/timer/background-terminal highlights follow recognized terminal text;
other agent layouts may not provide those highlights.

## Troubleshooting

- **No workspaces:** run as the user who owns the tmux server, or select an
  accessible server with `--socket`. Tmuxius does not elevate permissions.
- **Only one workspace appears:** each session contributes its active pane.
  Use separate sessions for independently monitored agents.
- **No colors:** check `NO_COLOR`, `--no-color`, and your terminal's `TERM` and
  256-color support. TOP/BOTTOM labels and the active control row still identify
  panels without color.
- **Codex itself stopped animating:** Tmuxius does not set Codex's `tui.animations`
  option. If you previously disabled it in your own Codex configuration, remove
  that override and restart **Codex itself** when convenient. Reopening only the
  dashboard does not reload a running agent's settings. A local 30-second check
  with Codex 0.153.4 reproduced a stationary Working timer with animations off
  and one-second increments with animations on, without new response text.
  OpenAI documents animations as [enabled by default](https://learn.chatgpt.com/docs/config-file/config-reference).
  This is independent of the dashboard's `--interval`, which defaults to 0.5
  seconds. tmux's `status-interval` controls its status bar, not how often
  application output is delivered.
- **Less history than expected:** tmux can only return retained scrollback.
  Set its `history-limit` before starting panes if you need more. Use
  `--history-lines` to bound work on very large histories.
- **Screen is cramped:** hide the workspace list with C, use S for one panel,
  or increase the terminal's rows/columns. The full-screen interface is not a
  screen-reader accessibility guarantee; `--summary` provides plain text.
- **Sending stops:** return to the original agent pane to resolve a pending
  draft, confirmation dialog, or unsupported composer. Inspect before retrying.
- **Host compatibility:** Linux with tmux 3.4 is tested. Python requires curses.
  macOS/BSD hosts are not yet verified; Linux `/proc`-based title enrichment is
  unavailable there. Windows users need a suitable Linux/WSL host environment.
