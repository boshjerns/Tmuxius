from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import types
import unittest
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "lib" / "tmux_communication.py"
SPEC = importlib.util.spec_from_file_location("tmux_communication", SCRIPT)
assert SPEC and SPEC.loader
TMUX_COMMUNICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TMUX_COMMUNICATION)


def framed(message: str = "") -> list[str]:
    return [
        "prior transcript",
        "────────────────────────────────────────",
        f"❯ {message}",
        "────────────────────────────────────────",
        "footer",
    ]


def framed_dim_suggestion(message: str) -> list[str]:
    return [
        "prior transcript",
        "\x1b[38;5;244m────────────────────────────────────────\x1b[0m",
        f"\x1b[39m❯ \x1b[2m{message}\x1b[0m",
        "\x1b[38;5;244m────────────────────────────────────────\x1b[0m",
        "footer",
    ]


def codex_busy_composer(message: str, *, dim: bool = False) -> list[str]:
    rendered = f"\x1b[2m{message}\x1b[0m" if dim else message
    return [
        "prior transcript",
        "Working (12s • esc to interrupt)",
        "",
        f"› {rendered}",
        "",
        "  tab to queue message                         92% context left",
    ]


def codex_slash_popup(command: str) -> list[str]:
    return [
        "prior transcript",
        "",
        f"› {command}",
        "",
        f"  {command}  matching command description",
        "",
    ]


class TmuxCommunicationTests(unittest.TestCase):
    def test_every_read_loudly_reports_unsent_composer(self) -> None:
        lines = framed("begin rewards now")
        banner = TMUX_COMMUNICATION.pane_state_banner(lines)
        self.assertIn("ACTION_REQUIRED", banner)
        self.assertIn("UNSENT_COMPOSER=true", banner)
        self.assertIn(
            TMUX_COMMUNICATION.message_sha256("begin rewards now"),
            banner,
        )

    def test_page_includes_composer_state_before_transcript(self) -> None:
        args = types.SimpleNamespace(socket="socket", target="target", page=0, lines=20)
        output = io.StringIO()
        with mock.patch.object(TMUX_COMMUNICATION, "snapshot", return_value=framed()), \
             contextlib.redirect_stdout(output):
            TMUX_COMMUNICATION.command_page(args)
        self.assertTrue(output.getvalue().startswith("PANE_STATE state=idle"))

    def test_read_commands_fail_closed_on_unsent_composer(self) -> None:
        args = types.SimpleNamespace(socket="socket", target="target", page=0, lines=20)
        output = io.StringIO()
        with mock.patch.object(
            TMUX_COMMUNICATION,
            "snapshot",
            return_value=framed("this was typed but not sent"),
        ), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                TMUX_COMMUNICATION.command_page(args)
        self.assertEqual(raised.exception.code, 3)
        self.assertIn("UNSENT_COMPOSER=true", output.getvalue())

    def test_state_fails_closed_and_puts_action_first(self) -> None:
        args = types.SimpleNamespace(socket="socket", target="target", lines=20)
        output = io.StringIO()
        with mock.patch.object(
            TMUX_COMMUNICATION,
            "snapshot",
            return_value=framed("still waiting"),
        ), mock.patch.object(
            TMUX_COMMUNICATION,
            "tmux",
            return_value="pane=%0 tty=/dev/pts/14",
        ), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                TMUX_COMMUNICATION.command_state(args)
        self.assertEqual(raised.exception.code, 3)
        self.assertTrue(output.getvalue().startswith("ACTION_REQUIRED"))

    def test_long_pending_composer_is_not_lost_outside_short_tail(self) -> None:
        message_lines = [f"line {index}" for index in range(220)]
        lines = [
            "prior transcript",
            "────────────────────────────────────────",
            f"❯ {message_lines[0]}",
            *message_lines[1:],
            "────────────────────────────────────────",
            "footer",
        ]
        self.assertEqual(TMUX_COMMUNICATION.pane_state(lines), "pending")
        self.assertEqual(
            TMUX_COMMUNICATION.composer_message(lines),
            "\n".join(message_lines),
        )

    def test_dim_history_suggestion_is_idle_not_unsent(self) -> None:
        lines = framed_dim_suggestion("report the hash and files")
        self.assertEqual(TMUX_COMMUNICATION.pane_state(lines), "idle")
        self.assertIsNone(TMUX_COMMUNICATION.composer_message(lines))
        self.assertIn(
            "composer is empty and ready",
            TMUX_COMMUNICATION.pane_state_banner(lines),
        )

    def test_codex_slash_popup_is_an_exact_pending_composer(self) -> None:
        lines = codex_slash_popup("/fast")
        self.assertEqual(TMUX_COMMUNICATION.pane_state(lines), "pending")
        self.assertEqual(TMUX_COMMUNICATION.composer_message(lines), "/fast")

    def test_busy_codex_follow_up_outranks_activity_state(self) -> None:
        idle_busy = codex_busy_composer("Explain this codebase", dim=True)
        pending_busy = codex_busy_composer(
            "human steering that should queue now"
        )
        self.assertEqual(TMUX_COMMUNICATION.pane_state(idle_busy), "busy")
        self.assertEqual(TMUX_COMMUNICATION.pane_state(pending_busy), "pending")
        self.assertEqual(
            TMUX_COMMUNICATION.composer_message(pending_busy),
            "human steering that should queue now",
        )

    def test_visual_wrap_whitespace_matches_exact_buffer(self) -> None:
        observed = "a long exact human message that\n  wraps in the Codex composer"
        expected = "a long exact human message that wraps in the Codex composer"
        self.assertTrue(
            TMUX_COMMUNICATION.composer_text_matches(observed, expected)
        )
        self.assertFalse(
            TMUX_COMMUNICATION.composer_text_matches(observed, expected + " changed")
        )

    def test_send_user_accepts_explicit_human_steering_while_busy(self) -> None:
        message = "human steering while Codex is busy"
        before = codex_busy_composer("Explain this codebase", dim=True)
        loaded = codex_busy_composer(message)
        calls: list[tuple[str, ...]] = []

        def fake_tmux(
            _socket: str,
            *command: str,
            input_text: str | None = None,
        ) -> str:
            calls.append(command)
            if command and command[0] == "show-buffer":
                return message
            return ""

        args = types.SimpleNamespace(socket="socket", target="target", lines=20)
        output = io.StringIO()
        with mock.patch.object(TMUX_COMMUNICATION.sys, "stdin", io.StringIO(message)), \
             mock.patch.object(TMUX_COMMUNICATION, "snapshot", return_value=before), \
             mock.patch.object(TMUX_COMMUNICATION, "tmux", side_effect=fake_tmux), \
             mock.patch.object(
                 TMUX_COMMUNICATION,
                 "wait_for_loaded_composer",
                 return_value=(loaded, message),
             ), \
             mock.patch.object(
                 TMUX_COMMUNICATION,
                 "submit_and_verify",
                 return_value=(before, "busy"),
             ), \
             contextlib.redirect_stdout(output):
            TMUX_COMMUNICATION.command_send_user(args)

        self.assertIn("steered_while_busy=true", output.getvalue())
        self.assertNotIn(("send-keys", "-t", "target", "C-u"), calls)
        self.assertTrue(any(call and call[0] == "paste-buffer" for call in calls))

    def test_send_user_types_bare_slash_command_outside_paste_burst_window(self) -> None:
        message = "/fast"
        before = framed()
        loaded = framed(message)
        calls: list[tuple[str, ...]] = []

        def fake_tmux(
            _socket: str,
            *command: str,
            input_text: str | None = None,
        ) -> str:
            calls.append(command)
            if command and command[0] == "show-buffer":
                return message
            return ""

        args = types.SimpleNamespace(socket="socket", target="target", lines=20)
        output = io.StringIO()
        with mock.patch.object(TMUX_COMMUNICATION.sys, "stdin", io.StringIO(message)), \
             mock.patch.object(TMUX_COMMUNICATION, "snapshot", return_value=before), \
             mock.patch.object(TMUX_COMMUNICATION, "tmux", side_effect=fake_tmux), \
             mock.patch.object(
                 TMUX_COMMUNICATION,
                 "wait_for_loaded_composer",
                 return_value=(loaded, message),
             ), \
             mock.patch.object(
                 TMUX_COMMUNICATION,
                 "submit_and_verify",
                 return_value=(before, "idle"),
             ), \
             mock.patch.object(TMUX_COMMUNICATION.time, "sleep") as sleep, \
             contextlib.redirect_stdout(output):
            TMUX_COMMUNICATION.command_send_user(args)

        literal_keys = [
            call[-1]
            for call in calls
            if call[:4] == ("send-keys", "-l", "-t", "target")
        ]
        self.assertEqual(literal_keys, list(message))
        self.assertFalse(any(call and call[0] == "paste-buffer" for call in calls))
        self.assertEqual(
            sleep.call_args_list[: len(message)],
            [
                mock.call(TMUX_COMMUNICATION.LITERAL_SLASH_KEY_INTERVAL_SECONDS)
                for _ in message
            ],
        )
        self.assertIn("USER_MESSAGE_SUBMITTED", output.getvalue())

    def test_send_user_keeps_slash_command_with_args_as_exact_bracketed_paste(self) -> None:
        message = "/rename working title"
        before = framed()
        loaded = framed(message)
        calls: list[tuple[str, ...]] = []

        def fake_tmux(
            _socket: str,
            *command: str,
            input_text: str | None = None,
        ) -> str:
            calls.append(command)
            if command and command[0] == "show-buffer":
                return message
            return ""

        args = types.SimpleNamespace(socket="socket", target="target", lines=20)
        with mock.patch.object(TMUX_COMMUNICATION.sys, "stdin", io.StringIO(message)), \
             mock.patch.object(TMUX_COMMUNICATION, "snapshot", return_value=before), \
             mock.patch.object(TMUX_COMMUNICATION, "tmux", side_effect=fake_tmux), \
             mock.patch.object(
                 TMUX_COMMUNICATION,
                 "wait_for_loaded_composer",
                 return_value=(loaded, message),
             ), \
             mock.patch.object(
                 TMUX_COMMUNICATION,
                 "submit_and_verify",
                 return_value=(before, "idle"),
             ), \
             mock.patch.object(TMUX_COMMUNICATION.time, "sleep"), \
             contextlib.redirect_stdout(io.StringIO()):
            TMUX_COMMUNICATION.command_send_user(args)

        self.assertTrue(any(call and call[0] == "paste-buffer" for call in calls))
        self.assertFalse(
            any(call[:2] == ("send-keys", "-l") for call in calls)
        )

    def test_send_user_recovers_exact_pending_message_while_busy(self) -> None:
        message = "exact pending dashboard message"
        pending = codex_busy_composer(message)
        args = types.SimpleNamespace(socket="socket", target="target", lines=20)
        output = io.StringIO()
        with mock.patch.object(TMUX_COMMUNICATION.sys, "stdin", io.StringIO(message)), \
             mock.patch.object(TMUX_COMMUNICATION, "snapshot", return_value=pending), \
             mock.patch.object(
                 TMUX_COMMUNICATION,
                 "submit_and_verify",
                 return_value=(codex_busy_composer("", dim=True), "busy"),
             ) as submit, \
             contextlib.redirect_stdout(output):
            TMUX_COMMUNICATION.command_send_user(args)

        submit.assert_called_once_with(
            "socket",
            "target",
            expected_composer=message,
        )
        self.assertIn("recovered_pending=true", output.getvalue())
        self.assertIn("steered_while_busy=true", output.getvalue())

    def test_receipt_waits_for_idle_empty_composer(self) -> None:
        args = types.SimpleNamespace(
            socket="socket",
            target="target",
            receipt="receipt-settle",
            timeout=2,
            lines=20,
        )
        before = framed()
        pending = framed("payload\n\nReply with exactly TMUX_ACK:receipt-settle when this message is received.")
        busy = ["request TMUX_ACK:receipt-settle", "response TMUX_ACK:receipt-settle", "Computing…"]
        idle = ["request TMUX_ACK:receipt-settle", "response TMUX_ACK:receipt-settle", *framed()]
        payload = (
            "payload\n\n"
            "Reply with exactly TMUX_ACK:receipt-settle when this message is received."
        )

        def fake_tmux(
            _socket: str,
            *command: str,
            input_text: str | None = None,
        ) -> str:
            if command and command[0] == "show-buffer":
                return payload
            return ""

        with mock.patch.object(TMUX_COMMUNICATION, "tmux", side_effect=fake_tmux), \
             mock.patch.object(
                 TMUX_COMMUNICATION,
                 "wait_for_loaded_composer",
                 return_value=(pending, TMUX_COMMUNICATION.composer_message(pending)),
             ), \
             mock.patch.object(TMUX_COMMUNICATION, "submit_and_verify"), \
             mock.patch.object(
                 TMUX_COMMUNICATION,
                 "snapshot",
                 side_effect=[busy, idle],
             ), \
             mock.patch.object(TMUX_COMMUNICATION.time, "sleep"), \
             mock.patch.object(TMUX_COMMUNICATION, "IDLE_SETTLE_SECONDS", 0.0):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                TMUX_COMMUNICATION.send_with_receipt(args, "payload", before)
        self.assertIn("state=idle composer=empty", output.getvalue())

    def test_clear_pending_uses_cancel_and_requires_stable_idle(self) -> None:
        pending = framed("unsent")
        idle = framed()
        calls: list[tuple[str, ...]] = []

        def fake_tmux(_socket: str, *command: str, input_text: str | None = None) -> str:
            calls.append(command)
            return ""

        with mock.patch.object(
            TMUX_COMMUNICATION,
            "snapshot",
            side_effect=[pending, idle],
        ), mock.patch.object(
            TMUX_COMMUNICATION,
            "tmux",
            side_effect=fake_tmux,
        ), mock.patch.object(
            TMUX_COMMUNICATION.time,
            "sleep",
        ), mock.patch.object(
            TMUX_COMMUNICATION,
            "IDLE_SETTLE_SECONDS",
            0.0,
        ):
            cleared, message = TMUX_COMMUNICATION.clear_pending(
                "socket",
                "target",
                TMUX_COMMUNICATION.message_sha256("unsent"),
                20,
            )
        self.assertEqual(message, "unsent")
        self.assertEqual(cleared, idle)
        self.assertIn(("send-keys", "-t", "target", "C-c"), calls)

    def test_send_recovers_identical_unsent_message(self) -> None:
        pending = framed("same message")
        idle = framed()
        args = types.SimpleNamespace(
            socket="socket",
            target="target",
            receipt="receipt-1",
            timeout=1,
            lines=20,
        )
        with mock.patch.object(TMUX_COMMUNICATION.sys, "stdin", io.StringIO("same message")), \
             mock.patch.object(TMUX_COMMUNICATION, "snapshot", return_value=pending), \
             mock.patch.object(
                 TMUX_COMMUNICATION,
                 "clear_pending",
                 return_value=(idle, "same message"),
             ) as clear_pending, \
             mock.patch.object(TMUX_COMMUNICATION, "send_with_receipt") as send:
            TMUX_COMMUNICATION.command_send(args)
        clear_pending.assert_called_once()
        send.assert_called_once_with(args, "same message", idle)

    def test_send_refuses_to_overwrite_different_unsent_message(self) -> None:
        args = types.SimpleNamespace(
            socket="socket",
            target="target",
            receipt="receipt-2",
            timeout=1,
            lines=20,
        )
        with mock.patch.object(TMUX_COMMUNICATION.sys, "stdin", io.StringIO("new message")), \
             mock.patch.object(
                 TMUX_COMMUNICATION,
                 "snapshot",
                 return_value=framed("different message"),
             ), \
             mock.patch.object(TMUX_COMMUNICATION, "send_with_receipt") as send:
            with self.assertRaisesRegex(SystemExit, "different unsent composer"):
                TMUX_COMMUNICATION.command_send(args)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
