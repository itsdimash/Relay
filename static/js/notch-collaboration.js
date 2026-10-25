/** Saved role activity, real handoffs, and evidence-based result counts. */
const roles = ['observer', 'builder', 'reviewer'];
const names = { observer: 'Observer', builder: 'Builder', reviewer: 'Reviewer' };
const steps = { observer: 'inspect', builder: 'build', reviewer: 'review' };
const providerName = provider => provider === 'claude' ? 'Claude' : provider === 'codex' ? 'Codex' : '';

export function createCollaboration({ doc = document, openRun, reducedMotion = false }) {
  const $ = id => doc.getElementById(id);
  let run = null, selectedRole = null, previousId = null, previousRole = null;
  let handoffTimer = null, exitTimer = null;

  function hideHandoff() {
    clearTimeout(handoffTimer);
    clearTimeout(exitTimer);
    $('handoff').hidden = true;
    delete $('handoff').dataset.leaving;
  }

  function showHandoff(from, to) {
    hideHandoff();
    const provider = role => providerName(run.team?.[role]?.provider) || names[role];
    const sameProvider = provider(from) === provider(to);
    $('handoffTitle').textContent = `${sameProvider ? names[from] : provider(from)} → ${sameProvider ? names[to] : provider(to)}`;
    const detail = to === 'reviewer' ? 'Reviewing changes' : to === 'builder' ? run.status === 'fixing' ? 'Applying review feedback' : 'Building the next step' : 'Inspecting the project';
    const count = run.result?.files;
    $('handoffDetail').textContent = `${detail}${Number.isInteger(count) && count > 0 ? ` · ${count} ${count === 1 ? 'file' : 'files'}` : ''}`;
    $('handoff').hidden = false;
    handoffTimer = setTimeout(() => {
      $('handoff').dataset.leaving = '';
      exitTimer = setTimeout(hideHandoff, reducedMotion ? 0 : 220);
    }, 3400);
  }

  function renderAgent() {
    $('agentCard').hidden = !selectedRole;
    $('panel').toggleAttribute('data-agent-detail', !!selectedRole);
    for (const button of doc.querySelectorAll('[data-agent]')) {
      button.setAttribute('aria-pressed', String(button.dataset.agent === selectedRole));
      button.setAttribute('aria-controls', 'agentCard');
    }
    if (!selectedRole) return;
    const provider = providerName(run?.team?.[selectedRole]?.provider);
    $('agentCardTitle').textContent = `${names[selectedRole]}${provider ? ` · ${provider}` : ''}`;
    const activity = run?.activities?.[selectedRole];
    const active = run?.running && !run.paused && run.actor === selectedRole;
    const state = active ? 'Working now' : run?.paused && run.actor === selectedRole ? 'Paused' : activity ? 'Last saved activity' : 'No saved activity';
    let time = '';
    const date = new Date(activity?.time || '');
    if (Number.isFinite(date.getTime())) time = ` · ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    $('agentCardState').textContent = state + time;
    $('agentCardMessage').textContent = activity?.message || (active ? 'This agent has started. Its next update will appear here.' : 'This role has not saved an update for this run.');
    $('openAgentStep').disabled = !run;
  }

  function renderResult() {
    const visible = !!run && !run.running && !selectedRole;
    $('resultCard').hidden = !visible;
    $('panel').toggleAttribute('data-result-card', visible);
    if (!visible) return;
    const result = run.result || {};
    const checks = result.checks || {};
    $('resultTitle').textContent = run.demo ? 'Example complete' : run.status === 'done' ? run.mode === 'build' ? 'Review approved' : 'Report ready' : 'Run needs attention';
    const parts = [];
    if (Number.isInteger(result.files)) parts.push(`${result.files} changed ${result.files === 1 ? 'file' : 'files'}`);
    if (Number.isInteger(result.findings)) parts.push(`${result.findings} open ${result.findings === 1 ? 'finding' : 'findings'}`);
    $('resultCounts').textContent = parts.join(' · ') || 'Open the saved report for details.';
    const total = (checks.passed || 0) + (checks.failed || 0) + (checks.not_run || 0);
    $('resultEvidence').textContent = run.demo ? 'Simulation · no real checks' : total ? `${checks.passed || 0} passed · ${checks.failed || 0} failed${checks.not_run ? ` · ${checks.not_run} not run` : ''} · builder-reported checks` : 'No builder checks reported';
    $('openChanges').hidden = run.mode !== 'build';
  }

  function update(next) {
    run = next;
    if ((run?.id || null) !== previousId) {
      hideHandoff();
      selectedRole = null;
      previousRole = null;
      previousId = run?.id || null;
    }
    if (run?.running && !run.paused && roles.includes(run.actor)) {
      if (previousRole && previousRole !== run.actor) showHandoff(previousRole, run.actor);
      previousRole = run.actor;
    }
    if (!run?.running) hideHandoff();
    renderAgent();
    renderResult();
  }

  for (const button of doc.querySelectorAll('[data-agent]')) button.addEventListener('click', () => {
    selectedRole = selectedRole === button.dataset.agent ? null : button.dataset.agent;
    hideHandoff();
    renderAgent();
    renderResult();
  });
  $('closeAgent').addEventListener('click', () => {
    const role = selectedRole;
    selectedRole = null;
    renderAgent();
    renderResult();
    doc.querySelector(`.room-roles [data-agent="${role}"]`)?.focus();
  });
  $('openAgentStep').addEventListener('click', () => run && selectedRole && openRun({ runId: run.id, tab: 'feed', step: selectedRole === 'builder' && run.status === 'fixing' ? 'refine' : steps[selectedRole] }));
  $('openChanges').addEventListener('click', () => run && openRun({ runId: run.id, tab: 'changes', step: 'result' }));
  $('openResult').addEventListener('click', () => run && openRun({ runId: run.id, tab: 'feed', step: 'result' }));
  return { update, hideHandoff };
}
