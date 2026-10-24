import { state as appState } from './state.js';
import { $, scrollBehavior } from './dom.js';
import { request } from './api.js';
import { terminal } from './constants.js';
export function createTasks({
  updateTeamCards,
  connections,
  selectedProject,
  imagePayload,
  clearImageDraft,
  clearSourceBrief,
  updateSourceBrief,
  render
}) {
  let devRevision = null;
  function updateTaskMode() {
    const mode = $('taskMode').value,
      build = mode === 'build';
    $('projectHint').textContent = build ? 'Save a name and folder once, then select it for future tasks. Work happens in a separate copy of a clean Git repository.' : 'The Observer reads your selected folder as it is, including uncommitted files. No Git repository or clean working tree is required.';
    $('task').placeholder = build ? 'Describe the change and what a successful result looks like…' : mode === 'plan' ? 'Describe what you want to achieve and ask for a plan…' : 'What should the Observer inspect or explain?…';
    $('taskModeHint').textContent = build ? 'Observer → Questions if needed → Your approval → Builder → Reviewer. Review the plan before editing begins.' : mode === 'plan' ? 'The Observer prepares a plan. Editing tools are disabled; no builder or reviewer runs.' : 'The Observer inspects the project and reports findings. Editing tools are disabled; no builder or reviewer runs.';
    document.querySelector('.agents').classList.toggle('single-role', !build);
    $('roundsSetting').hidden = !build;
    $('rounds').disabled = !build;
    $('start').innerHTML = (build ? 'Start collaboration' : mode === 'plan' ? 'Create a plan' : 'Start observation') + ' <span aria-hidden="true">→</span>';
    $('workflowSteps').innerHTML = (build ? [['Understand', 'The Observer explores the project, asks for missing details, and defines what to check.'], ['Approve & build', 'Review the proposed plan. The builder starts only after you approve.'], ['Review & refine', 'The reviewer gives evidence. The builder fixes issues or explains its decisions.']] : [['Inspect', 'The observer reads the project with editing tools disabled.'], [mode === 'plan' ? 'Plan' : 'Report', mode === 'plan' ? 'Receive proposed steps, affected files, risks, and verification criteria.' : 'Receive findings and explanations supported by the source.']]).map(([title, description], i) => `<li><span class="step-number">${i + 1}</span><div><strong>${title}</strong><p>${description}</p></div></li>`).join('');
    updateTeamCards();
  }
  function activeRun() {
    return appState.runs.find(r => !terminal.has(r.status));
  }
  function updateButtons() {
    $('start').disabled = !appState.connected || !!activeRun() || appState.loading || !!appState.imageLoading;
    $('demo').disabled = !!activeRun() || appState.loading || !!appState.imageLoading;
    $('sendFollowup').disabled = !!activeRun() || appState.loading || !!appState.imageLoading;
    $('start').title = !appState.connected ? 'Connect the selected tools before starting a real task' : '';
  }
  async function poll() {
    try {
      const state = await request('/api/state');
      if (state.dev) {
        if (devRevision && devRevision !== state.dev.revision && !state.dev.busy && !appState.imageDrafts.task.length && !appState.imageDrafts.followup.length && !appState.imageLoading) {
          try {
            sessionStorage.setItem('relay.devDraft', JSON.stringify({
              task: $('task').value,
              mode: $('taskMode').value,
              rounds: $('rounds').value,
              minutes: $('minutes').value,
              selected: appState.selected,
              pendingSource: appState.pendingSource
            }));
          } catch (_) {}
          location.reload();
          return;
        }
        if (!devRevision) devRevision = state.dev.revision;
      }
      appState.token = state.token;
      appState.runs = state.runs;
      if (appState.pendingSource) updateSourceBrief();
      if (appState.selected && !appState.runs.some(r => r.id === appState.selected)) appState.selected = null;
      $('serverState').textContent = 'Local workspace';
      render();
    } catch (error) {
      $('serverState').textContent = 'Connection lost · retrying';
    } finally {
      setTimeout(poll, 1200);
    }
  }
  async function start(demo = false) {
    if (appState.loading || appState.imageLoading) return;
    appState.loading = true;
    updateButtons();
    $('formError').textContent = '';
    try {
      const result = await request('/api/run', {
        ...(!demo && appState.pendingSource || {}),
        images: demo ? [] : imagePayload('task'),
        task: $('task').value,
        project: selectedProject(),
        mode: $('taskMode').value,
        team: appState.currentTeam,
        rounds: Number($('rounds').value),
        minutes: Number($('minutes').value),
        demo
      });
      if (!demo) clearImageDraft('task');
      clearSourceBrief();
      appState.selected = result.id;
      appState.rendered = '';
      const state = await request('/api/state');
      appState.runs = state.runs;
      render();
      $('feedTab').click();
      document.querySelector('.activity').scrollIntoView({
        behavior: scrollBehavior(),
        block: 'start'
      });
    } catch (error) {
      $('formError').textContent = error.message;
    } finally {
      appState.loading = false;
      updateButtons();
    }
  }
  function init() {
    $('taskMode').addEventListener('change', updateTaskMode);
    $('taskForm').addEventListener('submit', event => {
      event.preventDefault();
      start();
    });
    $('demo').addEventListener('click', () => start(true));
    $('refreshConnections').addEventListener('click', connections);
    for (const action of ['pause', 'stop']) $(action).addEventListener('click', async () => {
      const r = appState.runs.find(x => x.id === appState.selected);
      if (!r) return;
      const verb = action === 'pause' && r.paused ? 'resume' : action;
      $(action).disabled = true;
      try {
        await request('/api/' + verb, {
          id: appState.selected
        });
      } catch (error) {
        $('formError').textContent = error.message;
      } finally {
        $(action).disabled = false;
      }
    });
    for (const tab of document.querySelectorAll('[data-tab]')) {
      tab.addEventListener('click', () => {
        for (const t of document.querySelectorAll('[data-tab]')) {
          const on = t === tab;
          t.setAttribute('aria-selected', String(on));
          t.tabIndex = on ? 0 : -1;
          $(t.dataset.tab).hidden = !on || t.dataset.tab === 'feed' && ['awaiting_approval', 'awaiting_clarification'].includes(appState.runs.find(r => r.id === appState.selected)?.status);
        }
      });
      tab.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const tabs = [...document.querySelectorAll('[data-tab]')];
        let index = tabs.indexOf(tab);
        index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
        tabs[index].click();
        tabs[index].focus();
      });
    }
    $('followupForm').addEventListener('submit', async event => {
      event.preventDefault();
      if (appState.loading || appState.imageLoading || activeRun()) return;
      const run = appState.runs.find(r => r.id === appState.selected),
        question = $('followupQuestion').value.trim();
      if (!run || !question) return;
      appState.loading = true;
      updateButtons();
      $('sendFollowup').disabled = true;
      $('followupError').textContent = '';
      try {
        const result = await request('/api/followup', {
          source_id: run.id,
          task: question,
          images: imagePayload('followup'),
          minutes: Number($('minutes').value)
        });
        appState.selected = result.id;
        appState.rendered = '';
        $('followupQuestion').value = '';
        clearImageDraft('followup');
        const state = await request('/api/state');
        appState.runs = state.runs;
        render();
      } catch (error) {
        $('followupError').textContent = error.message;
      } finally {
        appState.loading = false;
        appState.rendered = '';
        render();
      }
    });
    for (const action of ['approvePlan', 'rejectPlan']) $(action).addEventListener('click', async () => {
      const run = appState.runs.find(r => r.id === appState.selected);
      if (run?.status !== 'awaiting_approval') return;
      $('approvePlan').disabled = true;
      $('rejectPlan').disabled = true;
      $('approvalError').textContent = '';
      try {
        await request(action === 'approvePlan' ? '/api/approve-plan' : '/api/stop', {
          id: run.id,
          plan_id: run.plan.id
        });
        const state = await request('/api/state');
        appState.runs = state.runs;
        appState.rendered = '';
        render();
      } catch (error) {
        $('approvalError').textContent = error.message;
      } finally {
        $('approvePlan').disabled = false;
        $('rejectPlan').disabled = false;
      }
    });
    $('changes').addEventListener('click', event => {
      const button = event.target.closest('[data-review-file]');
      if (!button) return;
      const panel = $('changes').querySelector(`[data-review-panel="${button.dataset.reviewFile}"]`);
      if (panel) {
        panel.open = true;
        panel.scrollIntoView({
          behavior: 'auto',
          block: 'start'
        });
        panel.querySelector('summary').focus();
      }
    });
  }
  return {
    init,
    updateTaskMode,
    updateButtons,
    activeRun,
    poll
  };
}
