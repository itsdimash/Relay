// What a spoken phrase means. A phrase that is only a command ("open music", "next song", "to-do buy milk") is carried out;
// "ask the agents why the build fails" or "tell the agents to fix the tests" becomes a task brief that waits for a yes.
// Anything else stays an ordinary note. This file only reads the words: it never touches the page or the engine.

export const MODES = ['observe', 'plan', 'build'];
export const MODE_LABELS = { observe: 'Ask', plan: 'Plan', build: 'Build' };

const VIEW_WORDS = [
  ['notes', /^(?:notes?|to-?dos?|to-?do\s+list|заметк\p{L}*|дел\p{L}*|список\s+дел)$/iu],
  ['music', /^(?:music|player|музык\p{L}*|плеер\p{L}*)$/iu],
  ['deliver', /^(?:files?|shelf|deliver|файл\p{L}*|полк\p{L}*)$/iu],
  ['task', /^(?:tasks?|queue|задач\p{L}*|очеред\p{L}*)$/iu],
  ['office', /^(?:office|agents?\s+room|офис\p{L}*|комнат\p{L}*(?:\s+агентов)?)$/iu],
];
export const VIEW_NAMES = { notes: 'Notes', music: 'Music', deliver: 'Files', task: 'Task', office: 'Office' };

const OPEN = /^(?:please\s+|пожалуйста\s+)?(?:open|show(?:\s+me)?|go\s+to|switch\s+to|take\s+me\s+to|открой|покажи|перейди\s+(?:в|на)|зайди\s+в|включи\s+вкладку)\s+(?:the\s+|my\s+|мои\s+|мою\s+)?(.+?)(?:\s+(?:tab|page|view|screen|вкладк\p{L}*|страниц\p{L}*))?(?:\s+(?:please|пожалуйста))?$/iu;

const MEDIA = [
  ['pause', /^(?:please\s+)?(?:pause|stop)(?:\s+(?:the\s+)?(?:music|song|track|playback))?$|^(?:пауза|(?:поставь\s+на\s+паузу|останови|выключи)(?:\s+музыку)?)$/iu],
  ['play', /^(?:please\s+)?(?:play|resume|continue|unpause)(?:\s+(?:the\s+)?(?:music|song|track))?$|^(?:играй|продолжи|продолжай|включи\s+музыку|поставь\s+музыку)$/iu],
  ['next', /^(?:please\s+)?(?:play\s+)?(?:next|skip)(?:\s+(?:the\s+)?(?:track|song))?$|^(?:следующ\p{L}*(?:\s+(?:трек|песн\p{L}*))?|дальше|пропусти(?:\s+(?:трек|песню))?)$/iu],
  ['previous', /^(?:please\s+)?(?:play\s+)?(?:previous|last|go\s+back)(?:\s+(?:track|song))?$|^(?:предыдущ\p{L}*(?:\s+(?:трек|песн\p{L}*))?|назад)$/iu],
];

// "translate this to Russian", "translate good morning into English", "how do you say thanks in Kazakh", "переведи на казахский: привет":
// the Translate page opens, with that language chosen. Without words ("this", "это") it translates what was copied.
const LANG_EN = '(english|russian|kazakh|kazak)';
const LANG_RU = '(английск\\p{L}*|русск\\p{L}*|казахск\\p{L}*)';
const THIS_EN = '(?:(?:this|that|it|the\\s+clipboard)(?:\\s+(?:text|message|sentence|phrase))?\\s+)?';
const THIS_RU = '(?:(?:это|эту\\s+фразу|этот\\s+текст|текст)\\s+)?';
const TRANSLATE = [
  { pattern: new RegExp(`^translate\\s+${THIS_EN}(?:in)?to\\s+${LANG_EN}(?:\\s+language)?\\s*[:,\\-–]?\\s*(.*)$`, 'iu'), language: 1, words: 2 },
  { pattern: new RegExp(`^translate\\s+(.+?)\\s+(?:in)?to\\s+${LANG_EN}(?:\\s+language)?$`, 'iu'), language: 2, words: 1 },
  { pattern: new RegExp(`^how\\s+(?:do\\s+(?:you|i)\\s+)?say\\s+(.+?)\\s+in\\s+${LANG_EN}$`, 'iu'), language: 2, words: 1 },
  { pattern: new RegExp(`^переведи\\s+${THIS_RU}на\\s+${LANG_RU}(?:\\s+язык)?\\s*[:,\\-–]?\\s*(.*)$`, 'iu'), language: 1, words: 2 },
  { pattern: new RegExp(`^переведи\\s+(.+?)\\s+на\\s+${LANG_RU}(?:\\s+язык)?$`, 'iu'), language: 2, words: 1 },
  { pattern: new RegExp(`^как\\s+(?:будет|сказать)\\s+(.+?)\\s+на\\s+${LANG_RU}$`, 'iu'), language: 2, words: 1 },
];
export const MAX_TRANSLATE = 5000;
// The language that was said, as the code the Translate page uses.
export function translateTarget(word) {
  const name = String(word || '').toLowerCase();
  if (/^(?:english|англ)/u.test(name)) return 'en';
  if (/^(?:russian|русск)/u.test(name)) return 'ru';
  if (/^(?:kazak|казах)/u.test(name)) return 'kk';
  return null;
}
const COPIED = /^(?:this|that|it|это|этот|эту)$/iu;

const TODO = [
  /^(?:please\s+)?(?:add\s+(?:a\s+|an\s+)?(?:new\s+)?)?(?:to-?do|todo)\s*[:,\-–]?\s+(.+)$/iu,
  /^(?:please\s+)?add\s+(.+?)\s+to\s+(?:my\s+)?(?:to-?do|todo)(?:\s+list)?$/iu,
  /^(?:пожалуйста\s+)?(?:добавь\s+)?(?:в\s+список\s+дел|в\s+дела|дело|туду)\s*[:,\-–]?\s+(.+)$/iu,
];

// "open Safari", "launch Slack", "открой телеграм": an app on the Mac. The name is checked by the app itself; when no app has it,
// the words stay a note (so "open the door" is not lost). Names people say aloud are mapped to the name the app really has.
const LAUNCH = /^(?:please\s+|пожалуйста\s+)?(?:open|launch|открой|запусти)\s+(?:the\s+|my\s+)?(?:app(?:lication)?\s+|приложение\s+)?(.+?)(?:\s+app)?(?:\s+(?:please|пожалуйста))?$/iu;
const APP_NAME = /^[\p{L}\p{N}][\p{L}\p{N} .+&'-]*$/u;
const APP_ALIASES = {
  'сафари': ['Safari'], 'телеграм': ['Telegram'], 'телеграмм': ['Telegram'], 'хром': ['Google Chrome'], 'гугл хром': ['Google Chrome'],
  'файрфокс': ['Firefox'], 'календарь': ['Calendar'], 'почта': ['Mail'], 'сообщения': ['Messages'], 'контакты': ['Contacts'],
  'карты': ['Maps'], 'фото': ['Photos'], 'калькулятор': ['Calculator'], 'терминал': ['Terminal'], 'настройки': ['System Settings', 'System Preferences'],
  'системные настройки': ['System Settings', 'System Preferences'], 'финдер': ['Finder'], 'ватсап': ['WhatsApp'], 'слак': ['Slack'],
  'зум': ['zoom.us', 'Zoom'], 'дискорд': ['Discord'], 'спотифай': ['Spotify'], 'ворд': ['Microsoft Word'], 'эксель': ['Microsoft Excel'],
  'иксод': ['Xcode'], 'икскод': ['Xcode'], 'вс код': ['Visual Studio Code'], 'код': ['Visual Studio Code'], 'нотион': ['Notion'], 'фигма': ['Figma'],
  'система': ['System Settings', 'System Preferences'], 'часы': ['Clock'], 'напоминания': ['Reminders'], 'книги': ['Books'], 'заметки приложение': ['Notes'],
  'apple notes': ['Notes'], 'chrome': ['Google Chrome'], 'settings': ['System Settings', 'System Preferences'], 'system settings': ['System Settings', 'System Preferences'],
  'vs code': ['Visual Studio Code'], 'vscode': ['Visual Studio Code'], 'code': ['Visual Studio Code'], 'zoom': ['zoom.us', 'Zoom'],
};
export function appNames(word) {
  const key = String(word || '').trim().toLowerCase();
  return APP_ALIASES[key] || [String(word || '').trim()];
}

// "Telegram: I will be late", "write in Telegram that dinner is ready", "в телеграм: буду через час": the words become a draft that
// Telegram opens with; the person chooses the chat and presses send.
const TELEGRAM = [
  /^(?:(?:draft|write|send|compose|post)\s+(?:a\s+)?(?:message\s+|text\s+)?)?(?:in|on|to|via)\s+telegram\s*[:,\-–]?\s+(?:that\s+)?(.+)$/iu,
  /^telegram\s*[:,\-–]\s*(.+)$/iu,
  /^(?:(?:напиши|отправь|пошли|набросай|сделай\s+черновик)\s+(?:сообщение\s+)?)?(?:в|через|на)\s+телеграм\p{L}*\s*[:,\-–]?\s+(?:что\s+)?(.+)$/iu,
  /^телеграм\p{L}*\s*[:,\-–]\s*(.+)$/iu,
];

// "type hello world", "напечатай привет": typed into the app that was in front, after the person has seen the words and said yes.
const TYPE = [
  /^type(?:\s+(?:out|in|this|the\s+following|the\s+text))?\s*[:,\-–]?\s+(?!of\b)(.+)$/iu,
  /^(?:напечатай|набери|введи)(?:\s+(?:текст|это))?\s*[:,\-–]?\s+(.+)$/iu,
];
export const MAX_TYPED = 500;
// What gets typed: one line (a spoken Return is never pressed), as long as the field allows.
export const typedText = text => String(text || '').replace(/\s+/gu, ' ').trim().slice(0, MAX_TYPED);

// Who is being addressed: the whole team ("the agents", "the team", "Relay"), one role ("the reviewer"), or one tool ("Codex").
// Group 1 is the name, so that what follows is group 2.
const WHO_EN = '(?:the\\s+)?(?:relay\\s+)?(agents?|team|relay|observer|builder|reviewer|claude|codex)';
const WHO_RU = '(агент(?:ов|ам|ы|а)|команд\\p{L}*|релей|relay|наблюдател\\p{L}*|разработчик\\p{L}*|ревьюер\\p{L}*|рецензент\\p{L}*|клод\\p{L}*|клауд\\p{L}*|claude|кодекс\\p{L}*|codex)';
const TO_ASK = [
  new RegExp(`^(?:ask|question)\\s+${WHO_EN}\\s*[,:]?\\s+(?:to\\s+)?(.+)$`, 'iu'),
  new RegExp(`^(?:спроси|узнай)\\s+(?:у\\s+)?${WHO_RU}\\s*[,:]?\\s+(.+)$`, 'iu'),
];
const TO_TELL = [
  new RegExp(`^(?:tell|have|get|let)\\s+${WHO_EN}\\s*[,:]?\\s+(?:to\\s+)?(.+)$`, 'iu'),
  new RegExp(`^(?:скажи|поручи|попроси|пусть)\\s+${WHO_RU}\\s*[,:]?\\s+(?:чтобы\\s+|они\\s+)?(.+)$`, 'iu'),
];
const ADDRESSED = [
  new RegExp(`^${WHO_EN}\\s*[,:]\\s+(.+)$`, 'iu'),
  new RegExp(`^${WHO_RU}\\s*[,:]\\s+(.+)$`, 'iu'),
];

// Speech recognition rarely writes a comma, so "Observer what did you observe" is heard as it is said. A name at the start with no
// comma counts only when what follows plainly asks or orders something (never "Claude is down again" or "team meeting at 5").
const BARE = [new RegExp(`^${WHO_EN}\\s+(.+)$`, 'iu'), new RegExp(`^${WHO_RU}\\s+(.+)$`, 'iu')];
const BARE_REQUEST = /^(?:what|why|how|where|which|when|explain|check|review|look|find|show|tell\s+me|summari[sz]e|investigate|fix|add|plan|refactor|implement|write|make|update|create|remove|test|что|почему|как|где|какой|какая|какие|сколько|когда|объясни|проверь|посмотри|найди|расскажи|исправь|добавь|спланируй|составь|почини\p{L}*|напиши|сделай|обнови)(?![\p{L}\p{N}])/iu;

export const AGENTS = ['observer', 'builder', 'reviewer', 'claude', 'codex']; // who can be asked by name; no name means the whole team

// The name that was said, as one of AGENTS (or null for the whole team).
export function agentOf(word) {
  const name = String(word || '').toLowerCase();
  if (/^(?:observer|наблюдател)/u.test(name)) return 'observer';
  if (/^(?:builder|разработчик)/u.test(name)) return 'builder';
  if (/^(?:reviewer|ревьюер|рецензент)/u.test(name)) return 'reviewer';
  if (/^(?:claude|клод|клауд)/u.test(name)) return 'claude';
  if (/^(?:codex|кодекс)/u.test(name)) return 'codex';
  return null;
}

// The observer and the reviewer only look; only the builder changes files. A request that asks them for more is a plan
// (the observer) or a question (the reviewer) instead.
export function fitMode(agent, mode) {
  if (mode !== 'build') return mode;
  if (agent === 'observer') return 'plan';
  if (agent === 'reviewer') return 'observe';
  return mode;
}
const WAKE = /^(?:(?:hey|ok|okay|эй|привет)\s+)?(?:relay|релей|рилей)\s*[,:.!\-–]\s*/iu;

const QUESTION = /^(?:what|why|how|where|which|who|when|is|are|does|do|can|could|should|explain|check|review|look|find|show|tell\s+me|why|что|почему|как|где|какой|какая|какие|сколько|кто|когда|объясни|проверь|посмотри|найди|расскажи)(?![\p{L}\p{N}])/iu;
const PLAN = /^(?:plan|make\s+a\s+plan|draft\s+a\s+plan|спланир\p{L}*|составь\s+план|план)(?![\p{L}\p{N}])/iu;

// The mode a request most likely wants: a question only looks, a plan is only a plan, anything else is work to do.
export function guessMode(text, asked = false, agent = null) {
  const words = String(text || '').trim();
  if (PLAN.test(words)) return 'plan';
  if (asked || QUESTION.test(words)) return 'observe';
  return fitMode(agent, 'build');
}

// "Take a note that I need to go to the canteen after 15 min", "remind me to call mom at 9": the words after the lead are
// saved as a note at once (a time in them becomes its reminder). Only a lead followed by words counts: "take a note" alone is
// nothing, and a phrase that merely contains "note" stays a note.
const NOTE = [
  /^(?:please\s+)?(?:take|make|write|add|create|save)(?:\s+down)?\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?notes?(?:\s+(?:that|to|about|of|saying))?\s*[:,\-–]?\s+(.+)$/iu,
  /^(?:please\s+)?note\s+(?:down\s+)?(?:that|to)\s+(.+)$/iu,
  /^(?:please\s+)?(?:write|jot|put)\s+down\s+(?:that\s+)?(.+)$/iu,
  /^(?:please\s+)?(?:add|save|put)\s+(.+?)\s+(?:to|in|into)\s+(?:my\s+)?notes$/iu,
  /^(?:please\s+)?remind\s+me\s+(?:to\s+|about\s+|of\s+|that\s+)?(.+)$/iu,
  /^(?:пожалуйста\s+)?(?:сделай|создай|запиши|добавь|напиши)\s+(?:новую\s+)?заметк\p{L}*(?:\s+(?:что|про|о|об))?\s*[:,\-–]?\s+(.+)$/iu,
  /^(?:пожалуйста\s+)?запиши(?:\s+(?:что|мне|себе))?\s*[:,\-–]?\s+(.+)$/iu,
  /^(?:пожалуйста\s+)?заметк[ау]\s*[:,\-–]?\s+(.+)$/iu,
  /^(?:пожалуйста\s+)?напомни(?:ть)?(?:\s+мне)?(?:\s+(?:о|про|что|чтобы))?\s*[:,\-–]?\s+(.+)$/iu,
];


const clean = text => String(text || '').trim().replace(/^[\s,.;:!?…-]+|[\s,.;:!?…]+$/gu, '');
const MIN_REQUEST = 4;

// null: an ordinary note. Otherwise { kind: 'view' | 'media' | 'translate' | 'todo' | 'note' | 'app' | 'telegram' | 'type' | 'agents', ... }.
export function routeCommand(spoken) {
  let text = clean(spoken);
  if (!text) return null;
  const named = WAKE.test(text);
  text = text.replace(WAKE, '').replace(/\s+(?:please|пожалуйста)$/iu, '');

  const open = OPEN.exec(text);
  if (open) {
    const word = clean(open[1]);
    const view = VIEW_WORDS.find(([, pattern]) => pattern.test(word));
    if (view) return { kind: 'view', view: view[0] };
  }
  for (const [command, pattern] of MEDIA) {
    if (pattern.test(text)) return { kind: 'media', command };
  }
  for (const { pattern, language, words } of TRANSLATE) {
    const match = pattern.exec(text);
    const target = translateTarget(match?.[language]);
    if (!target) continue;
    const said = clean(match[words]);
    return { kind: 'translate', target, text: COPIED.test(said) ? '' : Array.from(said).slice(0, MAX_TRANSLATE).join('') };
  }
  for (const pattern of TODO) {
    const match = pattern.exec(text);
    if (match && clean(match[1])) return { kind: 'todo', text: clean(match[1]) };
  }
  for (const pattern of NOTE) {
    const match = pattern.exec(text);
    if (match && clean(match[1])) return { kind: 'note', text: clean(match[1]) };
  }
  for (const pattern of TELEGRAM) {
    const match = pattern.exec(text);
    const draft = typedText(match?.[1]);
    if (draft) return { kind: 'telegram', text: draft };
  }
  for (const pattern of TYPE) {
    const match = pattern.exec(text);
    const typed = typedText(match?.[1]);
    if (typed) return { kind: 'type', text: typed };
  }
  const launch = LAUNCH.exec(text);
  if (launch) {
    const word = clean(launch[1]);
    if (word.length <= 40 && word.split(/\s+/u).length <= 3 && APP_NAME.test(word)) return { kind: 'app', name: word, names: appNames(word), spoken: text };
  }
  for (const [patterns, asked] of [[TO_ASK, true], [TO_TELL, false]]) {
    for (const pattern of patterns) {
      const match = pattern.exec(text);
      const request = clean(match?.[2]);
      const agent = agentOf(match?.[1]);
      if (request.length >= MIN_REQUEST) return { kind: 'agents', text: request, mode: guessMode(request, asked, agent), agent };
    }
  }
  for (const pattern of ADDRESSED) {
    const match = pattern.exec(text);
    const request = clean(match?.[2]);
    const agent = agentOf(match?.[1]);
    if (request.length >= MIN_REQUEST) return { kind: 'agents', text: request, mode: guessMode(request, false, agent), agent };
  }
  for (const pattern of BARE) {
    const match = pattern.exec(text);
    const request = clean(match?.[2]);
    const agent = agentOf(match?.[1]);
    if (request.length >= MIN_REQUEST && BARE_REQUEST.test(request)) return { kind: 'agents', text: request, mode: guessMode(request, false, agent), agent };
  }
  // "Relay, fix the login tests": the name alone, with something to do after it.
  if (named && text.length >= MIN_REQUEST) return { kind: 'agents', text: clean(text), mode: guessMode(text), agent: null };
  return null;
}

// The team a task runs with when one agent was asked by name. The observer's seat does all the looking (a question or a plan)
// and the builder's seat does the building, so the person asked takes that seat: the reviewer or builder looking at
// something sits in the observer's seat with their own tool, model and instructions; "Claude" or "Codex" takes the seat that
// does the work with that tool (its model and effort go back to the tool's default, because those belong to the other tool).
// The seats keep their powers: only the builder's seat can edit files. null when the whole team is asked.
export function teamFor(team, agent, mode) {
  if (!team?.roles || !AGENTS.includes(agent)) return team || null;
  const copy = JSON.parse(JSON.stringify(team));
  const seat = mode === 'build' ? 'builder' : 'observer';
  if (agent === 'observer' || agent === 'builder' || agent === 'reviewer') {
    if (seat === 'observer' && agent !== 'observer') copy.roles.observer = { ...copy.roles[agent] };
  } else if (copy.roles[seat].provider !== agent) {
    copy.roles[seat] = { ...copy.roles[seat], provider: agent, model: '', effort: '' };
  }
  return copy;
}

// What a brief carries when it is queued: a build gets review rounds, a question or a plan does not.
export function briefFor(request, project, mode, team = null) {
  const safe = MODES.includes(mode) ? mode : 'build';
  const brief = { task: String(request || '').trim(), project, mode: safe, rounds: safe === 'build' ? 3 : 0, minutes: 20, auto: false };
  return team ? { ...brief, team } : brief;
}

// The project the brief goes to: the one used last time if it still exists, otherwise the first folder that does.
export function pickProject(projects, remembered) {
  const usable = (Array.isArray(projects) ? projects : []).filter(project => project && project.exists !== false && typeof project.path === 'string');
  return usable.find(project => project.path === remembered) || usable[0] || null;
}
