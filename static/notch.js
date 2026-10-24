/** Notch panel: polls the local engine for the active task and shows it, with music, notes and the agent office. */
import { createRoom } from './js/notch-room.js';

const $ = id => document.getElementById(id);
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const room = createRoom($('room'), { reducedMotion });
const native = window.webkit?.messageHandlers?.relayPanel;
const tell = message => {
  try {
    native?.postMessage(message);
  } catch (_) {
    /* Running in a normal browser. */
  }
};

const LINES = {
  idle: ['Relay is idle', 'Your agents are waiting for a task.'],
  queued: ['Starting', 'Getting ready.'],
  preparing: ['Preparing', 'Making a safe copy of your project.'],
  observing: ['Observer is inspecting', 'Reading your project and planning the change.'],
  awaiting_clarification: ['Needs your answers', 'The Observer has a few questions.'],
  awaiting_approval: ['Needs your approval', 'Nothing is edited until you approve.'],
  building: ['Builder is working', 'Editing the working copy.'],
  fixing: ['Builder is refining', 'Applying the reviewer’s findings.'],
  reviewing: ['Reviewer is checking', 'Reading the actual changes.'],
  done: ['Finished', 'The result is ready in Relay.'],
  needs_attention: ['Needs attention', 'Open Relay to see what happened.'],
  failed: ['Stopped with an error', 'Open Relay to see what happened.'],
  stopped: ['Stopped', 'The task was stopped.'],
  interrupted: ['Interrupted', 'Open Relay to continue the task.']
};

let token = '';
let current = null;
let elapsedBase = 0;
let elapsedAt = 0;
let notified = '';
let busy = false;
let view = 'task';
let mode = 'compact'; // pill | compact | full, set by the app
const VIEWS = ['music', 'notes', 'task', 'office'];
let notes = [];
let noteBusy = false;
let inputFocused = false;
let holding = false;
let music = null;
let musicArt = '';

const format = seconds => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

function actorKey(run) {
  if (!run) return 'idle';
  if (run.status === 'done') return 'done';
  if (['failed', 'needs_attention', 'stopped', 'interrupted'].includes(run.status)) return 'failed';
  return run.actor || 'idle';
}

function render(run) {
  const key = actorKey(run);
  $('panel').dataset.actor = key;
  const [status, line] = LINES[run?.status] || LINES.idle;
  $('status').textContent = run?.paused ? 'Paused' : status;
  $('title').textContent = run ? run.title || 'Task' : 'Nothing running';
  $('roomLabel').textContent = run?.running ? (run.demo ? 'Example run. No real agents are called.' : line) : run ? line : LINES.idle[1];
  $('steps').replaceChildren(...(run?.steps || []).map(item => {
    const li = document.createElement('li');
    li.className = item.state;
    li.textContent = item.label;
    return li;
  }));
  const stepIndex = (run?.steps || []).findIndex(item => item.state === 'current');
  $('stepText').textContent = run?.steps?.length && stepIndex >= 0 ? `Step ${stepIndex + 1} of ${run.steps.length} · ${run.steps[stepIndex].label}` : '';
  const last = run?.last;
  $('last').replaceChildren();
  if (last && run.running) {
    const who = document.createElement('strong');
    who.textContent = last.agent ? `${last.agent}: ` : '';
    $('last').append(who, last.message);
  } else if (run && !run.running && run.summary) {
    $('last').textContent = run.summary;
  }
  const plan = run?.plan;
  $('approval').hidden = !plan;
  if (plan) $('panel').dataset.plan = '1';
  else delete $('panel').dataset.plan;
  if (plan && (view === 'notes' || view === 'music')) setView('task');
  if (plan) {
    $('planSummary').textContent = plan.summary;
    $('planChecks').replaceChildren(...plan.checks.map(check => {
      const li = document.createElement('li');
      li.textContent = check;
      return li;
    }));
  }
  if (!plan) $('approvalError').textContent = '';
  room.setScene({ actor: run?.running ? run.actor : null, terminal: key === 'done' ? 'done' : key === 'failed' ? 'failed' : null });
  elapsedBase = run?.running ? run.elapsed : 0;
  elapsedAt = Date.now();
  tickTimer();
}

function tickTimer() {
  $('timer').textContent = current?.running ? format(elapsedBase + Math.floor((Date.now() - elapsedAt) / 1000)) : '';
}

// Ask the app to bring the panel forward once per thing that needs attention or finishes.
let firstSnapshot = true;
let held = false;

function notifyNative(run) {
  if (!run || run.demo) return;
  const needsYou = !!run.plan || run.status === 'awaiting_clarification';
  let key = '';
  if (run.plan) key = `approve:${run.plan.id}`;
  else if (run.status === 'awaiting_clarification') key = `clarify:${run.id}`;
  else if (!run.running) key = `${run.status}:${run.id}`;
  if (held && !needsYou) {
    held = false;
    tell({ type: 'settle' });
  }
  const startup = firstSnapshot;
  firstSnapshot = false;
  if (!key || key === notified) return;
  notified = key;
  // A task that finished before the app opened is old news; one that waits for the person is not.
  if (startup && !needsYou) return;
  held = needsYou;
  if (view !== 'office' && !(view === 'notes' && inputFocused)) setView('task');
  tell({ type: 'attention', keep: needsYou });
}

async function poll() {
  try {
    const data = await fetch('/api/notch', { cache: 'no-store' }).then(r => r.json());
    token = data.token || token;
    const before = JSON.stringify(current);
    current = data.run;
    if (JSON.stringify(current) !== before) render(current);
    notifyNative(current);
  } catch (_) {
    $('status').textContent = 'Relay is not responding';
  }
}

async function post(path, body) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Relay-Token': token }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}

async function decide(path, body) {
  if (busy) return;
  busy = true;
  $('approve').disabled = true;
  $('reject').disabled = true;
  $('approvalError').textContent = '';
  try {
    await post(path, body);
    await poll();
  } catch (error) {
    $('approvalError').textContent = error.message;
  } finally {
    busy = false;
    $('approve').disabled = false;
    $('reject').disabled = false;
  }
}

// Views: Music, Notes, Task and (in the full panel only) Office.
const tabs = { music: $('tabMusic'), notes: $('tabNotes'), task: $('tabTask'), office: $('tabOffice') };

function fallbackView() {
  return music ? 'music' : 'task';
}

function setView(next, { focus = true } = {}) {
  if (next === 'notes' && current?.plan) next = 'task'; // a waiting plan always comes first
  if (!VIEWS.includes(next) || (next === 'office' && mode !== 'full')) next = fallbackView();
  view = next;
  $('panel').dataset.view = view;
  for (const [name, tab] of Object.entries(tabs)) tab.setAttribute('aria-selected', String(name === view));
  if (view === 'notes' && focus) {
    $('noteInput').focus();
    loadNotes();
  } else {
    if (view === 'notes') loadNotes();
    else $('noteInput').blur();
  }
  tickProgress();
  syncHold();
}

// While the person is typing, the panel must not close because the pointer moved away.
function syncHold() {
  const want = view === 'notes' && inputFocused;
  if (want === holding) return;
  holding = want;
  tell({ type: 'hold', on: want });
}

function noteItem(note) {
  const li = document.createElement('li');
  li.className = `note ${note.kind}${note.done ? ' done' : ''}`;
  let lead;
  if (note.kind === 'todo') {
    lead = document.createElement('input');
    lead.type = 'checkbox';
    lead.checked = !!note.done;
    lead.setAttribute('aria-label', `Done: ${note.text}`);
    lead.addEventListener('change', () => changeNotes('/api/notes/done', { id: note.id, done: lead.checked }));
  } else {
    lead = document.createElement('span');
    lead.classList.add('note-dot');
  }
  lead.classList.add('note-lead');
  const text = document.createElement('span');
  text.className = 'note-text';
  text.textContent = note.text;
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'note-remove';
  remove.textContent = '×';
  remove.setAttribute('aria-label', `Delete: ${note.text}`);
  remove.addEventListener('click', () => changeNotes('/api/notes/remove', { id: note.id }));
  li.append(lead, text, remove);
  return li;
}

function renderNotes() {
  const list = $('noteList');
  const top = list.scrollTop;
  const ordered = [...notes].sort((a, b) => Number(!!a.done) - Number(!!b.done)); // open items first
  if (ordered.length) {
    list.replaceChildren(...ordered.map(noteItem));
  } else {
    const empty = document.createElement('li');
    empty.className = 'note-empty';
    empty.textContent = 'Nothing yet.';
    list.replaceChildren(empty);
  }
  list.scrollTop = top;
  const open = notes.filter(note => note.kind === 'todo' && !note.done).length;
  $('noteCount').textContent = String(open);
  $('noteCount').hidden = open === 0;
}

async function loadNotes() {
  try {
    const data = await fetch('/api/notes', { cache: 'no-store' }).then(r => r.json());
    if (Array.isArray(data.notes)) {
      notes = data.notes;
      renderNotes();
    }
  } catch (_) {
    /* The next poll will bring the engine back; notes keep their last list. */
  }
}

async function changeNotes(path, body) {
  $('noteError').textContent = '';
  try {
    notes = (await post(path, body)).notes;
    renderNotes();
  } catch (error) {
    $('noteError').textContent = error.message;
    loadNotes();
  }
}

async function addNote(kind) {
  const text = $('noteInput').value.trim();
  if (!text || noteBusy) return;
  noteBusy = true;
  $('noteError').textContent = '';
  try {
    notes = (await post('/api/notes/add', { text, kind })).notes;
    $('noteInput').value = '';
    renderNotes();
    $('noteList').scrollTop = 0;
  } catch (error) {
    $('noteError').textContent = error.message;
  } finally {
    noteBusy = false;
  }
}

for (const [name, tab] of Object.entries(tabs)) {
  tab.addEventListener('click', () => {
    // The office lives in the full panel: from the small one, this button asks the app to grow it.
    if (name === 'office' && mode !== 'full') {
      tell({ type: 'expand', view: 'office' });
      return;
    }
    // Only the Office, and a plan waiting for an answer, need the big panel; every other view goes back to the small one.
    const needsRoom = name === 'office' || (name === 'task' && !!current?.plan);
    if (mode === 'full' && !needsRoom) tell({ type: 'shrink' });
    if (mode === 'compact' && needsRoom) tell({ type: 'expand' });
    setView(name);
  });
}
$('noteInput').addEventListener('focus', () => { inputFocused = true; syncHold(); });
$('noteInput').addEventListener('blur', () => { inputFocused = false; syncHold(); });
$('noteInput').addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.isComposing) return; // Escape bubbles up and hides the panel
  event.preventDefault();
  addNote(event.metaKey || event.ctrlKey ? 'todo' : 'note');
});
// Now playing. The app reads it from the system and calls relayNowPlaying; the buttons send commands back.
function position() {
  if (!music || !(music.duration > 0) || !Number.isFinite(music.elapsed)) return null;
  const rate = music.playing ? (music.rate > 0 ? music.rate : 1) : 0;
  const since = Math.max(0, (Date.now() - (Number.isFinite(music.updatedAt) ? music.updatedAt : music.receivedAt)) / 1000);
  return Math.min(music.duration, Math.max(0, music.elapsed + rate * since));
}

function tickProgress() {
  if (view !== 'music' || mode === 'pill') return;
  const pos = position();
  $('progress').toggleAttribute('data-empty', pos === null);
  if (pos === null) {
    $('musicElapsed').textContent = '';
    $('musicRemaining').textContent = '';
    return;
  }
  $('musicElapsed').textContent = format(Math.floor(pos));
  $('musicRemaining').textContent = `-${format(Math.max(0, Math.floor(music.duration) - Math.floor(pos)))}`;
  $('progressFill').style.width = `${(pos / music.duration * 100).toFixed(1)}%`;
}

function renderMusic() {
  const panel = $('panel');
  if (!music) {
    delete panel.dataset.music;
    $('musicTitle').textContent = 'Nothing is playing';
    $('musicArtist').textContent = 'Start music in any app and it shows up here.';
    $('music').removeAttribute('data-playing');
    $('pill').removeAttribute('data-playing');
    tabs.music.removeAttribute('data-live');
    $('musicArt').hidden = true;
    $('pillArt').hidden = true;
    musicArt = '';
    if (view === 'music' && mode === 'pill') setView(fallbackView(), { focus: false });
    return;
  }
  panel.dataset.music = '1';
  const artist = music.artist || music.album || '';
  $('musicTitle').textContent = music.title;
  $('musicArtist').textContent = artist;
  $('pillTitle').textContent = music.title;
  $('pillArtist').textContent = artist;
  $('music').toggleAttribute('data-playing', !!music.playing);
  $('pill').toggleAttribute('data-playing', !!music.playing);
  tabs.music.toggleAttribute('data-live', !!music.playing);
  $('musicToggle').setAttribute('aria-label', music.playing ? 'Pause' : 'Play');
  const art = typeof music.artwork === 'string' ? music.artwork : '';
  if (art !== musicArt) {
    musicArt = art;
    for (const id of ['musicArt', 'pillArt']) {
      if (art) $(id).src = art;
      else $(id).removeAttribute('src');
    }
  }
  $('musicArt').hidden = !art;
  $('pillArt').hidden = !art;
  tickProgress();
}

window.relayNowPlaying = state => {
  music = state && typeof state.title === 'string' && state.title ? { ...state, receivedAt: Date.now() } : null;
  renderMusic();
};

for (const [id, command] of [['musicPrev', 'previous'], ['musicToggle', 'toggle'], ['musicNext', 'next']]) {
  $(id).addEventListener('click', () => tell({ type: 'media', command }));
}

// The app sets the shape of the panel (pill, compact or full) and tells us how tall the notch is.
window.relayPanelMode = info => {
  if (!info || typeof info !== 'object') return;
  const next = ['pill', 'compact', 'full'].includes(info.mode) ? info.mode : 'compact';
  const root = document.documentElement.style;
  if (Number.isFinite(info.notchHeight) && info.notchHeight > 0) root.setProperty('--notch-h', `${Math.round(info.notchHeight)}px`);
  if (Number.isFinite(info.notchWidth) && info.notchWidth > 0) root.setProperty('--notch-w', `${Math.round(info.notchWidth)}px`);
  mode = next;
  $('panel').dataset.mode = mode;
  // A new appearance starts without the keyboard: typing begins only when the person clicks the note field.
  const wasHolding = holding;
  $('noteInput').blur();
  inputFocused = false;
  holding = false;
  if (wasHolding) tell({ type: 'hold', on: false });
  if (mode === 'pill') return;
  let target = typeof info.view === 'string' ? info.view : view;
  if (current?.plan && (target === 'notes' || target === 'music')) target = 'task';
  setView(target, { focus: false });
  // A plan that needs an answer does not fit in the small panel.
  if (mode === 'compact' && current?.plan) tell({ type: 'expand' });
};

// The app may have found something playing before this page finished loading: ask it to send that now.
tell({ type: 'ready' });

$('approve').addEventListener('click', () => current?.plan && decide('/api/approve-plan', { id: current.id, plan_id: current.plan.id }));
$('reject').addEventListener('click', () => current?.plan && decide('/api/stop', { id: current.id }));
for (const id of ['open', 'open2']) $(id).addEventListener('click', () => tell({ type: 'open' }));
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  $('noteInput').blur(); // lets go of the hold before the panel hides
  tell({ type: 'hide' });
});

room.start();
render(null);
renderMusic();
setView('task', { focus: false });
loadNotes();
poll();
setInterval(poll, 1000);
setInterval(tickTimer, 1000);
setInterval(tickProgress, 500);
