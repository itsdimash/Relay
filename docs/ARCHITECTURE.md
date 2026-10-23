# Architecture

This document describes the implementation that exists today. Relay is a small single-process application, not a distributed agent platform.

## System boundary

```mermaid
flowchart TB
    UI[Browser: HTML / CSS / JavaScript] -->|HTTP JSON; poll every 1.2 s| HTTP[Threaded localhost server]
    HTTP --> Registry[Saved projects and folder browser]
    HTTP --> Runner[One active Run worker]
    Runner --> Claude[Claude Code subprocess: assigned role]
    Runner --> Codex[Codex subprocess: assigned role]
    Runner --> Git[Git: detached task worktree]
    Runner --> Storage[Local task state and logs]
    Registry --> Storage
    Claude --> ProviderA[Configured Claude provider]
    Codex --> ProviderB[Configured Codex provider]
```

The browser does not connect to model APIs directly. Python launches the installed CLIs and receives newline-delimited JSON output. The CLIs handle provider authentication, requests, account limits, and their own session persistence.

## Source layout and responsibilities

| File | Responsibility |
| --- | --- |
| `dev.py` | Development supervisor; watches Python app files, defers restart while busy, and starts server with `RELAY_DEV=1` |
| `package.json` | Dependency-free npm entry points for dev, start, and tests |
| `server.py` | Entry point, HTTP routing, project persistence, Git helpers, workflow, process control, and event parsing |
| `static/markdown.js` | Escaping-first Markdown subset renderer; raw HTML and non-HTTP(S) links disabled |
| `static/report.css` | Final report document typography, code blocks, and tables |
| `static/index.html` | Forms, saved-project dialogs, workflow controls, and task panels |
| `static/app.js` | API calls, polling, project selection, and DOM rendering |
| `static/sidebar.css` | Conversation navigation, search list, day groups, and action-menu styles |
| `static/style.css` | Layout, responsive styles, focus states, and dialogs |
| `static/relay.svg`, icon assets | Branding and browser icons |
| `tests/test_relay.py` | Standard-library unit and local HTTP tests |
| `Start.command` | macOS launcher; resolves its own directory and runs Python |
| `data/` | Private runtime data; excluded from Git |

`server.py` currently groups several responsibilities in one module. That keeps installation simple, but provider parsing, HTTP code, and workflow changes are coupled. The sections below describe logical boundaries, not separate packages already implemented.

## Workflow and contract

A `Run` owns its task metadata, cancellation event, handoff gate, process reference, and optional deadline.

1. Check installation and sign-in for providers used by the selected mode.
2. For Build & review, require a clean repository root and create a detached worktree from `HEAD`. Observe only and Plan only use the existing folder directly, without Git checks or worktree creation.
3. Ask the observer to inspect source and return observation notes and acceptance checks.
4. Wait for explicit user approval of the Observer’s plan, then ask the builder to implement, or address the previous review's findings, and report checks.
5. Capture the tracked diff and untracked file list.
6. Ask the reviewer to inspect the actual files and return a structured review.
7. Finish on approval, repeat for changes, or stop on a limit or failure.

`mode` is validated and saved per task; omitted mode defaults to `build` for compatibility. For `observe` and `plan`, only the Observer runs with read tools against the current selected folder (including uncommitted files, or a non-Git folder). Final diff capture is skipped for these tasks, so pre-existing changes are not attributed to the agent. Its report, findings, and acceptance checks are saved before finishing (`observing → done`). Plan mode requests proposed implementation steps; Observe mode requests current behavior and findings. `run_role` rejects Builder or Reviewer dispatch for these modes.

Reviews contain `status`, `summary`, `findings`, and `acceptance_checks`. Each finding has `id`, `file`, `problem`, `evidence`, and `requested_change`. The CLI receives a JSON Schema; Python also checks the essential fields. An approved review cannot contain findings. A `needs_changes` review must provide actionable findings. This checks the response shape, not the correctness of its claims.

States follow:

```text
queued → preparing → observing → awaiting_approval → building → reviewing
                                      ↑         |
                                      |    needs_changes
                                      |         ↓
                                      └────── fixing → reviewing

reviewing → done                  when approved
reviewing → needs_attention       when the round limit is exhausted
any running stage → stopped      on cancellation
any running stage → failed       on an error or deadline
unfinished saved run → interrupted on server restart
```

Pause is a handoff gate, not a separate state or a suspended OS process. It permits the current step to finish and blocks the next stage, including finalization. Deadline checks continue. `0` means unlimited for either rounds or minutes; the two limits are independent. The simulation uses scripted messages and never invokes either CLI.

## Concurrency and lifecycle

- `ThreadingHTTPServer` serves browser requests; a daemon worker runs each accepted task.
- The in-process `ACTIVE` reference permits one non-terminal task at a time.
- A nonblocking POSIX file lock on `data/.instance.lock` prevents two coordinator instances from sharing runtime storage, even on different ports. The OS releases the lock when the process exits; the lock file may remain.
- `RLock` guards shared snapshots and file writes. This is not a database transaction system; some worker metadata updates occur between snapshots.
- Agent processes use separate process groups. Reader threads drain stdout and stderr into a queue while a writer thread sends the prompt over stdin.
- Stop requests set a cancellation event and signal the current process group, then attempt escalation. Detached processes that create their own session are not guaranteed to be terminated.
- Initial version/auth checks and synchronous Git operations have their own timeouts. Cancellation and the task deadline are observed at the next cooperative check, not a hard wall-clock kill at every instruction.

Restart preserves records and marks unfinished tasks interrupted. It does not recover a live provider session or resume the state machine.

## Persistence and history

Project saves and state snapshots use a temporary file and replacement. Readable events append to `events.jsonl` and are also included in `state.json`. Raw captured CLI lines append to `provider-events.jsonl`; prompts and final builder reports are separate files.

`state.json` is the dashboard snapshot, not a durable transaction journal. A crash can leave its last snapshot behind the appended event log. Startup does not replay events. Finished chats can be moved to `data/trash/<task-id>/` and restored. A worker completion event blocks deletion while its final writes are pending. Deletion preserves the Git worktree and does not affect provider-side histories. No disk quota, permanent Trash purge, encryption, or automatic worktree cleanup exists.

Tracked diffs use `git diff HEAD`. New files are listed separately and remain in the working copy; they are not included in `changes.patch`. Large diff excerpts and builder reports are bounded in review prompts, and the reviewer is instructed to read the actual files. A history entry records results, not a reproducible proof that all checks succeeded.

Each step launches a fresh CLI session. Relay passes context explicitly through observations, findings, and builder reports. The coordinator does not resume a provider session or automatically combine CLI histories in desktop applications.

## HTTP surface

All routes require a recognized localhost Host header. Mutating POST requests require the per-process `X-Relay-Token`; an Origin header, if present, must match the local server. JSON bodies must be objects and are limited to 128,000 bytes to accommodate the task and three role-instruction fields.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/` and named static assets | Dashboard and icons; assets are allowlisted |
| GET | `/api/state` | All stored task snapshots and browser mutation token |
| GET | `/api/dev` | Dev-only revision and busy state; returns 404 outside dev mode |
| GET | `/api/models` | Provider model choices and effort metadata |
| GET | `/api/teams` | Built-in team and saved presets |
| POST | `/api/teams/save` | Validate and create/update a named preset |
| GET | `/api/connections` | CLI versions and sign-in checks |
| GET | `/api/projects` | Saved project entries and current folder existence |
| POST | `/api/projects/save` | Validate and save a name and folder |
| POST | `/api/projects/remove` | Remove an entry, preserving its files |
| POST | `/api/folders` | List visible subfolders of a local path; at most 500 entries |
| POST | `/api/history/delete`, `/api/history/restore` | Move a finished chat to local Trash, or restore it; worktree preserved |
| POST | `/api/run` | Validate options and create one task |
| POST | `/api/pause`, `/api/resume`, `/api/stop` | Control the specified active task |

The folder API can navigate folders accessible to the server's OS user. It is not confined to saved projects. The token and local binding protect the browser interface from unrelated websites; they are not an authorization boundary against local processes or a multi-user identity system.

## Agent permissions and trust

Claude uses restricted mode, `dontAsk`, and an empty strict MCP configuration. Its read roles receive only read tools; its builder also receives Edit, Write, and Bash. Explicitly allowed Bash execution does not impose an OS sandbox equivalent to Codex. Codex uses `read-only` for observer/reviewer and `workspace-write` for builder, with normal installed configuration. No bypass flags are supplied.

Git worktrees separate source edits but are not security sandboxes. Project content, dependency setup, Codex configuration, hooks, network access, and provider behavior remain trusted inputs. Publishing restrictions in prompts are instructions, not independently enforced command allowlists. Relay stores potentially private code in logs and sends relevant context to configured agent providers.

## Known design limits

1. **History cost grows with use.** Every activity event rewrites the full state snapshot, every poll returns every run with full event history, and the frontend rerenders the selected feed. Unlimited runs are supported logically but are not memory-, disk-, or bandwidth-bounded.
2. **No recovery protocol.** A stopped or interrupted run cannot resume automatically. A new build task starts from the source repository's committed `HEAD`, not a previous task worktree. Read-only tasks inspect the selected folder's current files.
3. **Provider coupling.** CLI flags and event formats may change. Current tests use fake processes; a real end-to-end compatibility check is required before a stable release.
4. **Review is not independent test execution.** Read roles inspect source; the assigned builder reports the checks it runs.
5. **Single-user POSIX scope.** No Windows process control, login system, hosted deployment, or concurrent task scheduling is implemented.
6. **Absolute paths.** Moving Relay or task worktrees can break saved metadata and Git worktree pointers.

## Recommended evolution

Extract modules when changing their respective responsibilities rather than performing a broad rewrite first:

```text
relay/
  workflow.py       # Run state machine and handoff policy
  providers.py      # Claude/Codex launch arguments and event decoding
  processes.py      # subprocess lifecycle, cancellation, deadlines
  storage.py        # projects, snapshots, and event persistence
  workspaces.py     # Git validation, worktree creation, and diffs
  http.py           # request validation and response routing
server.py           # small launcher
```

Before adding more agents or concurrent tasks, prioritize incremental event retrieval, interrupted-run recovery, explicit check records, provider session IDs, and live integration tests. The module tree above is a proposal, not the current source layout.

## Configurable teams

Team profiles are implemented for observer, builder, and reviewer. Each role stores `provider` (`claude` or `codex`), an optional `model`, an optional `effort`, and additional `instructions`. `validate_team` normalizes and copies these values; `Run.info.team` snapshots them when a task is created. `data/teams.json` stores named presets, while the current browser selection is remembered in local storage. The built-in default is returned separately and is not overwritten by preset saves.

`Run.run_role` dispatches by the selected provider. `provider_command` constructs the provider-specific arguments and role-specific capabilities. The existing event parser still branches on the provider name; it presents consistent agent/role message, tool, review, and error events to the dashboard. Codex read roles use `--output-schema` and parse the final output file, separately from progress messages. Claude read roles use structured JSON output. Both return the same review contract.

Claude builders receive Edit, Write, and Bash in addition to read tools; Claude read roles do not. Codex builders use `workspace-write`; Codex read roles use `read-only`. Additional instructions do not change the selected capability set. Model selection is forwarded as a single `--model` argument. Effort becomes `--effort` for Claude and a `model_reasoning_effort` configuration override for Codex. Empty settings omit the override, and older presets are normalized to empty effort. `/api/models` returns Claude aliases and visible Codex cache entries (or fallback models) with supported effort menus; hidden/internal entries are excluded. The cache is metadata, not a live account entitlement check; supported model names and account access are checked by the provider during execution, not discovered by Relay.

Only providers assigned to the team must pass preflight checks. The same tool may fill all three roles, but stages remain sequential and only one builder is active. Existing histories without a team snapshot remain readable. The scripted simulation always uses the built-in example team and is not provider validation.

Adding another provider still needs a command adapter, event decoding, result normalization, cancellation checks, and compatibility tests. Merely adding a dropdown option is insufficient. Credentials should remain in the provider’s supported local sign-in/configuration flow.


## Development reload

`npm run dev` invokes `python3 dev.py`; Node is only a command runner and is not a backend dependency. The supervisor watches Python source changes, excluding private runtime data, tests, dependency directories, and itself. It starts the existing server with `RELAY_DEV=1`, debounces source changes, checks `/api/dev`, and defers restart until the task worker has finished. It sends SIGINT for normal cleanup before starting a replacement process. Direct Ctrl+C stops the supervisor and child; it intentionally stops an active task too.

In development mode, `/api/state` includes revision/busy metadata. Revision combines a hash of static asset mtimes/sizes with the per-process token, so it changes on static edits or server restart. Browser polling reloads the page when revision changes and the server is idle, retaining task drafts in session storage. Static edits do not restart the backend. Outside development mode no automatic refresh is enabled. There is no ASGI/Uvicorn entry point.

## Report follow-ups and finding handoffs

`POST /api/followup` takes `source_id`, `task`, and optional `minutes`. It resolves a completed non-demo chat server-side, rejects a still-finalizing worker, forces `mode=observe`, and inherits the chat's Observer configuration. Prior questions and summaries become reference context. A new `Run` reuses the conversation id/folder and snapshots the prior turn into `info.turns`; `conversation_title` and `original_project` remain stable. The worker remains subject to the single-active-run lock. This is a fresh provider invocation, not provider-session resumption. Per-turn prompt and Codex result filenames avoid overwriting earlier artifacts. History deletion/restoration moves the complete conversation folder, including its saved turns.

`POST /api/run` can take `source_id` and `finding_indexes`. Indexes are validated against canonical saved findings; an empty/invalid selection is rejected. Only selected findings and their evidence enter the new task's context, and the project must match the source's original project. The frontend opens a draft first; it does not start work when findings are selected. A source snapshot is stored in `info.source`, and the context is saved in the task record. Context over 90,000 characters is rejected explicitly. A read-only follow-up without new findings leaves the most recent earlier findings available for handoff; earlier build diffs are displayed from the saved turn.

## Plan approval gate

Real build tasks call `wait_for_plan` after observation and enter `awaiting_approval`. `info.plan` snapshots the structured report with a generated plan id. A dedicated `approval_event` gates the first Builder invocation; `run_role` independently rejects Builder dispatch unless `approved_plan_id` matches the current plan. `/api/approve-plan` requires the normal request token/origin protections, the current live worker and waiting state, and the exact plan id. It persists the approval id and timestamp before releasing the event; stale and duplicate approvals are rejected. Pause/resume uses a separate event and cannot approve a plan. Stop interrupts the waiting worker. The deadline is suspended during the approval wait and shifted by elapsed waiting time afterward. Approval records are preserved in conversation turns when following up. Server restart retains the existing interrupted-task behavior; approval is never inferred on load.

## Change review and report summaries

Structured provider output now requests `overview`, `next_actions`, and a priority enum on each finding. `validate_review` accepts older reports without those fields but validates present values; the UI labels missing priorities Unrated and older summary text as an excerpt. The full report remains expandable. Metadata is preserved per conversation turn.

Build snapshots save `file_reviews`: per-file status, content, line counts, and preview notices. Git paths use NUL-separated output and rename detection is disabled for the per-file list. Tracked-file previews come from Git with external diff/text conversion disabled. New-file text reads are bounded, binary/invalid UTF-8 content is not rendered, and symlink or outside-workspace targets are not read. A 100,000 per-file/600,000 overall character budget bounds saved previews, with notices when content is omitted. `changes.patch` retains the original tracked patch behavior.

Each Builder round saves the complete report and extracts an optional fenced `relay-checks` JSON list. Only commands with passed/failed/not_run outcomes are shown as structured results; unsupported or malformed data never becomes an inferred passing check. `static/review.js` renders saved diff lines and report overview cards with escaping; `static/review.css` styles file navigation, diffs, priorities, and reported checks. No filesystem-read API is exposed by the viewer. Saved Builder reports and file reviews are included in conversation turn snapshots.

## Image attachments

`/api/run` and `/api/followup` accept `images: [{name, mime, data}]` where `data` is plain base64. Only those routes allow a 24 MiB request body; other mutation routes keep the 128,000-byte limit. Decoding validates base64, image header/MIME agreement, and 4 MiB per-image/4-image count limits before task construction. Header checks do not replace a full image decoder; corrupt content can still be rejected by the provider.

Saved bytes use generated hex ids and server-chosen extensions in the chat's `attachments/` directory. State includes metadata, never raw base64. Image reads reject invalid ids, symlinks, oversized saved files, and paths outside the chat. `/api/image?run=<id>&image=<id>` serves only a referenced image from a chat present in `RUNS`; there is no arbitrary local-path read endpoint. Standard loopback Host protections and image MIME/nosniff responses remain in effect. Images in Trash are unavailable through this route until restored.

Every role receives the saved reference set. Codex attaches paths via repeated `--image` flags with an explicit option terminator before the stdin prompt. Claude switches to `--input-format stream-json` only when images exist and sends one newline-terminated user message containing text and base64 image blocks. The launcher's optional `input_data` keeps the readable prompt separate from the multimodal input. No tool permissions or approval gates are expanded. Conversation turns preserve metadata; follow-ups retain images in place, while derived tasks copy image bytes to their own record.

The browser keeps unsent image data in memory, supports picker/drop/paste with bounded files, and clears accepted images only after a successful task request. Development reload defers while unsent images exist; manual reload discards them. The image-count limit includes inherited references. Tests cover request ingestion, native provider payloads, inheritance, path safety, and Trash/restore. Browser submission checks use scripted providers, not live models.
