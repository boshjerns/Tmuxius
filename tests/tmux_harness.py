"""A disposable terminal that renders the fictional demo through real tmux."""

import fcntl
import os
from pathlib import Path
import pty
import runpy
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parents[1]
HELPER = runpy.run_path(str(ROOT / "lib/tmux_communication.py"))


class DemoTerminal:
    def __init__(self, width=100, height=72, *demo_args):
        self.width, self.height = width, height
        self.temp = tempfile.TemporaryDirectory(prefix="tmuxius-test-")
        self.socket = str(Path(self.temp.name) / "socket")
        self.command = ["tmux", "-S", self.socket]
        self.env = os.environ.copy()
        for key in ("TMUX", "TMUX_PANE", "NO_COLOR"):
            self.env.pop(key, None)
        self.env["TERM"] = "xterm-256color"
        config = Path(self.temp.name) / "tmux.conf"
        config.write_text("set -g status off\nset -g default-terminal tmux-256color\n")
        subprocess.run(self.command + ["-f", str(config), "new-session", "-d", "-s", "demo",
                                      "-x", str(width), "-y", str(height),
                                      sys.executable, "-B", str(ROOT / "examples/demo.py"), *demo_args],
                       env=self.env, check=True, capture_output=True)
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", height, width, 0, 0))
        self.child = subprocess.Popen(self.command + ["attach-session", "-t", "demo"],
                                      stdin=slave, stdout=slave, stderr=slave,
                                      env=self.env, start_new_session=True)
        os.close(slave)
        self.wait_for(lambda: "TMUXIUS" in self.text(), "dashboard startup")

    def pump(self, seconds=0.12):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.master], [], [], 0.02)
            if ready:
                try:
                    os.read(self.master, 262144)
                except OSError:
                    break

    def snapshot(self):
        return HELPER["snapshot"](self.socket, "demo:0.0")[-self.height:]

    def text(self):
        return "\n".join(HELPER["visible_text"](line) for line in self.snapshot())

    def key(self, value):
        os.write(self.master, value.encode())
        self.pump(0.18)

    def wait_for(self, predicate, label, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump(0.08)
            if predicate():
                return
            if self.child.poll() is not None:
                break
        raise AssertionError(label + "\n" + self.text())

    def close(self):
        subprocess.run(self.command + ["kill-server"], capture_output=True, timeout=3)
        self.pump(0.1)
        if self.child.poll() is None:
            self.child.terminate()
        try:
            self.child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=3)
        os.close(self.master)
        self.temp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
