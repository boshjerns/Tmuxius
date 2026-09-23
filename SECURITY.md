# Security and privacy

Tmuxius is a local terminal application. It has no network client, telemetry,
account system, or remote dashboard. It uses the permissions of the user who
launches it and connects to that user's tmux server or an explicit socket.

It reads pane output, process metadata, and (for Codex title enrichment) local
Codex SQLite thread metadata. It caches titles in a tmux pane option. Dashboard
drafts and parsed transcripts are held in process memory; it does not write
transcript logs. Submitting a message temporarily uses a named tmux paste buffer,
which the helper deletes in its cleanup path. A forcibly terminated process may
leave a temporary buffer or pasted draft behind. Agent behavior and any network
requests made by the agent are governed by that agent, not Tmuxius.

Treat the tmux server, socket, host user, installation files, and agents as
trusted. Anyone with access to the socket may already read or control its panes.
Tmuxius is not an isolation boundary. Terminal text is processed as text and
styling; it is not executed as shell commands. Message delivery invokes tmux
with argument lists rather than interpolated shell commands.

Message submission recognizes terminal layouts and checks for pending input.
This is a best-effort guard, not an atomic transaction with another process.
Avoid editing the agent's composer from another client while Tmuxius submits.
If delivery is ambiguous, inspect the pane before retrying. The dashboard only
sends text after you explicitly submit it.

## Sharing screenshots and examples

Heuristic filtering applies to workspace subjects and summaries. **Conversation
panels do not redact secrets.** Names, paths, customer details, source code, and
credentials may be visible in a live dashboard. Do not publish a real session
capture without reviewing every visible character.

The README uses an owner-provided real screenshot, with unrelated session
subjects and the lower conversation covered by opaque masks. Device chrome and
image metadata are removed. Pixels outside the masks are preserved; the image
is not a generated reconstruction. Never commit the unredacted original or its
metadata. New real screenshots require the owner's explicit direction and the
same review before upload.

Use `examples/demo.py` for fictional reproductions of UI issues. The example
disables real tmux access and message submission. Do not replace its data with
actual transcripts. The optional renderer writes to `local/demo-screenshots/`,
outside the published assets.

## Reporting a vulnerability

Use [GitHub's private vulnerability reporting](https://github.com/boshjerns/Tmuxius/security/advisories/new)
for a security-sensitive report. Do not put credentials, private transcripts,
socket paths from real deployments, or customer data in public issues.

## Maintainer publication checks

Keep development in this public source tree. Never copy private deployment
directories, configuration bundles, agent histories, or another repository's
Git history into it. Review the complete staged diff and file list before each
push. Run `scripts/check-publication.py` and a redacted Gitleaks scan before
publishing; the same checks run in CI. Enable the supplied local pre-push hook
with `git config core.hooksPath .githooks` to run them before uploading commits.

The file manifest rejects unexpected committed files; add intentional public
files explicitly and review their contents. Secret scanners cannot identify
every sensitive value, and CI runs after upload. Local checks and human review
are required before publication. Keep fixtures fictional and use public commit
identities. The reviewed screenshot exception above does not authorize runtime
logs, raw captures, or other private artifacts.
