import { $, e } from './dom.js';
import { state } from './state.js';
import { request } from './api.js';

export function createTaskQueue({ selectedProject, imagePayload, clearImageDraft, clearSourceBrief, render }) {
  let snapshot = {items:[],can_start:false,error:''};
  let key = '', busy = false;
  function paint(data = snapshot) {
    snapshot = data || snapshot;
    const nextKey = JSON.stringify([snapshot,busy]);
    if (nextKey === key) return;
    key = nextKey;
    const expanded = new Set([...$('queueItems').querySelectorAll('details[open]')].map(item => item.querySelector('[data-queue-id]')?.dataset.queueId));
    $('queueWorkspace').hidden = !snapshot.items?.length && !snapshot.error;
    $('queueCount').textContent = snapshot.items?.length || 0;
    $('queueStorageError').textContent = snapshot.error || '';
    $('queueItems').innerHTML = (snapshot.items || []).map((item,index,items) => {
      const mode = item.mode === 'build' ? 'Build & review' : item.mode === 'plan' ? 'Plan only' : 'Observe only';
      const project = item.project.split('/').filter(Boolean).pop() || item.project;
      return `<details class="queue-item"><summary><span class="queue-position">${index === 0 ? 'Next' : index + 1}</span><strong>${e(item.task)}</strong><span>${e(project)}</span></summary><div class="queue-item-detail"><p>${e(item.task)}</p><span class="hint">${e(item.project)}<br>${e(mode)} · ${e(item.team.name)} · ${item.minutes ? e(item.minutes) + ' min' : 'No time limit'}${item.mode === 'build' ? ' · ' + (item.rounds ? e(item.rounds) + ' review rounds' : 'No round limit') : ''}${item.image_count ? ' · ' + e(item.image_count) + ' images' : ''}</span><div class="queue-item-actions"><button type="button" class="secondary" data-queue-action="up" data-queue-id="${e(item.id)}" ${index === 0 || busy ? 'disabled' : ''} aria-label="Move task up">↑</button><button type="button" class="secondary" data-queue-action="down" data-queue-id="${e(item.id)}" ${index === items.length - 1 || busy ? 'disabled' : ''} aria-label="Move task down">↓</button><button type="button" class="secondary" data-queue-action="remove" data-queue-id="${e(item.id)}" ${busy ? 'disabled' : ''}>Remove</button>${index === 0 ? `<button type="button" class="secondary queue-start" data-queue-action="start" data-queue-id="${e(item.id)}" ${!snapshot.can_start || busy ? 'disabled' : ''}>Start task →</button>` : ''}</div></div></details>`;
    }).join('');
    for (const item of $('queueItems').querySelectorAll('details')) {
      item.open = expanded.has(item.querySelector('[data-queue-id]')?.dataset.queueId);
    }
  }
  function init() {
    const add = document.createElement('button');
    add.id = 'addToQueue';
    add.type = 'button';
    add.className = 'secondary add-to-queue';
    add.textContent = 'Save to task queue';
    $('start').after(add);
    const section = document.createElement('details');
    section.id = 'queueWorkspace';
    section.className = 'queue-workspace';
    section.hidden = true;
    section.innerHTML = '<summary>Task queue <span id="queueCount">0</span><small>Saved briefs · start only when you choose</small></summary><p id="queueStorageError" class="form-error" role="alert"></p><div id="queueItems"></div><p id="queueActionError" class="form-error" role="alert"></p>';
    document.querySelector('.workspace-grid').before(section);
    add.addEventListener('click', async () => {
      if (busy || state.imageLoading || !$('taskForm').reportValidity()) return;
      busy = true;
      add.disabled = true;
      $('formError').textContent = '';
      try {
        const saved = await request('/api/queue/add', {
          ...(state.pendingSource || {}),task:$('task').value,project:selectedProject(),
          mode:$('taskMode').value,team:state.currentTeam,rounds:Number($('rounds').value),minutes:Number($('minutes').value),images:imagePayload('task')
        });
        $('task').value = '';
        clearImageDraft('task');
        clearSourceBrief();
        snapshot = saved;
        $('queueWorkspace').open = true;
      } catch (error) {
        $('formError').textContent = error.message;
      } finally {
        busy = false;
        add.disabled = false;
        paint();
      }
    });
    $('queueItems').addEventListener('click', async event => {
      const button = event.target.closest('[data-queue-action]');
      if (!button || busy) return;
      const openItems = new Set([...$('queueItems').querySelectorAll('details[open]')].map(item => item.querySelector('[data-queue-id]').dataset.queueId));
      busy = true;
      $('queueActionError').textContent = '';
      const action = button.dataset.queueAction;
      try {
        const result = await request('/api/queue/' + (['up','down'].includes(action) ? 'move' : action), {
          id:button.dataset.queueId,...(['up','down'].includes(action) ? {direction:action === 'up' ? -1 : 1} : {})
        });
        if (action === 'start') {
          state.selected = result.id;
          state.rendered = '';
          const fresh = await request('/api/state');
          state.runs = fresh.runs;
          snapshot = fresh.queue;
          render();
          $('feedTab').click();
          document.querySelector('.activity').scrollIntoView({behavior:'auto',block:'start'});
        } else snapshot = result;
      } catch (error) {
        $('queueActionError').textContent = error.message;
      } finally {
        busy = false;
        paint();
        for (const item of $('queueItems').querySelectorAll('details')) {
          const id = item.querySelector('[data-queue-id]')?.dataset.queueId;
          item.open = openItems.has(id);
        }
      }
    });
  }
  return {init,render:paint};
}
