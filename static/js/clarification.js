import { state as appState } from './state.js';
import { $, e } from './dom.js';
import { request } from './api.js';
import '../markdown.js';

/** Questions refine requirements; this controller never calls the plan-approval API. */
export function createClarification({ render: renderConversation }) {
  let current = null;
  const draftKey = () => current ? `relay.clarification.${current.runId}.${current.id}` : '';
  function answers() {
    return Object.fromEntries([...$('clarificationQuestions').querySelectorAll('textarea')].map(input => [input.dataset.questionId, input.value]));
  }
  function saveDraft() {
    try { if (current) sessionStorage.setItem(draftKey(), JSON.stringify(answers())); } catch (_) {}
  }
  function render(run) {
    const pending = run?.status === 'awaiting_clarification' && run.clarification;
    $('clarificationPanel').hidden = !pending;
    const history = [...(run?.turns || []), run].filter(Boolean).flatMap(turn => turn.clarifications || []);
    const historyKey = JSON.stringify(history);
    if ($('clarificationHistory').dataset.key !== historyKey) {
      $('clarificationHistory').dataset.key = historyKey;
      $('clarificationHistory').innerHTML = history.length ? '<details><summary>Your clarification answers · ' + history.length + ' ' + (history.length === 1 ? 'round' : 'rounds') + '</summary>' + history.map(batch => '<dl>' + batch.questions.map(question => '<dt>' + e(question.question) + '</dt><dd>' + e(batch.answers[question.id]) + '</dd>').join('') + '</dl>').join('') + '</details>' : '';
    }
    $('clarificationHistory').hidden = !history.length;
    if (!pending || current?.id === pending.id && current.runId === run.id) return;
    current = { runId: run.id, id: pending.id };
    $('clarificationError').textContent = '';
    $('sendClarification').disabled = false;
    $('clarificationNotes').innerHTML = globalThis.renderMarkdown(pending.summary || '');
    $('clarificationQuestions').innerHTML = pending.questions.map((question, index) => '<div class="clarification-question"><label for="clarificationAnswer-' + e(question.id) + '">' + (index + 1) + '. ' + e(question.question) + '</label>' + (question.options?.length ? '<div class="clarification-options" role="group" aria-label="Suggestions for question ' + (index + 1) + '">' + question.options.map((option, optionIndex) => '<button type="button" class="secondary" data-question-option="' + e(question.id) + '" data-option-index="' + optionIndex + '">' + e(option) + '</button>').join('') + '</div>' : '') + '<textarea id="clarificationAnswer-' + e(question.id) + '" data-question-id="' + e(question.id) + '" rows="3" maxlength="2000" required placeholder="Your answer; you can also describe another preference."></textarea></div>').join('');
    try {
      const saved = JSON.parse(sessionStorage.getItem(draftKey()) || '{}');
      for (const input of $('clarificationQuestions').querySelectorAll('textarea')) {
        if (typeof saved[input.dataset.questionId] === 'string') input.value = saved[input.dataset.questionId].slice(0, 2000);
      }
    } catch (_) {}
  }
  function init() {
    $('clarificationQuestions').addEventListener('input', saveDraft);
    $('clarificationQuestions').addEventListener('click', event => {
      const button = event.target.closest('[data-question-option]');
      if (!button || !current) return;
      const run = appState.runs.find(run => run.id === current.runId);
      const question = run?.clarification?.questions.find(question => question.id === button.dataset.questionOption);
      const option = question?.options[Number(button.dataset.optionIndex)];
      if (typeof option !== 'string') return;
      const input = $('clarificationAnswer-' + question.id);
      input.value = option; input.focus(); saveDraft();
    });
    $('clarificationForm').addEventListener('submit', async event => {
      event.preventDefault();
      if (!current || $('sendClarification').disabled) return;
      const batch = { ...current }, key = draftKey();
      $('sendClarification').disabled = true;
      $('clarificationError').textContent = '';
      try {
        await request('/api/answer-clarification', { id: batch.runId, clarification_id: batch.id, answers: answers() });
        try { sessionStorage.removeItem(key); } catch (_) {}
        const snapshot = await request('/api/state');
        appState.runs = snapshot.runs; appState.rendered = '';
        renderConversation();
      } catch (error) {
        $('clarificationError').textContent = error.message;
      } finally {
        $('sendClarification').disabled = false;
      }
    });
  }
  return { init, render };
}
