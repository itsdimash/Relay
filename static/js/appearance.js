// The small switches in the header: the language (Automatic, English, Русский), the appearance (System, Light or Night)
// and, in the Mac app only, how Relay starts. theme.js and i18n.js (loaded first) do the work; this is only the menus.
import { $ } from './dom.js';

const THEMES = ['system', 'light', 'night'];

// One popup menu of radio items. `attribute` is the data-* name that carries each item's value.
function createSwitch({ button, menu, attribute, current, choose, changed }) {
  const items = () => [...menu.querySelectorAll('[role="menuitemradio"]')];

  function paint() {
    const value = current();
    for (const item of items()) item.setAttribute('aria-checked', String(item.dataset[attribute] === value));
  }

  function setOpen(open, { focus = false } = {}) {
    menu.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    if (open) {
      paint();
      const selected = items().find(item => item.getAttribute('aria-checked') === 'true') || items()[0];
      selected.focus({ preventScroll: true });
    } else if (focus) {
      button.focus({ preventScroll: true });
    }
  }

  button.addEventListener('click', () => setOpen(menu.hidden));
  for (const item of items()) {
    item.addEventListener('click', () => {
      choose(item.dataset[attribute]);
      paint();
      setOpen(false, { focus: true });
    });
  }
  document.addEventListener('pointerdown', event => {
    if (!menu.hidden && !menu.contains(event.target) && !button.contains(event.target)) setOpen(false);
  });
  document.addEventListener('keydown', event => {
    if (menu.hidden) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false, { focus: true });
    } else if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      const list = items();
      const at = list.indexOf(document.activeElement);
      const next = event.key === 'ArrowDown' ? (at + 1) % list.length : (at - 1 + list.length) % list.length;
      list[next].focus({ preventScroll: true });
    } else if (event.key === 'Tab') {
      setOpen(false);
    }
  });
  window.addEventListener(changed, paint);
  paint();
}

// A popup menu of check items (they stay open when one is pressed, so several can be set in one go).
function createChecklist({ button, menu, onOpen, onPick }) {
  const items = () => [...menu.querySelectorAll('[role="menuitemcheckbox"]')];

  function setOpen(open, { focus = false } = {}) {
    menu.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    if (open) {
      if (onOpen) onOpen();
      items()[0].focus({ preventScroll: true });
    } else if (focus) {
      button.focus({ preventScroll: true });
    }
  }

  button.addEventListener('click', () => setOpen(menu.hidden));
  for (const item of items()) item.addEventListener('click', () => { if (item.getAttribute('aria-disabled') !== 'true') onPick(item); });
  document.addEventListener('pointerdown', event => {
    if (!menu.hidden && !menu.contains(event.target) && !button.contains(event.target)) setOpen(false);
  });
  document.addEventListener('keydown', event => {
    if (menu.hidden) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false, { focus: true });
    } else if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      const list = items();
      const at = list.indexOf(document.activeElement);
      list[(at + (event.key === 'ArrowDown' ? 1 : -1) + list.length) % list.length].focus({ preventScroll: true });
    } else if (event.key === 'Tab') {
      setOpen(false);
    }
  });
  return { items, setOpen };
}

// Startup (Mac app only): open at login, open this window at start, hide the Dock icon. The choices live in the app, so the
// page only shows what the app says and asks for changes; a login item macOS refuses therefore shows as off.
function createStartup() {
  const native = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.relayWindow;
  const button = $('startupButton');
  const menu = $('startupMenu');
  if (!native || !button || !menu) return; // in a browser there is no app to start, so the button stays hidden
  const tell = message => { try { native.postMessage(message); } catch (_) {} };
  button.hidden = false;
  const list = createChecklist({
    button,
    menu,
    onOpen: () => tell({ type: 'startup' }), // ask for the real choices
    onPick: item => tell({ type: 'startup', name: item.dataset.startup, on: item.getAttribute('aria-checked') !== 'true' })
  });
  // The app answers when the menu opens and after every change.
  window.relayStartup = settings => {
    for (const item of list.items()) item.setAttribute('aria-checked', String(!!(settings && settings[item.dataset.startup])));
  };
}

// The notch panel's tabs and alerts. The choices are saved in the browser storage that this window and the panel share
// (same address), and the panel reads them when it opens and when they change.
const NOTCH_TABS_KEY = 'relay.notchTabs';
const BATTERY_ALERTS_KEY = 'relay.batteryAlerts';

function createNotchMenu() {
  const button = $('notchButton');
  const menu = $('notchMenu');
  if (!button || !menu) return;
  const read = key => { try { return localStorage.getItem(key); } catch (_) { return null; } };
  const write = (key, value) => { try { localStorage.setItem(key, value); } catch (_) {} };
  const hiddenTabs = () => {
    try {
      const saved = JSON.parse(read(NOTCH_TABS_KEY) || 'null');
      return new Set(Array.isArray(saved && saved.hidden) ? saved.hidden : []);
    } catch (_) {
      return new Set();
    }
  };
  const list = createChecklist({ button, menu, onOpen: paint, onPick: pick });

  function paint() {
    const hidden = hiddenTabs();
    for (const item of list.items()) {
      if (item.dataset.tab) item.setAttribute('aria-checked', String(!hidden.has(item.dataset.tab)));
      else if (item.dataset.alert === 'battery') item.setAttribute('aria-checked', String(read(BATTERY_ALERTS_KEY) !== 'off'));
    }
  }

  function pick(item) {
    if (item.dataset.tab) {
      const hidden = hiddenTabs();
      if (hidden.has(item.dataset.tab)) hidden.delete(item.dataset.tab);
      else hidden.add(item.dataset.tab);
      hidden.delete('task'); // plans wait in the Task tab, so it always stays
      write(NOTCH_TABS_KEY, JSON.stringify({ hidden: [...hidden] }));
    } else if (item.dataset.alert === 'battery') {
      write(BATTERY_ALERTS_KEY, read(BATTERY_ALERTS_KEY) === 'off' ? 'on' : 'off');
    }
    paint();
  }
  paint();
}

export function createAppearance() {
  return {
    init() {
      createStartup();
      createNotchMenu();
      createSwitch({
        button: $('themeButton'),
        menu: $('themeMenu'),
        attribute: 'theme',
        current: () => (window.relayTheme ? window.relayTheme.choice : 'light'),
        choose: value => { if (window.relayTheme && THEMES.includes(value)) window.relayTheme.set(value); },
        changed: 'relaythemechange'
      });
      const i18n = window.relayI18n;
      createSwitch({
        button: $('langButton'),
        menu: $('langMenu'),
        attribute: 'lang',
        current: () => (i18n ? i18n.choice : 'auto'),
        choose: value => { if (i18n && i18n.CHOICES.includes(value)) i18n.set(value); },
        changed: 'relaylangchange'
      });
    }
  };
}
