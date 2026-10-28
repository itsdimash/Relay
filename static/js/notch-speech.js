// Answers said out loud. The Mac app speaks (the Mac's own voices); this file decides what is worth saying and when: a short,
// plain version of the result, in the language it is written in, only for what you asked for by voice unless you chose more.

export const SPEAK_KEY = 'relay.speak'; // 'off' | 'voice' (the default: what was asked by voice) | 'all' (also tasks started by hand, and reminders)

export const speakMode = stored => (stored === 'off' || stored === 'all' ? stored : 'voice');

// A run is spoken about when it began with a spoken request, or when everything is to be spoken.
export const shouldSpeak = (mode, askedByVoice) => mode === 'all' || (mode === 'voice' && !!askedByVoice);

// Cyrillic text is read by the Russian voice, anything else by the English one: an answer may be in either language,
// whatever language the app is shown in.
export function languageOf(text) {
  const russian = (String(text || '').match(/\p{Script=Cyrillic}/gu) || []).length;
  const latin = (String(text || '').match(/\p{Script=Latin}/gu) || []).length;
  return russian > latin ? 'ru-RU' : 'en-US';
}

// What is read out of a written answer: no code, links, addresses or markup, and only the first sentences, because a long
// answer is for reading. Whole sentences only, unless the first one is longer than the limit.
export function spokenForm(text, limit = 320) {
  let plain = String(text || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/^\s{0,3}(?:#{1,6}|[-*+>]|\d+[.)])\s+/gm, '')
    .replace(/[*_~|]{1,3}/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (plain.length <= limit) return plain;
  const sentences = plain.match(/[^.!?…]+(?:[.!?…]+|$)/gu) || [plain];
  let result = '';
  for (const sentence of sentences) {
    if (result && (result + sentence).length > limit) break;
    result += sentence;
  }
  if (result.length > limit) result = result.slice(0, limit).replace(/\s+\S*$/, '');
  return result.trim();
}

// The words for a run that has changed: its own summary when it finished, otherwise a short line. null: nothing to say.
// `translate` turns the short lines into the language the app is shown in.
export function lineForRun(run, translate = text => text) {
  if (!run || run.demo) return null;
  switch (run.status) {
    case 'done': {
      const summary = spokenForm(run.summary);
      return summary || translate('The task is finished.');
    }
    case 'awaiting_approval': return translate('A plan is waiting for your approval.');
    case 'awaiting_clarification': return translate('The Observer has a few questions.');
    case 'needs_attention': return translate('The task needs your decision.');
    case 'failed': return translate('The task stopped with an error.');
    default: return null;
  }
}

// The words for a reminder that went off: "Reminder. Call mom."
export function lineForReminder(message, translate = text => text) {
  if (!message) return '';
  const title = translate(String(message.title || ''));
  const detail = translate(String(message.detail || ''));
  return message.detail === 'Reminder' ? `${detail}. ${title}` : [title, detail].filter(Boolean).join('. ');
}

// A short list of ids kept between openings of the panel: which queued tasks and runs came from a spoken request.
export function remember(list, id, max = 30) {
  const ids = Array.isArray(list) ? list.filter(item => typeof item === 'string') : [];
  if (typeof id !== 'string' || !id || ids.includes(id)) return ids;
  return [...ids, id].slice(-max);
}
