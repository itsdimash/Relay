import { state as appState } from './state.js';
import { $, e } from './dom.js';
import { request } from './api.js';
import { terminal } from './constants.js';

/** User-triggered recovery of a saved step; never approves a plan. */
export function createRecovery({ render: renderConversation }) {
  let current = null, submitting = null;
  function render(run) {
    const option = run?.recovery;
    const decision = run?.status === 'needs_attention' && !run.demo;
    $('recoveryPanel').hidden = !option && !decision;
    $('recoveryPanel').classList.toggle('decision', decision);
    const attempts = run?.recovery_attempts || [];
    const key = JSON.stringify(attempts);
    if ($('recoveryHistory').dataset.key !== key) {
      $('recoveryHistory').dataset.key = key;
      $('recoveryHistory').innerHTML = attempts.length ? '<details><summary>Recovery history · ' + attempts.length + '</summary><ol>' + attempts.map(attempt => '<li><strong>Attempt ' + e(attempt.attempt) + ' · ' + e(attempt.from_step) + ' · ' + e(attempt.status) + '</strong><p>' + e(attempt.previous_summary || attempt.previous_status) + '</p></li>').join('') + '</ol></details>' : '';
    }
    $('recoveryHistory').hidden = !attempts.length;
    if (decision) {
      const open = run.findings || [];
      $('recoveryTitle').textContent = 'Needs your decision';
      $('recoveryDescription').textContent = `The Builder and Reviewer used ${run.max_rounds ? 'all ' + run.max_rounds : 'the'} review rounds and the Reviewer still has ${open.length} open ${open.length === 1 ? 'finding' : 'findings'}. The Builder’s changes are already in your folder. Choose what happens next, or ask a question below.`;
      $('recoveryFindings').hidden = !open.length;
      $('recoveryFindings').innerHTML = open.map(f => '<li><span>' + e(f.priority || 'open') + '</span><strong>' + e(f.id) + '</strong> · ' + e(f.problem) + '<br><code>' + e(f.file) + '</code></li>').join('');
    } else {
      $('recoveryFindings').hidden = true;
    }
    $('recoveryRounds').hidden = !(decision && option?.available);
    $('reviewChanges').hidden = !decision;
    if (!option) { current = null; $('recoverTask').hidden = true; $('recoveryTime').hidden = true; $('recoveryBudget').textContent = ''; $('recoveryCompleted').innerHTML = ''; return; }
    const ident = run.id + ':' + (option.checkpoint_id || 'unavailable');
    if (current?.ident !== ident) $('recoveryError').textContent = '';
    current = { ident, runId: run.id, checkpoint: option.checkpoint_id };
    $('recoverTask').hidden = !option.available;
    $('recoverTask').disabled = submitting === ident || !run.worker_finished || !!appState.runs.find(task => !terminal.has(task.status) || task.worker_finished === false);
    $('recoverTask').textContent = submitting === ident ? 'Checking saved work…' : option.label || 'Continue task';
    if (!decision) $('recoveryTitle').textContent = run.status === 'interrupted' ? 'Continue interrupted work' : run.status === 'stopped' ? 'Continue stopped work' : 'Recover this task';
    if (decision && !option.available) $('recoveryDescription').textContent += ' ' + (option.reason || '');
    if (!decision) $('recoveryDescription').textContent = option.available ? 'Relay will check your folder and its saved baseline, then continue this saved step. Completed steps stay saved. An unapproved plan still needs your approval.' : option.reason;
    $('recoveryCompleted').innerHTML = (option.completed || []).map(item => '<li>' + e(item) + '</li>').join('');
    $('recoveryTime').hidden = !option.available;
    $('recoveryBudget').textContent = !option.available ? '' : decision ? 'Pick how many more review rounds and how much time this attempt gets.' : (/time limit/i.test(run.summary || '') ? 'The previous attempt ran out of time. Pick how long this one may run.' : 'Pick how long this attempt may run.') + ' The original review-round limit still applies.';
  }
  function init() {
    $('reviewChanges').addEventListener('click', () => {
      $('changesTab').click();
      $('changesTab').scrollIntoView({ block: 'start', behavior: 'smooth' });
    });
    $('recoverTask').addEventListener('click', async () => {
      if (!current || $('recoverTask').disabled) return;
      const target = { ...current };
      submitting = target.ident;
      $('recoverTask').disabled = true; $('recoverTask').textContent = 'Checking saved work…'; $('recoveryError').textContent = '';
      try {
        const decision = !$('recoveryRounds').hidden;
        await request('/api/recover', { id: target.runId, checkpoint_id: target.checkpoint, minutes: Number($('recoveryMinutes').value), ...(decision ? { rounds: Number($('recoveryRoundsSelect').value) } : {}) });
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
