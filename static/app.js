const $ = id => document.getElementById(id);
let devRevision = null;
const imageDrafts={task:[],followup:[]};
let imageLoading=0, followupImageChat=null;
let deletedChat = null, deleteTarget = null, pendingSource = null;
let token = '', runs = [], selected = null, rendered = '', connected = false, loading = false;
const roleNames = ['observer','builder','reviewer'];
const defaultTeam = {name:'Claude reviews · Codex builds', roles:Object.fromEntries(roleNames.map(role=>[role,{provider:role==='builder'?'codex':'claude',model:'',effort:'',instructions:''}]))};
let currentTeam = structuredClone(defaultTeam), presets = [], connectionStates = null, modelCatalog = null;
const sourceFindings = run => [run,...[...(run.turns||[])].reverse()].find(turn=>turn.findings?.length)?.findings||[];
const modeNames = {observe:'Observe only',plan:'Plan only',build:'Build & review'};
function updateTaskMode() {
  const mode=$('taskMode').value, build=mode==='build';
  $('projectHint').textContent=build?'Save a name and folder once, then select it for future tasks. Work happens in a separate copy of a clean Git repository.':'The Observer reads your selected folder as it is, including uncommitted files. No Git repository or clean working tree is required.';
  $('task').placeholder=build?'Describe the change and what a successful result looks like…':mode==='plan'?'Describe what you want to achieve and ask for a plan…':'What should the Observer inspect or explain?…';
  $('taskModeHint').textContent=build?'Observer → Your approval → Builder → Reviewer. Review the plan before editing begins.':mode==='plan'?'The Observer prepares a plan. Editing tools are disabled; no builder or reviewer runs.':'The Observer inspects the project and reports findings. Editing tools are disabled; no builder or reviewer runs.';
  document.querySelector('.agents').classList.toggle('single-role',!build);
  $('roundsSetting').hidden=!build; $('rounds').disabled=!build;
  $('start').innerHTML=(build?'Start collaboration':mode==='plan'?'Create a plan':'Start observation')+' <span aria-hidden="true">→</span>';
  $('workflowSteps').innerHTML=(build?[['Understand','The observer explores the project and defines what to check.'],['Approve & build','Review the proposed plan. The builder starts only after you approve.'],['Review & refine','The reviewer gives evidence. The builder fixes issues or explains its decisions.']]:[['Inspect','The observer reads the project with editing tools disabled.'],[mode==='plan'?'Plan':'Report',mode==='plan'?'Receive proposed steps, affected files, risks, and verification criteria.':'Receive findings and explanations supported by the source.']]).map(([title,description],i)=>`<li><span class="step-number">${i+1}</span><div><strong>${title}</strong><p>${description}</p></div></li>`).join('');
  updateTeamCards();
}
const providerLabel = name => name==='claude'?'Claude':'Codex';
function updateTeamCards() {
  $('teamName').textContent=$('taskMode').value==='build'?currentTeam.name:providerLabel(currentTeam.roles.observer.provider)+' observes · '+(modeNames[$('taskMode').value]);
  for(const role of roleNames){
    const p=currentTeam.roles[role];
    $(role+'Provider').textContent=providerLabel(p.provider);
    $(role+'Avatar').className='avatar '+p.provider;$(role+'Avatar').textContent=p.provider==='claude'?'Cl':'Cx';
    $(role+'Model').textContent=(p.model||'Tool default model')+' · '+(p.effort?p.effort+' effort':'default effort');
  }
  const activeRoles=$('taskMode').value==='build'?roleNames:['observer'];
  for(const role of roleNames)$(role+'Avatar').closest('.agent-card').hidden=!activeRoles.includes(role);
  connected=!!connectionStates&&activeRoles.every(role=>connectionStates[currentTeam.roles[role].provider]?.signed_in);
  if(connectionStates)$('connectionSummary').textContent=connected?'Your selected tools are signed in':'A selected tool needs your attention';
  updateButtons();
}
function fillRoleChoices(role, model='', effort='') {
  const provider=$(role+'Tool').value, catalog=modelCatalog[provider];
  const models=catalog.models;
  $(role+'ModelInput').innerHTML='<option value="">Tool default</option>'+models.map(m=>`<option value="${e(m.id)}">${e(m.label)}</option>`).join('');
  if(model&&!models.some(m=>m.id===model))$(role+'ModelInput').insertAdjacentHTML('beforeend',`<option value="${e(model)}">${e(model)} (saved model)</option>`);
  $(role+'ModelInput').value=model;
  fillEffortChoices(role,effort);
}
function fillEffortChoices(role, effort='') {
  const provider=$(role+'Tool').value, model=$(role+'ModelInput').value;
  const catalog=modelCatalog[provider], entry=catalog.models.find(m=>m.id===model);
  const levels=entry?entry.efforts:catalog.default_efforts;
  const names={low:'Low',medium:'Medium',high:'High',xhigh:'Extra high',max:'Max',ultra:'Ultra'};
  $(role+'Effort').innerHTML='<option value="">Tool default</option>'+levels.map(level=>`<option value="${e(level)}">${e(names[level]||level)}</option>`).join('');
  $(role+'Effort').value=levels.includes(effort)?effort:'';
  if(effort&&!levels.includes(effort))$('teamNotice').textContent='Effort reset to Tool default because it is not offered for this model.';
}
function fillTeamEditor(team) {
  $('teamLabel').value=team.name;
  for(const role of roleNames){const p=team.roles[role];$(role+'Tool').value=p.provider;fillRoleChoices(role,p.model,p.effort||'');$(role+'Instructions').value=p.instructions;}
}
function readTeamEditor(){return {name:$('teamLabel').value.trim(),roles:Object.fromEntries(roleNames.map(role=>[role,{provider:$(role+'Tool').value,model:$(role+'ModelInput').value,effort:$(role+'Effort').value,instructions:$(role+'Instructions').value.trim()}]))};}
function teamKey(team){return JSON.stringify([team.name,roleNames.map(role=>{const p=team.roles[role];return [p.provider,p.model||'',p.effort||'',p.instructions||''];})]);}
function presetOptions(selected='') {
  $('teamPreset').innerHTML='<option value="">New / custom team</option><option value="__default__">Built-in default</option>'+presets.map(p=>`<option value="${e(p.id)}">${e(p.team.name)}</option>`).join('');
  $('teamPreset').value=selected;
  $('saveTeamPreset').textContent=selected&&selected!=='__default__'?'Update preset':'Save preset';
}
async function loadTeams(){
  try{
    const [data,catalog]=await Promise.all([request('/api/teams'),request('/api/models')]);presets=data.presets;modelCatalog=catalog;
    let saved=null;try{saved=JSON.parse(localStorage.getItem('relay.team')||'null');}catch(_){}
    if(saved&&typeof saved.name==='string'&&roleNames.every(role=>saved.roles?.[role]&&['claude','codex'].includes(saved.roles[role].provider)&&typeof saved.roles[role].model==='string'&&typeof saved.roles[role].instructions==='string'))currentTeam=saved;
    else currentTeam=data.default;
    for(const role of roleNames)currentTeam.roles[role].effort=currentTeam.roles[role].effort||'';
    updateTeamCards();$('configureTeam').disabled=false;
  }catch(error){$('teamName').textContent='Team settings unavailable. Restart Relay. '+error.message;}
}
const terminal = new Set(['done','needs_attention','failed','stopped','interrupted']);
const labels = {queued:'Queued',preparing:'Preparing',observing:'Observer working',awaiting_approval:'Awaiting your approval',building:'Builder working',reviewing:'Reviewer working',fixing:'Builder fixing',done:'Approved',needs_attention:'Needs your decision',failed:'Could not finish',stopped:'Stopped',interrupted:'Interrupted'};
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const e = escapeHTML;
async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Relay-Token':token},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
let savedProjects = [], browsingPath = '', browsingParent = '';
function projectChanged() {
  const project = savedProjects.find(p => p.path === $('project').value);
  $('projectPath').textContent = project ? project.path : '';
  $('removeProject').disabled = !project;
  try { localStorage.setItem('relay.project', $('project').value); } catch (_) {}
}
function selectedProject() { return $('project').value; }
async function loadProjects(preferred) {
  try {
    const result = await request('/api/projects');
    savedProjects = result.projects;
    $('project').innerHTML = '<option value="">' + (savedProjects.length ? 'Choose a saved project…' : 'No saved projects — add your first') + '</option>' + savedProjects.map(p =>
      `<option value="${e(p.path)}" ${p.exists ? '' : 'disabled'}>${e(p.name)}${p.exists ? '' : ' (folder not found)'}</option>`
    ).join('');
    let saved = preferred || '';
    try { if (!saved) saved = localStorage.getItem('relay.project') || ''; } catch (_) {}
    if ([...$('project').options].some(o => o.value === saved && !o.disabled)) $('project').value = saved;
    projectChanged();
  } catch(error) {
    $('project').innerHTML = '<option value="">Saved projects unavailable</option>';
    $('projectNotice').textContent = 'Could not load saved projects. Restart Relay and try again. ' + error.message;
  }
}
async function browseFolders(path) {
  $('folderError').textContent = '';
  $('folderList').setAttribute('aria-busy', 'true');
  $('chooseFolder').disabled = true;
  $('folderGo').disabled = true;
  $('folderUp').disabled = true;
  try {
    const result = await request('/api/folders', {path:path || null});
    browsingPath = result.path; browsingParent = result.parent;
    $('folderLocation').value = result.path;
    $('folderList').innerHTML = result.folders.length ? result.folders.map(p =>
      `<button type="button" class="folder-row" data-folder="${e(p.path)}"><span aria-hidden="true">▱</span><span>${e(p.name)}</span><span aria-hidden="true">›</span></button>`
    ).join('') : '<p class="muted">No visible subfolders. You can choose this folder.</p>';
    $('folderHint').textContent = result.truncated ? 'Showing the first 500 folders. Enter a full path above to open another.' : 'Only folders are shown. Hidden folders can be opened by entering their path above.';
    $('chooseFolder').disabled = false;
    $('folderUp').disabled = browsingPath === browsingParent;
  } catch(error) {
    $('folderError').textContent = error.message;
    $('folderList').innerHTML = '';
    browsingPath = '';
    $('folderUp').disabled = false;
  } finally {
    $('folderList').setAttribute('aria-busy', 'false');
    $('folderGo').disabled = false;
  }
}
async function connections() {
  $('refreshConnections').disabled = true;
  try {
    const status = await request('/api/connections');
    connectionStates = status;
    updateTeamCards();
    for (const name of ['claude','codex']) {
      $(name+'Status').textContent = status[name].signed_in ? 'Signed in' : status[name].installed ? 'Sign in needed' : 'Not installed';
      $(name+'Status').className = 'badge '+(status[name].signed_in?'ready':'');
    }
    $('connectionSummary').textContent = connected ? 'Your selected tools are signed in' : 'A selected tool needs your attention';
    $('connectionDetails').innerHTML = Object.entries(status).map(([name,s])=>`<p>${e(name)} · ${e(s.version || 'Not installed')} · ${e(s.message)}</p>`).join('');
    $('connectionHelp').open = !connected;
    updateButtons();
  } catch(error) { $('connectionSummary').textContent = error.message; }
  finally { $('refreshConnections').disabled = false; }
}
function activeRun() { return runs.find(r=>!terminal.has(r.status)); }
function updateButtons() {
  $('start').disabled = !connected || !!activeRun() || loading || !!imageLoading;
  $('demo').disabled = !!activeRun() || loading || !!imageLoading;
  $('sendFollowup').disabled = !!activeRun() || loading || !!imageLoading;
  $('start').title = !connected ? 'Connect the selected tools before starting a real task' : '';
}
let historyMenuTarget = null, historyMenuTrigger = null;
function conversationTitle(run) {
  const title = run.demo ? (run.conversation_title||run.task).replace(/^(?:example\s*[:·]\s*)+/i, '') : (run.conversation_title||run.task);
  return title ? title.charAt(0).toUpperCase()+title.slice(1) : 'Untitled conversation';
}
function historyDay(created) {
  const date=new Date(created), today=new Date();
  if(!Number.isFinite(date.getTime()))return 'Earlier';
  if(date.toDateString()===today.toDateString())return 'Today';
  today.setDate(today.getDate()-1);
  return date.toDateString()===today.toDateString()?'Yesterday':'Earlier';
}
function renderHistory() {
  const query=$('historySearch').value.trim().toLocaleLowerCase();
  const filtered=runs.filter(run=>(run.conversation_title||run.task).toLocaleLowerCase().includes(query));
  const key=JSON.stringify([filtered.map(run=>[run.id,run.status,run.task,run.created,run.demo]),selected,query]);
  if($('history').dataset.key===key)return;
  closeHistoryMenu(false);
  $('history').dataset.key=key;
  $('taskCount').textContent=query?`${filtered.length}/${runs.length}`:runs.length;
  let group='';
  const states={done:'Completed',stopped:'Stopped',failed:'Could not finish',needs_attention:'Needs review',interrupted:'Interrupted',queued:'Queued',preparing:'Preparing',observing:'Observing',awaiting_approval:'Awaiting approval',building:'Building',reviewing:'Reviewing',fixing:'Refining'};
  $('history').innerHTML=filtered.length?filtered.map(run=>{
    const day=historyDay(run.created), heading=day!==group?`<div class="history-group">${day}</div>`:'';group=day;
    const title=conversationTitle(run), date=new Date(run.created);
    const time=Number.isFinite(date.getTime())?date.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'';
    const active=!terminal.has(run.status);
    return `${heading}<div class="history-row ${run.id===selected?'is-selected':''}"><button class="history-open" data-run="${e(run.id)}" ${run.id===selected?'aria-current="true"':''} title="${e(conversationTitle(run))}"><span class="history-title">${e(title)}</span><span class="history-meta"><span class="history-status ${active?'is-running':run.status==='done'?'is-complete':''}"></span><span>${e(states[run.status]||run.status)}</span>${run.demo?'<span class="history-demo">Demo</span>':''}<time datetime="${e(run.created)}">${e(time)}</time></span></button><button class="history-more" data-history-menu="${e(run.id)}" aria-label="Actions for ${e(title)}" aria-haspopup="menu" aria-expanded="false" title="Conversation actions"><svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg></button></div>`;
  }).join(''):`<div class="history-empty"><svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M4 4h16v12H9l-5 4z"/></svg><p>${query?'No conversations found':'No conversations yet'}</p><span>${query?'Try a different search.':'Your next idea starts here.'}</span></div>`;
}
function closeHistoryMenu(returnFocus=true) {
  $('historyMenu').hidden=true;
  if(historyMenuTrigger){historyMenuTrigger.setAttribute('aria-expanded','false');if(returnFocus&&historyMenuTrigger.isConnected)historyMenuTrigger.focus();}
  historyMenuTarget=null;historyMenuTrigger=null;
}
function openHistoryMenu(id,trigger) {
  if(historyMenuTarget===id&&!$('historyMenu').hidden){closeHistoryMenu();return;}
  closeHistoryMenu(false);
  const run=runs.find(r=>r.id===id);if(!run)return;
  historyMenuTarget=id;historyMenuTrigger=trigger;
  $('historyMenuTitle').textContent=conversationTitle(run);
  $('historyMenuDelete').disabled=!terminal.has(run.status);
  $('historyMenuDelete').title=terminal.has(run.status)?'Move chat to local Trash':'Stop the running task before deleting its history';
  const rect=trigger.getBoundingClientRect();
  $('historyMenu').style.left=Math.max(12,Math.min(rect.right-216,window.innerWidth-228))+'px';
  $('historyMenu').style.top=Math.max(12,Math.min(rect.bottom+5,window.innerHeight-170))+'px';
  $('historyMenu').hidden=false;trigger.setAttribute('aria-expanded','true');$('historyMenuOpen').focus();
}
function render() {
  renderHistory();
  updateButtons();
  const r = runs.find(x=>x.id===selected);
  document.querySelector('.activity').hidden=!r;
  if (!r) {
    rendered='';
    $('followupForm').hidden=true;$('planApproval').hidden=true;
    $('runTitle').textContent='Your team’s activity'; $('runStatus').textContent='Ready for a task'; $('runStatus').className='badge';
    for(const id of ['pause','stop','deleteHistory','simulationBanner','summary']) $(id).hidden=true;
    for(const id of ['pipeline','taskMeta','changes','findings','summary']) $(id).textContent='';
    $('fileCount').textContent='0'; $('findingCount').textContent='0';
    $('feed').innerHTML='<div class="empty"><h3>No chat selected.</h3><p>Start a task or select a saved chat.</p></div>';
    return;
  }
  const key = JSON.stringify(r);
  if (key === rendered) return;
  rendered = key;
  const active = !terminal.has(r.status);
  $('runTitle').textContent = r.demo ? 'Example collaboration' : (r.conversation_title||r.task).slice(0,100);
  $('runStatus').textContent = r.demo && r.status==='done' ? 'Example complete' : r.status==='done' && (r.mode||'build')!=='build' ? 'Report ready' : r.paused && active ? 'Pause after current step' : labels[r.status]||r.status;
  $('runStatus').className = 'badge '+r.status;
  const awaiting=r.status==='awaiting_approval';
  $('pause').hidden = !active||awaiting;
  $('planApproval').hidden=!awaiting;
  if(awaiting&&r.plan){
    if($('planApproval').dataset.planId!==r.plan.id){$('approvalError').textContent='';$('planApproval').dataset.planId=r.plan.id;}
    $('approvalReport').innerHTML=renderMarkdown(r.plan.summary);
    $('approvalChecks').innerHTML='<h4>Verification checks</h4><ul>'+r.plan.acceptance_checks.map(check=>'<li>'+e(check)+'</li>').join('')+'</ul>'+(r.plan.findings.length?'<h4>Risks to consider</h4><ul>'+r.plan.findings.map(f=>'<li><strong>'+e(f.file)+'</strong> · '+e(f.problem)+'</li>').join('')+'</ul>':'');
  }
  $('stop').hidden = !active;
  $('deleteHistory').hidden = active;
  $('pause').textContent = r.paused ? 'Resume handoffs' : 'Pause handoffs';
  $('simulationBanner').hidden = !r.demo;
  $('pipeline').innerHTML = ((r.mode||'build')==='build'?[['observing','1 · Plan'],['awaiting_approval','2 · Approve'],['building','3 · Build'],['reviewing','4 · Review'],['fixing','5 · Refine'],['done','6 · Result']]:[['observing',r.mode==='plan'?'1 · Inspect & plan':'1 · Observe'],['done','2 · Report']]).map(([stage,label])=>`<span class="${r.status===stage?'current':''}">${label}</span>`).join('');
  $('taskMeta').textContent = `${modeNames[r.mode||'build']}${(r.mode||'build')==='build'?' · Round '+r.round+(r.max_rounds?' of '+r.max_rounds:' · No round limit'):''} · ${r.minutes ? r.minutes+' minute limit' : 'No time limit'}${r.team?'\nTeam: '+r.team.name+' · '+((r.mode||'build')==='build'?roleNames:['observer']).map(role=>role+': '+providerLabel(r.team.roles[role].provider)).join(' / '):''}${r.workspace?'\n'+((r.mode||'build')==='build'?'Working copy: ':'Inspected folder: ')+r.workspace:''}`;
  const finished = terminal.has(r.status);
  const lastError = [...r.events].reverse().find(event=>event.kind==='error');
  const report = r.summary || lastError?.message || '';
  const shownImages=new Set();
  const savedImages=turn=>(turn.attachments||[]).filter(image=>!shownImages.has(image.id)&&shownImages.add(image.id)).map(image=>{const url='/api/image?run='+encodeURIComponent(r.id)+'&image='+encodeURIComponent(image.id);return `<a href="${url}" target="_blank" rel="noopener" title="Open ${e(image.name)}"><img src="${url}" alt="${e(image.name)}" loading="lazy"><span>${e(image.name)}</span></a>`;}).join('');
  const renderTurn = (turn, index, current=false) => {
    const role=(turn.mode||'build')==='build'?'reviewer':'observer';
    const provider=turn.team?.roles[role]?.provider;
    const author=turn.status==='failed'?'Relay':provider?providerLabel(provider):'Relay';
    const question=index>0?`<div class="followup-question"><span>You</span><p>${e(turn.task)}</p></div>`:'';
    const body=current&&!finished?`<div class="empty"><h3>${e(labels[r.status]||'Your team is working…')}</h3><p>The final result will appear here when this task finishes.</p></div>`:turn.summary?`<article class="event final-report"><div class="avatar ${e(author.toLowerCase())}">${author==='Claude'?'Cl':author==='Codex'?'Cx':'r'}</div><div class="event-body"><div class="event-head"><strong>${e(author)}</strong><span>${turn.status==='failed'?'Task could not finish':index>0?'Follow-up answer':'Final result'}</span></div>${renderReportBrief(turn)}<details class="report-evidence" ${!turn.overview&&turn.summary.length<1200?'open':''}><summary>Full report &amp; evidence</summary><div class="event-text report-content">${renderMarkdown(turn.summary)}</div></details></div></article>`:'<div class="empty"><p>This task ended before a final report was saved.</p></div>';
    const images=savedImages(turn);
    return question+(images?'<div class="saved-images">'+images+'</div>':'')+body;
  };
  if(followupImageChat!==r.id){clearImageDraft('followup');followupImageChat=r.id;}
  const turns=r.turns||[];
  $('feed').hidden=awaiting||$('feedTab').getAttribute('aria-selected')!=='true';
  $('feed').innerHTML=turns.map((turn,i)=>renderTurn(turn,i)).join('')+renderTurn({...r,summary:report},turns.length,true);
  $('followupForm').hidden=!finished||r.demo||(!['done','needs_attention'].includes(r.status)&&!turns.length);
  $('sendFollowup').disabled=!!activeRun()||loading||!!imageLoading;
  $('followupNotice').textContent=activeRun()?'Wait for the active task to finish.':'Read-only · uses your Observer model and account'+(r.attachments?.length?' · '+r.attachments.length+' saved images included':'');
  const changeRun=(r.mode||'build')==='build'?r:[...(r.turns||[])].reverse().find(turn=>turn.mode==='build')||r;
  $('fileCount').textContent = changeRun.files.length;
  $('changes').innerHTML = (changeRun.mode||'build')==='build'?renderChangeReview(changeRun):'<p class="muted">Read-only task. Editing tools are disabled; existing project changes are not recorded as task edits.</p>';
  const findings=sourceFindings(r);
  $('findingCount').textContent = findings.length;
  $('findings').innerHTML = findings.length ? findings.map((f,index)=>`<article class="finding"><label class="finding-choice"><input type="checkbox" name="selectedFinding" value="${index}" ${active||r.demo?'disabled':''}><span>Select ${e(f.id)} for a new task</span></label><h3><span class="priority ${reportPriority(f.priority)}">${f.priority?e(f.priority):'Unrated'}</span>${e(f.id)} · ${e(f.problem)}</h3><code>${e(f.file)}</code><p><strong>Evidence</strong>\n${e(f.evidence)}</p><p><strong>Requested change</strong>\n${e(f.requested_change)}</p></article>`).join('') : '<p class="muted">No open findings recorded. The task status indicates whether a review has finished.</p>';
  if(findings.length&&!active&&!r.demo){
    $('findings').insertAdjacentHTML('beforeend','<div class="finding-actions"><div><strong>Turn findings into a task</strong><p class="hint" id="findingSelectionCount">Choose the findings you want to address.</p></div><button type="button" class="secondary" id="selectAllFindings">Select all</button><button type="button" class="secondary" id="planFindings" disabled>Plan selected</button><button type="button" class="primary" id="buildFindings" disabled>Build & review selected</button></div>');
  }
  $('summary').hidden = true;
  $('summary').textContent = '';
}
async function poll() {
  try {
    const state = await request('/api/state');
    if(state.dev){
      if(devRevision && devRevision!==state.dev.revision && !state.dev.busy&&!imageDrafts.task.length&&!imageDrafts.followup.length&&!imageLoading){
        try{sessionStorage.setItem('relay.devDraft',JSON.stringify({task:$('task').value,mode:$('taskMode').value,rounds:$('rounds').value,minutes:$('minutes').value,selected,pendingSource}));}catch(_){}
        location.reload();return;
      }
      if(!devRevision)devRevision=state.dev.revision;
    }
    token = state.token; runs = state.runs;if(pendingSource)updateSourceBrief();
    if (selected && !runs.some(r=>r.id===selected)) selected = null;
    $('serverState').textContent = 'Local workspace';
    render();
  } catch(error) { $('serverState').textContent = 'Connection lost · retrying'; }
  finally { setTimeout(poll, 1200); }
}
async function start(demo=false) {
  if (loading||imageLoading) return;
  loading=true; updateButtons(); $('formError').textContent='';
  try {
    const result = await request('/api/run',{...(!demo&&pendingSource||{}),images:demo?[]:imagePayload('task'),task:$('task').value,project:selectedProject(),mode:$('taskMode').value,team:currentTeam,rounds:Number($('rounds').value),minutes:Number($('minutes').value),demo});
    if(!demo)clearImageDraft('task');
    clearSourceBrief();selected=result.id; rendered='';
    const state=await request('/api/state');runs=state.runs;render();$('feedTab').click();
    document.querySelector('.activity').scrollIntoView({behavior:'smooth',block:'start'});
  } catch(error) { $('formError').textContent=error.message; }
  finally {loading=false; updateButtons();}
}
$('taskMode').addEventListener('change',updateTaskMode);
$('taskForm').addEventListener('submit',event=>{event.preventDefault();start();});
$('demo').addEventListener('click',()=>start(true));
$('refreshConnections').addEventListener('click',connections);
$('history').addEventListener('click',event=>{
  const more=event.target.closest('[data-history-menu]');if(more){openHistoryMenu(more.dataset.historyMenu,more);return;}
  const button=event.target.closest('[data-run]');if(button){closeHistoryMenu(false);selected=button.dataset.run;rendered='';render();}
});
$('historySearch').addEventListener('input',renderHistory);
$('historyToggle').addEventListener('click',()=>{const open=document.querySelector('.sidebar').classList.toggle('history-visible');$('historyToggle').setAttribute('aria-expanded',String(open));});
$('historyMenuOpen').addEventListener('click',()=>{const id=historyMenuTarget;closeHistoryMenu(false);selected=id;rendered='';render();document.querySelector('.activity').scrollIntoView({behavior:'auto',block:'start'});});
$('historyMenuDelete').addEventListener('click',()=>{const id=historyMenuTarget;closeHistoryMenu(false);openDeleteDialog(id);});
$('historyMenu').addEventListener('keydown',event=>{
  const buttons=[...$('historyMenu').querySelectorAll('button:not(:disabled)')];
  if(event.key==='Escape'){event.preventDefault();closeHistoryMenu();}
  else if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
    event.preventDefault();let index=buttons.indexOf(document.activeElement);
    index=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;buttons[index].focus();
  }else if(event.key==='Tab'){
    event.preventDefault();const trigger=historyMenuTrigger;closeHistoryMenu(false);
    const targets=[...document.querySelectorAll('a[href],button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')].filter(el=>el.getClientRects().length>0);
    const next=targets[targets.indexOf(trigger)+(event.shiftKey?-1:1)];(next||trigger)?.focus();
  }
});
document.addEventListener('click',event=>{if(!$('historyMenu').hidden&&!event.target.closest('#historyMenu')&&!event.target.closest('[data-history-menu]'))closeHistoryMenu(false);});
window.addEventListener('resize',()=>closeHistoryMenu(false));
$('history').addEventListener('scroll',()=>closeHistoryMenu(false));
$('newTask').addEventListener('click',()=>{clearSourceBrief();closeHistoryMenu(false);selected=null;rendered='';render();$('composer').scrollIntoView({behavior:'smooth'});$('task').focus({preventScroll:true});});
for(const action of ['pause','stop']) $(action).addEventListener('click',async()=>{
  const r=runs.find(x=>x.id===selected);if(!r)return;
  const verb=action==='pause'&&r.paused?'resume':action;
  $(action).disabled=true;
  try{await request('/api/'+verb,{id:selected});}catch(error){$('formError').textContent=error.message;}finally{$(action).disabled=false;}
});
for(const tab of document.querySelectorAll('[data-tab]')) {
  tab.addEventListener('click',()=>{
    for(const t of document.querySelectorAll('[data-tab]')){const on=t===tab;t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1;$(t.dataset.tab).hidden=!on||(t.dataset.tab==='feed'&&runs.find(r=>r.id===selected)?.status==='awaiting_approval');}
  });
  tab.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();const tabs=[...document.querySelectorAll('[data-tab]')];let index=tabs.indexOf(tab);
    index=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
    tabs[index].click();tabs[index].focus();
  });
}
$('project').addEventListener('change', projectChanged);
$('addProject').addEventListener('click',()=>{
  $('projectForm').reset(); $('projectError').textContent=''; $('projectDialog').showModal(); $('projectName').focus();
});
$('cancelProject').addEventListener('click',()=>$('projectDialog').close());
$('projectForm').addEventListener('submit',async event=>{
  event.preventDefault(); $('projectError').textContent=''; $('saveProject').disabled=true;
  try {
    const project=await request('/api/projects/save',{name:$('projectName').value.trim(),path:$('projectFolder').value.trim()});
    await loadProjects(project.path); $('projectDialog').close(); $('projectNotice').textContent='Project saved on this computer.';
  } catch(error) { $('projectError').textContent=error.message; }
  finally { $('saveProject').disabled=false; }
});
$('removeProject').addEventListener('click',async()=>{
  const project=savedProjects.find(p=>p.path===$('project').value);if(!project)return;
  $('removeProject').disabled=true;
  try {await request('/api/projects/remove',{id:project.id});await loadProjects();$('projectNotice').textContent='Saved project removed. The folder and its files are unchanged.';}
  catch(error){$('projectNotice').textContent=error.message;projectChanged();}
});
$('browseFolder').addEventListener('click',()=>{ $('folderDialog').showModal();browseFolders($('projectFolder').value.trim()); });
$('cancelFolder').addEventListener('click',()=>$('folderDialog').close());
$('folderGo').addEventListener('click',()=>browseFolders($('folderLocation').value.trim()));
$('folderLocation').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();if(!$('folderGo').disabled)browseFolders($('folderLocation').value.trim());}});
$('folderUp').addEventListener('click',()=>browseFolders(browsingParent));
$('folderList').addEventListener('click',event=>{const button=event.target.closest('[data-folder]');if(button&&$('folderList').getAttribute('aria-busy')==='false')browseFolders(button.dataset.folder);});
$('chooseFolder').addEventListener('click',()=>{if(browsingPath){$('projectFolder').value=browsingPath;$('folderDialog').close();$('projectFolder').focus();}});
try{
  const draft=JSON.parse(sessionStorage.getItem('relay.devDraft')||'null');
  if(draft){$('taskMode').value=draft.mode||'build';$('task').value=draft.task||'';$('rounds').value=draft.rounds||'3';$('minutes').value=draft.minutes||'20';selected=draft.selected;pendingSource=draft.pendingSource||null;updateSourceBrief();sessionStorage.removeItem('relay.devDraft');}
}catch(_){}
updateTaskMode();poll();connections();loadProjects();loadTeams();

function openDeleteDialog(id){const run=runs.find(r=>r.id===id);if(!run||!terminal.has(run.status))return;deleteTarget=id;$('deleteChatName').textContent=run.task;$('deleteDialog').showModal();$('cancelDelete').focus();}
$('deleteHistory').addEventListener('click',()=>openDeleteDialog(selected));
$('cancelDelete').addEventListener('click',()=>$('deleteDialog').close());
$('confirmDelete').addEventListener('click',async()=>{
  const id=deleteTarget;if(!id)return;
  $('confirmDelete').disabled=true;
  try {
    const result=await request('/api/history/delete',{id});
    deletedChat=id; runs=runs.filter(r=>r.id!==id);if(selected===id)selected=null;rendered='';
    $('deleteDialog').close();$('historyFeedback').hidden=false;$('historyMessage').textContent=result.message;$('undoDelete').hidden=false;
    render();
  }catch(error){$('deleteDialog').close();$('historyFeedback').hidden=false;$('historyMessage').textContent=error.message;}
  finally{$('confirmDelete').disabled=false;}
});
$('undoDelete').addEventListener('click',async()=>{
  if(!deletedChat)return;$('undoDelete').disabled=true;
  try{
    const restored=await request('/api/history/restore',{id:deletedChat});
    const state=await request('/api/state');runs=state.runs;selected=restored.id;deletedChat=null;rendered='';
    $('historyMessage').textContent='Chat restored.';$('undoDelete').hidden=true;render();
  }catch(error){$('historyMessage').textContent=error.message;}
  finally{$('undoDelete').disabled=false;}
});

$('configureTeam').addEventListener('click',()=>{
  $('teamError').textContent='';$('teamNotice').textContent='';
  const matching=presets.find(p=>teamKey(p.team)===teamKey(currentTeam));
  presetOptions(matching?.id || (teamKey(currentTeam)===teamKey(defaultTeam)?'__default__':''));
  fillTeamEditor(currentTeam);$('teamDialog').showModal();$('teamPreset').focus();
});
$('cancelTeam').addEventListener('click',()=>$('teamDialog').close());
$('teamPreset').addEventListener('change',()=>{
  $('teamError').textContent='';$('teamNotice').textContent='';const id=$('teamPreset').value;
  if(id==='__default__')fillTeamEditor(defaultTeam);
  else if(id)fillTeamEditor(presets.find(p=>p.id===id).team);
  else $('teamLabel').value='My team';
  $('saveTeamPreset').textContent=id&&id!=='__default__'?'Update preset':'Save preset';
});
$('saveTeamPreset').addEventListener('click',async()=>{
  if(!$('teamForm').reportValidity())return;$('saveTeamPreset').disabled=true;$('teamError').textContent='';
  try{
    const id=$('teamPreset').value;const entry=await request('/api/teams/save',{team:readTeamEditor(),id:id&&id!=='__default__'?id:null});
    presets=(await request('/api/teams')).presets;presetOptions(entry.id);$('teamNotice').textContent='Preset saved. Click Use team to apply it to new tasks.';
  }catch(error){$('teamError').textContent=error.message;}
  finally{$('saveTeamPreset').disabled=false;}
});
$('teamForm').addEventListener('submit',event=>{
  event.preventDefault();const team=readTeamEditor();
  if(!team.name){$('teamError').textContent='Enter a team name.';return;}
  currentTeam=team;try{localStorage.setItem('relay.team',JSON.stringify(team));}catch(_){}
  updateTeamCards();$('teamDialog').close();
});

for(const role of roleNames){
  $(role+'Tool').addEventListener('change',()=>fillRoleChoices(role));
  $(role+'ModelInput').addEventListener('change',()=>fillEffortChoices(role,$(role+'Effort').value));
}

function updateSourceBrief(){
  $('sourceBrief').hidden=!pendingSource;
  $('sourceBriefText').textContent=pendingSource?`${pendingSource.finding_indexes.length} ${pendingSource.finding_indexes.length===1?'finding':'findings'} will travel with this task. ${(runs.find(r=>r.id===pendingSource.source_id)?.attachments?.length||0)} images inherited from the source report. Review the prompt, model settings, and project before starting.`:'';
}
function clearSourceBrief(){pendingSource=null;updateSourceBrief();}
$('clearSource').addEventListener('click',clearSourceBrief);
$('project').addEventListener('change',clearSourceBrief);
$('findings').addEventListener('change',()=>{
  const count=document.querySelectorAll('[name="selectedFinding"]:checked').length;
  $('findingSelectionCount').textContent=count?`${count} selected · opens a task draft for you to review.`:'Choose the findings you want to address.';
  $('planFindings').disabled=!count;$('buildFindings').disabled=!count;
});
$('findings').addEventListener('click',async event=>{
  const action=event.target.closest('button')?.id;
  if(action==='selectAllFindings'){
    const choices=[...document.querySelectorAll('[name="selectedFinding"]')],checked=choices.some(input=>!input.checked);
    choices.forEach(input=>input.checked=checked);$('findings').dispatchEvent(new Event('change'));return;
  }
  if(!['planFindings','buildFindings'].includes(action))return;
  const run=runs.find(r=>r.id===selected),indexes=[...document.querySelectorAll('[name="selectedFinding"]:checked')].map(input=>Number(input.value));
  if(!run||!indexes.length)return;
  const project=run.original_project||run.project;
  if(![...$('project').options].some(option=>option.value===project)){
    const option=new Option('Report project · '+project,project);$('project').add(option);
  }
  $('project').value=project;projectChanged();
  currentTeam=structuredClone(run.team||defaultTeam);updateTeamCards();
  pendingSource={source_id:run.id,finding_indexes:indexes};updateSourceBrief();
  $('taskMode').value=action==='planFindings'?'plan':'build';updateTaskMode();
  $('task').value=(action==='planFindings'?'Create an implementation plan for':'Verify and fix')+' the selected findings from the earlier report:\n\n'+indexes.map(i=>`${sourceFindings(run)[i].id}: ${sourceFindings(run)[i].problem}`).join('\n')+'\n\nStay within these findings. Verify each against the current code and explain any finding that is no longer valid.';
  $('composer').scrollIntoView({behavior:'smooth'});$('task').focus({preventScroll:true});
});
$('followupForm').addEventListener('submit',async event=>{
  event.preventDefault();if(loading||imageLoading||activeRun())return;
  const run=runs.find(r=>r.id===selected),question=$('followupQuestion').value.trim();if(!run||!question)return;
  loading=true;updateButtons();$('sendFollowup').disabled=true;$('followupError').textContent='';
  try{
    const result=await request('/api/followup',{source_id:run.id,task:question,images:imagePayload('followup'),minutes:Number($('minutes').value)});
    selected=result.id;rendered='';$('followupQuestion').value='';clearImageDraft('followup');
    const state=await request('/api/state');runs=state.runs;render();
  }catch(error){$('followupError').textContent=error.message;}
  finally{loading=false;rendered='';render();}
});

for(const action of ['approvePlan','rejectPlan'])$(action).addEventListener('click',async()=>{
  const run=runs.find(r=>r.id===selected);if(run?.status!=='awaiting_approval')return;
  $('approvePlan').disabled=true;$('rejectPlan').disabled=true;$('approvalError').textContent='';
  try{
    await request(action==='approvePlan'?'/api/approve-plan':'/api/stop',{id:run.id,plan_id:run.plan.id});
    const state=await request('/api/state');runs=state.runs;rendered='';render();
  }catch(error){$('approvalError').textContent=error.message;}
  finally{$('approvePlan').disabled=false;$('rejectPlan').disabled=false;}
});

$('changes').addEventListener('click',event=>{
  const button=event.target.closest('[data-review-file]');if(!button)return;
  const panel=$('changes').querySelector(`[data-review-panel="${button.dataset.reviewFile}"]`);
  if(panel){panel.open=true;panel.scrollIntoView({behavior:'auto',block:'start'});panel.querySelector('summary').focus();}
});

function imagePayload(prefix){return imageDrafts[prefix].map(({name,mime,data})=>({name,mime,data}));}
function clearImageDraft(prefix){imageDrafts[prefix]=[];$(prefix+'ImageInput').value='';renderImageDraft(prefix);}
function renderImageDraft(prefix){
  $(prefix+'ImagePreviews').innerHTML=imageDrafts[prefix].map((image,i)=>`<div class="image-preview"><img src="data:${image.mime};base64,${image.data}" alt="${e(image.name)}"><div><strong>${e(image.name)}</strong><span>${(image.size/1024/1024).toFixed(1)} MB</span></div><button type="button" data-remove-image="${i}" aria-label="Remove ${e(image.name)}">×</button></div>`).join('');
  $(prefix+'ImageNotice').textContent=imageDrafts[prefix].length?`${imageDrafts[prefix].length} selected · saved with your chat when sent. Reselect unsent images after reloading.`:'';
}
async function addImageFiles(prefix,files){
  if(imageLoading){$(prefix+'ImageNotice').textContent='Wait for the current images to finish loading.';return;}
  const inherited=prefix==='followup'?(runs.find(r=>r.id===selected)?.attachments?.length||0):(pendingSource?runs.find(r=>r.id===pendingSource.source_id)?.attachments?.length||0:0);
  if(imageDrafts[prefix].length+files.length+inherited>4){$(prefix+'ImageNotice').textContent=`Up to four images are allowed, including ${inherited} inherited from this report.`;return;}
  imageLoading++;updateButtons();$(prefix+'ImageNotice').textContent='Reading images…';
  try{
    const added=[];
    for(const file of files){
      const mime=file.type||(/\.png$/i.test(file.name)?'image/png':/\.jpe?g$/i.test(file.name)?'image/jpeg':/\.webp$/i.test(file.name)?'image/webp':'');
      if(!['image/png','image/jpeg','image/webp'].includes(mime))throw new Error('Choose PNG, JPEG, or WebP images. Convert HEIC files first.');
      if(!file.size||file.size>4*1024*1024)throw new Error('Each image must be 4 MB or smaller.');
      const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('Could not read this image.'));reader.readAsDataURL(file);});
      added.push({name:file.name||'Screenshot.png',mime,data,size:file.size});
    }
    imageDrafts[prefix].push(...added);renderImageDraft(prefix);
  }catch(error){$(prefix+'ImageNotice').textContent=error.message;}
  finally{imageLoading--;updateButtons();$(prefix+'ImageInput').value='';}
}
for(const prefix of ['task','followup']){
  const input=$(prefix+'ImageInput'),drop=$(prefix+'ImageDrop');
  $(prefix+'AttachImages').addEventListener('click',()=>input.click());
  input.addEventListener('change',()=>addImageFiles(prefix,[...input.files]));
  $(prefix+'ImagePreviews').addEventListener('click',event=>{const button=event.target.closest('[data-remove-image]');if(button){imageDrafts[prefix].splice(Number(button.dataset.removeImage),1);renderImageDraft(prefix);}});
  for(const kind of ['dragenter','dragover'])drop.addEventListener(kind,event=>{event.preventDefault();drop.classList.add('is-dragging');});
  drop.addEventListener('dragleave',event=>{if(!drop.contains(event.relatedTarget))drop.classList.remove('is-dragging');});
  drop.addEventListener('drop',event=>{event.preventDefault();drop.classList.remove('is-dragging');addImageFiles(prefix,[...event.dataTransfer.files]);});
  const textarea=$(prefix==='task'?'task':'followupQuestion');
  textarea.addEventListener('dragover',event=>{if([...event.dataTransfer.types].includes('Files'))event.preventDefault();});
  textarea.addEventListener('drop',event=>{if(event.dataTransfer.files.length){event.preventDefault();addImageFiles(prefix,[...event.dataTransfer.files]);}});
  $(prefix==='task'?'task':'followupQuestion').addEventListener('paste',event=>{
    const files=[...event.clipboardData.items].filter(item=>item.kind==='file').map(item=>item.getAsFile()).filter(Boolean);
    if(files.length){event.preventDefault();addImageFiles(prefix,files);}
  });
}
