# Contributing

Relay is an early prototype. Read the [README](README.md) and [architecture](docs/ARCHITECTURE.md) before proposing changes.

## Local development

Use Python 3.10+ and Git in a POSIX environment. macOS is the primary environment; Windows is not supported. Node.js is optional for the JavaScript syntax check. No third-party Python packages are required.

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile server.py
node --check static/app.js
python3 server.py --open
```

Use `npm run dev` or `python3 dev.py` for automatic Python restarts and browser refresh. No npm install is required. The dev supervisor waits for active tasks to finish before restarting. If running `python3 server.py` directly instead, restart it after Python changes and reload after frontend changes. Stop the existing instance before launching another against the same data folder. The scripted example is useful for UI checks but does not verify real agent integration.

## Changes and validation

- Keep changes focused and describe their user-visible behavior.
- Add regression coverage for workflow, process, persistence, or API bugs. Avoid tests that only repeat implementation details.
- Provider parser changes should include representative, sanitized event fixtures and failure cases. Never add private production transcripts.
- Check folder dialogs, form validation, keyboard focus, narrow layouts, and status labels when changing the interface.
- Report tests actually run. Label simulations, fake-process tests, and real provider runs distinctly.
- Do not add approval-bypass flags or imply that prompt instructions enforce OS-level security.

For a real integration report, use a disposable Git repository, record the Python/CLI versions and OS, describe the task and exact results, and verify that a reviewer examined actual changed files. Do not run live model calls as part of ordinary automated tests.

## Data and publication

`data/` holds saved folder paths, prompts, code, logs, and task worktrees. It must remain untracked. Also keep account credentials and `.env` files out of commits. Review Git's staged file list before publishing. Ignore rules do not remove already tracked files.

Do not delete or prune task worktrees that contain work someone needs. For bug reports, share minimal reproductions and redact personal paths, code, account details, and tokens.

A distribution license has not yet been selected. The project owner should select and add one before inviting contributions under an open-source license; do not assume a license from this file.
