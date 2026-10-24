import { state as appState } from './state.js';
import { $, e } from './dom.js';
import { request } from './api.js';
import { roleNames, defaultTeam, modeNames, providerLabel } from './constants.js';
export function createTeams({
  updateButtons
}) {
  let presets = [];
  let connectionStates = null;
  let modelCatalog = null;
  function updateTeamCards() {
    $('teamName').textContent = $('taskMode').value === 'build' ? appState.currentTeam.name : providerLabel(appState.currentTeam.roles.observer.provider) + ' observes · ' + modeNames[$('taskMode').value];
    for (const role of roleNames) {
      const p = appState.currentTeam.roles[role];
      $(role + 'Provider').textContent = providerLabel(p.provider);
      $(role + 'Avatar').className = 'avatar ' + p.provider;
      $(role + 'Avatar').textContent = p.provider === 'claude' ? 'Cl' : 'Cx';
      $(role + 'Model').textContent = (p.model || 'Tool default model') + ' · ' + (p.effort ? p.effort + ' effort' : 'default effort');
    }
    const activeRoles = $('taskMode').value === 'build' ? roleNames : ['observer'];
    for (const role of roleNames) $(role + 'Avatar').closest('.agent-card').hidden = !activeRoles.includes(role);
    appState.connected = !!connectionStates && activeRoles.every(role => connectionStates[appState.currentTeam.roles[role].provider]?.signed_in);
    if (connectionStates) $('connectionSummary').textContent = appState.connected ? 'Your selected tools are signed in' : 'A selected tool needs your attention';
    updateButtons();
  }
  function fillRoleChoices(role, model = '', effort = '') {
    const provider = $(role + 'Tool').value,
      catalog = modelCatalog[provider];
    const models = catalog.models;
    $(role + 'ModelInput').innerHTML = '<option value="">Tool default</option>' + models.map(m => `<option value="${e(m.id)}">${e(m.label)}</option>`).join('');
    if (model && !models.some(m => m.id === model)) $(role + 'ModelInput').insertAdjacentHTML('beforeend', `<option value="${e(model)}">${e(model)} (saved model)</option>`);
    $(role + 'ModelInput').value = model;
    fillEffortChoices(role, effort);
  }
  function fillEffortChoices(role, effort = '') {
    const provider = $(role + 'Tool').value,
      model = $(role + 'ModelInput').value;
    const catalog = modelCatalog[provider],
      entry = catalog.models.find(m => m.id === model);
    const levels = entry ? entry.efforts : catalog.default_efforts;
    const names = {
      low: 'Low',
      medium: 'Medium',
      high: 'High',
      xhigh: 'Extra high',
      max: 'Max',
      ultra: 'Ultra'
    };
    $(role + 'Effort').innerHTML = '<option value="">Tool default</option>' + levels.map(level => `<option value="${e(level)}">${e(names[level] || level)}</option>`).join('');
    $(role + 'Effort').value = levels.includes(effort) ? effort : '';
    if (effort && !levels.includes(effort)) $('teamNotice').textContent = 'Effort reset to Tool default because it is not offered for this model.';
  }
  function fillTeamEditor(team) {
    $('teamLabel').value = team.name;
    for (const role of roleNames) {
      const p = team.roles[role];
      $(role + 'Tool').value = p.provider;
      fillRoleChoices(role, p.model, p.effort || '');
      $(role + 'Instructions').value = p.instructions;
    }
  }
  function readTeamEditor() {
    return {
      name: $('teamLabel').value.trim(),
      roles: Object.fromEntries(roleNames.map(role => [role, {
        provider: $(role + 'Tool').value,
        model: $(role + 'ModelInput').value,
        effort: $(role + 'Effort').value,
        instructions: $(role + 'Instructions').value.trim()
      }]))
    };
  }
  function teamKey(team) {
    return JSON.stringify([team.name, roleNames.map(role => {
      const p = team.roles[role];
      return [p.provider, p.model || '', p.effort || '', p.instructions || ''];
    })]);
  }
  function presetOptions(selected = '') {
    $('teamPreset').innerHTML = '<option value="">New / custom team</option><option value="__default__">Built-in default</option>' + presets.map(p => `<option value="${e(p.id)}">${e(p.team.name)}</option>`).join('');
    $('teamPreset').value = selected;
    $('saveTeamPreset').textContent = selected && selected !== '__default__' ? 'Update preset' : 'Save preset';
  }
  async function loadTeams() {
    try {
      const [data, catalog] = await Promise.all([request('/api/teams'), request('/api/models')]);
      presets = data.presets;
      modelCatalog = catalog;
      let saved = null;
      try {
        saved = JSON.parse(localStorage.getItem('relay.team') || 'null');
      } catch (_) {}
      if (saved && typeof saved.name === 'string' && roleNames.every(role => saved.roles?.[role] && ['claude', 'codex'].includes(saved.roles[role].provider) && typeof saved.roles[role].model === 'string' && typeof saved.roles[role].instructions === 'string')) appState.currentTeam = saved;else appState.currentTeam = data.default;
      for (const role of roleNames) appState.currentTeam.roles[role].effort = appState.currentTeam.roles[role].effort || '';
      updateTeamCards();
      $('configureTeam').disabled = false;
    } catch (error) {
      $('teamName').textContent = 'Team settings unavailable. Restart Relay. ' + error.message;
    }
  }
  async function connections() {
    $('refreshConnections').disabled = true;
    try {
      const status = await request('/api/connections');
      connectionStates = status;
      updateTeamCards();
      for (const name of ['claude', 'codex']) {
        $(name + 'Status').textContent = status[name].signed_in ? 'Signed in' : status[name].installed ? 'Sign in needed' : 'Not installed';
        $(name + 'Status').className = 'badge ' + (status[name].signed_in ? 'ready' : '');
      }
      $('connectionSummary').textContent = appState.connected ? 'Your selected tools are signed in' : 'A selected tool needs your attention';
      $('connectionDetails').innerHTML = Object.entries(status).map(([name, s]) => `<p>${e(name)} · ${e(s.version || 'Not installed')} · ${e(s.message)}</p>`).join('');
      $('connectionHelp').open = !appState.connected;
      updateButtons();
    } catch (error) {
      $('connectionSummary').textContent = error.message;
    } finally {
      $('refreshConnections').disabled = false;
    }
  }
  function init() {
    $('configureTeam').addEventListener('click', () => {
      $('teamError').textContent = '';
      $('teamNotice').textContent = '';
      const matching = presets.find(p => teamKey(p.team) === teamKey(appState.currentTeam));
      presetOptions(matching?.id || (teamKey(appState.currentTeam) === teamKey(defaultTeam) ? '__default__' : ''));
      fillTeamEditor(appState.currentTeam);
      $('teamDialog').showModal();
      $('teamPreset').focus();
    });
    $('cancelTeam').addEventListener('click', () => $('teamDialog').close());
    $('teamPreset').addEventListener('change', () => {
      $('teamError').textContent = '';
      $('teamNotice').textContent = '';
      const id = $('teamPreset').value;
      if (id === '__default__') fillTeamEditor(defaultTeam);else if (id) fillTeamEditor(presets.find(p => p.id === id).team);else $('teamLabel').value = 'My team';
      $('saveTeamPreset').textContent = id && id !== '__default__' ? 'Update preset' : 'Save preset';
    });
    $('saveTeamPreset').addEventListener('click', async () => {
      if (!$('teamForm').reportValidity()) return;
      $('saveTeamPreset').disabled = true;
      $('teamError').textContent = '';
      try {
        const id = $('teamPreset').value;
        const entry = await request('/api/teams/save', {
          team: readTeamEditor(),
          id: id && id !== '__default__' ? id : null
        });
        presets = (await request('/api/teams')).presets;
        presetOptions(entry.id);
        $('teamNotice').textContent = 'Preset saved. Click Use team to apply it to new tasks.';
      } catch (error) {
        $('teamError').textContent = error.message;
      } finally {
        $('saveTeamPreset').disabled = false;
      }
    });
    $('teamForm').addEventListener('submit', event => {
      event.preventDefault();
      const team = readTeamEditor();
      if (!team.name) {
        $('teamError').textContent = 'Enter a team name.';
        return;
      }
      appState.currentTeam = team;
      try {
        localStorage.setItem('relay.team', JSON.stringify(team));
      } catch (_) {}
      updateTeamCards();
      $('teamDialog').close();
    });
    for (const role of roleNames) {
      $(role + 'Tool').addEventListener('change', () => fillRoleChoices(role));
      $(role + 'ModelInput').addEventListener('change', () => fillEffortChoices(role, $(role + 'Effort').value));
    }
  }
  return {
    init,
    updateTeamCards,
    loadTeams,
    connections
  };
}
