<div align="center">
  <img src="static/relay.svg" width="72" alt="Relay logo">
  <h1>Relay</h1>
  <p><strong>Your agents. One shared workflow. You approve the changes.</strong></p>
  <p>A local macOS workspace where Claude Code and Codex inspect, plan, build, and review software together.</p>

  <p>
    <a href="#install-the-macos-app"><strong>Download</strong></a> ·
    <a href="#how-it-works">How it works</a> ·
    <a href="#your-first-task">First task</a> ·
    <a href="#privacy-and-security">Privacy</a> ·
    <a href="#troubleshooting">Troubleshooting</a> ·
    <a href="https://relay-tau-eight.vercel.app/">Website</a>
  </p>

  <p>
    <img alt="Platform: macOS 13+" src="https://img.shields.io/badge/macOS-13%2B-225b4d">
    <img alt="Apple silicon" src="https://img.shields.io/badge/Apple%20silicon-arm64-225b4d">
    <img alt="Status: early prototype" src="https://img.shields.io/badge/status-early%20prototype-lightgrey">
    <img alt="Runs locally" src="https://img.shields.io/badge/runs-100%25%20local-225b4d">
  </p>
</div>

Relay coordinates the coding agents you already have installed. Give it a task, choose which agent does which job, approve the plan, and follow the build and review handoffs in one window.

- **Local.** Relay runs on your Mac and uses your existing Claude Code and Codex sign-ins. No Relay account, no Relay API key.
- **Approval first.** Nothing is edited until you approve the plan.
- **Your choice of team.** Put Claude Code or Codex in any role, pick models and effort, and save presets.

> **Early prototype · macOS first.** Automated tests and scripted browser checks cover the coordinator and its interfaces. A real Claude observation has been verified; a complete live multi-provider build/review cycle and live image understanding have not yet been verified in the development environment.

## Contents

- [Install the macOS app](#install-the-macos-app)
- [How it works](#how-it-works)
- [What you can do](#what-you-can-do)
- [Your first task](#your-first-task)
- [Task modes](#task-modes)
- [Working with Relay](#working-with-relay) (clarification, approval, teams, images, reports, reviewing changes, recovery, controls)
- [Privacy and security](#privacy-and-security)
- [Run from source](#run-from-source)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Current limits](#current-limits-and-next-steps)
- [License](#license)

## Install the macOS app

**You need:** an Apple silicon Mac on macOS 13 or newer, plus [Claude Code](https://code.claude.com), Codex CLI, or both, installed and signed in. [Git](https://git-scm.com) is required for build tasks.

1. **Download** `Relay-macOS-arm64.dmg` from the [latest release](https://github.com/itsdimash/Relay/releases/latest).
2. **Open the disk image** and drag **Relay** onto the **Applications** shortcut. (If you open Relay from Downloads instead, it offers to move itself to Applications.)
3. **Open it the first time through System Settings.** Relay is not yet signed with an Apple Developer ID or notarized, so macOS blocks the first launch.
   - Double-click **Relay**. When macOS warns about it, click **Done** (do not move it to the Trash).
   - Open **System Settings → Privacy & Security** and scroll to the bottom.
   - Next to the message that Relay was blocked, click **Open Anyway**, then confirm.
   - On macOS 14 and earlier you can instead Control-click Relay, choose **Open**, and confirm.

   You only need to do this once.
4. **Sign in to your agents** in Terminal, skipping any you will not use:

   ```sh
   claude auth login
   codex login
   ```

Relay opens in its own macOS window with the project picker, task composer, conversation history, plan approval, clarification, and handoff controls. Everything runs on your Mac. Click any role in **Your team** to choose its tool, model, and effort.

History and settings for the packaged app live in `~/Library/Application Support/Relay`.

> A `.zip` of the same app is attached to each release too. Prefer to build the app yourself? See [Releasing Relay](docs/RELEASING.md).

### Updates

The app checks this repository's latest GitHub Release when it opens. When a newer version exists, a banner offers **Update now**: Relay downloads the new app, verifies its checksum, replaces itself in Applications, and reopens. Pushing code to GitHub does not update installed apps; publishing a release (a `v*` tag) does. Relay must be in Applications, and it will not update while a task is running.

### Notch panel

Move the pointer to the notch and a small dark panel grows out of it, with icon tabs on both sides of the notch: **Music**, **Notes**, **Deliver** and **Task**. Each tab is its own view. It also opens by itself when a plan or questions need you, and briefly when a task finishes.

- **Double-tap the right Command key** (⌘) opens the **full panel** in any app and keeps it open. It adds a fourth tab, **Office**: the pixel-art room where the Observer, Builder and Reviewer pass work to each other. The room only appears here. Double-tap again, press Escape, or choose **View → Show or Hide Notch Panel** to close it. A Command shortcut such as ⌘C does not count.
- **Task:** the step of the task, the latest agent message, and **Approve** / **Reject** when a plan is waiting. A waiting plan opens the full panel and always switches back to the Task view, so you never miss an approval.
- **Task queue:** use **Save to task queue** in the dashboard to prepare another brief while agents work. Each brief keeps its project, team settings, mode, limits, images, and selected-finding context. The dashboard lets you reorder or remove up to 20 waiting tasks. **Next** in Task and Office expands the next brief; **Start task** explicitly starts it after the current worker finishes. Restarting Relay or finishing another task never starts the queue automatically. Build tasks still wait for plan approval. Queue metadata lives in `queue.json`, with private payloads in `queue/`; removed briefs are moved to `queue/removed/`.
- **Recent activity:** expand this in Task or Office to see the latest 12 saved events for the displayed task, with the agent, role, and timestamp. Repeated updates are folded together and raw tool calls are omitted. The activity area scrolls independently so the status and Office usage indicators stay visible.
- **Music:** whatever is playing on your Mac: Apple Music, Spotify, YouTube in Chrome, Yandex Music, anything that appears in Control Center. The view shows the cover, title, artist, a progress bar with the time played and left, and previous, play/pause and next. When a **new track starts**, the notch grows into a small pill with the cover, title, artist and a moving equalizer, then retracts after a few seconds. Move the pointer onto the pill to open the Music view. It reads the system's Now Playing information through the bundled [MediaRemoteAdapter](third_party/mediaremote-adapter/SOURCE.txt) (BSD 3-Clause), which relies on a private Apple interface. If a future macOS update breaks it, music simply does not show and nothing else is affected. No permission prompt is needed.
- **Deliver:** a shelf for files you need to move from one place to another, so you stop copying them by hand. **Drag files toward the notch** (from Finder, or from the Downloads stack): the panel opens by itself on Deliver, and you drop them on it. Later, open the panel (it comes back to the tab you used last), then **drag a row out** into the page, mail or folder where the file is needed, or press **Drag all** to carry every file in one move. To carry only some, **click** a file to select it, **⌘-click** to add or remove one, or **⇧-click** to select a range; dragging any selected file carries them all. Files are never copied: Deliver remembers only where they are (in `deliver.json` in Relay's data folder), so a file you moved or deleted shows greyed out as *missing*. Dropping a row in Finder behaves like dragging the file there yourself (it moves on the same disk, and ⌥ copies it). The **×** on a row takes it off the shelf without touching the file, and **Clear** empties the shelf. Files you moved with the drop (a move in Finder) leave the shelf by themselves. **Auto-clear** also takes copied files off the shelf once they are dropped somewhere (off by default; the choice is kept in `deliver-settings.json`). **Auto-catch** puts each new download from your `~/Downloads` folder on the shelf by itself (off by default). Relay looks at the folder every couple of seconds and takes a file once it has stopped changing, so a download that is still arriving (`.crdownload`, `.download`, `.part`) and hidden files are skipped; files already there when you switch it on, folders, and anything you took off the shelf are left alone, and files that arrive while Relay is closed are not caught. The first time, macOS may ask to let Relay open your Downloads folder; if you said no, the panel tells you where to allow it (System Settings › Privacy & Security › Files & Folders). **Zip** packs the files you picked (or all of them when none is picked, folders included) into one `.zip` that appears on the shelf, ready to drag out as a single file; the originals stay where they are, and the zip, which lives in Relay's data folder, is deleted when you take it off the shelf. The **sliders** button next to it folds out the shelf's options: **Auto-catch**, **Auto-clear**, and **Keep**, which takes items off the shelf by themselves once they have been there for 1 hour, 6 hours, 1 day or 1 week (click it to step through the choices; the files themselves are never deleted, only the shelf entry). The shelf holds up to 100 items.
- **Notes:** quick notes and to-dos. Click the field, type, and press **Enter** to save a note, or **⌘ Enter** to save a to-do you can tick off. The panel stays open while you type, and Escape closes it. Notes are saved in `notes.json` in Relay's data folder.
- **Motion:** while agents work, a soft light in the working agent's colour pours down from the notch, a bright thread runs under the tabs, and the Task tab and the room glow. While music plays, the light takes the colour of the cover, the cover breathes, an equalizer moves, and in the Office the agents put on headphones, nod to the beat and send up little notes. Even with the panel closed, the notch itself comes alive: a halo breathes around it and bright sparks run around its edge. While music plays it takes the cover's colour; while agents work it takes the working agent's colour, with three sparks (one per agent, the one with the baton longest). A new track or a new agent taking over sends a ripple of light out. It only appears on Macs with a notch, never takes mouse clicks, and agents take priority over music. Reduced-motion settings turn all of it off. The Music view also shows which app the sound comes from, with its icon.
- **Office:** the full panel's room is larger (the panel grows to about 780 pixels wide) and redrawn in more detail. Its window follows your real time of day (sun, moon, stars, clouds, city lights), a wall clock shows the time, the picture becomes the music level meter while music plays, and a whiteboard fills with checks as the Reviewer works. Each agent has its own desk, monitor and props; the baton glows as work passes between them, and the door sign turns green, red or amber for finished, failed or needs-you. In **Auto mode** a neon AUTO sign flickers on the wall. If you are needed, the Observer walks to the door and calls you.
- **Notifications:** the panel announces what happens with a small animated card that slides in under the notch: a task starting, a plan waiting for approval, a question for you, the plan being approved, a decision needed, a retry countdown, an Auto-mode decision, a failure, and a finished task with a burst of confetti. The panel edge also flashes in the matching colour, and the Task tab breathes while something needs you. The Office reacts too (sparks on a retry, confetti on approval). Reduced-motion settings replace the movement with a plain fade. The native panel size constants changed (`FullWidth` 780, `FullBodyHeight` 312), so rebuild the app to see the larger room.
- **View → Open Notch Panel from Screen Top** turns the hover trigger off and on.
- While it is on, closing the main window leaves Relay running so the panel keeps working; click the Dock icon to bring the window back, or press Command-Q to quit.
- The panel is a page served by the local engine at `/notch`, so you can also open `http://127.0.0.1:48765/notch` in a browser.

### Usage left

Relay shows how much of your 5-hour and weekly limits is left for each tool, in the dashboard (under the connection badges) and in the notch panel's Office. Claude Code only reports it while answering, so Relay takes the reading from its own Claude tasks and, when none is recent, asks Claude one tiny question (the cheapest model, no tools, an empty folder) at most every 15 minutes. That question counts against your Claude usage, and if your 5-hour window was not running it starts a new one. Set `RELAY_NO_CLAUDE_PROBE=1` to turn it off. Readings are kept between launches. Codex is asked through its app-server about once a minute. Both exist only on subscription sign-ins; with an API key the row stays empty. A reading older than 30 minutes shows its age.

### Provider logos

The Claude and OpenAI (Codex) logos appear in the agent avatars on the Team cards and in the activity feed. They are the files `static/providers/claude.png` and `static/providers/openai.png`. To replace them, put `claude.svg` / `openai.svg` (or new `.png` files) in the same folder; an SVG takes priority over a PNG. If a file is missing, the avatar falls back to the letters "Cl" or "Cx". See `static/providers/README.md`.

### Connect your own accounts

Relay uses the authentication already configured in your installed CLIs. It does not provide shared accounts, ask you to upload credentials, or require a separate Relay API key. Model access, provider configuration, billing, and usage limits remain those of your tools and accounts.

Open **Agent connections** in Relay to check installation and sign-in status. A successful connection check does not guarantee a model request will succeed, and Relay has no combined spending or token cap.

If Relay cannot find an executable, set its path before launching from Terminal:

```sh
export RELAY_CLAUDE="/absolute/path/to/claude"
export RELAY_CODEX="/absolute/path/to/codex"
```

Relay also checks the usual macOS installation locations.

## How it works

```mermaid
flowchart LR
    Brief[Task and references] --> Observer[Observer inspects and plans]
    Observer --> Decision{You approve?}
    Decision -->|Reject| Stop[Stop without building]
    Decision -->|Approve| Builder[Builder implements and checks]
    Builder --> Reviewer[Reviewer inspects the result]
    Reviewer -->|Changes needed| Fix[Builder fixes or explains]
    Fix --> Reviewer
    Reviewer -->|Approved| Result[You review and keep the changes]
```

| Role | Responsibility |
| --- | --- |
| **Observer** | Inspect source and visual references; identify findings and propose a plan. |
| **Builder** | Implement the approved task, run appropriate checks, and report outcomes or blockers. Handles frontend and backend work. |
| **Reviewer** | Inspect the actual result against the task and acceptance checks; approve it or request evidence-backed fixes. |
| **You** | Define the task, approve the plan, inspect the result, and decide whether to keep it. |

The default team uses Claude as Observer and Reviewer, and Codex as Builder. You can assign the same provider to all three roles, and only the providers needed by the selected task mode must be ready.

## What you can do

- **Inspect without editing.** Get an observation or a plan from the current files, including uncommitted changes.
- **Choose your team.** Assign Claude Code or Codex to each role, select models and effort, add instructions, and save presets.
- **Clarify before approving.** The Observer asks focused questions when key requirements are missing. Your answers refine the plan and never authorize edits.
- **Approve before building.** Review the proposed plan, risks, and verification checks before the Builder starts.
- **Bring visual context.** Pick, drop, or paste screenshots and reference images into tasks and follow-ups.
- **Talk to your agent.** Keep chatting in the same saved chat: ask questions, or tell the agent to change things and it does it right away.
- **Act on findings.** Select issues and turn them into an editable planning or implementation brief with evidence attached.
- **Review the result.** Read an overview, priority labels, next actions, file-by-file diffs, new-file previews, and Builder-reported checks.
- **Recover saved work.** Retry a failed step or explicitly continue interrupted work in the same working copy, preserving completed results and approval records.
- **Keep local history.** Search chats, reopen reports, or delete conversations you no longer need. Optional limits keep only the newest chats or cap disk use.

Relay opens with no conversation selected. Saved chats stay in the sidebar until you choose one.

## Your first task

1. Choose **Add project**, give it a name, select its folder, and save it.
2. Select the project and a [task mode](#task-modes).
3. Describe the desired result and any acceptance criteria. Attach visual references if useful.
4. Open **Configure team** to choose tools, models, effort, and role instructions.
5. Set the time limit and, for builds, the review-round limit. Start the task.
6. For **Build & review**, inspect the proposed plan and approve or reject it.
7. Read the final report and review any file changes before keeping them.

**Remove** in the project selector forgets the saved entry; it does not delete the folder.

**Watch an example** runs a clearly labeled simulation. It does not call agents, spend model usage, or change a project.

## Task modes

| Mode | What runs | Editing | Project requirement |
| --- | --- | --- | --- |
| **Observe only** | Observer inspects and reports current behavior, risks, and findings | Disabled | Any existing folder |
| **Plan only** | Observer proposes steps, affected files, risks, and verification criteria | Disabled | Any existing folder |
| **Build & review** | Observer → clarification if needed → your approval → Builder → Reviewer → fix/review rounds as needed | Builder only, after approval | Any project folder (Git is optional) |

Read-only modes inspect your selected folder directly. They can see staged, unstaged, and untracked files without requiring a commit or stash, and they do not treat those existing edits as changes made by an agent.

Build tasks edit your project folder directly; Git is not required. Just before the Builder starts, Relay records a baseline of the folder's files in a private store inside Relay's data folder, never inside your project. The Changes tab, the complete patch and the Reviewer all compare against that baseline, so uncommitted work you already had is not counted as the Builder's change. The folder's own `.gitignore` is respected. Caches (`node_modules`, `.venv`, `__pycache__`), nested Git repositories, files over 5 MB and top-level folders over 50 MB are left out of the baseline, so changes there are not shown. The Builder is still told not to commit or change Git history.

## Working with Relay

<details>
<summary><strong>Clarify missing details</strong></summary>

For **Plan only** and **Build & review**, the Observer can ask up to five focused questions at a time when important requirements are unclear. Clear tasks go straight to a plan. Questions appear in **A few details before the plan**, with optional suggested answers and a text field for your own answer.

Answer every question and choose **Send answers & update plan**. Relay sends the answers to the read-only Observer, which revises the plan or asks remaining questions. The task timer pauses while waiting for answers. Stop remains available.

**Sending answers never approves edits.** A build still stops at **Awaiting your approval** with the final revised plan. Plan-only tasks finish with a read-only report. Observe-only tasks keep their read-only report behavior; chat messages in a finished chat are different and act immediately.

Questions and submitted answers stay in the chat under **Your clarification answers**, are preserved in follow-ups, and are included in the Builder and Reviewer handoffs. Unsent text is saved in the browser tab's session storage, so you can reload and reopen the waiting chat. A server restart interrupts the task; it does not resume questions or approve work automatically.

</details>

<details>
<summary><strong>Approval before editing</strong></summary>

Every real build task waits at **Awaiting your approval** after observation and any clarification rounds. **Approve & start building** releases the Builder; **Reject plan** stops the task without starting it. Approval covers the proposed implementation and its configured review/fix rounds.

The task's time limit pauses while waiting for this decision, and refreshing preserves the pending plan. Graceful shutdown stops the task and saves its changes. After a crash or forced termination, restart marks unfinished tasks interrupted. Neither path approves or resumes work automatically.

Read-only tasks do not start a Builder and do not require this approval gate. A chat message is different: it goes straight to the Builder and acts immediately.

**Auto mode.** Tick **Auto mode** when you start a Plan-only or Build & review task to let the agents work until it is done while you are away. The Observer is told not to ask questions and to state its assumptions in the plan; the plan approves itself (the Approve step shows "Auto mode approved the plan"); and the Builder and Reviewer keep going until the Reviewer approves. When the Reviewer reports the same findings three rounds in a row, or a review-round limit you set is reached, an agent makes the decision instead of asking you: it either gives the Builder a different approach to try (at a round limit it grants itself two more rounds) or accepts what is there and finishes. It changes approach at most twice per task; after that it finishes and lists what is left under **Open items Auto mode accepted**, the status reads **Finished with open items**, and the findings stay in the Review findings tab. A time limit you set is still a hard stop. If an agent fails (a dropped connection, a usage limit, an invalid answer), Auto mode retries that step up to two more times, waiting 30 seconds and then 2 minutes, and tells the Builder to continue from the files as they are. The timeline shows each retry. When an Auto task finishes, needs your decision, or stops with an error, Relay also shows a macOS notification with a sound; pressing **Stop** yourself does not notify. The notification comes from macOS Script Editor, so if you never see one, allow notifications for Script Editor in System Settings → Notifications, or set `RELAY_NO_NOTIFY=1` to turn them off. Auto mode never pushes or commits in the Build flow (the Builder rule is unchanged), and **Stop** always works. The choice is remembered for your next task.

</details>

<details>
<summary><strong>Team presets, models, and effort</strong></summary>

Each role stores its provider, model, effort, and additional instructions. **Tool default** leaves the corresponding setting to the installed CLI. The model and effort menus show Relay's configured choices; Codex can also use its visible local model cache. Availability still depends on your installed tool, provider settings, and account.

Use **Save preset** to store a named team and **Use team** to apply the current settings. New tasks save their own team configuration, so changing a preset does not rewrite existing tasks. Follow-ups inherit the conversation's Observer settings. Additional instructions do not grant extra tools or editing permissions.

Adding another AI provider requires a new adapter and compatibility tests. The current integrations are Claude Code and Codex CLI.

</details>

<details>
<summary><strong>Images and screenshots</strong></summary>

Use **Attach images**, drop files onto the attachment area or prompt, or paste an image into the prompt. Thumbnails show the selected images, with a Remove button for each one.

- Supported formats: **PNG, JPEG, WebP**. Convert HEIC files first.
- Limits: **four images**, including inherited references, at **4 MB per image**.
- Images are saved with the chat when you send the task, outside your project files.
- Each assigned role receives the references when its provider runs.
- Follow-ups inherit saved images; findings-based tasks copy them into the new task.
- Unsent selections stay in memory. Reselect them after a manual page reload.

Starting a real task sends its images, prompts, and relevant project context to the configured agent providers. Image support and usage limits depend on the selected model and tool.

</details>

<details>
<summary><strong>Reports, follow-ups, and findings</strong></summary>

The conversation shows a compact progress state while agents work and the final result when they finish. Individual tool calls and intermediate messages remain in local logs.

New structured reports include:

- A short overview.
- Findings labeled **Critical**, **High**, **Medium**, or **Low** by the agent.
- Recommended next actions.
- An expandable **Full report & evidence** section with Markdown formatting.

Older reports remain readable. Missing priority ratings are labeled **Unrated** rather than generated afterward.

**Talk to your agent.** Use **Talk to your agent** below a finished real chat. Each message goes to your configured **Builder** model as a conversation turn, with the earlier questions, reports and decisions as context. It answers questions without changing anything, and when you ask it to change, build, fix, run, commit or push something it does it immediately with its editing and command tools, with no plan or approval step and no Reviewer. Just before it starts, Relay records a baseline of the folder, so anything it changes appears in **Changes**; a message that changes nothing leaves earlier changes and their patch alone. Codex-based agents are also given network access in chat so a push you ask for can work. Relay does not manage credentials, and the agent is told to commit or push only when you explicitly ask in that message. Answers stay in the same chat, with earlier reports and build changes preserved. Each answer uses a fresh CLI invocation; this is not a resumed desktop-app session. Very long conversations are rejected with a request for a focused new task instead of silently dropping context.

**Build this plan.** After a Plan-only report, **Build this plan** runs the full Build & review pipeline in the same chat (choosing it is the plan approval, so no second planning pass runs, and the Reviewer checks the result). The plan that gets built is the latest plan plus every question and answer from the chat after it, listed under **Changes and decisions agreed in the conversation after this plan**; those take precedence where they conflict. The Approve step shows exactly that text. The Review findings buttons prefill the chat box instead of starting a new chat. Each build keeps its own patch; earlier patches are saved next to the latest as `changes-before-turn-N.patch`.

**Turn findings into a task.** Open **Review findings**, select the issues to address, then choose **Plan selected** or **Build & review selected**. Relay opens an editable draft with the original project, team, selected evidence, and image references. Review it before pressing Start. A build waits for plan approval (or Auto mode approves it). Changing the project or choosing **Clear** removes the attached finding context.

</details>

<details>
<summary><strong>Review and keep code changes</strong></summary>

The **Changes** tab provides:

- File navigation with modified, added, deleted, and new-file labels.
- Line-numbered diffs with additions and deletions highlighted.
- Saved previews of new text files.
- The latest round's **Builder-reported checks**, distinguished as passed, failed, or not run.
- Expandable Builder reports from earlier rounds.

**Reported checks are claims from the Builder, not tests independently rerun by Relay.** The Reviewer inspects source evidence; it does not serve as a separate test runner. A completed task does not establish that every check passed.

Previews are bounded and show notices for truncation, binary files, and unavailable content. Older tasks without saved per-file previews use their existing patch where possible; their new-file bodies may be unavailable. New build snapshots save a complete `changes.patch`, including added, modified, deleted, and binary files, symlinks, and executable permissions. Ignored files are excluded. Generating the patch does not change the working copy's Git staging area. Older patches may omit new files and are not offered as complete downloads.

**The changes are already in your folder.** To copy them elsewhere, choose **Download complete patch** in **Changes** and, in a checkout that matches the folder as it was before the build, run:

```sh
git apply --check /path/to/relay-<chat-id>.patch
git apply /path/to/relay-<chat-id>.patch
```

Then rerun your checks. If the folder is a Git repository, review the changes with `git diff` and commit them through your normal Git workflow.

**Relay does not automatically merge, commit, or push the result.** Each build keeps its baseline under `baselines/` in Relay's data folder until you delete it.

</details>

<details>
<summary><strong>Recover a failed or interrupted task</strong></summary>

For tasks created with checkpoint support, a **Recover this task** or **Continue interrupted work** panel shows what is saved and which step comes next. Choose the action shown there:

- **Retry review** reruns only the Reviewer against the preserved working copy and saved Builder report. It does not repeat observation or building.
- **Continue build** keeps partial edits, asks the Builder to inspect what already exists, and continues the same round.
- **Return to plan approval** reopens the saved plan for an explicit decision. An unapproved plan stays unapproved.
- **Continue questions** preserves the pending question batch and previous answers; answers still do not authorize edits.
- **Retry observation / plan update** repeats only the failed read-only stage.

Relay checks that the task folder and your project folder still exist and that the saved baseline is intact. It does not reset, recreate, merge, or commit the working copy. A saved completed review can be reused only if its source fingerprint still matches; changed files require another review.

Each recovery attempt gets a fresh time budget using the task's configured limit. The original review-round cap remains in force. Only one task can run, and a recovery cannot start while a previous worker is finishing its saves. **Recovery history** keeps previous errors and attempt outcomes. Provider prompts and results from retries have distinct attempt filenames.

Recovery is always explicit. Restart never starts agents or approves a plan on its own. A rejected plan cannot be resumed. Reaching the review-round limit never grants more rounds by itself: the chat shows **Needs your decision**, lists the open findings, and lets you either review the changes (already in your folder) or choose **Fix the remaining findings** with a number of extra rounds you pick. Older tasks and setup failures without a checkpoint need a new task; their working copies remain available for manual inspection.

A checkpoint records results only after Relay receives them. If a process crashes before a result is saved, that unsaved step may need to run again. Existing files remain available; recovery is a fresh CLI invocation with saved context, not a restored provider session.

</details>

<details>
<summary><strong>Controls, history, and deleting chats</strong></summary>

| Control or action | Behavior |
| --- | --- |
| **Pause handoffs** | Finish the current step, then wait before the next handoff. The task deadline continues. |
| **Stop** | Stop the current process group and prevent later handoffs. Written changes remain available. |
| **Without limit — rounds** | Continue fix/review rounds until approval, failure, Stop, or a configured deadline. |
| **Without limit — time** | Remove Relay's deadline; a configured round limit still applies. |
| Close the window | In source mode, leaves the coordinator running in its terminal. |
| Stop or restart Relay | Quitting or Control+C stops the agent group and waits for task persistence. After a crash, unfinished tasks become interrupted. No automatic resume. |

Unlimited settings do not bypass provider quotas, authentication failures, machine sleep, or process failures. Only one task runs at a time.

Search saved conversations in the sidebar. On smaller screens, use **History** to open the list. **New task** clears the selected conversation and returns to the brief.

**Delete a chat.** Open a chat's **…** menu and choose **Delete chat**, or use that button in a finished chat's activity panel. Running tasks must be stopped first.

Deleting is immediate and permanent: Relay removes the chat's conversation, attachments, prompts, logs and baseline. There is no Trash and no Undo. Your project folder is never touched, and this does not erase the CLIs' own histories.

**Limit how much history is kept.** Open **Storage** in the sidebar to see how much space saved chats use. You can optionally keep only the newest 25 to 250 chats, or keep history under 1, 2 or 5 GB. Relay shows how many chats a limit would delete and asks before deleting them. Limits are off by default; the newest finished chat and any running task are always kept.

</details>

## Privacy and security

### Where your data lives

| Setup | Data folder |
| --- | --- |
| Packaged app | `~/Library/Application Support/Relay` |
| Run from source | `./data` inside the Relay folder |

Set `RELAY_DATA_DIR` to use a different folder. Only one Relay may use a data folder at a time.

| Path inside the data folder | Contents |
| --- | --- |
| `projects.json` | Saved project names and local folder paths |
| `teams.json` | Saved team presets |
| `runs/<chat-id>/state.json` | Conversation turns, status, checkpoints, recovery attempts, reports, findings, approval records, checks, and saved change previews |
| `runs/<chat-id>/attachments/` | Images attached to that chat |
| `runs/<chat-id>/events.jsonl` | Readable activity log (the only copy of the events) |
| `runs/<chat-id>/provider-events.jsonl` | Captured provider output and diagnostics |
| `runs/<chat-id>/*.prompt.txt` | Agent instructions and handoffs |
| `runs/<chat-id>/builder-*.txt` | Builder implementation reports |
| `runs/<chat-id>/changes.patch` | Complete patch of the build's changes |
| `baselines/<task-id>.git/` | Private pre-build baselines of edited folders (older tasks used `workspaces/`) |
| `runs/<chat-id>/summary.json` | Small record (title, status, dates) read at startup instead of the full state |
| `retention.json` | Optional history limits (absent when no limit is chosen) |

Relay's combined history is local. The installed tools may save their own sessions, but Relay does not sync a combined conversation into the Claude or Codex desktop apps.

Runtime data is not encrypted by Relay. The supplied `.gitignore` excludes `data/`, environment files, and generated caches. Do not force-add private logs or workspaces to a public repository; ignore rules do not remove files already tracked by Git.

Avoid moving Relay while a task runs. Existing worktrees and saved records can contain absolute paths, so moving the data folder after creating tasks may require Git worktree repair and path updates.

### Security boundaries

Relay is a single-user local application. It binds to loopback, validates request hosts and origins, and requires a per-process token for mutations. These controls are not user authentication. Keep the server local and use trusted projects.

Observer and Reviewer roles use read-only tools. Codex uses its read-only sandbox for those roles and workspace-write for the Builder. Claude read roles receive Read, Glob, and Grep; its Builder additionally receives Edit, Write, and Bash. Claude's restricted tool configuration is not an OS sandbox equivalent to Codex's.

Relay supplies no permission-bypass flags. Instructions against deployment, publishing, or pushing are not an independently enforced shell-command policy. Project instructions, dependencies, tool configuration, and agent behavior remain part of the trust boundary.

## Run from source

Prefer the code over the packaged app? Relay's backend uses only Python's standard library, so **no `pip install` or `npm install` is required.**

| Requirement | Details |
| --- | --- |
| Python | 3.10 or newer |
| Git | Required for build tasks and the repository-based test suite |
| Agent tools | Claude Code, Codex CLI, or both, installed and signed in for the roles you choose |
| Operating system | macOS is the primary environment. The backend requires POSIX process groups and file locking; Linux is not yet validated and Windows is unsupported. |
| Node.js 18+ and npm | Optional, for the convenience scripts and frontend checks |

Clone the repository, open a terminal **inside the Relay folder**, sign in to your agents (`claude auth login`, `codex login`), and start Relay:

```sh
git clone https://github.com/itsdimash/Relay.git
cd Relay
python3 server.py --open
```

The dashboard opens at [http://127.0.0.1:8765](http://127.0.0.1:8765). Keep the terminal running; press **Control+C** to stop the server. On macOS you can also double-click `Start.command`, and `npm start` launches the same server.

For another port, use `python3 server.py --port 8766 --open`. Changing the port does not bypass the data-folder lock.

## Development

For automatic reload:

```sh
python3 dev.py --open
# or
npm run dev -- --open
```

Python source changes restart the backend after a short debounce, and static asset changes refresh the browser. Reloads wait while a task is active; browser reload also waits while unsent image selections exist. Draft text, mode, limits, and selected chat are retained across automatic refresh; unsaved dialog edits are not. Stop any normal server before switching to development mode. Changes to `dev.py` itself require restarting the development command.

Run the tests:

```sh
python3 -m unittest discover -s tests -v
# Equivalent convenience command:
npm test
```

Optional frontend syntax checks:

```sh
node --check static/app.js
# Also check any changed module under static/js/
node --check static/markdown.js
node --check static/review.js
```

The tests use temporary files and repositories and fake provider processes rather than paid model calls. Node-based renderer tests are skipped if Node.js is unavailable. They cover workflow behavior, plan approval, read-only modes, persistence, image inputs, diff capture, Markdown escaping, and HTTP protections; they do not establish full live-provider compatibility.

Relay uses Python's `ThreadingHTTPServer`, not ASGI. `uvicorn server:app --reload` is not supported.

### Building the macOS app

```sh
scripts/setup_macos_packaging.sh
scripts/build_macos_app.sh
open dist/Relay.app
```

This produces an ad-hoc-signed Apple-silicon build for local testing. See [Releasing Relay](docs/RELEASING.md) for signing, notarization, and publishing.

### Project structure

```text
server.py                  CLI launcher; composes and starts the backend
dev.py                     Development reload supervisor
relay/                     Backend modules and application composition
static/                    Dashboard: HTML, styles (brand.css), fonts, report renderers, icons
static/app.js              Frontend startup and feature wiring
static/js/                 Notifications, history, projects, teams, attachments, tasks, and shared helpers
packaging/                 Native macOS app shell: window, notch panel, engine launcher, Info.plist, entitlements
scripts/                   macOS app build, disk image (make_dmg.sh) and icon scripts
dist/                      Packaged app output (Relay-macOS-arm64.zip)
tests/                     Workflow, HTTP, development, distribution, and rendering tests
docs/ARCHITECTURE.md       Architecture and implementation details
docs/RELEASING.md          Building, signing, and publishing the macOS app
CONTRIBUTING.md            Contribution and verification guide
Start.command              macOS launcher for source mode
package.json               Optional npm convenience scripts
data/                      Private runtime data in source mode; ignored by Git
```

See [Architecture](docs/ARCHITECTURE.md) for implementation details and [Contributing](CONTRIBUTING.md) before proposing changes.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| macOS says Relay "can't be opened" or "can't be verified" | Relay is not notarized yet. Click **Done**, then open **System Settings → Privacy & Security** and click **Open Anyway** next to the Relay message. |
| Relay asks to move itself to Applications | Choose **Move to Applications**. It copies itself, then reopens from there. Choose **Don't ask again** to skip it. |
| Relay does not run on my Mac | The packaged app needs an Apple silicon Mac on macOS 13 or newer. On Intel Macs, [run from source](#run-from-source). |
| Agent needs sign-in | Run the relevant login command in Terminal, then choose **Refresh connections**. |
| Relay cannot find `claude` or `codex` | Set `RELAY_CLAUDE` or `RELAY_CODEX` to the absolute path. When launching the packaged app from Finder, make sure the CLI is installed in a standard location. |
| Requested model fails | Check the installed CLI's supported models, configuration, and account access; try **Tool default**. |
| Changes tab is missing a file | The baseline leaves out caches, nested Git repositories, files over 5 MB and top-level folders over 50 MB, so changes there are not listed. Check the event log for the excluded items. |
| Codex cannot start inside another agent's sandbox | Launch Relay yourself from Terminal, `Start.command`, or the app. |
| Relay is already running | Use the existing instance or quit it. Changing ports does not bypass the data-folder lock. |
| Port is occupied (source mode) | Choose another port with `--port 8766`. |
| Build appears to be waiting | Open the chat: the Observer may need answers, or the final plan may be awaiting approval. |
| Updated interface behaves incorrectly (source mode) | Restart the server after backend changes and refresh the page, or use development mode. |
| Image is rejected | Use PNG, JPEG, or WebP under 4 MB; convert HEIC first. Inherited images count toward the four-image limit. |
| Task was interrupted | Open it and use the recovery action when available. Otherwise inspect the preserved working copy and start a new task. Nothing resumes automatically. |

Still stuck? [Open an issue](https://github.com/itsdimash/Relay/issues) with your macOS version, how you launched Relay, and the relevant lines from the chat's `events.jsonl`. Remove anything private first.

## Current limits and next steps

- No automatic recovery, provider-session resumption, or checkpoint migration for legacy tasks.
- No independent Verifier role or enforced browser visual check for frontend work.
- No automatic merge, provider quota tracking, or combined spending cap.
- History limits are opt-in and apply by chat count or total size, not by age.
- No hosted multi-user deployment, Windows support, or Intel build of the packaged app.
- No signed or notarized release, and no automatic updates, yet.

Before a stable release, verify complete live workflows with supported provider versions, including images, and record the environment and results.

## License

A distribution license has not been selected, and no `LICENSE` file is included yet. Until one is added, all rights are reserved by the author.

## Integration references

- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Codex image inputs](https://learn.chatgpt.com/docs/image-inputs?surface=cli)
- [Claude Code programmatic usage](https://code.claude.com/docs/en/headless)
- [Claude image input through streaming messages](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode)
