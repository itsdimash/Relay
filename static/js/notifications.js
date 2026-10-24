/** Transient feedback with an optional action. This module knows nothing about chats or APIs. */
export function createNotifications({
  container = document.getElementById('historyFeedback'),
  message = document.getElementById('historyMessage'),
  actionButton = document.getElementById('undoDelete'),
  closeButton = document.getElementById('dismissNotification'),
  now = () => performance.now(),
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  activeElement = () => document.activeElement
} = {}) {
  let timer = null,
    remaining = 0,
    started = 0,
    generation = 0;
  let action = null,
    busy = false,
    previousFocus = null;
  const pauses = new Set();
  function clear() {
    if (timer !== null) clearTimer(timer);
    timer = null;
  }
  function dismiss() {
    clear();
    generation++;
    if (container.contains(activeElement()) && previousFocus?.isConnected) previousFocus.focus();
    container.hidden = true;
    action = null;
    busy = false;
    pauses.clear();
  }
  function schedule() {
    clear();
    if (container.hidden || pauses.size || remaining <= 0) return;
    const version = generation;
    started = now();
    timer = setTimer(() => {
      if (generation === version) dismiss();
    }, remaining);
  }
  function pause(reason) {
    if (timer !== null) remaining = Math.max(1, remaining - (now() - started));
    clear();
    pauses.add(reason);
  }
  function resume(reason) {
    pauses.delete(reason);
    schedule();
  }
  function show(text, {
    duration = 4000,
    actionLabel = '',
    onAction = null
  } = {}) {
    clear();
    generation++;
    if (!container.contains(activeElement())) previousFocus = activeElement();
    message.textContent = text;
    action = onAction;
    busy = false;
    actionButton.textContent = actionLabel;
    actionButton.hidden = !onAction;
    actionButton.disabled = false;
    container.hidden = false;
    remaining = duration;
    pauses.clear();
    if (container.matches?.(':hover')) pauses.add('hover');
    if (container.contains(activeElement())) pauses.add('focus');
    schedule();
  }
  container.addEventListener('mouseenter', () => pause('hover'));
  container.addEventListener('mouseleave', () => resume('hover'));
  container.addEventListener('focusin', () => pause('focus'));
  container.addEventListener('focusout', () => queueMicrotask(() => {
    if (!container.contains(activeElement())) resume('focus');
  }));
  closeButton.addEventListener('click', dismiss);
  actionButton.addEventListener('click', async () => {
    if (!action || busy) return;
    const version = generation,
      callback = action;
    busy = true;
    actionButton.disabled = true;
    pause('action');
    try {
      await callback();
      if (generation === version) dismiss();
    } catch (error) {
      if (generation === version) show(error.message, {
        duration: 0
      });
    } finally {
      if (generation === version) {
        busy = false;
        actionButton.disabled = false;
        resume('action');
      }
    }
  });
  return {
    show,
    dismiss
  };
}
