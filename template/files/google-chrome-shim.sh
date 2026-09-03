#!/usr/bin/env bash
# PATH shim installed at /usr/local/bin/google-chrome (shadows /usr/bin).
#
# OSWorld task configs launch `google-chrome --remote-debugging-port=1337`
# bare. Two stock-Chrome behaviors break that through E2B's ingress path:
#   - Chrome >=136 silently disables the remote debugging port when running
#     on the default profile dir; a non-default --user-data-dir re-enables it.
#   - The CDP WebSocket upgrade rejects cross-origin connects without
#     --remote-allow-origins (the connect arrives via the public ingress).
#   - An empty GNOME login keyring prompts for a new password on first launch.
#     The reference benchmark must start without an agent-blocking modal.
# Add a debug port and both compatibility flags on every launch path. This is
# important because a user can close Chrome and relaunch it from the GNOME app
# menu; that launch must remain reachable by OSWorld's CDP getters too.
#
# Passing the default dir explicitly does NOT re-enable the port (probed on
# Chrome 150), so a separate dir is required. The template symlinks
# ~/.config/google-chrome -> google-chrome-cdp so OSWorld's profile-file
# getters (bookmarks, history, enable_do_not_track, ...) still read the
# profile Chrome actually uses.
args=("$@")
[[ "$*" != *"--remote-debugging-port"* ]] && args+=("--remote-debugging-port=1337")
[[ "$*" != *"--remote-allow-origins"* ]] && args+=("--remote-allow-origins=*")
[[ "$*" != *"--user-data-dir"* ]] && args+=("--user-data-dir=/home/user/.config/google-chrome-cdp")
[[ "$*" != *"--password-store"* ]] && args+=("--password-store=basic")
[[ "$*" != *"--no-first-run"* ]] && args+=("--no-first-run")
[[ "$*" != *"--no-default-browser-check"* ]] && args+=("--no-default-browser-check")
exec /usr/bin/google-chrome-stable "${args[@]}"
