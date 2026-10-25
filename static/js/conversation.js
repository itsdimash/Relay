import { state as appState } from './state.js';
import { $, e } from './dom.js';
import { roleNames, sourceFindings, modeNames, providerLabel, terminal, labels } from './constants.js';
import '../markdown.js';
import '../review.js';
const {
  renderMarkdown,
  renderReportBrief,
  renderChangeReview,
  reportPriority
} = globalThis;

const buildSteps = [
  { key: 'inspect', stage: 'observing', label: 'Inspect', empty: 'The run ended before inspection activity was saved.' },
  { key: 'clarify', stage: 'awaiting_clarification', label: 'Clarify', empty: 'No clarification was needed for this run.' },
  { key: 'approve', stage: 'awaiting_approval', label: 'Approve', empty: 'No approval activity was saved.' },
  { key: 'build', stage: 'building', label: 'Build', empty: 'The Builder did not run.' },
  { key: 'review', stage: 'reviewing', label: 'Review', empty: 'The Reviewer did not run.' },
  { key: 'refine', stage: 'fixing', label: 'Refine', empty: 'No refinement round was needed.' },
  { key: 'result', stage: 'done', label: 'Result', empty: 'A final result has not been saved yet.' }
];

const stageKeys = {
  queued: 'inspect',
  preparing: 'inspect',
  observing: 'inspect',
  awaiting_clarification: 'clarify',
  awaiting_approval: 'approve',
  building: 'build',
  reviewing: 'review',
  fixing: 'refine',
  done: 'result',
  needs_attention: 'result',
  failed: 'result',
  stopped: 'result',
  interrupted: 'result'
};

const eventStageKeys = {
  preparing: 'inspect',
  observing: 'inspect',
  'awaiting clarification': 'clarify',
  'awaiting approval': 'approve',
  building: 'build',
  reviewing: 'review',
  fixing: 'refine',
  refining: 'refine',
  done: 'result'
};

function ensureRunBrief() {
  if ($('runBrief')) return;
  const brief = document.createElement('section');
  brief.id = 'runBrief';
  brief.className = 'run-brief';
  brief.setAttribute('aria-labelledby', 'runBriefLabel');
  brief.innerHTML = '<div class="run-brief-heading"><span id="runBriefLabel">Ran prompt</span><time id="runBriefTime"></time></div><p id="runBriefText"></p><div class="run-brief-note"><span aria-hidden="true">✓</span><span id="runBriefNote">Already submitted · this is the saved run</span></div>';
  $('pipeline').before(brief);
  $('pipeline').setAttribute('role', 'tablist');
  $('pipeline').setAttribute('aria-label', 'Run steps');
}

function eventsByStep(run) {
  const grouped = Object.fromEntries(buildSteps.map(step => [step.key, []]));
  let current = 'inspect';
  for (const event of run.events || []) {
    if (event.kind === 'stage') current = eventStageKeys[String(event.message || '').toLowerCase()] || current;
    if (event.kind === 'control' && /approv/i.test(event.message || '')) current = 'approve';
    grouped[current].push(event);
  }
  return grouped;
}

function eventBody(event) {
  let message = event.message || '';
  if (event.role && event.kind === 'message') {
    try {
      const parsed = JSON.parse(message);
      message = [parsed.overview, parsed.summary].filter(Boolean).join('\n\n') || message;
    } catch (_) {}
  }
  if (event.kind === 'tool') return `<details class="step-tool"><summary>Tool activity</summary><code>${e(message)}</code></details>`;
  return `<div class="step-event-copy">${renderMarkdown(message)}</div>`;
}

function renderStepEvents(events) {
  return events.map(event => {
    const who = event.role ? event.role.charAt(0).toUpperCase() + event.role.slice(1) : 'Relay';
    const date = new Date(event.time);
    const time = Number.isFinite(date.getTime()) ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
    const kind = event.kind === 'stage' ? 'Stage' : event.kind === 'control' ? 'Decision' : event.kind === 'tool' ? 'Tool' : 'Update';
    return `<article class="step-event ${e(event.kind || '')}"><div class="step-event-marker" aria-hidden="true"></div><div><div class="step-event-head"><strong>${e(who)}</strong><span>${e(kind)}</span>${time ? `<time datetime="${e(event.time)}">${e(time)}</time>` : ''}</div>${eventBody(event)}</div></article>`;
  }).join('');
}
export function createConversation({
  renderRecovery,
  renderClarification,
  renderHistory,
  updateButtons,
  activeRun,
  clearImageDraft
}) {
  let followupImageChat = null;
  const selectedSteps = new Map();
  const manualStepRuns = new Set();
  let appliedDestination = null;
  function applyDestination() {
    const hash = location.hash;
    if (!hash || hash === appliedDestination) return;
    const destination = new URLSearchParams(hash.slice(1));
    const id = destination.get('run');
    if (!appState.runs.some(run => run.id === id)) return;
    const step = destination.get('step');
    appState.selected = id;
    if (buildSteps.some(item => item.key === step)) {
      selectedSteps.set(id, step);
      manualStepRuns.add(id);
    }
    const tab = destination.get('tab');
    (tab === 'changes' ? $('changesTab') : tab === 'findings' ? $('findingsTab') : $('feedTab')).click();
    appState.rendered = '';
    appliedDestination = hash;
  }
  function render() {
    applyDestination();
    renderHistory();
    updateButtons();
    const r = appState.runs.find(x => x.id === appState.selected);
    document.querySelector('.activity').hidden = !r;
    document.querySelector('.content').classList.toggle('run-open', !!r);
    renderClarification(r);
    renderRecovery(r);
    if (!r) {
      appState.rendered = '';
      $('followupForm').hidden = true;
      $('planApproval').hidden = true;
      $('runTitle').textContent = 'Your team’s activity';
      $('runStatus').textContent = 'Ready for a task';
      $('runStatus').className = 'badge';
      for (const id of ['pause', 'stop', 'deleteHistory', 'simulationBanner', 'summary']) $(id).hidden = true;
      for (const id of ['pipeline', 'taskMeta', 'changes', 'findings', 'summary']) $(id).textContent = '';
      $('fileCount').textContent = '0';
      $('findingCount').textContent = '0';
      $('feed').innerHTML = '<div class="empty"><h3>No chat selected.</h3><p>Start a task or select a saved chat.</p></div>';
      return;
    }
    ensureRunBrief();
    const key = JSON.stringify(r);
    if (key === appState.rendered) return;
    appState.rendered = key;
    const active = !terminal.has(r.status);
    $('runTitle').textContent = r.demo ? 'Example collaboration' : (r.conversation_title || r.task).slice(0, 100);
    $('runStatus').textContent = r.demo && r.status === 'done' ? 'Example complete' : r.status === 'done' && (r.mode || 'build') !== 'build' ? 'Report ready' : r.paused && active ? 'Pause after current step' : labels[r.status] || r.status;
    $('runStatus').className = 'badge ' + r.status;
    const awaiting = r.status === 'awaiting_approval';
    const clarifying = r.status === 'awaiting_clarification';
    $('pause').hidden = !active || awaiting || clarifying;
    $('planApproval').hidden = !awaiting;
    if (awaiting && r.plan) {
      if ($('planApproval').dataset.planId !== r.plan.id) {
        $('approvalError').textContent = '';
        $('planApproval').dataset.planId = r.plan.id;
      }
      $('approvalReport').innerHTML = renderMarkdown(r.plan.summary);
      $('approvalChecks').innerHTML = '<h4>Verification checks</h4><ul>' + r.plan.acceptance_checks.map(check => '<li>' + e(check) + '</li>').join('') + '</ul>' + (r.plan.findings.length ? '<h4>Risks to consider</h4><ul>' + r.plan.findings.map(f => '<li><strong>' + e(f.file) + '</strong> · ' + e(f.problem) + '</li>').join('') + '</ul>' : '');
    }
    $('stop').hidden = !active;
    $('deleteHistory').hidden = active;
    $('pause').textContent = r.paused ? 'Resume handoffs' : 'Pause handoffs';
    $('simulationBanner').hidden = !r.demo;
    const finished = terminal.has(r.status);
    const created = new Date(r.created);
    $('runBriefLabel').textContent = active ? 'Running prompt' : 'Ran prompt';
    $('runBriefTime').textContent = Number.isFinite(created.getTime()) ? `Submitted ${created.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}` : '';
    $('runBriefTime').dateTime = r.created || '';
    $('runBriefText').textContent = r.task;
    $('runBriefNote').textContent = active ? 'In progress · this prompt has already been submitted' : 'Already submitted · this is the saved run';

    const groupedEvents = eventsByStep(r);
    const steps = (r.mode || 'build') === 'build' ? buildSteps : r.mode === 'plan' ? [buildSteps[0], buildSteps[1], { ...buildSteps[6], label: 'Plan' }] : [{ ...buildSteps[0], label: 'Observe' }, { ...buildSteps[6], label: 'Report' }];
    $('pipeline').style.setProperty('--run-step-count', steps.length);
    const availableKeys = new Set(steps.map(step => step.key));
    const automaticStep = availableKeys.has(stageKeys[r.status]) ? stageKeys[r.status] : steps[steps.length - 1].key;
    if (!manualStepRuns.has(r.id) || !availableKeys.has(selectedSteps.get(r.id))) selectedSteps.set(r.id, automaticStep);
    const selectedStep = selectedSteps.get(r.id);
    $('pipeline').innerHTML = steps.map((step, index) => {
      const hasActivity = groupedEvents[step.key]?.length > 0;
      const skipped = finished && !hasActivity && step.key !== 'result';
      const current = step.key === automaticStep && !finished;
      const selected = step.key === selectedStep;
      const state = skipped ? 'Not needed' : current ? 'In progress' : hasActivity || step.key === 'result' && finished ? 'Complete' : 'Not started';
      return `<button type="button" role="tab" data-run-step="${e(step.key)}" aria-selected="${selected}" aria-controls="feed" tabindex="${selected ? '0' : '-1'}" class="run-step${selected ? ' selected' : ''}${current ? ' current' : ''}${skipped ? ' skipped' : ''}${hasActivity ? ' visited' : ''}" title="${e(step.label)} · ${state}"><span>${index + 1}</span>${e(step.label)}<small>${e(state)}</small></button>`;
    }).join('');
    $('taskMeta').textContent = `${modeNames[r.mode || 'build']}${(r.mode || 'build') === 'build' ? ' · Round ' + r.round + (r.max_rounds ? ' of ' + r.max_rounds : ' · No round limit') : ''} · ${r.minutes ? r.minutes + ' minute limit' : 'No time limit'}${r.team ? '\nTeam name: ' + r.team.name + ' · ' + ((r.mode || 'build') === 'build' ? roleNames : ['observer']).map(role => role + ': ' + providerLabel(r.team.roles[role].provider)).join(' / ') : ''}${r.workspace ? '\n' + ((r.mode || 'build') === 'build' ? 'Working copy: ' : 'Inspected folder: ') + r.workspace : ''}`;
    const lastError = [...r.events].reverse().find(event => event.kind === 'error');
    const report = r.summary || lastError?.message || '';
    const shownImages = new Set();
    const savedImages = turn => (turn.attachments || []).filter(image => !shownImages.has(image.id) && shownImages.add(image.id)).map(image => {
      const url = '/api/image?run=' + encodeURIComponent(r.id) + '&image=' + encodeURIComponent(image.id);
      return `<a href="${url}" target="_blank" rel="noopener" title="Open ${e(image.name)}"><img src="${url}" alt="${e(image.name)}" loading="lazy"><span>${e(image.name)}</span></a>`;
    }).join('');
    const renderTurn = (turn, index, current = false) => {
      const role = (turn.mode || 'build') === 'build' ? 'reviewer' : 'observer';
      const provider = turn.team?.roles[role]?.provider;
      const author = turn.status === 'failed' ? 'Relay' : provider ? providerLabel(provider) : 'Relay';
      const question = index > 0 ? `<div class="followup-question"><span>You</span><p>${e(turn.task)}</p></div>` : '';
      const body = current && !finished ? `<div class="empty"><h3>${e(labels[r.status] || 'Your team is working…')}</h3><p>The final result will appear here when this task finishes.</p></div>` : turn.summary ? `<article class="event final-report"><div class="avatar ${e(author.toLowerCase())}">${author === 'Claude' ? 'Cl' : author === 'Codex' ? 'Cx' : 'r'}</div><div class="event-body"><div class="event-head"><strong>${e(author)}</strong><span>${turn.status === 'failed' ? 'Task could not finish' : index > 0 ? 'Follow-up answer' : 'Final result'}</span></div>${renderReportBrief(turn)}<details class="report-evidence" ${!turn.overview && turn.summary.length < 1200 ? 'open' : ''}><summary>Full report &amp; evidence</summary><div class="event-text report-content">${renderMarkdown(turn.summary)}</div></details></div></article>` : '<div class="empty"><p>This task ended before a final report was saved.</p></div>';
      const images = savedImages(turn);
      return question + (images ? '<div class="saved-images">' + images + '</div>' : '') + body;
    };
    if (followupImageChat !== r.id) {
      clearImageDraft('followup');
      followupImageChat = r.id;
    }
    const turns = r.turns || [];
    $('feed').hidden = $('feedTab').getAttribute('aria-selected') !== 'true';
    if (selectedStep === 'result') {
      $('feed').innerHTML = turns.map((turn, i) => renderTurn(turn, i)).join('') + renderTurn({
        ...r,
        summary: report
      }, turns.length, true);
    } else {
      const step = steps.find(item => item.key === selectedStep);
      const events = groupedEvents[selectedStep] || [];
      const plan = selectedStep === 'approve' && r.plan ? `<article class="step-plan"><div class="step-panel-label">Approved plan</div><div class="report-content">${renderMarkdown(r.plan.summary)}</div></article>` : '';
      $('feed').innerHTML = `<div class="step-panel-heading"><div><span>Step ${steps.indexOf(step) + 1}</span><h3>${e(step?.label || 'Activity')}</h3></div><p>${events.length} saved ${events.length === 1 ? 'event' : 'events'}</p></div>${plan}${events.length ? `<div class="step-timeline">${renderStepEvents(events)}</div>` : `<div class="step-empty"><span aria-hidden="true">—</span><div><strong>${e(step?.empty || 'No activity was saved.')}</strong><p>Relay skipped this step because the run did not need it.</p></div></div>`}`;
    }
    $('followupForm').hidden = !finished || r.demo || !['done', 'needs_attention'].includes(r.status) && !turns.length;
    $('sendFollowup').disabled = !!activeRun() || appState.loading || !!appState.imageLoading;
    $('followupNotice').textContent = activeRun() ? 'Wait for the active task to finish.' : 'Read-only · uses your Observer model and account' + (r.attachments?.length ? ' · ' + r.attachments.length + ' saved images included' : '');
    const changeRun = (r.mode || 'build') === 'build' ? r : [...(r.turns || [])].reverse().find(turn => turn.mode === 'build') || r;
    $('fileCount').textContent = changeRun.files.length;
    $('changes').innerHTML = (changeRun.mode || 'build') === 'build' ? renderChangeReview({
      ...changeRun,
      id: r.id,
      export_complete: finished && changeRun.export_complete
    }) : '<p class="muted">Read-only task. Editing tools are disabled; existing project changes are not recorded as task edits.</p>';
    const findings = sourceFindings(r);
    $('findingCount').textContent = findings.length;
    $('findings').innerHTML = findings.length ? findings.map((f, index) => `<article class="finding"><label class="finding-choice"><input type="checkbox" name="selectedFinding" value="${index}" ${active || r.demo ? 'disabled' : ''}><span>Select ${e(f.id)} for a new task</span></label><h3><span class="priority ${reportPriority(f.priority)}">${f.priority ? e(f.priority) : 'Unrated'}</span>${e(f.id)} · ${e(f.problem)}</h3><code>${e(f.file)}</code><p><strong>Evidence</strong>\n${e(f.evidence)}</p><p><strong>Requested change</strong>\n${e(f.requested_change)}</p></article>`).join('') : '<p class="muted">No open findings recorded. The task status indicates whether a review has finished.</p>';
    if (findings.length && !active && !r.demo) {
      $('findings').insertAdjacentHTML('beforeend', '<div class="finding-actions"><div><strong>Turn findings into a task</strong><p class="hint" id="findingSelectionCount">Choose the findings you want to address.</p></div><button type="button" class="secondary" id="selectAllFindings">Select all</button><button type="button" class="secondary" id="planFindings" disabled>Plan selected</button><button type="button" class="primary" id="buildFindings" disabled>Build & review selected</button></div>');
    }
    $('summary').hidden = true;
    $('summary').textContent = '';
  }
  function selectStep(button) {
    const run = appState.runs.find(item => item.id === appState.selected);
    if (!run) return;
    selectedSteps.set(run.id, button.dataset.runStep);
    manualStepRuns.add(run.id);
    $('feedTab').click();
    appState.rendered = '';
    render();
    $('pipeline').querySelector(`[data-run-step="${button.dataset.runStep}"]`)?.focus();
  }
  function init() {
    window.addEventListener('hashchange', () => {
      appliedDestination = null;
      render();
      if (appState.selected) document.querySelector('.activity').scrollIntoView({ block: 'start', behavior: 'auto' });
    });
    $('pipeline').addEventListener('click', event => {
      const button = event.target.closest('[data-run-step]');
      if (button) selectStep(button);
    });
    $('pipeline').addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const buttons = [...$('pipeline').querySelectorAll('[data-run-step]')];
      const current = event.target.closest('[data-run-step]');
      if (!current || !buttons.length) return;
      event.preventDefault();
      let index = buttons.indexOf(current);
      index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
      selectStep(buttons[index]);
    });
  }
  return {
    init,
    render
  };
}
