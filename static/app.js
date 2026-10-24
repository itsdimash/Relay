import { createRecovery } from './js/recovery.js';
import { createClarification } from './js/clarification.js';
import { state } from './js/state.js';
import { $ } from './js/dom.js';
import { createNotifications } from './js/notifications.js';
import { createTeams } from './js/teams.js';
import { createProjects } from './js/projects.js';
import { createAttachments } from './js/attachments.js';
import { createHistory } from './js/history.js';
import { createConversation } from './js/conversation.js';
import { createFindings } from './js/findings.js';
import { createTasks } from './js/tasks.js';
const notifications = createNotifications();
const recovery = createRecovery({ render: () => conversation.render() });
const clarification = createClarification({ render: () => conversation.render() });
const teams = createTeams({
  updateButtons: () => tasks.updateButtons()
});
const projects = createProjects({
  clearSourceBrief: () => findings.clearSourceBrief()
});
const attachments = createAttachments({
  updateButtons: () => tasks.updateButtons()
});
const history = createHistory({
  render: () => conversation.render(),
  clearSourceBrief: () => findings.clearSourceBrief(),
  notifications
});
const conversation = createConversation({
  renderRecovery: run => recovery.render(run),
  renderClarification: run => clarification.render(run),
  renderHistory: () => history.renderHistory(),
  updateButtons: () => tasks.updateButtons(),
  activeRun: () => tasks.activeRun(),
  clearImageDraft: prefix => attachments.clearImageDraft(prefix)
});
const findings = createFindings({
  projectChanged: () => projects.projectChanged(),
  updateTeamCards: () => teams.updateTeamCards(),
  updateTaskMode: () => tasks.updateTaskMode()
});
const tasks = createTasks({
  updateTeamCards: () => teams.updateTeamCards(),
  connections: () => teams.connections(),
  selectedProject: () => projects.selectedProject(),
  imagePayload: prefix => attachments.imagePayload(prefix),
  clearImageDraft: prefix => attachments.clearImageDraft(prefix),
  clearSourceBrief: () => findings.clearSourceBrief(),
  updateSourceBrief: () => findings.updateSourceBrief(),
  render: () => conversation.render()
});
for (const feature of [recovery, clarification, teams, projects, attachments, history, conversation, findings, tasks]) feature.init();
try {
  const draft = JSON.parse(sessionStorage.getItem('relay.devDraft') || 'null');
  if (draft) {
    $('taskMode').value = draft.mode || 'build';
    $('task').value = draft.task || '';
    $('rounds').value = draft.rounds || '3';
    $('minutes').value = draft.minutes || '20';
    state.selected = draft.selected;
    state.pendingSource = draft.pendingSource || null;
    findings.updateSourceBrief();
    sessionStorage.removeItem('relay.devDraft');
  }
} catch (_) {}
tasks.updateTaskMode();
tasks.poll();
teams.connections();
projects.loadProjects();
teams.loadTeams();
