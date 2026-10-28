/** Notch panel: polls the local engine for the active task and shows it, with music, notes, files to deliver and the agent office. */
import { createRoom } from './js/notch-room.js';
import { limitRow } from './js/limits.js';
import { createCollaboration } from './js/notch-collaboration.js';
import { createActivity } from './js/notch-activity.js';
import { createMusicFx, STYLES, DEFAULT_STYLE, isStyle } from './js/notch-music-fx.js';
import { createBatteryWatcher } from './js/notch-battery.js';
import { parseReminder, dueLabel, createReminderWatcher, quickChoices, startingMoment, stepMoment, canSet, dayLabel, hourText, minuteText } from './js/notch-reminders.js';

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
const openRun = destination => {
  if (native) tell({ type: 'open', ...destination });
  else window.open('/#' + new URLSearchParams({ run: destination.runId, tab: destination.tab, step: destination.step }), '_blank', 'noopener');
};
const collaboration = createCollaboration({ reducedMotion, openRun });
const activity = createActivity({post, openRun});

// Music animation (drawn by js/notch-music-fx.js): behind the Music view, beside its title, and in the track-change pill.
// "Customize" (or the animation next to the title) opens a small picker with two tabs: the animation in the panel, and, in
// the app, the light around the notch on the screen, which the app itself draws and remembers.
const fx = createMusicFx({ reducedMotion });
const rectOf = (canvas, element, radius) => () => {
  const area = canvas.getBoundingClientRect();
  const box = element.getBoundingClientRect();
  return box.width ? { x: box.left - area.left, y: box.top - area.top, w: box.width, h: box.height, r: radius } : null;
};
fx.attach($('musicFx'), { kind: 'stage', anchor: rectOf($('musicFx'), document.querySelector('#music .cover'), 14) });
fx.attach($('musicMini'), { kind: 'mini' });
fx.attach($('pillFx'), { kind: 'pill' });
let fxStyle = DEFAULT_STYLE;
try {
  const saved = localStorage.getItem('relay.musicFx');
  if (isStyle(saved)) fxStyle = saved;
} catch (_) {}
fx.setStyle(fxStyle);
$('panel').dataset.fx = fxStyle;

const GLOWS = [{ id: 'off', name: 'Off' }, { id: 'line', name: 'Line' }, { id: 'halo', name: 'Halo' }, { id: 'sparks', name: 'Sparks' }];
let glowStyle = 'line'; // the app keeps the real choice and tells us through relayGlowStyle
let fxTab = 'panel';
const fxTiles = { panel: new Map(), screen: new Map() };

function offPreview() {
  const preview = document.createElement('span');
  preview.className = 'fx-none';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 20 20');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', 'M6 10h8');
  svg.append(path);
  preview.append(svg);
  return preview;
}

function addTile(group, grid, id, name, preview, choose) {
  const tile = document.createElement('button');
  tile.type = 'button';
  tile.className = 'fx-tile';
  tile.setAttribute('role', 'radio');
  const label = document.createElement('span');
  label.textContent = name;
  tile.append(preview, label);
  tile.addEventListener('click', choose);
  $(grid).append(tile);
  fxTiles[group].set(id, tile);
}

function previewCanvas(style) {
  const canvas = document.createElement('canvas');
  canvas.setAttribute('aria-hidden', 'true');
  fx.attach(canvas, { kind: 'tile', style });
  return canvas;
}

for (const { id, name } of STYLES) addTile('panel', 'fxGridPanel', id, name, id === 'off' ? offPreview() : previewCanvas(id), () => chooseFx(id));
for (const { id, name } of GLOWS) addTile('screen', 'fxGridScreen', id, name, id === 'off' ? offPreview() : previewCanvas(`glow-${id}`), () => chooseGlow(id));
$('fxTabs').hidden = !native; // the light on the screen belongs to the app: nothing to choose in a normal browser

function paintFxChoice() {
  for (const [group, chosen] of [['panel', fxStyle], ['screen', glowStyle]]) {
    for (const [id, tile] of fxTiles[group]) {
      tile.setAttribute('aria-checked', String(id === chosen));
      tile.tabIndex = id === chosen ? 0 : -1;
    }
  }
  $('panel').dataset.fx = fxStyle;
}

function setFxTab(name) {
  fxTab = name === 'screen' && native ? 'screen' : 'panel';
  for (const [tab, grid, key] of [['fxTabPanel', 'fxGridPanel', 'panel'], ['fxTabScreen', 'fxGridScreen', 'screen']]) {
    $(tab).setAttribute('aria-selected', String(fxTab === key));
    $(tab).tabIndex = fxTab === key ? 0 : -1;
    $(grid).hidden = fxTab !== key;
  }
  fx.refresh(); // the previews that just appeared start moving
}

function setFxPicker(open) {
  const picker = $('fxPicker');
  if (open === !picker.hidden) return;
  picker.hidden = !open;
  for (const id of ['fxOpen', 'fxCustomize']) $(id).setAttribute('aria-expanded', String(open));
  fx.setPicker(open);
  if (open) {
    setFxTab(fxTab);
    const tiles = fxTiles[fxTab];
    tiles.get(fxTab === 'panel' ? fxStyle : glowStyle)?.focus({ preventScroll: true });
  }
}

function closeSoon() {
  setTimeout(() => {
    if ($('fxPicker').contains(document.activeElement)) fxOpener.focus({ preventScroll: true });
    setFxPicker(false);
  }, 240);
}

function chooseFx(id) {
  fxStyle = id;
  try {
    localStorage.setItem('relay.musicFx', id);
  } catch (_) {}
  fx.setStyle(id);
  paintFxChoice();
  closeSoon();
}

function chooseGlow(id) {
  glowStyle = id;
  paintFxChoice();
  tell({ type: 'glowStyle', style: id });
  closeSoon();
}

// The app tells us which glow is saved, when the page loads and whenever it changes.
window.relayGlowStyle = style => {
  if (!GLOWS.some(glow => glow.id === style)) return;
  glowStyle = style;
  paintFxChoice();
};

paintFxChoice();
setFxTab('panel');
// Two ways in, the animation next to the title and the Customize button; both open the same picker.
let fxOpener = $('fxOpen');
for (const id of ['fxOpen', 'fxCustomize']) {
  $(id).addEventListener('click', () => {
    fxOpener = $(id);
    setFxPicker($('fxPicker').hidden);
  });
}
$('fxClose').addEventListener('click', () => {
  setFxPicker(false);
  fxOpener.focus({ preventScroll: true });
});
$('fxTabPanel').addEventListener('click', () => setFxTab('panel'));
$('fxTabScreen').addEventListener('click', () => setFxTab('screen'));
document.addEventListener('pointerdown', event => {
  if (!$('fxPicker').hidden && !event.target.closest('#fxPicker, #fxOpen, #fxCustomize')) setFxPicker(false);
});
// Capture phase: Escape closes the picker first, and only a second Escape hides the whole panel.
document.addEventListener('keydown', event => {
  if ($('fxPicker').hidden) return;
  if (event.key === 'Escape') {
    event.stopPropagation();
    setFxPicker(false);
    fxOpener.focus({ preventScroll: true });
    return;
  }
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
  if (!step) return;
  event.preventDefault();
  if (document.activeElement?.classList.contains('fx-tab')) {
    if (!$('fxTabs').hidden) {
      setFxTab(fxTab === 'panel' ? 'screen' : 'panel');
      $(fxTab === 'panel' ? 'fxTabPanel' : 'fxTabScreen').focus({ preventScroll: true });
    }
    return;
  }
  const tiles = [...fxTiles[fxTab].values()];
  const at = tiles.indexOf(document.activeElement);
  tiles[(at + step + tiles.length) % tiles.length].focus({ preventScroll: true });
}, true);

const LINES = {
  idle: ['Relay is idle', 'Your agents are waiting for a task.'],
  queued: ['Starting', 'Getting ready.'],
  preparing: ['Preparing', 'Making a safe copy of your project.'],
  observing: ['Observer is inspecting', 'Reading your project and planning the change.'],
  awaiting_clarification: ['Needs your answers', 'The Observer has a few questions.'],
  awaiting_approval: ['Needs your approval', 'Nothing is edited until you approve.'],
  building: ['Builder is working', 'Editing your folder.'],
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
let view = 'notes';
// The tab the person picked last. The first opening after the app starts is the Notes; after that the panel comes back to this.
let chosenView = 'notes';
let mode = 'compact'; // pill | compact | full, set by the app
const VIEWS = ['music', 'notes', 'deliver', 'task', 'office'];
let notes = [];
let deliver = [];
let noteBusy = false;
let shownNotes = null; // ids of the notes drawn last time (null before the first draw, so the first list does not animate)
let inputFocused = false;
let holding = false;
let music = null;
let musicArt = '';
let musicTrack = '';
let officeMusicEnabled = true;
try { officeMusicEnabled = localStorage.getItem('relay.officeMusic') !== 'off'; } catch (_) {}
$('officeMusic').setAttribute('aria-pressed', String(officeMusicEnabled));
$('officeMusic').addEventListener('click', () => {
  officeMusicEnabled = !officeMusicEnabled;
  $('officeMusic').setAttribute('aria-pressed', String(officeMusicEnabled));
  try { localStorage.setItem('relay.officeMusic', officeMusicEnabled ? 'on' : 'off'); } catch (_) {}
  room.setMusic(!!music?.playing && officeMusicEnabled);
});

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
  for (const label of document.querySelectorAll('[data-room-role]')) {
    const active = label.dataset.roomRole === key;
    label.toggleAttribute('data-active', active);
    if (active) label.setAttribute('aria-current', 'step');
    else label.removeAttribute('aria-current');
  }
  $('panel').toggleAttribute('data-working', !!run?.running && !run.paused);
  $('panel').toggleAttribute('data-attention', !!run?.running && (!!run.plan || run.status === 'awaiting_clarification'));
  tabs.task.toggleAttribute('data-live', !!run?.running && !run.paused);
  updateGlow();
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
  room.setScene({ actor: run?.running && !run.paused ? run.actor : null, terminal: key === 'done' ? 'done' : key === 'failed' ? 'failed' : null, id: run?.id, auto: !!run?.auto, steps: run?.steps || [] });
  elapsedBase = run?.running ? run.elapsed : 0;
  elapsedAt = Date.now();
  tickTimer();
  collaboration.update(run);
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

// Usage left for each tool, shown in the Office. Rebuilt only when the numbers change.
let limitsKey = '';
function renderLimits(limits) {
  if (!limits) return;
  const { now, ...readings } = limits;
  const key = JSON.stringify(readings);
  if (key === limitsKey) return;
  limitsKey = key;
  $('limits').replaceChildren(
    limitRow(document, 'Claude', readings.claude, now, 'no reading yet'),
    limitRow(document, 'Codex', readings.codex, now, 'no reading')
  );
}

// Banners that drop in from the notch. Music has its own animations and is not announced here.
const ICONS = {
  play: '<svg viewBox="0 0 24 24"><path d="M8 5.5v13l11-6.5z" fill="currentColor" stroke="none"/></svg>',
  bell: '<svg viewBox="0 0 24 24"><path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0"/></svg>',
  help: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.6 2.6 0 1 1 3.6 2.4c-.8.4-1.2 1-1.2 1.9M12 17h.01"/></svg>',
  check: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path class="draw" d="M7.5 12.5l3 3 6-6.5"/></svg>',
  alert: '<svg viewBox="0 0 24 24"><path d="M12 4l9 16H3zM12 10v4M12 17h.01"/></svg>',
  cross: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/></svg>',
  sync: '<svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 0 0-14.5-4M4 13a8 8 0 0 0 14.5 4M4 4.5V8h3.5M20 19.5V16h-3.5"/></svg>',
  spark: '<svg viewBox="0 0 24 24"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18.5 16l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/></svg>',
  bolt: '<svg viewBox="0 0 24 24"><path d="M13 3 5.5 13.5H11L10 21l7.5-10.5H12z"/></svg>',
  battery: '<svg viewBox="0 0 24 24"><rect x="3" y="8" width="16" height="9" rx="2.2"/><path d="M21.5 11v3M6.5 11.5v2"/></svg>'
};
const TOASTS = {
  start: { icon: 'play' }, approve: { icon: 'bell' }, question: { icon: 'help' }, approved: { icon: 'check' },
  done: { icon: 'check', burst: true }, attention: { icon: 'alert' }, failed: { icon: 'cross' }, retry: { icon: 'sync' }, decision: { icon: 'spark' },
  charging: { icon: 'bolt' }, lowbattery: { icon: 'battery' }, reminder: { icon: 'bell' }
};
let toastTimer = null;
let toastLeave = null;
let flashTimer = null;
function toast(kind, title, detail = '') {
  const spec = TOASTS[kind];
  if (!spec) return;
  clearTimeout(toastTimer);
  clearTimeout(toastLeave);
  const box = $('toast');
  box.hidden = false;
  box.dataset.kind = kind;
  box.removeAttribute('data-show');
  box.removeAttribute('data-leaving');
  $('toastIcon').innerHTML = ICONS[spec.icon];
  $('toastTitle').textContent = title;
  $('toastDetail').textContent = detail;
  $('toastDetail').hidden = !detail;
  void box.offsetWidth; // restart the entrance animation
  box.setAttribute('data-show', '');
  $('panel').dataset.flash = kind;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => delete $('panel').dataset.flash, 1400);
  const burst = $('toastBurst');
  burst.replaceChildren();
  if (spec.burst && !reducedMotion) {
    const colors = ['#4fb594', '#f0a63f', '#a18bf0', '#4db6c9', '#fff6c2'];
    for (let i = 0; i < 22; i++) {
      const angle = (i / 22) * Math.PI * 2 + Math.random() * 0.4;
      const distance = 50 + Math.random() * 70;
      const dot = document.createElement('i');
      dot.style.setProperty('--dx', `${Math.cos(angle) * distance * 1.5}px`);
      dot.style.setProperty('--dy', `${Math.sin(angle) * distance * 0.8 + 24}px`);
      dot.style.setProperty('--rot', `${Math.round(Math.random() * 540 - 270)}deg`);
      dot.style.setProperty('--c', colors[i % colors.length]);
      burst.append(dot);
    }
  }
  toastTimer = setTimeout(() => {
    box.setAttribute('data-leaving', '');
    toastLeave = setTimeout(() => { box.hidden = true; box.removeAttribute('data-show'); box.removeAttribute('data-leaving'); burst.replaceChildren(); }, reducedMotion ? 0 : 280);
  }, spec.burst ? 4200 : 3400);
}

// Battery: the engine reads it from macOS. The person can turn the alerts off in the Relay window (Notch menu).
const batteryAlertsOn = () => {
  try {
    return localStorage.getItem('relay.batteryAlerts') !== 'off';
  } catch (_) {
    return true;
  }
};
const batteryWatcher = createBatteryWatcher({
  enabled: batteryAlertsOn,
  announce: message => {
    toast(message.kind, message.title, message.detail);
    tell({ type: 'attention', keep: false }); // the panel peeks out for a moment
  }
});

// Reminders: a note with a time ("in 30 min", "tomorrow at 9:00") is kept by the engine, which says on every poll which ones
// are due. The panel slides out on the Notes for a few seconds, longer than for other banners.
const reminderWatcher = createReminderWatcher({
  announce: message => {
    toast(message.kind, message.title, message.detail);
    if (current?.plan) tell({ type: 'attention', keep: true }); // a plan waiting for an answer needs the big panel anyway
    else tell({ type: 'reminder' });                           // otherwise the small panel opens on the Notes for a while
    loadNotes();
  },
  acknowledge: ids => post('/api/notes/reminded', { ids }).then(result => { if (Array.isArray(result.notes)) { notes = result.notes; renderNotes(); } })
});

const announced = { id: '', status: '', event: -1, first: true };
const brief = (text, limit = 90) => {
  const flat = String(text || '').replace(/\s+/g, ' ').trim();
  return flat.length > limit ? flat.slice(0, limit - 1).trimEnd() + '…' : flat;
};
function announce(run) {
  if (!run || run.demo) {
    announced.id = '';
    return;
  }
  const events = run.recent_events || [];
  const newest = events.reduce((highest, event) => Math.max(highest, Number(event.id)), -1);
  const startup = announced.first;
  announced.first = false;
  if (run.id !== announced.id) {
    // A different task: remember where it stands and say hello, unless the app only just opened.
    announced.id = run.id;
    announced.status = run.status;
    announced.event = newest;
    if (run.running && !startup) {
      toast('start', run.auto ? 'Auto mode started' : 'Task started', brief(run.title));
      room.pulse('start');
    }
    return;
  }
  for (const event of [...events].reverse()) {
    if (Number(event.id) <= announced.event) continue;
    const message = event.message || '';
    const retry = message.match(/Retrying in (\d+) seconds \(try (\d+) of (\d+)\)/);
    if (event.kind === 'control' && /^Auto mode approved the plan/.test(message)) {
      toast('approved', 'Plan approved', 'Auto mode approved it. The Builder is starting.');
      room.pulse('approved');
    } else if (event.kind === 'control' && /^Auto mode decided/.test(message)) {
      toast('decision', 'Auto mode decided', brief(message.replace(/^Auto mode decided\s*/, ''), 110));
      room.pulse('decision');
    } else if (retry) {
      toast('retry', 'Retrying after an error', `In ${retry[1]} seconds · try ${retry[2]} of ${retry[3]}`);
      room.pulse('retry');
    }
  }
  announced.event = Math.max(announced.event, newest);
  if (run.status === announced.status) return;
  const previous = announced.status;
  announced.status = run.status;
  if (run.status === 'awaiting_approval') toast('approve', 'Needs your approval', 'Nothing is edited until you approve.');
  else if (run.status === 'awaiting_clarification') toast('question', 'Needs your answers', 'The Observer has a few questions.');
  else if (previous === 'awaiting_approval' && ['building', 'preparing'].includes(run.status)) {
    toast('approved', 'Plan approved', 'The Builder is starting.');
    room.pulse('approved');
  } else if (run.status === 'done') {
    const files = run.result?.files;
    toast('done', run.accepted ? 'Finished with open items' : 'Finished', Number.isInteger(files) && files > 0 ? `${files} changed ${files === 1 ? 'file' : 'files'} · ready to review` : 'The result is ready in Relay.');
  } else if (run.status === 'needs_attention') toast('attention', 'Needs your decision', 'Open Relay to see what is left.');
  else if (run.status === 'failed') toast('failed', 'Stopped with an error', brief(run.summary) || 'Open Relay to see what happened.');
}

async function poll() {
  try {
    const data = await fetch('/api/notch', { cache: 'no-store' }).then(r => r.json());
    token = data.token || token;
    const before = JSON.stringify(current);
    current = data.run;
    if (JSON.stringify(current) !== before) render(current);
    announce(current);
    renderLimits(data.limits);
    batteryWatcher.update(data.battery);
    reminderWatcher.update(data.reminders);
    activity.update(data.queue, current);
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

// Views: Music, Notes, Deliver, Task and (in the full panel only) Office.
const tabs = { music: $('tabMusic'), notes: $('tabNotes'), deliver: $('tabDeliver'), task: $('tabTask'), office: $('tabOffice') };

// Tabs the person hid (Notch menu in the Relay window). The Task tab always stays: plans wait there for approval.
const TAB_KEY = 'relay.notchTabs';
let hiddenTabs = new Set();
const shown = name => !hiddenTabs.has(name);

function fallbackView() {
  if (shown(chosenView)) return chosenView;
  return ['notes', 'music', 'deliver', 'task'].find(shown) || 'task';
}

function setView(next, { focus = true } = {}) {
  if (next === 'notes' && current?.plan) next = 'task'; // a waiting plan always comes first
  if (!VIEWS.includes(next) || !shown(next) || (next === 'office' && mode !== 'full')) next = fallbackView();
  view = next;
  $('panel').dataset.view = view;
  fx.setScene({ mode, view });
  if (view !== 'music') setFxPicker(false);
  if (view === 'office' && !document.hidden) room.start();
  else room.stop();
  updateGlow();
  for (const [name, tab] of Object.entries(tabs)) tab.setAttribute('aria-selected', String(name === view));
  if (view === 'notes' && focus) {
    $('noteInput').focus();
    loadNotes();
  } else {
    if (view === 'notes') loadNotes();
    else $('noteInput').blur();
  }
  if (view === 'deliver') loadDeliver();
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
    lead.className = 'note-check';
    lead.checked = !!note.done;
    lead.setAttribute('aria-label', `Done: ${note.text}`);
    lead.addEventListener('change', () => {
      li.classList.toggle('done', lead.checked); // the tick and the strike-through show at once; the list follows when the engine answers
      changeNotes('/api/notes/done', { id: note.id, done: lead.checked });
    });
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
  remove.innerHTML = '<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7"/></svg>';
  remove.setAttribute('aria-label', `Delete: ${note.text}`);
  remove.addEventListener('click', () => changeNotes('/api/notes/remove', { id: note.id }));
  li.append(lead, text);
  if (Number.isFinite(note.due) && note.reminded && !note.done) {
    // A reminder that has gone off can be put off by ten minutes; it stays in view for the first hour, then only on hover.
    const snooze = document.createElement('button');
    snooze.type = 'button';
    snooze.className = `note-snooze${Date.now() - note.due < 3600000 ? ' recent' : ''}`;
    snooze.textContent = '+10 min';
    snooze.title = 'Snooze 10 minutes';
    snooze.setAttribute('aria-label', `Snooze: ${note.text}`);
    snooze.addEventListener('click', () => changeNotes('/api/notes/snooze', { id: note.id, minutes: 10 }));
    li.append(snooze);
  }
  if (Number.isFinite(note.due)) {
    const due = document.createElement('span');
    due.className = `note-due${note.reminded ? ' passed' : ''}`;
    due.textContent = dueLabel(note.due);
    due.title = new Date(note.due).toLocaleString();
    li.append(due);
  }
  li.append(remove);
  return li;
}

function renderNotes() {
  const list = $('noteList');
  const top = list.scrollTop;
  const ordered = [...notes].sort((a, b) => Number(!!a.done) - Number(!!b.done)); // open items first
  if (ordered.length) {
    // Rows that were not on the screen before slide in; the ones already there stay still when something else changes.
    const rows = ordered.map(note => {
      const row = noteItem(note);
      if (shownNotes && !shownNotes.has(note.id)) row.classList.add('enter');
      return row;
    });
    list.replaceChildren(...rows);
  } else {
    const empty = document.createElement('li');
    empty.className = 'note-empty';
    empty.innerHTML = '<span class="note-empty-icon"><svg viewBox="0 0 20 20" aria-hidden="true"><rect x="4" y="3" width="12" height="14" rx="2.2"/><path d="M7.2 7.6h5.6M7.2 11.2h3.6"/></svg></span><strong></strong><small></small>';
    empty.querySelector('strong').textContent = 'Nothing yet.';
    empty.querySelector('small').textContent = 'Try “call mom in 30 min” and Relay will remind you.';
    list.replaceChildren(empty);
  }
  shownNotes = new Set(notes.map(note => note.id));
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
  const typed = $('noteInput').value.trim();
  if (!typed || noteBusy) return;
  // A time picked with the buttons wins; otherwise the words are read for one ("in 30 min", "tomorrow at 9:00").
  const picked = pendingDue();
  const reminder = picked ? { text: typed, due: picked } : parseReminder(typed);
  noteBusy = true;
  $('noteError').textContent = '';
  try {
    notes = (await post('/api/notes/add', reminder ? { text: reminder.text, kind, due: reminder.due } : { text: typed, kind })).notes;
    $('noteInput').value = '';
    pending = null;
    setRemind(false);
    showNoteHint();
    renderNotes();
    $('noteList').scrollTop = 0;
  } catch (error) {
    $('noteError').textContent = error.message;
  } finally {
    noteBusy = false;
  }
}

// Picking a tab, by a click or because files were dropped on the panel.
function pickTab(name) {
  if (name !== 'office') chosenView = name; // the Office needs the big panel, so it is never what a hover comes back to
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
}

for (const [name, tab] of Object.entries(tabs)) tab.addEventListener('click', () => pickTab(name));

function applyTabs() {
  try {
    const saved = JSON.parse(localStorage.getItem(TAB_KEY) || 'null');
    hiddenTabs = new Set((Array.isArray(saved?.hidden) ? saved.hidden : []).filter(name => VIEWS.includes(name) && name !== 'task'));
  } catch (_) {
    hiddenTabs = new Set();
  }
  for (const [name, tab] of Object.entries(tabs)) tab.hidden = hiddenTabs.has(name);
  if (hiddenTabs.has(view)) setView(fallbackView(), { focus: false });
}
// The Relay window and this panel are separate pages; a change made in the window reaches the panel here.
window.addEventListener('storage', event => { if (event.key === TAB_KEY) applyTabs(); });

// More: a small menu with the two things that have no tab. It only exists in the app; a browser has nothing to quit.
const moreButton = $('moreButton');
const moreMenu = $('moreMenu');
moreButton.hidden = !native;
let quitArmed = false; // a task is running, so the first press on Quit only asks
function paintQuit() {
  $('quitLabel').hidden = quitArmed;
  $('quitConfirm').hidden = !quitArmed;
}
function setMore(open) {
  moreMenu.hidden = !open;
  moreButton.setAttribute('aria-expanded', String(open));
  quitArmed = false;
  paintQuit();
  if (open) $('moreOpen').focus({ preventScroll: true });
}
moreButton.addEventListener('click', () => setMore(moreMenu.hidden));
$('moreOpen').addEventListener('click', () => {
  setMore(false);
  tell({ type: 'open' });
});
$('moreQuit').addEventListener('click', () => {
  if (current?.running && !quitArmed) {
    quitArmed = true;
    paintQuit();
    return;
  }
  setMore(false);
  tell({ type: 'quit' });
});
document.addEventListener('pointerdown', event => {
  if (!moreMenu.hidden && !event.target.closest('#moreMenu, #moreButton')) setMore(false);
});
// Capture phase: Escape closes the menu first, and only a second Escape hides the whole panel.
document.addEventListener('keydown', event => {
  if (moreMenu.hidden) return;
  if (event.key === 'Escape') {
    event.stopPropagation();
    setMore(false);
    moreButton.focus({ preventScroll: true });
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    const items = [$('moreOpen'), $('moreQuit')];
    items[(items.indexOf(document.activeElement) + 1) % items.length].focus({ preventScroll: true });
  }
}, true);
// While typing, the line under the field says what was understood as a time, before anything is saved.
// pending: a time chosen with the buttons, kept until the note is saved. "minutes" counts from the moment of saving.
let pending = null;
const pendingDue = () => (pending ? (pending.minutes ? Date.now() + pending.minutes * 60000 : pending.at) : 0);
function showNoteHint() {
  const hint = $('noteHint');
  const due = pendingDue() || parseReminder($('noteInput').value)?.due;
  if (due) hint.textContent = `Reminder · ${dueLabel(due)}`;
  hint.hidden = !due;
  hint.toggleAttribute('data-clearable', !!pending);
  hint.title = pending ? 'Remove reminder' : '';
  $('noteKeys').hidden = !!due;
  document.querySelector('.composer').toggleAttribute('data-typing', !!$('noteInput').value);
}
$('noteHint').addEventListener('click', () => {
  if (!pending) return;
  pending = null;
  showNoteHint();
  $('noteInput').focus({ preventScroll: true });
});

// The reminder picker (the clock beside the field): a few ready-made times, and a time set by hand.
const remindPop = $('remindPop');
let custom = 0; // the moment the steppers show
function paintCustom() {
  const now = Date.now();
  $('remindDay').textContent = dayLabel(custom, now);
  $('remindHour').textContent = hourText(custom);
  $('remindMinute').textContent = minuteText(custom);
  $('remindSet').disabled = !canSet(custom, now);
}
function choose(choice) {
  pending = choice;
  setRemind(false);
  showNoteHint();
  $('noteInput').focus({ preventScroll: true });
}
function setRemind(open) {
  remindPop.hidden = !open;
  $('remindButton').setAttribute('aria-expanded', String(open));
  if (!open) return;
  const now = Date.now();
  $('remindQuick').replaceChildren(...quickChoices(now).map(choice => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'remind-chip';
    const label = document.createElement('span');
    label.textContent = choice.label;
    button.append(label);
    if (choice.time) {
      const time = document.createElement('small');
      time.textContent = choice.time;
      button.append(time);
    }
    button.addEventListener('click', () => choose(choice.minutes ? { minutes: choice.minutes } : { at: choice.at }));
    return button;
  }));
  custom = pending?.at && pending.at > now ? pending.at : startingMoment(now);
  paintCustom();
}
$('remindButton').addEventListener('click', () => setRemind(remindPop.hidden));
for (const stepper of remindPop.querySelectorAll('.stepper')) {
  for (const button of stepper.querySelectorAll('button')) {
    button.addEventListener('click', () => {
      custom = stepMoment(custom, stepper.dataset.field, Number(button.dataset.dir));
      paintCustom();
    });
  }
}
$('remindSet').addEventListener('click', () => {
  if (canSet(custom)) choose({ at: custom });
});
// Pressing a button here must not take the keyboard away from the note field.
for (const element of [remindPop, $('remindButton'), $('noteHint')]) element.addEventListener('mousedown', event => event.preventDefault());
document.addEventListener('pointerdown', event => {
  if (!remindPop.hidden && !event.target.closest('#remindPop, #remindButton')) setRemind(false);
});
// Capture phase, like the menus: Escape closes the picker first, and only a second Escape hides the panel.
document.addEventListener('keydown', event => {
  if (remindPop.hidden || event.key !== 'Escape') return;
  event.stopPropagation();
  setRemind(false);
}, true);
$('noteInput').addEventListener('input', showNoteHint);
$('noteInput').addEventListener('focus', () => { inputFocused = true; syncHold(); });
$('noteInput').addEventListener('blur', () => { inputFocused = false; syncHold(); });
$('noteInput').addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.isComposing) return; // Escape bubbles up and hides the panel
  event.preventDefault();
  addNote(event.metaKey || event.ctrlKey ? 'todo' : 'note');
});
// Deliver: files waiting on the shelf. The app does the real dragging, in and out, because a web page never gets
// the path of a dropped file; this page keeps the list and tells the app which files a press on a row would drag.
let selected = new Set(); // ids of the rows picked to be dragged together
let lastPicked = '';
let carrying = [];        // ids of the files that are being dragged out right now
let deliverSettings = { remove_after_drop: false, auto_catch: false, expire_hours: 0 };
let zipping = false; // a zip is being made
let deliverProblem = null; // why Auto-catch cannot read the Downloads folder, when it cannot

function sizeText(bytes) {
  if (!Number.isFinite(bytes)) return '';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

function hintText() {
  const ready = deliver.filter(item => !item.missing).length;
  if (!deliver.length) return deliverSettings.auto_catch ? 'Catching downloads' : 'Drop files on the notch';
  if (!ready) return 'Nothing left to deliver';
  if (selected.size) return `${selected.size} selected · drag out`;
  return `${ready} ${ready === 1 ? 'file' : 'files'} · drag out`;
}

// Selection changes repaint the rows that are there, so a press on a row is never swallowed by a rebuilt list.
function paintSelection() {
  for (const row of $('deliverList').children) row.toggleAttribute('data-selected', selected.has(row.dataset.id));
  $('deliverHint').textContent = hintText();
}

// Tells the app which files a press on the shelf would drag if the pointer now moves with the button down.
function carryOut(entries) {
  carrying = entries.map(entry => entry.id);
  if (entries.length) tell({ type: 'deliverArm', paths: entries.map(entry => entry.path) });
}

// A press on a row picks it (⌘ adds or removes it, ⇧ takes a range) and arms the drag of everything picked.
function pressRow(event, item) {
  if (event.button !== 0 || item.missing || event.target.closest('.file-remove')) return;
  const additive = event.metaKey || event.ctrlKey;
  if (event.shiftKey && lastPicked) {
    const ids = deliver.filter(entry => !entry.missing).map(entry => entry.id);
    const from = ids.indexOf(lastPicked);
    const to = ids.indexOf(item.id);
    selected = from >= 0 && to >= 0 ? new Set(ids.slice(Math.min(from, to), Math.max(from, to) + 1)) : new Set([item.id]);
  } else if (additive) {
    if (selected.has(item.id)) {
      selected.delete(item.id); // taken out of the picked files: nothing to drag from this row
      lastPicked = item.id;
      paintSelection();
      return;
    }
    selected.add(item.id);
  } else if (!selected.has(item.id)) {
    selected = new Set([item.id]);
  }
  if (!event.shiftKey) lastPicked = item.id;
  paintSelection();
  carryOut(deliver.filter(entry => selected.has(entry.id) && !entry.missing));
}

// A plain click (no drag) on one of several picked rows leaves just that row picked, as in Finder.
function clickRow(event, item) {
  if (item.missing || event.shiftKey || event.metaKey || event.ctrlKey || event.target.closest('.file-remove')) return;
  if (selected.size > 1 && selected.has(item.id)) {
    selected = new Set([item.id]);
    paintSelection();
  }
}

function deliverRow(item) {
  const li = document.createElement('li');
  li.className = 'file';
  li.dataset.id = item.id;
  li.dataset.kind = item.kind;
  li.toggleAttribute('data-missing', !!item.missing);
  li.toggleAttribute('data-selected', selected.has(item.id));
  li.title = item.missing ? `${item.path} (moved or deleted)` : item.path;
  const icon = document.createElement('span');
  icon.className = 'file-icon';
  const extension = item.name.includes('.') ? item.name.split('.').pop() : '';
  icon.textContent = item.kind === 'folder' ? 'DIR' : (extension.slice(0, 4) || 'FILE');
  const name = document.createElement('span');
  name.className = 'file-name';
  name.textContent = item.name;
  const size = document.createElement('span');
  size.className = 'file-size';
  size.textContent = item.missing ? 'missing' : sizeText(item.size);
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'file-remove';
  remove.textContent = '×';
  remove.setAttribute('aria-label', `Remove from Deliver: ${item.name}`);
  remove.addEventListener('click', () => changeDeliver('/api/deliver/remove', { id: item.id }));
  li.addEventListener('pointerdown', event => pressRow(event, item));
  li.addEventListener('click', event => clickRow(event, item));
  li.append(icon, name, size, remove);
  return li;
}

const PROBLEMS = {
  denied: 'Relay is not allowed to open your Downloads folder. Allow it in System Settings › Privacy & Security › Files & Folders.',
  unreadable: 'Relay cannot read your Downloads folder right now.',
};

const EXPIRY = [[0, 'forever'], [1, '1 hour'], [6, '6 hours'], [24, '1 day'], [168, '1 week']]; // hours a file may stay, as the engine allows

function paintSettings() {
  $('deliverAuto').setAttribute('aria-pressed', String(!!deliverSettings.remove_after_drop));
  $('deliverCatch').setAttribute('aria-pressed', String(!!deliverSettings.auto_catch));
  const keep = EXPIRY.find(([hours]) => hours === deliverSettings.expire_hours) || EXPIRY[0];
  $('deliverExpire').textContent = `Keep: ${keep[1]}`;
  $('deliverExpire').setAttribute('aria-pressed', String(keep[0] > 0));
  // The options are folded away; the button shows when one of them is on.
  $('deliverOptionsButton').toggleAttribute('data-active', !!(deliverSettings.remove_after_drop || deliverSettings.auto_catch || keep[0]));
  const problem = deliverSettings.auto_catch && deliverProblem ? PROBLEMS[deliverProblem] || PROBLEMS.unreadable : '';
  $('deliverNotice').textContent = problem;
  $('deliverNotice').hidden = !problem;
  $('deliverHint').textContent = hintText();
}

function renderDeliver() {
  const list = $('deliverList');
  const top = list.scrollTop;
  const ready = new Set(deliver.filter(item => !item.missing).map(item => item.id));
  selected = new Set([...selected].filter(id => ready.has(id))); // a file that went away is no longer picked
  list.replaceChildren(...deliver.map(deliverRow));
  list.scrollTop = top;
  $('deliverEmpty').hidden = deliver.length > 0;
  $('deliverHint').textContent = hintText();
  $('deliverAll').disabled = ready.size < 2;
  $('deliverZip').disabled = zipping || !ready.size;
  $('deliverZip').textContent = zipping ? 'Zipping…' : 'Zip';
  $('deliverClear').disabled = !deliver.length;
  $('deliverCount').textContent = String(ready.size);
  $('deliverCount').hidden = ready.size === 0;
  paintSettings();
}

async function loadDeliver() {
  try {
    const data = await fetch('/api/deliver', { cache: 'no-store' }).then(r => r.json());
    if (!Array.isArray(data.items)) return;
    const valid = typeof data.settings?.remove_after_drop === 'boolean' && typeof data.settings?.auto_catch === 'boolean'
      && Number.isInteger(data.settings?.expire_hours);
    const settings = valid ? data.settings : deliverSettings;
    const problem = typeof data.problem === 'string' ? data.problem : null;
    if (JSON.stringify([data.items, settings, problem]) === JSON.stringify([deliver, deliverSettings, deliverProblem])) return;
    deliver = data.items;
    deliverSettings = settings;
    deliverProblem = problem;
    renderDeliver();
  } catch (_) {
    /* The next poll will bring the engine back; the shelf keeps its last list. */
  }
}

async function changeDeliver(path, body) {
  $('deliverError').textContent = '';
  try {
    deliver = (await post(path, body)).items;
    renderDeliver();
  } catch (error) {
    $('deliverError').textContent = error.message;
    loadDeliver();
  }
}

$('deliverAll').addEventListener('pointerdown', event => {
  if (event.button === 0) carryOut(deliver.filter(item => !item.missing));
});
$('deliverClear').addEventListener('click', () => changeDeliver('/api/deliver/clear', {}));
async function changeSetting(change) {
  $('deliverError').textContent = '';
  try {
    deliverSettings = (await post('/api/deliver/settings', change)).settings;
    deliverProblem = null;
    paintSettings();
    return true;
  } catch (error) {
    $('deliverError').textContent = error.message;
    return false;
  }
}
$('deliverAuto').addEventListener('click', () => changeSetting({ remove_after_drop: !deliverSettings.remove_after_drop }));
$('deliverExpire').addEventListener('click', () => {
  const at = EXPIRY.findIndex(([hours]) => hours === deliverSettings.expire_hours);
  changeSetting({ expire_hours: EXPIRY[(at + 1) % EXPIRY.length][0] });
});
$('deliverOptionsButton').addEventListener('click', () => {
  const open = $('deliverOptions').hidden;
  $('deliverOptions').hidden = !open;
  $('deliverOptionsButton').setAttribute('aria-expanded', String(open));
});
// Zip: the picked files (all of them when none is picked) become one file on the shelf, which is then dragged out like any other.
$('deliverZip').addEventListener('click', async () => {
  const ready = deliver.filter(item => !item.missing);
  const picked = selected.size ? ready.filter(item => selected.has(item.id)) : ready;
  if (zipping || !picked.length) return;
  zipping = true;
  $('deliverError').textContent = '';
  renderDeliver();
  try {
    const data = await post('/api/deliver/zip', { ids: picked.map(item => item.id) });
    deliver = data.items;
    selected = new Set(deliver.filter(item => item.path === data.zip).map(item => item.id));
    lastPicked = [...selected][0] || '';
    $('deliverList').scrollTop = 0;
  } catch (error) {
    $('deliverError').textContent = error.message;
  } finally {
    zipping = false;
    renderDeliver();
  }
});
$('deliverCatch').addEventListener('click', async () => {
  // The engine looks at the folder every couple of seconds; ask again after its first look to show a problem if there is one.
  if (await changeSetting({ auto_catch: !deliverSettings.auto_catch }) && deliverSettings.auto_catch) setTimeout(loadDeliver, 2600);
});
// A press on the empty part of the list lets go of the picked rows.
$('deliverList').addEventListener('pointerdown', event => {
  if (event.target !== $('deliverList') || !selected.size) return;
  selected = new Set();
  paintSelection();
});

// The app calls these while files are dragged over the panel, when they are dropped, and when a drag out has ended.
window.relayDeliverDragState = over => $('panel').toggleAttribute('data-dropping', !!over);
window.relayDeliverDrop = async paths => {
  $('panel').removeAttribute('data-dropping');
  if (!Array.isArray(paths) || !paths.length) return;
  pickTab('deliver');
  $('deliverError').textContent = '';
  try {
    if (!token) await poll();
    deliver = (await post('/api/deliver/add', { paths })).items;
    renderDeliver();
  } catch (error) {
    $('deliverError').textContent = error.message;
  }
};
// accepted: somebody took the files. moved: they were moved, so they are no longer where the shelf has them.
window.relayDeliverDragEnded = async (accepted, moved) => {
  const ids = carrying;
  carrying = [];
  if (accepted && ids.length && (moved || deliverSettings.remove_after_drop)) {
    selected = new Set();
    await changeDeliver('/api/deliver/remove', { ids });
  } else {
    loadDeliver();
  }
};

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

// The colour of the cover, for the glow, the equalizer and the dot on the Music tab.
const colours = new Map();
function coverColour(src) {
  if (colours.has(src)) return Promise.resolve(colours.get(src));
  return new Promise(resolve => {
    const image = new Image();
    image.onload = () => {
      let found = null;
      try {
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 16;
        const context = canvas.getContext('2d', { willReadFrequently: true });
        context.drawImage(image, 0, 0, 16, 16);
        const data = context.getImageData(0, 0, 16, 16).data;
        let r = 0, g = 0, b = 0, weight = 0;
        for (let i = 0; i < data.length; i += 4) {
          const high = Math.max(data[i], data[i + 1], data[i + 2]);
          const low = Math.min(data[i], data[i + 1], data[i + 2]);
          // Vivid, bright pixels speak for the cover; grey and dark ones barely count.
          const w = ((high ? (high - low) / high : 0) ** 2) * (high / 255) + 0.01;
          r += data[i] * w; g += data[i + 1] * w; b += data[i + 2] * w; weight += w;
        }
        r /= weight; g /= weight; b /= weight;
        const top = Math.max(r, g, b);
        if (top > 0) {
          const lift = top < 170 ? 170 / top : 1; // dark covers still need a visible glow
          found = `rgb(${Math.min(255, Math.round(r * lift))}, ${Math.min(255, Math.round(g * lift))}, ${Math.min(255, Math.round(b * lift))})`;
        }
      } catch (_) {
        /* No canvas, or the image cannot be read: keep the default colour. */
      }
      colours.set(src, found);
      if (colours.size > 20) colours.delete(colours.keys().next().value);
      resolve(found);
    };
    image.onerror = () => resolve(null);
    image.src = src;
  });
}

// The cover frame takes the cover's own shape (9:16, 3:4, square, 16:9...), so the whole picture shows.
function resetCoverShape() {
  const style = $('panel').style;
  for (const name of ['--cover-w', '--cover-h', '--pill-w', '--pill-h']) style.removeProperty(name);
}

function fitInto(ratio, maxWidth, maxHeight) {
  const width = Math.min(maxWidth, maxHeight * ratio);
  return [Math.round(width), Math.round(width / ratio)];
}

function fitCoverShape() {
  const { naturalWidth: width, naturalHeight: height } = $('musicArt');
  const ratio = width && height ? Math.min(3, Math.max(0.5, width / height)) : 1;
  if (Math.abs(ratio - 1) < 0.03) {
    resetCoverShape(); // square covers fill the square frame
    return;
  }
  const style = $('panel').style;
  const [coverWidth, coverHeight] = fitInto(ratio, 150, 112);
  const [pillWidth, pillHeight] = fitInto(ratio, 38, 24);
  style.setProperty('--cover-w', `${coverWidth}px`);
  style.setProperty('--cover-h', `${coverHeight}px`);
  style.setProperty('--pill-w', `${pillWidth}px`);
  style.setProperty('--pill-h', `${pillHeight}px`);
}
$('musicArt').addEventListener('load', fitCoverShape);

// What gives off light: agents at work, or music. The Music view prefers the music, everything else the agents.
function updateGlow() {
  const panel = $('panel');
  const working = !!current?.running && !current.paused;
  const playing = !!music?.playing;
  let glow = '';
  if (mode === 'pill') glow = playing ? 'music' : '';
  else if (view === 'music') glow = playing ? 'music' : working ? 'agent' : '';
  else glow = working ? 'agent' : playing ? 'music' : '';
  if (glow) panel.dataset.glow = glow;
  else delete panel.dataset.glow;
  room.setMusic(playing && officeMusicEnabled);
  $('officeMusic').hidden = !playing;
}

function renderMusic() {
  const panel = $('panel');
  if (!music) {
    delete panel.dataset.music;
    panel.style.removeProperty('--cover');
    resetCoverShape();
    $('musicTitle').textContent = 'Nothing is playing';
    $('musicArtist').textContent = 'Start music in any app and it shows up here.';
    $('music').removeAttribute('data-playing');
    $('pill').removeAttribute('data-playing');
    tabs.music.removeAttribute('data-live');
    $('musicArt').hidden = true;
    $('pillArt').hidden = true;
    $('musicSource').hidden = true;
    musicArt = '';
    musicTrack = '';
    fx.setPlaying(false);
    fx.setColour('');
    if (view === 'music' && mode === 'pill') setView(fallbackView(), { focus: false });
    updateGlow();
    return;
  }
  panel.dataset.music = '1';
  const artist = music.artist || music.album || '';
  const track = `${music.title}\n${artist}`;
  if (track !== musicTrack) {
    musicTrack = track;
    fx.setTrack(track); // every track gets its own tempo and phrasing
  }
  fx.setPlaying(!!music.playing);
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
    panel.style.removeProperty('--cover');
    if (!art) fx.setColour(''); // with a cover, the old colours stay until the new cover's arrive: no flash of the default
    resetCoverShape();
    if (art) coverColour(art).then(colour => {
      if (!colour || art !== musicArt) return;
      panel.style.setProperty('--cover', colour);
      fx.setColour(colour);
    });
  }
  $('musicArt').hidden = !art;
  $('pillArt').hidden = !art;
  // Where the sound comes from: the app's icon and name, when the app told us.
  const appName = typeof music.appName === 'string' ? music.appName : '';
  const appIcon = typeof music.appIcon === 'string' && music.appIcon.startsWith('data:image/png') ? music.appIcon : '';
  $('musicSource').hidden = !appName;
  $('musicApp').textContent = appName;
  $('musicAppIcon').hidden = !appIcon;
  if (appIcon && $('musicAppIcon').getAttribute('src') !== appIcon) $('musicAppIcon').src = appIcon;
  updateGlow();
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
  setFxPicker(false); // a freshly shown panel never starts with the picker open
  setMore(false);
  setRemind(false);
  applyTabs(); // the window may have changed the tabs while the panel was away
  fx.setScene({ mode, view });
  updateGlow();
  // A new appearance starts without the keyboard: typing begins only when the person clicks the note field.
  const wasHolding = holding;
  $('noteInput').blur();
  inputFocused = false;
  holding = false;
  if (wasHolding) tell({ type: 'hold', on: false });
  if (mode === 'pill') return;
  let target = typeof info.view === 'string' ? info.view : chosenView;
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
document.addEventListener('visibilitychange', () => {
  fx.refresh(); // stops drawing while the panel is hidden, and picks up again when it shows
  if (!document.hidden && view === 'office') room.start();
  else room.stop();
});
window.addEventListener('pagehide', () => {
  room.stop();
  collaboration.hideHandoff();
});
render(null);
renderMusic();
renderDeliver();
applyTabs();
setView('notes', { focus: false });
loadNotes();
loadDeliver();
poll();
setInterval(poll, 1000);
setInterval(tickTimer, 1000);
setInterval(tickProgress, 500);
// A file may have been moved or deleted since; with Auto-catch or a time limit on, the shelf changes by itself on any tab.
setInterval(() => { if ((view === 'deliver' || deliverSettings.auto_catch || deliverSettings.expire_hours) && mode !== 'pill') loadDeliver(); }, 3000);
