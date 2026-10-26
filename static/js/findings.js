import { state as appState } from './state.js';
import { $, scrollBehavior } from './dom.js';
import { defaultTeam, sourceFindings } from './constants.js';
export function createFindings({
  renderDraft,
  projectChanged,
  updateTeamCards,
  updateTaskMode
}) {
  function updateSourceBrief() {
    $('sourceBrief').hidden = !appState.pendingSource;
    $('sourceBriefText').textContent = appState.pendingSource ? `${appState.pendingSource.finding_indexes.length} ${appState.pendingSource.finding_indexes.length === 1 ? 'finding' : 'findings'} will travel with this task. ${appState.runs.find(r => r.id === appState.pendingSource.source_id)?.attachments?.length || 0} images inherited from the source report. Review the prompt, model settings, and project before starting.` : '';
  }
  function clearSourceBrief() {
    appState.pendingSource = null;
    updateSourceBrief();
  }
  function init() {
    $('clearSource').addEventListener('click', clearSourceBrief);
    $('project').addEventListener('change', clearSourceBrief);
    $('findings').addEventListener('change', () => {
      const count = document.querySelectorAll('[name="selectedFinding"]:checked').length;
      $('findingSelectionCount').textContent = count ? `${count} selected · opens a task draft for you to review.` : 'Choose the findings you want to address.';
      $('planFindings').disabled = !count;
      $('buildFindings').disabled = !count;
    });
    $('findings').addEventListener('click', async event => {
      const action = event.target.closest('button')?.id;
      if (action === 'selectAllFindings') {
        const choices = [...document.querySelectorAll('[name="selectedFinding"]')],
          checked = choices.some(input => !input.checked);
        choices.forEach(input => input.checked = checked);
        $('findings').dispatchEvent(new Event('change'));
        return;
      }
      if (!['planFindings', 'buildFindings'].includes(action)) return;
      const run = appState.runs.find(r => r.id === appState.selected),
        indexes = [...document.querySelectorAll('[name="selectedFinding"]:checked')].map(input => Number(input.value));
      if (!run || !indexes.length) return;
      if (!$('followupForm').hidden) {
        // Continue in this chat: the agent acts on it as the next turn of the conversation.
        const plan = action === 'planFindings';
        $('followupQuestion').value = (plan ? 'Create an implementation plan for' : 'Verify and fix') + ' the selected findings from the earlier report:\n\n' + indexes.map(i => `${sourceFindings(run)[i].id}: ${sourceFindings(run)[i].problem}`).join('\n') + '\n\nStay within these findings. Verify each against the current code and explain any finding that is no longer valid.';
        $('followupForm').scrollIntoView({ behavior: scrollBehavior() });
        $('followupQuestion').focus({ preventScroll: true });
        return;
      }
      const project = run.original_project || run.project;
      if (![...$('project').options].some(option => option.value === project)) {
        const option = new Option('Report project · ' + project, project);
        $('project').add(option);
      }
      $('project').value = project;
      projectChanged();
      appState.currentTeam = structuredClone(run.team || defaultTeam);
      updateTeamCards();
      appState.pendingSource = {
        source_id: run.id,
        finding_indexes: indexes
      };
      updateSourceBrief();
      $('taskMode').value = action === 'planFindings' ? 'plan' : 'build';
      updateTaskMode();
      $('task').value = (action === 'planFindings' ? 'Create an implementation plan for' : 'Verify and fix') + ' the selected findings from the earlier report:\n\n' + indexes.map(i => `${sourceFindings(run)[i].id}: ${sourceFindings(run)[i].problem}`).join('\n') + '\n\nStay within these findings. Verify each against the current code and explain any finding that is no longer valid.';
      appState.selected = null;
      appState.rendered = '';
      renderDraft?.();
      $('composer').scrollIntoView({
        behavior: scrollBehavior()
      });
      $('task').focus({
        preventScroll: true
      });
    });
  }
  return {
    init,
    updateSourceBrief,
    clearSourceBrief
  };
}
