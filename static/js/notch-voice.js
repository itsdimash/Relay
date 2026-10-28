// Talking to the notes. The Mac app listens (Apple's speech recognition, on the Mac where it can) and sends the words to
// the page; this file holds the small rules around that: which language to listen for, how spoken words join what is
// already typed, the words that mean "save it", and what to say when the microphone cannot be used.

export const VOICE_KEY = 'relay.voice';      // 'off' removes the microphone button and the right Option key
export const LANGUAGE_KEY = 'relay.voiceLang'; // 'ru' or 'en': the language of the speech, when it is not the language of the app

const LOCALES = { ru: 'ru-RU', en: 'en-US' };

// The language to listen for: the one picked on the microphone, otherwise the language Relay is shown in.
export function speechLocale(saved, pageLanguage) {
  if (LOCALES[saved]) return LOCALES[saved];
  return LOCALES[pageLanguage] || LOCALES.en;
}

export const otherLanguage = locale => (locale === LOCALES.ru ? 'en' : 'ru');
export const languageCode = locale => (locale === LOCALES.ru ? 'RU' : 'EN');

// What is in the field when the person starts talking stays; the spoken words go after it.
export function joinSpeech(base, spoken) {
  const before = String(base || '').trim();
  const after = String(spoken || '').trim();
  return before && after ? `${before} ${after}` : before || after;
}

const END = '[\\s,.;!?…]*$';
const SAVE_EN = new RegExp(`[\\s,.;!?…]*(?<![\\p{L}\\p{N}])(?:and\\s+)?(?:(save)(?:\\s+it)?(?:\\s+as\\s+(?:an?\\s+)?(to-?do|task|note))?|add\\s+(?:it\\s+)?(?:as\\s+)?(?:an?\\s+)?(to-?do|task))${END}`, 'iu');
const SAVE_RU = new RegExp(`[\\s,.;!?…]*(?<![\\p{L}\\p{N}])(?:и\\s+)?(сохрани(?:ть)?)(?:\\s+(?:как|в)\\s+(дело|задач\\p{L}*|заметк\\p{L}*))?${END}`, 'iu');

// "buy milk save" -> save the note "buy milk"; "call mom and save as to-do" -> save it as a to-do.
// Only the very end counts, and only when words are left to save.
export function spokenCommand(text) {
  const spoken = String(text || '').trim();
  for (const pattern of [SAVE_EN, SAVE_RU]) {
    const match = pattern.exec(spoken);
    if (!match) continue;
    const rest = spoken.slice(0, match.index).trim();
    if (!rest) continue;
    const kind = (match[2] || match[3] || '').toLowerCase();
    return { text: rest, save: /^(to-?do|task|дело|задач)/.test(kind) || /^add/i.test(match[0].trim()) ? 'todo' : 'note' };
  }
  return { text: spoken, save: null };
}

// What the person sees when the microphone cannot be used.
export function voiceProblem(code) {
  switch (code) {
    case 'mic-denied': return 'Microphone access is off. Turn it on in System Settings › Privacy & Security › Microphone.';
    case 'speech-denied': return 'Speech recognition is off. Turn it on in System Settings › Privacy & Security › Speech Recognition.';
    case 'unavailable': return 'Speech recognition is not available for this language right now.';
    default: return 'Could not hear you. Try again.';
  }
}
