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

// Startup (Mac app only): open at login, open this window at start, hide the Dock icon. The choices live in the app, so the
// page only shows what the app says and asks for changes; a login item macOS refuses therefore shows as off.
function createStartup() {
  const native = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.relayWindow;
  const button = $('startupButton');
  const menu = $('startupMenu');
  if (!native || !button || !menu) return; // in a browser there is no app to start, so the button stays hidden
  const tell = message => { try { native.postMessage(message); } catch (_) {} };
  const items = () => [...menu.querySelectorAll('[role="menuitemcheckbox"]')];
  button.hidden = false;

  function setOpen(open, { focus = false } = {}) {
    menu.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    if (open) {
      tell({ type: 'startup' }); // ask for the real choices
      items()[0].focus({ preventScroll: true });
    } else if (focus) {
      button.focus({ preventScroll: true });
    }
  }

  // The app answers when the menu opens and after every change.
  window.relayStartup = settings => {
    for (const item of items()) item.setAttribute('aria-checked', String(!!(settings && settings[item.dataset.startup])));
  };
  button.addEventListener('click', () => setOpen(menu.hidden));
  for (const item of items()) {
    // The menu stays open: several choices can be set in one go.
    item.addEventListener('click', () => tell({ type: 'startup', name: item.dataset.startup, on: item.getAttribute('aria-checked') !== 'true' }));
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
      list[(at + (event.key === 'ArrowDown' ? 1 : -1) + list.length) % list.length].focus({ preventScroll: true });
    } else if (event.key === 'Tab') {
      setOpen(false);
    }
  });
}

export function createAppearance() {
  return {
    init() {
      createStartup();
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
