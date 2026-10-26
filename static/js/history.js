import { state as appState } from './state.js';
import { $, e, scrollBehavior } from './dom.js';
import { request } from './api.js';
import { terminal } from './constants.js';
export function createHistory({
  render,
  clearSourceBrief,
  notifications
}) {
  let deleteTarget = null;
  let historyMenuTarget = null;
  let historyMenuTrigger = null;
  function conversationTitle(run) {
    const title = run.demo ? (run.conversation_title || run.task).replace(/^(?:example\s*[:·]\s*)+/i, '') : run.conversation_title || run.task;
    return title ? title.charAt(0).toUpperCase() + title.slice(1) : 'Untitled conversation';
  }
  function historyDay(created) {
    const date = new Date(created),
      today = new Date();
    if (!Number.isFinite(date.getTime())) return 'Earlier';
    if (date.toDateString() === today.toDateString()) return 'Today';
    today.setDate(today.getDate() - 1);
    return date.toDateString() === today.toDateString() ? 'Yesterday' : 'Earlier';
  }
  const HISTORY_PAGE = 30;
  let shownCount = HISTORY_PAGE;
  function renderHistory() {
    const query = $('historySearch').value.trim().toLocaleLowerCase();
    const filtered = appState.runs.filter(run => (run.conversation_title || run.task).toLocaleLowerCase().includes(query));
    // Long histories show a page at a time; the open chat is always included.
    const limit = Math.max(shownCount, filtered.findIndex(run => run.id === appState.selected) + 1);
    const visible = filtered.slice(0, limit);
    const more = filtered.length - visible.length;
    const key = JSON.stringify([visible.map(run => [run.id, run.status, run.task, run.created, run.demo]), more, appState.selected, query]);
    if ($('history').dataset.key === key) return;
    closeHistoryMenu(false);
    $('history').dataset.key = key;
    $('taskCount').textContent = query ? `${filtered.length}/${appState.runs.length}` : appState.runs.length;
    let group = '';
    const states = {
      done: 'Completed',
      stopped: 'Stopped',
      failed: 'Could not finish',
      needs_attention: 'Needs review',
      interrupted: 'Interrupted',
      queued: 'Queued',
      preparing: 'Preparing',
      observing: 'Observing',
      awaiting_clarification: 'Needs your answers',
      awaiting_approval: 'Awaiting approval',
      building: 'Building',
      reviewing: 'Reviewing',
      fixing: 'Refining'
    };
    $('history').innerHTML = filtered.length ? visible.map(run => {
      const day = historyDay(run.created),
        heading = day !== group ? `<div class="history-group">${day}</div>` : '';
      group = day;
      const title = conversationTitle(run),
        date = new Date(run.created);
      const time = Number.isFinite(date.getTime()) ? date.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit'
      }) : '';
      const active = !terminal.has(run.status);
      return `${heading}<div class="history-row ${run.id === appState.selected ? 'is-selected' : ''}"><button class="history-open" data-run="${e(run.id)}" ${run.id === appState.selected ? 'aria-current="true"' : ''} title="${e(conversationTitle(run))}"><span class="history-title">${e(title)}</span><span class="history-meta"><span class="history-status ${active ? 'is-running' : run.status === 'done' ? 'is-complete' : ''}"></span><span>${e(states[run.status] || run.status)}</span>${run.demo ? '<span class="history-demo">Demo</span>' : ''}<time datetime="${e(run.created)}">${e(time)}</time></span></button><button class="history-more" data-history-menu="${e(run.id)}" aria-label="Actions for ${e(title)}" aria-haspopup="menu" aria-expanded="false" title="Conversation actions"><svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg></button></div>`;
    }).join('') + (more > 0 ? `<button type="button" class="history-show-more" data-history-more>Show ${Math.min(HISTORY_PAGE, more)} more</button>` : '') : `<div class="history-empty"><svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M4 4h16v12H9l-5 4z"/></svg><p>${query ? 'No conversations found' : 'No conversations yet'}</p><span>${query ? 'Try a different search.' : 'Your next idea starts here.'}</span></div>`;
  }
  function closeHistoryMenu(returnFocus = true) {
    $('historyMenu').hidden = true;
    if (historyMenuTrigger) {
      historyMenuTrigger.setAttribute('aria-expanded', 'false');
      if (returnFocus && historyMenuTrigger.isConnected) historyMenuTrigger.focus();
    }
    historyMenuTarget = null;
    historyMenuTrigger = null;
  }
  function openHistoryMenu(id, trigger) {
    if (historyMenuTarget === id && !$('historyMenu').hidden) {
      closeHistoryMenu();
      return;
    }
    closeHistoryMenu(false);
    const run = appState.runs.find(r => r.id === id);
    if (!run) return;
    historyMenuTarget = id;
    historyMenuTrigger = trigger;
    $('historyMenuTitle').textContent = conversationTitle(run);
    $('historyMenuDelete').disabled = !terminal.has(run.status);
    $('historyMenuDelete').title = terminal.has(run.status) ? 'Delete chat permanently' : 'Stop the running task before deleting its history';
    const rect = trigger.getBoundingClientRect();
    $('historyMenu').style.left = Math.max(12, Math.min(rect.right - 216, window.innerWidth - 228)) + 'px';
    $('historyMenu').style.top = Math.max(12, Math.min(rect.bottom + 5, window.innerHeight - 170)) + 'px';
    $('historyMenu').hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    $('historyMenuOpen').focus();
  }
  function openDeleteDialog(id) {
    const run = appState.runs.find(r => r.id === id);
    if (!run || !terminal.has(run.status)) return;
    deleteTarget = id;
    $('deleteChatName').textContent = run.task;
    $('deleteDialog').showModal();
    $('cancelDelete').focus();
  }
  function init() {
    $('history').addEventListener('click', event => {
      const more = event.target.closest('[data-history-menu]');
      if (more) {
        openHistoryMenu(more.dataset.historyMenu, more);
        return;
      }
      if (event.target.closest('[data-history-more]')) {
        shownCount += HISTORY_PAGE;
        renderHistory();
        return;
      }
      const button = event.target.closest('[data-run]');
      if (button) {
        closeHistoryMenu(false);
        appState.selected = button.dataset.run;
        appState.rendered = '';
        render();
      }
    });
    $('historySearch').addEventListener('input', () => {
      shownCount = HISTORY_PAGE;
      renderHistory();
    });
    $('historyToggle').addEventListener('click', () => {
      const open = document.querySelector('.sidebar').classList.toggle('history-visible');
      $('historyToggle').setAttribute('aria-expanded', String(open));
    });
    $('historyMenuOpen').addEventListener('click', () => {
      const id = historyMenuTarget;
      closeHistoryMenu(false);
      appState.selected = id;
      appState.rendered = '';
      render();
      document.querySelector('.activity').scrollIntoView({
        behavior: 'auto',
        block: 'start'
      });
    });
    $('historyMenuDelete').addEventListener('click', () => {
      const id = historyMenuTarget;
      closeHistoryMenu(false);
      openDeleteDialog(id);
    });
    $('historyMenu').addEventListener('keydown', event => {
      const buttons = [...$('historyMenu').querySelectorAll('button:not(:disabled)')];
      if (event.key === 'Escape') {
        event.preventDefault();
        closeHistoryMenu();
      } else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        let index = buttons.indexOf(document.activeElement);
        index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
        buttons[index].focus();
      } else if (event.key === 'Tab') {
        event.preventDefault();
        const trigger = historyMenuTrigger;
        closeHistoryMenu(false);
        const targets = [...document.querySelectorAll('a[href],button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')].filter(el => el.getClientRects().length > 0);
        const next = targets[targets.indexOf(trigger) + (event.shiftKey ? -1 : 1)];
        (next || trigger)?.focus();
      }
    });
    document.addEventListener('click', event => {
      if (!$('historyMenu').hidden && !event.target.closest('#historyMenu') && !event.target.closest('[data-history-menu]')) closeHistoryMenu(false);
    });
    window.addEventListener('resize', () => closeHistoryMenu(false));
    $('history').addEventListener('scroll', () => closeHistoryMenu(false));
    $('newTask').addEventListener('click', () => {
      clearSourceBrief();
      closeHistoryMenu(false);
      appState.selected = null;
      appState.rendered = '';
      render();
      $('composer').scrollIntoView({
        behavior: scrollBehavior()
      });
      $('task').focus({
        preventScroll: true
      });
    });
    $('deleteHistory').addEventListener('click', () => openDeleteDialog(appState.selected));
    $('cancelDelete').addEventListener('click', () => $('deleteDialog').close());
    $('confirmDelete').addEventListener('click', async () => {
      const id = deleteTarget;
      if (!id) return;
      $('confirmDelete').disabled = true;
      try {
        const result = await request('/api/history/delete', {
          id
        });
        appState.runs = appState.runs.filter(r => r.id !== id);
        if (appState.selected === id) appState.selected = null;
        appState.rendered = '';
        $('deleteDialog').close();
        notifications.show(result.message);
        render();
      } catch (error) {
        $('deleteDialog').close();
        notifications.show(error.message, {
          duration: 0
        });
      } finally {
        $('confirmDelete').disabled = false;
      }
    });
  }
  return {
    init,
    renderHistory
  };
}
