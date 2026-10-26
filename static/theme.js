// The saved appearance, applied before the page is painted so there is no flash of the wrong theme.
// This is a plain script (not a module) loaded in <head>. The choice is "system", "light" or "night";
// the page sees the result as data-theme="light" or data-theme="night" on <html>.
(() => {
  const KEY = 'relay.theme';
  const CHOICES = ['system', 'light', 'night'];
  const root = document.documentElement;
  const media = typeof matchMedia === 'function' ? matchMedia('(prefers-color-scheme: dark)') : null;

  const read = () => {
    try {
      const saved = localStorage.getItem(KEY);
      return CHOICES.includes(saved) ? saved : 'light';
    } catch (_) {
      return 'light';
    }
  };

  let choice = read();
  let applied = null;
  const resolve = () => (choice === 'system' ? (media && media.matches ? 'night' : 'light') : choice);

  function apply() {
    const theme = resolve();
    applied = theme;
    root.setAttribute('data-theme', theme);
    root.setAttribute('data-theme-choice', choice);
    // The native window follows, so the title bar, scroll bars and the colour behind the page match.
    try {
      window.webkit.messageHandlers.relayWindow.postMessage({ type: 'theme', night: theme === 'night', choice });
      // Choosing System frees the window from a forced dark or light look, which changes what the page sees as the
      // Mac's setting. Look once more after that has happened.
      if (choice === 'system') setTimeout(() => { if (choice === 'system' && resolve() !== applied) apply(); }, 150);
    } catch (_) {}
    window.dispatchEvent(new CustomEvent('relaythemechange', { detail: { choice, theme } }));
  }

  window.relayTheme = {
    CHOICES,
    get choice() { return choice; },
    get theme() { return resolve(); },
    set(next) {
      if (!CHOICES.includes(next)) return;
      choice = next;
      try {
        localStorage.setItem(KEY, next);
      } catch (_) {}
      apply();
    }
  };

  const follow = () => { if (choice === 'system') apply(); };
  if (media) (media.addEventListener ? media.addEventListener('change', follow) : media.addListener(follow));
  // Another window of the dashboard changed it.
  window.addEventListener('storage', event => {
    if (event.key === KEY) {
      choice = read();
      apply();
    }
  });
  apply();
})();
