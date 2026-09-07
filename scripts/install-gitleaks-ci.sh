#!/usr/bin/env bash
set -euo pipefail
# Verified release archive; isolated CI install, never part of the app installer.
scan_dir="$(mktemp -d)"
trap 'rm -rf -- "$scan_dir"' EXIT
curl --fail --silent --show-error --location \
  https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz \
  --output "$scan_dir/gitleaks.tar.gz"
printf '%s  %s\n' 551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb \
  "$scan_dir/gitleaks.tar.gz" | sha256sum --check
tar -xzf "$scan_dir/gitleaks.tar.gz" -C "$scan_dir" gitleaks
install -m 0755 "$scan_dir/gitleaks" "$RUNNER_TEMP/gitleaks"
printf '%s\n' "$RUNNER_TEMP" >> "$GITHUB_PATH"
