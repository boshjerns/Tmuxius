#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
install_prefix="${PREFIX:-$HOME/.local}"

command -v python3 >/dev/null || { printf 'Python 3.10+ is required.\n' >&2; exit 1; }
python3 -c 'import curses, sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'
command -v tmux >/dev/null || { printf 'Install tmux first.\n' >&2; exit 1; }

install -d "$install_prefix/bin" "$install_prefix/share/tmuxius"
install -m 0755 "$project_dir/tmuxius" "$install_prefix/bin/tmuxius"
install -m 0755 "$project_dir/tmuxius-mouse" "$install_prefix/bin/tmuxius-mouse"
install -m 0644 "$project_dir/lib/tmux_communication.py" \
  "$install_prefix/share/tmuxius/tmux_communication.py"
install -m 0644 "$project_dir/LICENSE" "$install_prefix/share/tmuxius/LICENSE"
printf 'Installed Tmuxius in %s/bin/tmuxius\n' "$install_prefix"
printf 'Ensure %s/bin is on your PATH, then run tmuxius.\n' "$install_prefix"
