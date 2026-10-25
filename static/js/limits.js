// How much of a tool's usage limits is left, as a small row: name, bar, "50% left · week 9%".
// Used by the dashboard and by the notch panel. The server sends percent left and when each window resets.

const OLD_AFTER_SECONDS = 30 * 60;

function ago(seconds) {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

function resetsIn(seconds) {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ${Math.round((seconds % 3600) / 60)} min`;
  return `${Math.floor(seconds / 86400)} d ${Math.round((seconds % 86400) / 3600)} h`;
}

function windowTitle(name, window, now) {
  const reset = Number.isFinite(window.resets_at) ? `, resets in ${resetsIn(Math.max(0, window.resets_at - now))}` : '';
  return `${name} limit: ${window.left}% left${reset}`;
}

export function describeLimit(reading, now) {
  const windows = reading ? [reading.session && ['5-hour', reading.session], reading.week && ['Weekly', reading.week]].filter(Boolean) : [];
  if (!windows.length) return null;
  const tightest = Math.min(...windows.map(([, window]) => window.left));
  const level = tightest >= 40 ? 'ok' : tightest >= 15 ? 'low' : 'critical';
  const parts = [];
  if (reading.session && reading.week) parts.push(`${reading.session.left}% left`, `week ${reading.week.left}%`);
  else if (reading.session) parts.push(`${reading.session.left}% left`);
  else parts.push(`week ${reading.week.left}% left`);
  const age = Number.isFinite(reading.seen_at) ? Math.max(0, now - reading.seen_at) : 0;
  if (age > OLD_AFTER_SECONDS) parts.push(ago(age));
  const title = windows.map(([name, window]) => windowTitle(name, window, now)).join('\n') + (age > OLD_AFTER_SECONDS ? `\nLast reading ${ago(age)}` : '');
  return { level, tightest, text: parts.join(' · '), title };
}

// A row for one tool. `empty` is what to say when there is no reading yet.
export function limitRow(doc, label, reading, now, empty) {
  const info = describeLimit(reading, now);
  const row = doc.createElement('span');
  row.className = 'limit';
  row.dataset.level = info ? info.level : 'none';
  const name = doc.createElement('span');
  name.className = 'limit-name';
  name.textContent = label;
  const bar = doc.createElement('span');
  bar.className = 'limit-bar';
  const fill = doc.createElement('i');
  fill.style.setProperty('--left', `${info ? info.tightest : 0}%`);
  bar.append(fill);
  const text = doc.createElement('span');
  text.className = 'limit-text';
  text.textContent = info ? info.text : empty;
  if (info) row.title = info.title;
  row.setAttribute('aria-label', `${label}: ${info ? info.text : empty}`);
  row.append(name, bar, text);
  return row;
}
