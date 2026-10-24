import { state as appState } from './state.js';
import { $, e } from './dom.js';
import { request } from './api.js';
import { terminal } from './constants.js';

/** User-triggered recovery of a saved step; never approves a plan. */
export function createRecovery({ render: renderConversation }) {
  let current = null, submitting = null;
  function render(run) {
    const option = run?.recovery;
    $('recoveryPanel').hidden = !option;
    const attempts = run?.recovery_attempts || [];
    const key = JSON.stringify(attempts);
    if ($('recoveryHistory').dataset.key !== key) {
      $('recoveryHistory').dataset.key = key;
      $('recoveryHistory').innerHTML = attempts.length ? '<details><summary>Recovery history · ' + attempts.length + '</summary><ol>' + attempts.map(attempt => '<li><strong>Attempt ' + e(attempt.attempt) + ' · ' + e(attempt.from_step) + ' · ' + e(attempt.status) + '</strong><p>' + e(attempt.previous_summary || attempt.previous_status) + '</p></li>').join('') + '</ol></details>' : '';
    }
    $('recoveryHistory').hidden = !attempts.length;
    if (!option) { current = null; return; }
    const ident = run.id + ':' + (option.checkpoint_id || 'unavailable');
    if (current?.ident !== ident) $('recoveryError').textContent = '';
    current = { ident, runId: run.id, checkpoint: option.checkpoint_id };
    $('recoverTask').hidden = !option.available;
    $('recoverTask').disabled = submitting === ident || !run.worker_finished || !!appState.runs.find(task => !terminal.has(task.status) || task.worker_finished === false);
    $('recoverTask').textContent = submitting === ident ? 'Checking saved work…' : option.label || 'Continue task';
    $('recoveryTitle').textContent = run.status === 'interrupted' ? 'Continue interrupted work' : run.status === 'stopped' ? 'Continue stopped work' : 'Recover this task';
    $('recoveryDescription').textContent = option.available ? 'Relay will check the preserved working copy and continue this saved step. Completed steps stay saved. An unapproved plan still needs your approval.' : option.reason;
    $('recoveryCompleted').innerHTML = (option.completed || []).map(item => '<li>' + e(item) + '</li>').join('');
    $('recoveryBudget').textContent = option.available ? (run.minutes ? 'This attempt gets a new ' + run.minutes + '-minute time budget.' : 'This attempt has no time limit.') + ' The original review-round limit still applies.' : '';
  }
  function init() {
    $('recoverTask').addEventListener('click', async () => {
      if (!current || $('recoverTask').disabled) return;
      const target = { ...current };
      submitting = target.ident;
      $('recoverTask').disabled = true; $('recoverTask').textContent = 'Checking saved work…'; $('recoveryError').textContent = '';
      try {
        await request('/api/recover', { id: target.runId, checkpoint_id: target.checkpoint });
        const snapshot = await request('/api/state');
        appState.runs = snapshot.runs; appState.rendered = '';
        renderConversation();
      } catch (error) {
        if (current?.ident === target.ident) $('recoveryError').textContent = error.message;
      } finally {
        submitting = null;
        if (current?.ident === target.ident) render(appState.runs.find(run => run.id === target.runId));
      }
    });
  }
  return { init, render };
}
