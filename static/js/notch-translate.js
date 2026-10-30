// The Translate page of the notch: type or paste text, pick English, Russian or Kazakh, and the translation appears below.
// The engine does the translating (Gemini) and keeps the API key; this file only draws the page and asks the panel to grow.
//
// The small panel has a fixed height. When a result is taller than the room it has, the page tells the app how much height it
// needs (tell 'fit') and the app grows the panel downward, up to a share of the screen. After that the result scrolls. Closing the
// panel clears the page, so the next opening starts clean at the usual size.

export const MAX_TEXT = 5000;
export const TARGET_KEY = 'relay.translateTarget';
export const TARGETS = ['en', 'ru', 'kk'];
// The 6px above the page inside the stage and the 14px of padding under it (notch.css: .stage, .panel).
export const PANEL_PADDING = 20;
const COPIED_MS = 1400;

// Only the first MAX_TEXT characters (whole characters, never half of an emoji).
export const clip = text => Array.from(String(text || '')).slice(0, MAX_TEXT).join('');
export const savedTarget = value => (TARGETS.includes(value) ? value : 'en');
export const direction = result => (result ? `${String(result.from || '?').toUpperCase()} → ${String(result.to || '').toUpperCase()}` : '');
// The height to ask the app for: what the page needs, or nothing when the page is not showing.
export const wantedHeight = (visible, contentHeight) => (visible && Number.isFinite(contentHeight) && contentHeight > 0 ? Math.ceil(contentHeight) + PANEL_PADDING : 0);

export function createTranslator({ post, tell, native = false, onHold = () => {}, onSpeak = () => {}, win = window }) {
  const $ = id => document.getElementById(id);
  const state = { target: 'en', configured: null, changing: false, busy: false, result: null, error: '', keyError: '', fitted: 0, run: 0, active: false, copied: 0, speakNext: false };
  try {
    state.target = savedTarget(localStorage.getItem(TARGET_KEY));
  } catch (_) {}

  const typedText = () => $('trInput').value.trim();
  const focused = () => document.activeElement === $('trInput') || document.activeElement === $('trKey');
  const wantsHold = () => state.active && (focused() || state.busy);

  function fit() {
    win.requestAnimationFrame(() => {
      const want = wantedHeight(state.active, $('trBody').offsetHeight);
      if (want === state.fitted) return;
      state.fitted = want;
      tell({ type: 'fit', height: want });
    });
  }

  // The key box shows when there is no key, or when the person asked to change it.
  const keyBoxShowing = () => state.configured === false || state.changing;

  function render() {
    const needsKey = keyBoxShowing();
    $('trSetup').hidden = !needsKey;
    $('trMain').hidden = needsKey;
    $('trKeyCancel').hidden = !(state.changing && state.configured);
    $('trKeyError').textContent = state.keyError;
    for (const button of $('trTargets').querySelectorAll('button')) {
      const on = button.dataset.target === state.target;
      button.setAttribute('aria-checked', String(on));
      button.tabIndex = on ? 0 : -1;
    }
    const result = state.result;
    $('trResult').hidden = !result;
    $('trText').textContent = result ? result.translation : '';
    $('trText').lang = result ? result.to : '';
    $('trLangs').textContent = direction(result);
    $('trCopy').textContent = state.copied ? 'Copied' : 'Copy';
    $('trGo').textContent = state.busy ? 'Translating…' : 'Translate';
    $('trGo').disabled = state.busy;
    $('trPaste').disabled = state.busy;
    $('trError').textContent = state.error;
    $('translate').toggleAttribute('data-busy', state.busy);
    onHold();
    fit();
  }

  // The field that is showing: the text box, or the key box when the key is still missing.
  function focusField() {
    if (!state.active) return;
    ($('trSetup').hidden ? $('trInput') : $('trKey')).focus();
  }

  async function load() {
    try {
      const data = await fetch('/api/translate', { cache: 'no-store' }).then(response => response.json());
      state.configured = !!data.configured;
    } catch (_) {
      state.configured = state.configured ?? true; // the engine is not answering; the first translation will say so
    }
    render();
  }

  async function translate() {
    const text = clip(typedText());
    if (!text || state.busy) return;
    const run = ++state.run;
    state.busy = true;
    state.error = '';
    render();
    try {
      const result = await post('/api/translate', { text, target: state.target });
      if (run !== state.run) return; // the page was cleared or closed while the answer was on its way
      state.result = result;
      if (state.speakNext) onSpeak(result); // it was asked for by voice: the answer may be said out loud
    } catch (error) {
      if (run !== state.run) return;
      state.result = null;
      state.error = error.message;
      if (/API key/.test(error.message) && /first|accept/.test(error.message)) {
        state.configured = false; // the key is missing or wrong: ask for it again
        state.changing = false;
        state.keyError = /accept/.test(error.message) ? error.message : '';
      }
    } finally {
      if (run === state.run) {
        state.busy = false;
        state.speakNext = false;
        render();
      }
    }
  }

  function setTarget(target) {
    if (!TARGETS.includes(target) || target === state.target) return;
    state.target = target;
    try {
      localStorage.setItem(TARGET_KEY, target);
    } catch (_) {}
    render();
    if (state.result && typedText()) translate(); // choosing another language is a request to translate again
  }

  function clear({ focus = true } = {}) {
    state.run += 1; // an answer that is still on its way is dropped
    state.busy = false;
    state.result = null;
    state.error = '';
    state.copied = 0;
    $('trInput').value = '';
    render();
    if (focus && !$('trMain').hidden) $('trInput').focus();
  }

  async function saveKey(event) {
    event.preventDefault();
    const key = $('trKey').value.trim();
    if (!key) return;
    $('trKeySave').disabled = true;
    state.keyError = '';
    try {
      const data = await post('/api/translate/key', { key });
      state.configured = !!data.configured;
      state.changing = false;
      state.error = '';
      $('trKey').value = '';
      render();
      if (state.configured) $('trInput').focus();
    } catch (error) {
      state.keyError = error.message;
      render();
    } finally {
      $('trKeySave').disabled = false;
    }
  }

  function copy() {
    const text = state.result?.translation;
    if (!text) return;
    if (native) tell({ type: 'copy', text });
    else navigator.clipboard?.writeText(text).catch(() => {});
    state.copied = Date.now();
    render();
    setTimeout(() => {
      if (Date.now() - state.copied >= COPIED_MS - 50) {
        state.copied = 0;
        render();
      }
    }, COPIED_MS);
  }

  // The Paste button asks the app for the clipboard (only now, when it is pressed) and translates what comes back.
  function paste() {
    if (state.busy) return;
    if (native) tell({ type: 'clipboard' });
    else navigator.clipboard?.readText().then(text => pasted(text)).catch(() => {});
  }

  function pasted(text) {
    const words = clip(String(text || '').trim());
    if (!words) {
      state.error = 'The clipboard has no text.';
      render();
      return;
    }
    $('trInput').value = words;
    translate();
  }

  $('trInput').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      translate();
    }
  });
  $('trInput').addEventListener('input', () => {
    if (state.error) {
      state.error = '';
      render();
    }
  });
  for (const id of ['trInput', 'trKey']) {
    $(id).addEventListener('focus', onHold);
    $(id).addEventListener('blur', () => setTimeout(onHold, 0));
  }
  $('trGo').addEventListener('click', translate);
  $('trPaste').addEventListener('click', paste);
  $('trCopy').addEventListener('click', copy);
  $('trClear').addEventListener('click', () => clear());
  $('trSetup').addEventListener('submit', saveKey);
  $('trChangeKey').addEventListener('click', () => {
    state.changing = true;
    state.keyError = '';
    $('trKey').value = '';
    render();
    focusField();
  });
  $('trKeyCancel').addEventListener('click', () => {
    state.changing = false;
    state.keyError = '';
    $('trKey').value = '';
    render();
    focusField();
  });
  for (const button of $('trTargets').querySelectorAll('button')) button.addEventListener('click', () => setTarget(button.dataset.target));

  return {
    wantsHold,
    focused,
    pasted,
    // Dictation: the words go into the text box as they are heard, and a problem is shown like any other.
    text: () => $('trInput').value,
    fill(text) {
      $('trInput').value = String(text || '');
      render();
    },
    listening(on) {
      $('trInput').closest('.tr-field')?.toggleAttribute('data-listening', !!on);
      $('trInput').placeholder = on ? 'Listening…' : 'Type or paste text…';
    },
    problem(message) {
      state.error = String(message || '');
      render();
    },
    dictatable: () => state.active && !keyBoxShowing(),
    // The person opened this page.
    enter({ focus = true } = {}) {
      state.active = true;
      if (state.configured === null) {
        render();
        load().then(() => { if (focus) focusField(); });
        return;
      }
      render();
      if (focus) focusField();
    },
    // The person went to another page: the panel goes back to its usual size.
    leave() {
      state.active = false;
      $('trInput').blur();
      $('trKey').blur();
      fit();
      onHold();
    },
    // The panel was closed: the next opening starts clean.
    reset() {
      clear({ focus: false });
      state.changing = false;
      state.keyError = '';
      $('trKey').value = '';
      state.fitted = 0;
      if (state.active) tell({ type: 'fit', height: 0 });
    },
    // The app changed the panel's shape and forgot what height was asked for: ask again.
    refit() {
      state.fitted = 0;
      if (state.active) fit();
    },
    blur() {
      $('trInput').blur();
      $('trKey').blur();
    },
    // A spoken "translate this to Russian": the language is chosen, and the words (or, with none, the clipboard) are translated.
    async request({ text = '', target, spoken = false }) {
      if (state.configured === null) await load();
      if (keyBoxShowing()) return; // the key box is showing: nothing can be translated before it is filled in
      if (TARGETS.includes(target)) {
        state.target = target;
        try {
          localStorage.setItem(TARGET_KEY, target);
        } catch (_) {}
      }
      state.result = null;
      state.error = '';
      state.speakNext = !!spoken;
      const words = clip(String(text || '').trim());
      if (words) {
        $('trInput').value = words;
        render();
        translate();
      } else {
        render();
        paste();
      }
    },
  };
}
