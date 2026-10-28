// Reminders for the notch notes. A note can carry a time written in plain words ("in 30 min", "tomorrow at 9:00",
// "через полчаса", "в пятницу в 18:00"); this file finds it, and tells the notch what to say when the time comes.
// Times are read in the Mac's own time zone. Nothing here talks to the network.

const L = '\\p{L}\\p{N}';
const START = `(?<![${L}])`;
const END = `(?![${L}])`;
const MINUTE = 60000;
const DAY = 24 * 60 * MINUTE;
const MAX_AHEAD = 366 * DAY;

const WEEKDAYS = {
  sunday: 0, monday: 1, tuesday: 2, wednesday: 3, thursday: 4, friday: 5, saturday: 6,
  воскресенье: 0, воскресенья: 0, понедельник: 1, вторник: 2, среда: 3, среду: 3, четверг: 4, пятница: 5, пятницу: 5, суббота: 6, субботу: 6
};
const DAY_WORDS = {
  today: 0, tomorrow: 1, tmrw: 1, 'day after tomorrow': 2,
  сегодня: 0, завтра: 1, послезавтра: 2
};

const dayRe = new RegExp(
  `${START}(?:(?:on|в|во)\\s+)?(day after tomorrow|today|tomorrow|tmrw|сегодня|послезавтра|завтра|(?:next\\s+)?(?:${Object.keys(WEEKDAYS).join('|')}))${END}`, 'iu'
);
const timeRe = new RegExp(
  `(?<![${L}:.])(?:(at|around|@|в|к)\\s*)?(\\d{1,2})(?:[:.](\\d{2}))?(?:\\s*(a\\.?m\\.?|p\\.?m\\.?|утра|дня|вечера|ночи))?${END}`, 'giu'
);

// "in 1h30", "in 2 hours", "in half an hour", "через 15 минут", "через полчаса", "через 3 дня"
const EN_UNITS = [{ word: 'days?|d', minutes: 1440 }, { word: 'hours?|hrs?|h', minutes: 60 }, { word: 'minutes?|mins?|m', minutes: 1 }];
const RU_UNITS = [{ word: 'дн\\p{L}*|день|д', minutes: 1440 }, { word: 'час\\p{L}*|ч', minutes: 60 }, { word: 'мин\\p{L}*|м', minutes: 1 }];
const relativeRes = [
  { re: new RegExp(`${START}in\\s+(\\d{1,3})\\s*(?:hours?|hrs?|h)\\s*(?:and\\s*)?(\\d{1,3})\\s*(?:minutes?|mins?|m)?${END}`, 'iu'), compound: true },
  { re: new RegExp(`${START}через\\s+(\\d{1,3})\\s*(?:час\\p{L}*|ч)\\s*(?:и\\s*)?(\\d{1,3})\\s*(?:мин\\p{L}*|м)?${END}`, 'iu'), compound: true },
  { re: new RegExp(`${START}in\\s+(\\d{1,4}|an?|one)\\s*(${EN_UNITS.map(u => u.word).join('|')})${END}`, 'iu'), units: EN_UNITS },
  { re: new RegExp(`${START}через\\s+(\\d{1,4})\\s*(${RU_UNITS.map(u => u.word).join('|')})${END}`, 'iu'), units: RU_UNITS },
  { re: new RegExp(`${START}in\\s+(?:a\\s+)?half\\s+(?:an?\\s+)?hour${END}`, 'iu'), fixed: 30 },
  { re: new RegExp(`${START}через\\s+полчаса${END}`, 'iu'), fixed: 30 },
  { re: new RegExp(`${START}через\\s+час${END}`, 'iu'), fixed: 60 },
  { re: new RegExp(`${START}через\\s+минуту${END}`, 'iu'), fixed: 1 },
  { re: new RegExp(`${START}через\\s+день${END}`, 'iu'), fixed: 1440 }
];

function relative(text, now) {
  for (const spec of relativeRes) {
    const match = spec.re.exec(text);
    if (!match) continue;
    let minutes;
    if (spec.fixed) minutes = spec.fixed;
    else if (spec.compound) minutes = Number(match[1]) * 60 + Number(match[2]);
    else {
      const count = /^\d/.test(match[1]) ? Number(match[1]) : 1;
      const kind = spec.units.find(u => new RegExp(`^(?:${u.word})$`, 'iu').test(match[2]));
      if (!kind) continue;
      minutes = count * kind.minutes;
    }
    if (!(minutes > 0)) continue;
    return { spans: [{ start: match.index, end: match.index + match[0].length }], due: Math.floor((now + minutes * MINUTE) / 1000) * 1000 };
  }
  return null;
}

// The hour and minute of a written time, or null when it is not a time ("9:75", "25").
function clock(match) {
  let hour = Number(match[2]);
  const minute = match[3] === undefined ? 0 : Number(match[3]);
  const word = (match[4] || '').toLowerCase().replace(/\./g, '');
  if (minute > 59) return null;
  if (word === 'am' || word === 'pm') {
    if (hour < 1 || hour > 12) return null;
    hour = word === 'pm' ? (hour % 12) + 12 : hour % 12;
  } else if (word) {
    if (hour < 1 || hour > 12) return null;
    if (word === 'утра') hour %= 12;
    else if (word === 'дня') hour = hour < 6 ? hour + 12 : hour;           // 2 дня = 14:00, 12 дня = noon
    else if (word === 'вечера') hour = hour < 12 ? hour + 12 : hour;
    else if (word === 'ночи') hour = hour === 12 ? 0 : hour >= 6 ? hour + 12 : hour; // 11 ночи = 23:00, 2 ночи = 02:00
  } else if (hour > 23) return null;
  return { hour, minute, explicit: !!word };
}

function at(base, dayOffset, time) {
  const date = new Date(base);
  date.setHours(time.hour, time.minute, 0, 0);
  date.setDate(date.getDate() + dayOffset);
  return date.getTime();
}

function absolute(text, now) {
  const dayMatch = dayRe.exec(text);
  let chosen = null;
  for (const match of text.matchAll(timeRe)) {
    const time = clock(match);
    if (!time) continue;
    const hasPreposition = !!match[1];
    const hasMinutes = match[3] !== undefined;
    const adjacent = !!dayMatch && (
      !text.slice(dayMatch.index + dayMatch[0].length, match.index).trim() ||
      !text.slice(match.index + match[0].length, dayMatch.index).trim()
    );
    // A lone number is a time only after "at" or "в"; "9:30" and "9pm" are times by themselves next to a day.
    if (!(hasPreposition || (adjacent && (hasMinutes || time.explicit)))) continue;
    chosen = { match, time };
    break;
  }
  if (!chosen) return null;
  const { match, time } = chosen;
  const spans = [{ start: match.index, end: match.index + match[0].length }];
  let due;
  if (dayMatch) {
    spans.push({ start: dayMatch.index, end: dayMatch.index + dayMatch[0].length });
    const word = dayMatch[1].toLowerCase().replace(/^next\s+/, '');
    if (word in DAY_WORDS) due = at(now, DAY_WORDS[word], time);
    else {
      let ahead = (WEEKDAYS[word] - new Date(now).getDay() + 7) % 7;
      if (ahead === 0 && (at(now, 0, time) <= now || /^next\s/i.test(dayMatch[1]))) ahead = 7;
      due = at(now, ahead, time);
    }
  } else {
    due = at(now, 0, time);
    // "at 5" at three in the afternoon means 17:00; any other time that has gone by today means tomorrow.
    const evening = at(now, 0, { ...time, hour: time.hour + 12 });
    if (due <= now && !time.explicit && time.hour < 12 && evening > now && evening - now <= 3 * 60 * MINUTE) due = evening;
    if (due <= now) due = at(now, 1, time);
  }
  return { spans, due };
}

const LEAD = /^\s*(?:remind me(?:\s+to|\s+about|\s+of)?|напомни(?:ть)?(?:\s+мне)?(?:\s+о|\s+про|\s+чтобы)?)[\s,:-]*/iu;

function tidy(text) {
  return text.replace(/\s+/g, ' ').replace(/^[\s,;:.\-–—]+|[\s,;:.\-–—]+$/gu, '').trim();
}

// Finds a time in the words of a note. Returns the note without the time phrase and the moment as milliseconds, or
// null when there is none (or it is more than a year away). "Buy milk tomorrow" alone has no time, so it stays a note.
export function parseReminder(input, now = Date.now()) {
  if (typeof input !== 'string') return null;
  const found = absolute(input, now) || relative(input, now);
  if (!found || !(found.due > now) || found.due - now > MAX_AHEAD) return null;
  let rest = input;
  for (const span of [...found.spans].sort((a, b) => b.start - a.start)) rest = rest.slice(0, span.start) + ' ' + rest.slice(span.end);
  rest = tidy(rest.replace(LEAD, ''));
  return { text: rest || tidy(input), due: found.due };
}

const two = n => String(n).padStart(2, '0');

// How a reminder's time is shown beside the note: "17:30", "Tomorrow 09:00", "03.11 09:00".
export function dueLabel(due, now = Date.now()) {
  if (!Number.isFinite(due)) return '';
  const date = new Date(due);
  const clockText = `${two(date.getHours())}:${two(date.getMinutes())}`;
  const sameDay = other => other.getFullYear() === date.getFullYear() && other.getMonth() === date.getMonth() && other.getDate() === date.getDate();
  const today = new Date(now);
  if (sameDay(today)) return clockText;
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  if (sameDay(tomorrow)) return `Tomorrow ${clockText}`;
  return `${two(date.getDate())}.${two(date.getMonth() + 1)} ${clockText}`;
}

const brief = (text, limit = 60) => {
  const flat = String(text || '').replace(/\s+/g, ' ').trim();
  return flat.length > limit ? flat.slice(0, limit - 1).trimEnd() + '…' : flat;
};

// Watches the reminders the engine says are due. Each one is announced once; the engine is told after that, and the
// call repeats until the engine has taken it, so a reminder is never lost or said twice.
export function createReminderWatcher({ announce, acknowledge }) {
  const said = new Set();
  let busy = false;
  return {
    update(reminders) {
      const list = (Array.isArray(reminders) ? reminders : []).filter(item => item && typeof item.id === 'string');
      const present = new Set(list.map(item => item.id));
      for (const id of said) if (!present.has(id)) said.delete(id); // the engine has it marked: nothing more to do
      const fresh = list.filter(item => !said.has(item.id));
      if (fresh.length) {
        fresh.forEach(item => said.add(item.id));
        announce(fresh.length === 1
          ? { kind: 'reminder', title: brief(fresh[0].text), detail: 'Reminder' }
          : { kind: 'reminder', title: `${fresh.length} reminders`, detail: brief(fresh[0].text) });
      }
      if (list.length && !busy) {
        busy = true;
        Promise.resolve()
          .then(() => acknowledge(list.map(item => item.id)))
          .catch(() => {})
          .finally(() => { busy = false; });
      }
    }
  };
}
