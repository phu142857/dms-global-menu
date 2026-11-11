# DMS Global Menu Bridge for VS Code

This companion extension exposes a local Unix socket so the DMS Global Menu
plugin can execute VS Code and Cursor commands. It does not use the network,
collect telemetry, or read editor contents.

After installing the VSIX, run **Developer: Reload Window** once. The bridge
creates a per-editor Unix socket under `$XDG_RUNTIME_DIR`; only VS Code command
identifiers are accepted.
