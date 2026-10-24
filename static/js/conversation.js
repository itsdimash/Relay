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
export function createConversation({
  renderRecovery,
  renderClarification,
  renderHistory,
  updateButtons,
  activeRun,
  clearImageDraft
}) {
  let followupImageChat = null;
  function render() {
    renderHistory();
    updateButtons();
    const r = appState.runs.find(x => x.id === appState.selected);
    document.querySelector('.activity').hidden = !r;
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
    $('pipeline').innerHTML = ((r.mode || 'build') === 'build' ? [['observing', '1 · Inspect'], ['awaiting_clarification', '2 · Clarify'], ['awaiting_approval', '3 · Approve'], ['building', '4 · Build'], ['reviewing', '5 · Review'], ['fixing', '6 · Refine'], ['done', '7 · Result']] : r.mode === 'plan' ? [['observing', '1 · Inspect'], ['awaiting_clarification', '2 · Clarify'], ['done', '3 · Plan']] : [['observing', '1 · Observe'], ['done', '2 · Report']]).map(([stage, label]) => `<span class="${r.status === stage ? 'current' : ''}">${label}</span>`).join('');
    $('taskMeta').textContent = `${modeNames[r.mode || 'build']}${(r.mode || 'build') === 'build' ? ' · Round ' + r.round + (r.max_rounds ? ' of ' + r.max_rounds : ' · No round limit') : ''} · ${r.minutes ? r.minutes + ' minute limit' : 'No time limit'}${r.team ? '\nTeam: ' + r.team.name + ' · ' + ((r.mode || 'build') === 'build' ? roleNames : ['observer']).map(role => role + ': ' + providerLabel(r.team.roles[role].provider)).join(' / ') : ''}${r.workspace ? '\n' + ((r.mode || 'build') === 'build' ? 'Working copy: ' : 'Inspected folder: ') + r.workspace : ''}`;
    const finished = terminal.has(r.status);
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
    $('feed').hidden = awaiting || clarifying || $('feedTab').getAttribute('aria-selected') !== 'true';
    $('feed').innerHTML = turns.map((turn, i) => renderTurn(turn, i)).join('') + renderTurn({
      ...r,
      summary: report
    }, turns.length, true);
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
  function init() {}
  return {
    init,
    render
  };
}
