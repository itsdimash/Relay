// Relay language support. English is the source language; every other language is a dictionary of the
// exact English strings the app shows (plus patterns for sentences that contain numbers or names), so
// the app code never has to know about translations. It runs in the dashboard and in the notch panel.
//
// Loaded before the page paints. A MutationObserver translates text and a few attributes as the page is
// built and as the app updates it, and remembers the English original of everything it changes so that
// switching back to English (or to another language) is exact.
(function () {
  'use strict';
  var KEY = 'relay.lang';
  var CHOICES = ['auto', 'en', 'ru'];
  var LANGS = ['en', 'ru'];
  var LOCALES = { en: undefined, ru: 'ru-RU' };
  var ATTRS = ['title', 'aria-label', 'placeholder', 'alt'];
  // Never translated: code, and what the person typed into a field. A textarea's placeholder is the app's own
  // text and is translated.
  var SKIP = 'script,style,textarea,code,pre,[translate="no"]';
  var SKIP_ATTRIBUTES = 'script,style,code,pre,[translate="no"]';
  // The person's and the agents' own writing (reports, chat titles, task text). Only whole-string entries
  // apply there, never templates with free-text holes, so a title such as "Open dashboard" stays as written.
  var STRICT = '.report-content,[data-i18n-strict],.history-title,#runBriefText,.followup-question';
  var dictionaries = {};
  var choice = 'auto';
  var active = 'en';
  var observer = null;
  var texts = new WeakMap();   // Text node -> { src, out }
  var attrs = new WeakMap();   // Element -> { name: { src, out } }

  try {
    var saved = localStorage.getItem(KEY);
    if (CHOICES.indexOf(saved) !== -1) choice = saved;
  } catch (_) { /* storage can be blocked; fall back to automatic */ }

  function systemLanguage() {
    var list = (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || 'en']);
    for (var i = 0; i < list.length; i++) {
      var code = String(list[i] || '').slice(0, 2).toLowerCase();
      if (LANGS.indexOf(code) !== -1) return code;
    }
    return 'en';
  }

  function resolve() {
    return choice === 'auto' ? systemLanguage() : choice;
  }

  // Russian, like other Slavic languages, has three plural forms: 1 file, 2 файла, 5 файлов.
  function plural(n, one, few, many) {
    var mod10 = Math.abs(n) % 10;
    var mod100 = Math.abs(n) % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
    return many;
  }

  // A template is a sentence with holes: "Round {#n} of {#m}" matches "Round 2 of 3" ({#x} is a number,
  // {x} is any text up to a separator, {*x} is any text at all) and is written out as "Раунд {n} из {m}". In the written-out form {x!} translates
  // the captured text too, and {x?file|files|many} picks the plural form for the number x.
  function template(source, target, pluralize) {
    var names = [];
    var pattern = '^';
    var last = 0;
    var escape = function (literal) { return literal.replace(/[.*+?^$()|[\]\\]/g, '\\$&'); };
    source.replace(/\{([#*]?)(\w+)\}/g, function (all, kind, name, offset) {
      names.push(name);
      pattern += escape(source.slice(last, offset));
      // A hole stops at " · ", " / " and line breaks, so lists of pieces are translated piece by piece;
      // {*x} may contain them.
      pattern += kind === '#' ? '(\\d+)' : kind === '*' ? '([\\s\\S]+?)' : '((?:(?! · | / |\\n)[\\s\\S])+?)';
      last = offset + all.length;
      return all;
    });
    pattern += escape(source.slice(last)) + '$';
    var expression = new RegExp(pattern);
    var free = names.length > 0 && /\{[*]?\w+\}/.test(source.replace(/\{#\w+\}/g, ''));
    return [expression, function () {
      var values = {};
      for (var i = 0; i < names.length; i++) values[names[i]] = arguments[i];
      return target.replace(/\{(\w+)(!|\?([^}]*))?\}/g, function (all, name, mark, forms) {
        if (!Object.prototype.hasOwnProperty.call(values, name)) return all;
        var value = values[name];
        if (mark === '!') return api.translate(value);
        if (forms !== undefined) {
          var list = forms.split('|');
          return (pluralize || plural)(Number(value), list[0], list[1] === undefined ? list[0] : list[1], list[2] === undefined ? list[0] : list[2]);
        }
        return value;
      });
    }, free];
  }

  // One whole string: an exact entry first, then a pattern.
  function whole(dictionary, key, strict) {
    if (Object.prototype.hasOwnProperty.call(dictionary.exact, key)) return dictionary.exact[key];
    var patterns = dictionary.patterns || [];
    for (var i = 0; i < patterns.length; i++) {
      if (strict && patterns[i][2]) continue;
      var match = patterns[i][0].exec(key);
      if (match) {
        var result = patterns[i][1].apply(null, match.slice(1));
        if (typeof result === 'string' && result !== key) return result;
      }
    }
    return null;
  }

  // Lines and "A · B · C" or "A / B" lists are translated piece by piece when the whole text is not an entry.
  var SEPARATORS = ['\n', ' · ', ' / '];

  function piecewise(dictionary, text, level) {
    var key = text.replace(/\s+/g, ' ').trim();
    if (!key || !/[A-Za-z]/.test(key)) return null;
    var done = level === 0 ? null : whole(dictionary, key);
    if (done !== null) return done;
    for (var i = level; i < SEPARATORS.length; i++) {
      var parts = text.split(SEPARATORS[i]);
      if (parts.length < 2) continue;
      var changed = false;
      var out = parts.map(function (part) {
        var lead = part.match(/^\s*/)[0];
        var trail = part.match(/\s*$/)[0];
        var inner = part.slice(lead.length, part.length - trail.length);
        var result = inner ? piecewise(dictionary, inner, i + 1) : null;
        if (result === null) return part;
        changed = true;
        return lead + result + trail;
      });
      return changed ? out.join(SEPARATORS[i]) : null;
    }
    return null;
  }

  function translate(text, strict) {
    var dictionary = dictionaries[active];
    if (!dictionary) return null;
    var key = text.replace(/\s+/g, ' ');
    if (Object.prototype.hasOwnProperty.call(dictionary.exact, key)) return dictionary.exact[key];
    // Text with line breaks is several lines first (a wrapped paragraph in the HTML source is not).
    if (!strict && text.indexOf('\n') !== -1) {
      var lines = piecewise(dictionary, text, 0);
      if (lines !== null) return lines;
    }
    var done = whole(dictionary, key, strict);
    return done !== null || strict ? done : piecewise(dictionary, text, 0);
  }

  function skipped(node, selector) {
    var element = node.nodeType === 1 ? node : node.parentElement;
    return !element || !!(element.closest && element.closest(selector || SKIP));
  }

  function strictAt(node) {
    var element = node.nodeType === 1 ? node : node.parentElement;
    return !!(element && element.closest && element.closest(STRICT));
  }

  function text(node) {
    if (skipped(node)) return;
    var record = texts.get(node);
    var current = node.nodeValue;
    var source = record && current === record.out ? record.src : current;
    var out = source;
    if (active !== 'en' && /[A-Za-z]/.test(source)) {
      var lead = source.match(/^\s*/)[0];
      var trail = source.match(/\s*$/)[0];
      var core = source.slice(lead.length, source.length - trail.length);
      var done = core ? translate(core, strictAt(node)) : null;
      if (done !== null) out = lead + done + trail;
    }
    if (out === source && !record) return;
    if (out !== current) node.nodeValue = out;
    if (out === source) texts.delete(node); else texts.set(node, { src: source, out: out });
  }

  function attribute(element, name) {
    if (!element.hasAttribute(name) || skipped(element, SKIP_ATTRIBUTES)) return;
    var all = attrs.get(element) || {};
    var record = all[name];
    var current = element.getAttribute(name);
    var source = record && current === record.out ? record.src : current;
    var out = source;
    if (active !== 'en' && /[A-Za-z]/.test(source)) {
      var done = translate(source.trim(), strictAt(element));
      if (done !== null) out = done;
    }
    if (out === source && !record) return;
    if (out !== current) element.setAttribute(name, out);
    if (out === source) delete all[name]; else all[name] = { src: source, out: out };
    attrs.set(element, all);
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { text(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    var start = root.nodeType === 9 ? root.documentElement : root;
    if (!start) return;
    if (start.nodeType === 1 && start.closest && start.closest(SKIP_ATTRIBUTES)) return;
    var list = document.createTreeWalker(start, 1 | 4, {
      acceptNode: function (node) {
        if (node.nodeType === 1 && (/^(SCRIPT|STYLE|CODE|PRE)$/.test(node.tagName) || node.getAttribute('translate') === 'no')) return 2; // reject subtree
        return 1;
      }
    });
    var node = start.nodeType === 1 ? start : list.nextNode();
    while (node) {
      if (node.nodeType === 3) text(node);   // text() leaves a textarea's own text alone
      else for (var i = 0; i < ATTRS.length; i++) attribute(node, ATTRS[i]);
      node = list.nextNode();
    }
  }

  function observe() {
    if (observer || !window.MutationObserver) return;
    observer = new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var record = records[i];
        if (record.type === 'characterData') text(record.target);
        else if (record.type === 'attributes') attribute(record.target, record.attributeName);
        else for (var j = 0; j < record.addedNodes.length; j++) walk(record.addedNodes[j]);
      }
    });
    observer.observe(document.documentElement, {
      childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS
    });
  }

  function apply() {
    active = resolve();
    if (!dictionaries[active]) active = 'en';
    document.documentElement.lang = active;
    walk(document);
  }

  function set(next) {
    if (CHOICES.indexOf(next) === -1) return;
    choice = next;
    try { localStorage.setItem(KEY, next); } catch (_) { /* keep the choice for this session */ }
    apply();
    window.dispatchEvent(new CustomEvent('relaylangchange', { detail: { choice: choice, language: active } }));
  }

  var api = {
    CHOICES: CHOICES,
    plural: plural,
    translate: function (value, strict) {
      var done = translate(String(value), strict);
      return done === null ? String(value) : done;
    },
    template: template,
    register: function (language, dictionary) {
      var compiled = (dictionary.patterns || []).slice();
      (dictionary.templates || []).forEach(function (pair) { compiled.push(template(pair[0], pair[1], dictionary.plural)); });
      dictionaries[language] = { exact: dictionary.exact || {}, patterns: compiled };
      if (resolve() === language) apply();
    },
    set: set,
    apply: apply,
    locale: function () { return LOCALES[active]; },
    get choice() { return choice; },
    get language() { return active; }
  };
  window.relayI18n = api;

  active = resolve();
  document.documentElement.lang = active === 'ru' || active === 'en' ? active : 'en';
  observe();
  document.addEventListener('DOMContentLoaded', apply);
  // The dashboard and the notch panel are separate pages; a change in one reaches the other.
  window.addEventListener('storage', function (event) {
    if (event.key !== KEY) return;
    choice = CHOICES.indexOf(event.newValue) !== -1 ? event.newValue : 'auto';
    apply();
    window.dispatchEvent(new CustomEvent('relaylangchange', { detail: { choice: choice, language: active } }));
  });
})();
