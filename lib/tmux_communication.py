#!/usr/bin/env python3
"""Read and communicate with a tmux pane from a bottom-relative snapshot."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import time
import uuid


SEPARATOR_RE = re.compile(r"^\s*─{20,}\s*$")
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")
SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
BUSY_STATUS_RE = re.compile(
    r"^\s*(?:[◦•✻✽✢·*]\s*)?(?:"
    r"(?:Working|Computing)\s*\([^\r\n)]*"
    r"(?:esc to interrupt|press esc to cancel)[^\r\n)]*\)(?:\s*·[^\r\n]*)?"
    r"|Computing…)\s*$",
    re.IGNORECASE,
)
INTERRUPT_STATUS_RE = re.compile(
    r"^\s*[^\r\n()]{0,80}\([^\r\n)]{0,160}"
    r"(?:esc to interrupt|press esc to cancel)[^\r\n)]{0,160}\)"
    r"(?:\s*·[^\r\n]*)?\s*$",
    re.IGNORECASE,
)
CODEX_COMPOSER_STATUS_RE = re.compile(
    r"^\s*(?:gpt-\d|tab to queue message\b)", re.IGNORECASE
)
IDLE_SETTLE_SECONDS = 2.0
POLL_SECONDS = 0.1
PASTE_SETTLE_SECONDS = 0.15
# Codex classifies characters arriving within 8 ms as a paste burst. Bare slash
# commands must look like human typing so its command popup dispatches them as
# commands instead of treating them as pasted prompt text.
LITERAL_SLASH_KEY_INTERVAL_SECONDS = 0.012
BARE_SLASH_COMMAND_RE = re.compile(r"^/[A-Za-z0-9][A-Za-z0-9_-]*$")


def tmux(socket: str, *args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["tmux", "-S", socket, *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "tmux command failed"
        raise SystemExit(detail)
    return result.stdout


def snapshot(socket: str, target: str) -> list[str]:
    # Preserve SGR styling. Claude uses dim text for an autocomplete/history suggestion;
    # stripping it makes ghost text indistinguishable from a genuinely unsent draft.
    text = tmux(socket, "capture-pane", "-e", "-p", "-J", "-t", target, "-S", "-")
    return text.replace("\u00a0", " ").splitlines()


def visible_text(text: str) -> str:
    return ANSI_RE.sub("", text)


def numbered_page(lines: list[str], page: int, size: int) -> str:
    total = len(lines)
    end = max(0, total - page * size)
    start = max(0, end - size)
    width = max(1, len(str(total)))
    header = f"SNAPSHOT lines {start + 1 if end else 0}-{end} of {total}; page={page}; page_size={size}; page=0 is latest"
    body = [
        f"{index + 1:>{width}} | {visible_text(lines[index])}"
        for index in range(start, end)
    ]
    return "\n".join([header, *body])


def composer_frame(lines: list[str]) -> list[str] | None:
    """Return the live framed composer, regardless of how many lines it spans."""
    separators = [
        index for index, line in enumerate(lines) if SEPARATOR_RE.match(visible_text(line))
    ]
    if len(separators) < 2:
        return None
    framed = lines[separators[-2] + 1 : separators[-1]]
    if not framed or not re.match(r"^\s*❯", visible_text(framed[0])):
        return None
    return framed


def codex_composer(lines: list[str]) -> list[str] | None:
    """Return Codex's live composer above its model/status row."""
    start = max(0, len(lines) - 80)
    for index in range(len(lines) - 1, start - 1, -1):
        prompt_line = visible_text(lines[index])
        if not re.match(r"^\s*›(?:\s|$)", prompt_line):
            continue
        status_index: int | None = None
        for following in range(index + 1, min(len(lines), index + 30)):
            if CODEX_COMPOSER_STATUS_RE.match(visible_text(lines[following])):
                status_index = following
                break
        if status_index is None:
            command_match = re.match(
                r"^\s*›\s*(/[A-Za-z0-9][A-Za-z0-9_-]*)\s*$",
                prompt_line,
            )
            if command_match and any(
                visible_text(lines[following]).strip().startswith(
                    f"{command_match.group(1)}  "
                )
                for following in range(index + 1, min(len(lines), index + 12))
            ):
                # Codex temporarily replaces its normal model/status row with
                # slash-command suggestions. The exact prompt plus its matching
                # suggestion is still positive evidence of a live composer.
                return [lines[index]]
            continue
        framed = lines[index:status_index]
        while len(framed) > 1 and not visible_text(framed[-1]).strip():
            framed.pop()
        return framed
    return None


def active_composer(lines: list[str]) -> list[str] | None:
    return composer_frame(lines) or codex_composer(lines)


def composer_is_dim_suggestion(framed: list[str]) -> bool:
    """Detect a dim history/autocomplete hint, which is not a pending draft."""
    raw = "\n".join(framed)
    dim = False
    prompt_seen = False
    cursor = 0
    while cursor < len(raw):
        sgr = SGR_RE.match(raw, cursor)
        if sgr:
            params = [int(value) for value in sgr.group(1).split(";") if value]
            if not params or 0 in params:
                dim = False
            if 2 in params:
                dim = True
            if 22 in params:
                dim = False
            cursor = sgr.end()
            continue
        ansi = ANSI_RE.match(raw, cursor)
        if ansi:
            cursor = ansi.end()
            continue
        character = raw[cursor]
        cursor += 1
        if not prompt_seen:
            if character in {"❯", "›"}:
                prompt_seen = True
            continue
        if character.isspace():
            continue
        return dim
    return False


def live_busy_status(lines: list[str], framed: list[str] | None) -> bool:
    """Recognize the live activity row without treating scrollback prose as status."""
    prompt_index: int | None = None
    if framed:
        for index in range(len(lines) - 1, -1, -1):
            if lines[index] == framed[0] and re.match(
                r"^\s*[❯›]", visible_text(lines[index])
            ):
                prompt_index = index
                break

    if prompt_index is None:
        candidates = lines[-12:]
    else:
        candidates = lines[
            max(0, prompt_index - 8) : min(
                len(lines), prompt_index + len(framed or []) + 8
            )
        ]

    for line in candidates:
        visible = visible_text(line)
        if BUSY_STATUS_RE.match(visible) or INTERRUPT_STATUS_RE.match(visible):
            return True
    return False


def pane_state(lines: list[str]) -> str:
    framed = active_composer(lines)
    if framed:
        if not composer_is_dim_suggestion(framed):
            visible_frame = [visible_text(line) for line in framed]
            prompt = re.sub(r"^\s*[❯›]\s*", "", visible_frame[0])
            continuation = [line.strip() for line in visible_frame[1:] if line.strip()]
            if prompt or continuation:
                # An explicitly typed follow-up outranks the live activity row:
                # it must be submitted or cleared even while the peer is working.
                return "pending"

    if live_busy_status(lines, framed):
        return "busy"

    if framed:
        return "idle"

    # Some terminal widths omit one frame edge; accept only a truly empty prompt.
    if any(re.match(r"^\s*[❯›]\s*$", visible_text(line)) for line in lines[-8:]):
        return "idle"
    return "unknown"


def composer_message(lines: list[str]) -> str | None:
    framed = active_composer(lines)
    if not framed or composer_is_dim_suggestion(framed):
        return None
    visible_frame = [visible_text(line) for line in framed]
    first = re.sub(r"^\s*[❯›]\s*", "", visible_frame[0]).rstrip()
    rest = [line.rstrip() for line in visible_frame[1:]]
    text = "\n".join([first, *rest]).strip()
    return text or None


def composer_text_matches(observed: str, expected: str) -> bool:
    """Match exact input against a TUI rendering that may add wrap whitespace."""
    if observed == expected:
        return True
    return re.sub(r"\s+", "", observed) == re.sub(r"\s+", "", expected)


def composer_has_expected(
    message: str,
    marker: str | None = None,
    expected_text: str | None = None,
) -> bool:
    return bool(marker and marker in message) or bool(
        expected_text is not None and composer_text_matches(message, expected_text)
    )


def message_sha256(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def idle_composer_is_empty(lines: list[str]) -> bool:
    return pane_state(lines) == "idle" and composer_message(lines) is None


def pane_state_banner(lines: list[str]) -> str:
    """Make an unsent composer impossible to miss on every read path."""
    state = pane_state(lines)
    pending = composer_message(lines) if state == "pending" else None
    if pending:
        return (
            "ACTION_REQUIRED state=pending UNSENT_COMPOSER=true "
            f"pending_sha256={message_sha256(pending)} characters={len(pending)}\n"
            "Resolve it with submit, resend-pending, discard-pending, or "
            "replace-pending before doing anything else."
        )
    guidance = {
        "idle": "composer is empty and ready",
        "pending": "nonempty composer detected; resolve it before sending",
        "busy": "peer is computing; do not type",
        "unknown": "composer state is unknown; do not type",
    }[state]
    return f"PANE_STATE state={state}: {guidance}"


def command_page(args: argparse.Namespace) -> None:
    lines = snapshot(args.socket, args.target)
    print(f"{pane_state_banner(lines)}\n{numbered_page(lines, args.page, args.lines)}")
    if pane_state(lines) == "pending":
        raise SystemExit(3)


def command_find(args: argparse.Namespace) -> None:
    lines = snapshot(args.socket, args.target)
    print(pane_state_banner(lines))
    if pane_state(lines) == "pending":
        print(numbered_page(lines, 0, min(args.context * 4 + 12, 100)))
        raise SystemExit(3)
    pattern = re.compile(args.pattern, re.IGNORECASE if args.ignore_case else 0)
    matches = [
        index for index, line in enumerate(lines) if pattern.search(visible_text(line))
    ]
    if not matches:
        raise SystemExit("no matches")
    emitted: set[int] = set()
    width = max(1, len(str(len(lines))))
    for match in matches:
        start = max(0, match - args.context)
        end = min(len(lines), match + args.context + 1)
        if emitted and start > max(emitted) + 1:
            print("--")
        for index in range(start, end):
            if index in emitted:
                continue
            marker = ">" if index == match else " "
            print(f"{marker}{index + 1:>{width}} | {visible_text(lines[index])}")
            emitted.add(index)


def command_state(args: argparse.Namespace) -> None:
    metadata = tmux(
        args.socket,
        "display-message",
        "-p",
        "-t",
        args.target,
        "pane=#{pane_id} tty=#{pane_tty} session=#{session_name} window=#{window_index} pane_index=#{pane_index} command=#{pane_current_command} mode=#{pane_in_mode} alt=#{alternate_on} history=#{history_size}",
    ).strip()
    lines = snapshot(args.socket, args.target)
    state = pane_state(lines)
    pending = composer_message(lines) if state == "pending" else None
    guidance = {
        "idle": "idle composer detected",
        "pending": "nonempty composer detected; submit or clear it before sending another message",
        "busy": "peer is computing; do not type yet",
        "unknown": "composer state unknown; do not type yet",
    }[state]
    pending_detail = f"\npending_sha256={message_sha256(pending)}" if pending else ""
    print(
        f"{pane_state_banner(lines)}\n{metadata}\n"
        f"state={state}: {guidance}{pending_detail}\n"
        f"{numbered_page(lines, 0, args.lines)}"
    )
    if state == "pending":
        raise SystemExit(3)


def wait_for_loaded_composer(
    socket: str,
    target: str,
    marker: str | None = None,
    expected_text: str | None = None,
    timeout: float = 5.0,
) -> tuple[list[str], str]:
    """Prove that the exact outbound payload reached the live composer."""
    deadline = time.monotonic() + timeout
    current = snapshot(socket, target)
    while time.monotonic() < deadline:
        message = composer_message(current) or ""
        collapsed_paste = bool(
            re.fullmatch(r"\[Pasted [^\]\r\n]{1,80}\]", message, re.IGNORECASE)
        )
        expected_loaded = composer_has_expected(message, marker, expected_text)
        if pane_state(current) == "pending" and (expected_loaded or collapsed_paste):
            return current, message
        time.sleep(0.1)
        current = snapshot(socket, target)

    observed = composer_message(current)
    state = pane_state(current)
    observed_detail = (
        f" observed_sha256={message_sha256(observed)}"
        if observed is not None
        else " observed_composer=none"
    )
    expected_detail = (
        f" expected_sha256={message_sha256(expected_text)}"
        if expected_text is not None
        else ""
    )
    print(numbered_page(current, 0, 100), file=sys.stderr)
    raise SystemExit(
        "outbound payload was not verified in the live composer: "
        f"state={state}{observed_detail}{expected_detail}"
    )


def submit_and_verify(
    socket: str,
    target: str,
    *,
    expected_marker: str | None = None,
    expected_composer: str | None = None,
    attempts: int = 4,
) -> tuple[list[str], str]:
    """Submit a pending composer and prove it actually left the composer.

    Claude Code occasionally ignores an Enter sent immediately after a paste. Retry only
    while the same expected payload is demonstrably still pending; once the pane is busy,
    idle, or the payload has left the composer, never press another submit key.
    """
    current = snapshot(socket, target)
    if pane_state(current) != "pending":
        print(numbered_page(current, 0, 100), file=sys.stderr)
        raise SystemExit("refusing to submit: the live composer is not pending")
    initial_message = composer_message(current) or ""
    expected_loaded = composer_has_expected(
        initial_message, expected_marker, expected_composer
    )
    if (expected_marker or expected_composer) and not expected_loaded:
        print(numbered_page(current, 0, 100), file=sys.stderr)
        raise SystemExit("refusing to submit: expected payload is not in the live composer")

    submit_keys = ("Enter", "C-m")
    for attempt in range(1, attempts + 1):
        key = submit_keys[(attempt - 1) % len(submit_keys)]
        tmux(socket, "send-keys", "-t", target, key)
        deadline = time.monotonic() + 2.0

        while time.monotonic() < deadline:
            time.sleep(0.1)
            current = snapshot(socket, target)
            state = pane_state(current)
            message = composer_message(current)

            if state in {"busy", "idle"}:
                print(f"SUBMITTED attempt={attempt} key={key} state={state}", flush=True)
                return current, state
            if state == "pending":
                expected_pending = composer_has_expected(
                    message or "", expected_marker, expected_composer
                )
                if (expected_marker or expected_composer) and not expected_pending:
                    print(numbered_page(current, 0, 100), file=sys.stderr)
                    raise SystemExit("composer changed while submitting; refusing to press Enter again")
                continue
            expected_left = not composer_has_expected(
                message or "", expected_marker, expected_composer
            )
            if (expected_marker or expected_composer) and expected_left:
                # Some full-screen refreshes briefly classify as unknown. The exact payload
                # leaving the framed composer is still positive submission evidence.
                print(
                    f"SUBMITTED attempt={attempt} key={key} state={state} payload_left_composer=true",
                    flush=True,
                )
                return current, state

        current = snapshot(socket, target)
        if pane_state(current) != "pending":
            print(
                f"SUBMITTED attempt={attempt} key={key} state={pane_state(current)}",
                flush=True,
            )
            return current, pane_state(current)
        current_message = composer_message(current) or ""
        expected_still_pending = composer_has_expected(
            current_message, expected_marker, expected_composer
        )
        if (expected_marker or expected_composer) and not expected_still_pending:
            print(numbered_page(current, 0, 100), file=sys.stderr)
            raise SystemExit("composer changed while submitting; refusing to press Enter again")

    print(numbered_page(current, 0, 120), file=sys.stderr)
    raise SystemExit(f"submission unverified after {attempts} bounded attempts")


def send_with_receipt(args: argparse.Namespace, message: str, before: list[str]) -> None:
    marker = f"TMUX_ACK:{args.receipt}"
    baseline = "\n".join(before).count(marker)
    payload = f"{message}\n\nReply with exactly {marker} when this message is received."
    buffer_name = f"tmux-communication-{uuid.uuid4().hex}"

    tmux(args.socket, "send-keys", "-t", args.target, "C-u")
    tmux(args.socket, "load-buffer", "-b", buffer_name, "-", input_text=payload)
    loaded_buffer = tmux(args.socket, "show-buffer", "-b", buffer_name)
    if loaded_buffer != payload:
        tmux(args.socket, "delete-buffer", "-b", buffer_name)
        raise SystemExit("tmux buffer differs from the outbound payload")
    # -p asks tmux to emit bracketed-paste guards when the application supports
    # them; -r preserves literal LF bytes instead of rewriting them as Enter/CR.
    tmux(
        args.socket,
        "paste-buffer",
        "-p",
        "-r",
        "-b",
        buffer_name,
        "-t",
        args.target,
    )
    _, expected_composer = wait_for_loaded_composer(
        args.socket,
        args.target,
        marker=marker,
        expected_text=payload,
    )
    time.sleep(PASTE_SETTLE_SECONDS)
    tmux(args.socket, "delete-buffer", "-b", buffer_name)
    submit_and_verify(
        args.socket,
        args.target,
        expected_marker=marker,
        expected_composer=expected_composer,
    )

    deadline = time.monotonic() + args.timeout
    acknowledgement_seen = False
    idle_since: float | None = None
    while time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        current = snapshot(args.socket, args.target)
        # One occurrence is in our request; the second is the peer's receipt.
        if "\n".join(current).count(marker) >= baseline + 2:
            acknowledgement_seen = True
            if pane_state(current) == "pending":
                pending = composer_message(current) or ""
                print(numbered_page(current, 0, min(args.lines, 120)), file=sys.stderr)
                raise SystemExit(
                    "delivery was acknowledged, but another unsent composer remains: "
                    f"pending_sha256={message_sha256(pending)}"
                )
            if idle_composer_is_empty(current):
                now = time.monotonic()
                if idle_since is None:
                    idle_since = now
                if now - idle_since >= IDLE_SETTLE_SECONDS:
                    print(
                        f"DELIVERED {marker} state=idle composer=empty "
                        f"stable_seconds={IDLE_SETTLE_SECONDS:.1f}"
                    )
                    return
            else:
                idle_since = None

    current = snapshot(args.socket, args.target)
    print(numbered_page(current, 0, min(args.lines, 120)), file=sys.stderr)
    if acknowledgement_seen:
        raise SystemExit(
            f"delivery acknowledgement appeared, but the pane did not settle idle with an empty composer within {args.timeout}s"
        )
    raise SystemExit(f"delivery unverified: did not receive a second {marker} within {args.timeout}s")


def command_send(args: argparse.Namespace) -> None:
    message = sys.stdin.read().strip()
    if not message:
        raise SystemExit("send requires a non-empty message on stdin")
    before = snapshot(args.socket, args.target)
    state = pane_state(before)
    if state == "pending":
        pending = composer_message(before) or ""
        marker = f"TMUX_ACK:{args.receipt}"
        canonical_payload = (
            f"{message}\n\nReply with exactly {marker} when this message is received."
        )
        if not any(
            composer_text_matches(pending, candidate)
            for candidate in (message, canonical_payload)
        ):
            print(numbered_page(before, 0, min(args.lines, 100)), file=sys.stderr)
            raise SystemExit(
                "refusing to send over a different unsent composer: "
                f"pending_sha256={message_sha256(pending)}"
            )
        before, recovered = clear_pending(
            args.socket,
            args.target,
            message_sha256(pending),
            args.lines,
        )
        print(
            f"RECOVERED identical_unsent_composer_sha256={message_sha256(recovered)}",
            flush=True,
        )
        state = "idle"
    if state != "idle":
        print(numbered_page(before, 0, min(args.lines, 100)), file=sys.stderr)
        raise SystemExit("refusing to send: no idle composer detected")
    send_with_receipt(args, message, before)


def command_send_user(args: argparse.Namespace) -> None:
    """Submit exact, explicitly human-composed stdin without receipt text."""
    message = sys.stdin.read()
    if not message.strip():
        raise SystemExit("send-user requires a non-empty message on stdin")
    before = snapshot(args.socket, args.target)
    state = pane_state(before)
    if state == "pending":
        steered_while_busy = live_busy_status(before, active_composer(before))
        pending = composer_message(before) or ""
        if not composer_text_matches(pending, message):
            print(numbered_page(before, 0, min(args.lines, 100)), file=sys.stderr)
            raise SystemExit(
                "refusing to send-user over a different unsent composer: "
                f"pending_sha256={message_sha256(pending)}"
            )
        _, submitted_state = submit_and_verify(
            args.socket,
            args.target,
            expected_composer=pending,
        )
        print(
            "USER_MESSAGE_SUBMITTED "
            f"sha256={message_sha256(message)} characters={len(message)} "
            f"state={submitted_state} exact_text=true recovered_pending=true "
            f"steered_while_busy={str(steered_while_busy).lower()}"
        )
        return
    if state not in {"idle", "busy"}:
        print(numbered_page(before, 0, min(args.lines, 100)), file=sys.stderr)
        raise SystemExit(
            f"refusing to send-user: composer state is {state}, not idle or busy"
        )

    buffer_name = f"tmux-user-message-{uuid.uuid4().hex}"
    started_busy = state == "busy"
    if not started_busy:
        tmux(args.socket, "send-keys", "-t", args.target, "C-u")
    tmux(args.socket, "load-buffer", "-b", buffer_name, "-", input_text=message)
    try:
        loaded_buffer = tmux(args.socket, "show-buffer", "-b", buffer_name)
        if loaded_buffer != message:
            raise SystemExit("tmux buffer differs from the exact human-composed message")
        if BARE_SLASH_COMMAND_RE.fullmatch(message):
            # Codex routes literal typing through its slash-command popup. A
            # bracketed paste can instead take the ordinary prompt path on
            # affected releases, which makes argumentless commands such as
            # /new and /fast appear to submit without executing. Pace each
            # character beyond Codex's paste-burst window to faithfully emulate
            # a human typing the exact command.
            for character in message:
                tmux(
                    args.socket,
                    "send-keys",
                    "-l",
                    "-t",
                    args.target,
                    character,
                )
                time.sleep(LITERAL_SLASH_KEY_INTERVAL_SECONDS)
        else:
            # Preserve multiline human text as one bracketed paste. Without
            # -p/-r, an embedded LF may be rewritten to CR and submit only the
            # first line.
            tmux(
                args.socket,
                "paste-buffer",
                "-p",
                "-r",
                "-b",
                buffer_name,
                "-t",
                args.target,
            )
        _, expected_composer = wait_for_loaded_composer(
            args.socket,
            args.target,
            expected_text=message,
        )
        time.sleep(PASTE_SETTLE_SECONDS)
    finally:
        tmux(args.socket, "delete-buffer", "-b", buffer_name)

    _, submitted_state = submit_and_verify(
        args.socket,
        args.target,
        expected_composer=expected_composer,
    )
    print(
        "USER_MESSAGE_SUBMITTED "
        f"sha256={message_sha256(message)} characters={len(message)} "
        f"state={submitted_state} exact_text=true "
        f"steered_while_busy={str(started_busy).lower()}"
    )


def command_submit(args: argparse.Namespace) -> None:
    before = snapshot(args.socket, args.target)
    if pane_state(before) != "pending":
        print(numbered_page(before, 0, min(args.lines, 100)), file=sys.stderr)
        raise SystemExit("refusing to submit: the live composer is not nonempty and pending")

    _, state = submit_and_verify(args.socket, args.target)
    print(f"VERIFIED state={state}; read page 0 and wait for the response before sending again")


def command_resend_pending(args: argparse.Namespace) -> None:
    before = snapshot(args.socket, args.target)
    if pane_state(before) != "pending":
        print(numbered_page(before, 0, min(args.lines, 100)), file=sys.stderr)
        raise SystemExit("refusing to resend: the live composer is not nonempty and pending")
    message = composer_message(before)
    if not message:
        raise SystemExit("could not extract pending composer text")

    cleared, _ = clear_pending(
        args.socket,
        args.target,
        message_sha256(message),
        args.lines,
    )
    send_with_receipt(args, message, cleared)


def clear_pending(
    socket: str,
    target: str,
    expected_sha256: str,
    lines: int,
) -> tuple[list[str], str]:
    before = snapshot(socket, target)
    if pane_state(before) != "pending":
        print(numbered_page(before, 0, min(lines, 100)), file=sys.stderr)
        raise SystemExit("refusing to clear: the live composer is not nonempty and pending")
    message = composer_message(before)
    if not message:
        raise SystemExit("could not extract pending composer text")
    actual_sha256 = message_sha256(message)
    if actual_sha256 != expected_sha256:
        print(numbered_page(before, 0, min(lines, 100)), file=sys.stderr)
        raise SystemExit(
            f"refusing to clear: pending sha256 is {actual_sha256}, not {expected_sha256}"
        )

    # Ctrl-J can temporarily hide a draft and restore it after the next response. Ctrl-C
    # cancels Claude Code's live composer. Require a continuously empty composer before
    # claiming the draft is gone so delayed restoration cannot be mistaken for success.
    tmux(socket, "send-keys", "-t", target, "C-c")
    deadline = time.monotonic() + max(5.0, IDLE_SETTLE_SECONDS + 2.0)
    idle_since: float | None = None
    cleared = before
    while time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        cleared = snapshot(socket, target)
        if idle_composer_is_empty(cleared):
            now = time.monotonic()
            if idle_since is None:
                idle_since = now
            if now - idle_since >= IDLE_SETTLE_SECONDS:
                return cleared, message
            continue

        idle_since = None
        if pane_state(cleared) == "pending":
            current_message = composer_message(cleared)
            if current_message and message_sha256(current_message) != actual_sha256:
                print(numbered_page(cleared, 0, min(lines, 100)), file=sys.stderr)
                raise SystemExit("pending composer changed while clearing")

    print(numbered_page(cleared, 0, min(lines, 100)), file=sys.stderr)
    raise SystemExit(
        "pending composer did not remain cleared for the required stable interval"
    )


def command_discard_pending(args: argparse.Namespace) -> None:
    _, message = clear_pending(
        args.socket,
        args.target,
        args.expected_sha256,
        args.lines,
    )
    print(
        f"DISCARDED pending_sha256={message_sha256(message)} "
        f"characters={len(message)} state=idle"
    )


def command_replace_pending(args: argparse.Namespace) -> None:
    replacement = sys.stdin.read().strip()
    if not replacement:
        raise SystemExit("replace-pending requires a non-empty replacement on stdin")
    cleared, discarded = clear_pending(
        args.socket,
        args.target,
        args.expected_sha256,
        args.lines,
    )
    print(
        f"DISCARDED pending_sha256={message_sha256(discarded)} "
        f"characters={len(discarded)} state=idle",
        flush=True,
    )
    send_with_receipt(args, replacement, cleared)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument("--socket", required=True, help="tmux socket path")
    root.add_argument("--target", required=True, help="session:window.pane target")
    sub = root.add_subparsers(dest="command", required=True)

    page = sub.add_parser("page", help="read a bottom-relative page")
    page.add_argument("--page", type=int, default=0)
    page.add_argument("--lines", type=int, default=120)
    page.set_defaults(run=command_page)

    find = sub.add_parser("find", help="search the full snapshot")
    find.add_argument("--pattern", required=True)
    find.add_argument("--context", type=int, default=3)
    find.add_argument("--ignore-case", action=argparse.BooleanOptionalAction, default=True)
    find.set_defaults(run=command_find)

    state = sub.add_parser("state", help="show pane identity, idle state, and latest page")
    state.add_argument("--lines", type=int, default=80)
    state.set_defaults(run=command_state)

    send = sub.add_parser("send", help="send stdin and require an acknowledgement")
    send.add_argument("--receipt", required=True)
    send.add_argument("--timeout", type=float, default=120)
    send.add_argument("--lines", type=int, default=100)
    send.set_defaults(run=command_send)

    send_user = sub.add_parser(
        "send-user",
        help="submit exact human-composed stdin and prove it left the composer",
    )
    send_user.add_argument("--lines", type=int, default=100)
    send_user.set_defaults(run=command_send_user)

    submit = sub.add_parser("submit", help="submit text already waiting in a nonempty composer")
    submit.add_argument("--timeout", type=float, default=10)
    submit.add_argument("--lines", type=int, default=100)
    submit.set_defaults(run=command_submit)

    resend = sub.add_parser("resend-pending", help="extract pending text and resend it through the verified path")
    resend.add_argument("--receipt", required=True)
    resend.add_argument("--timeout", type=float, default=120)
    resend.add_argument("--lines", type=int, default=100)
    resend.set_defaults(run=command_resend_pending)

    discard = sub.add_parser(
        "discard-pending",
        help="clear one exact stale pending composer without submitting it",
    )
    discard.add_argument("--expected-sha256", required=True)
    discard.add_argument("--lines", type=int, default=100)
    discard.set_defaults(run=command_discard_pending)

    replace = sub.add_parser(
        "replace-pending",
        help="clear one exact stale composer, then send stdin with acknowledgement",
    )
    replace.add_argument("--expected-sha256", required=True)
    replace.add_argument("--receipt", required=True)
    replace.add_argument("--timeout", type=float, default=120)
    replace.add_argument("--lines", type=int, default=100)
    replace.set_defaults(run=command_replace_pending)
    return root


def main() -> None:
    args = parser().parse_args()
    if getattr(args, "page", 0) < 0 or getattr(args, "lines", 1) <= 0:
        raise SystemExit("page must be nonnegative and lines must be positive")
    args.run(args)


if __name__ == "__main__":
    main()
