/* Render saved report and diff data only; no filesystem paths are fetched by the browser. */
(function(root){
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const priority=p=>['critical','high','medium','low'].includes(p)?p:'unrated';
 function summaryCard(turn){
   if(!turn.summary||['failed','stopped','interrupted'].includes(turn.status))return '';
   const overview=turn.overview||turn.summary.split('\n').find(line=>line.trim()&&!/^\s*#/.test(line))||turn.summary;
   const actions=turn.next_actions?.length?turn.next_actions:(turn.findings||[]).slice(0,3).map(f=>f.requested_change);
   const counts={};for(const f of turn.findings||[]){const p=priority(f.priority);counts[p]=(counts[p]||0)+1;}
   return '<div class="report-brief"><div class="brief-label">'+(turn.overview?'Overview':'Report excerpt')+'</div><div class="brief-overview">'+root.renderMarkdown(overview.length>450?overview.slice(0,450)+'…':overview)+'</div>'+
     (Object.keys(counts).length?'<div class="priority-counts">'+['critical','high','medium','low','unrated'].filter(p=>counts[p]).map(p=>'<span class="priority '+p+'">'+counts[p]+' '+(p==='unrated'?'without priority':p)+'</span>').join('')+'</div>':'')+
     (actions.length?'<div class="brief-label next-label">Recommended next actions</div><ol>'+actions.map(a=>'<li>'+root.renderMarkdown(a)+'</li>').join('')+'</ol>':'')+'</div>';
 }
 function legacyFiles(run){
   const blocks=(run.diff||'').split(/(?=^diff --git )/m).filter(Boolean);
   return (run.files||[]).map(path=>({path,status:'saved',content:blocks.find(block=>block.split('\n')[0].endsWith(' b/'+path))||'',notice:'Per-file previews were not captured for this older task. Your folder contains the complete files.'}));
 }
 function diffLines(file){
   let oldLine=0,newLine=0;
   const lines=(file.content||'').split('\n');
   if(lines.at(-1)==='')lines.pop();
   return lines.map((line,i)=>{
     let kind='context',old='',fresh='';
     const hunk=line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)/);
     if(file.status==='new'){kind='added';fresh=i+1;}
     else if(hunk){kind='hunk';oldLine=Number(hunk[1]);newLine=Number(hunk[2]);}
     else if(/^(diff --git|index |--- |\+\+\+ |new file |deleted file |old mode |new mode |Binary files)/.test(line)){kind='meta';}
     else if(line.startsWith('+')){kind='added';fresh=newLine++;}
     else if(line.startsWith('-')){kind='removed';old=oldLine++;}
     else if(line.startsWith(' ')){old=oldLine++;fresh=newLine++;}
     return '<div class="diff-line '+kind+'"><span class="line-number">'+old+'</span><span class="line-number">'+fresh+'</span><code>'+esc(line)+'</code></div>';
   }).join('');
 }
 function changeReview(run){
   const files=run.file_reviews||legacyFiles(run),reports=run.builder_reports||[];
   const latest=reports.at(-1);
   const checks=(latest?.checks||[]).map(c=>({...c,round:latest.round}));
   const counts={passed:0,failed:0,not_run:0};checks.forEach(c=>counts[c.status]=(counts[c.status]||0)+1);
   let html='<div class="change-review"><div class="review-overview"><div><span class="brief-label">Changes in your folder</span><h3>'+files.length+' changed '+(files.length===1?'file':'files')+'</h3></div><p>Review the diff before keeping changes. The changes are already in your folder.</p></div>';
   if(run.export_complete&&run.id)html+='<a class="export-patch" href="/api/export?run='+encodeURIComponent(run.id)+'" download>Download complete patch</a>';
   if(run.workspace)html+='<p class="review-location">'+esc(run.workspace)+'</p>';
   html+='<section class="reported-checks"><div class="checks-heading"><h4>Builder-reported checks · latest round</h4><span>Reported by the agent · not independently rerun by Relay</span></div>';
   if(checks.length){
     html+='<div class="check-totals"><span class="check-state passed">'+counts.passed+' passed</span><span class="check-state failed">'+counts.failed+' failed</span><span class="check-state not_run">'+counts.not_run+' not run</span></div>';
     html+=checks.map(c=>'<div class="reported-check"><span class="check-state '+esc(c.status)+'">'+esc(c.status.replace('_',' '))+'</span><div><code>'+esc(c.command)+'</code><p>'+esc(c.details)+'</p></div><span class="check-round">Round '+esc(c.round)+'</span></div>').join('');
   }else html+='<p class="hint">No structured check results were reported. Review the Builder’s report below; a completed task does not establish that tests passed.</p>';
   html+=reports.map(r=>'<details class="builder-report"><summary>Builder report · round '+esc(r.round)+'</summary><div class="report-content">'+root.renderMarkdown(r.report)+'</div></details>').join('')+'</section>';
   if(files.length){
     html+='<div class="file-review-layout"><nav class="changed-file-nav" aria-label="Changed files">'+files.map((f,i)=>'<button type="button" data-review-file="'+i+'"><span class="file-state '+esc(f.status)+'">'+esc(f.status.replace('_',' '))+'</span><span class="file-nav-name" title="'+esc(f.path)+'">'+esc(f.path)+'</span></button>').join('')+'</nav><div class="file-review-panels">';
     html+=files.map((f,i)=>'<details class="file-review" data-review-panel="'+i+'" '+(i===0?'open':'')+'><summary><span class="file-state '+esc(f.status)+'">'+esc(f.status.replace('_',' '))+'</span><strong>'+esc(f.path)+'</strong><span class="diff-count"><b>+'+esc(f.additions??'—')+'</b> <em>−'+esc(f.deletions??'—')+'</em></span></summary>'+(f.notice?'<p class="preview-notice">'+esc(f.notice)+'</p>':'')+(f.content?'<div class="file-diff" tabindex="0" role="region" aria-label="Diff for '+esc(f.path)+'">'+diffLines(f)+'</div>':'<p class="hint file-empty">No text preview available.</p>')+'</details>').join('');
     html+='</div></div>';
   }else html+='<p class="hint">No file differences were captured for this task.</p>';
   return html+'</div>';
 }
 root.renderReportBrief=summaryCard;root.renderChangeReview=changeReview;root.reportPriority=priority;
 if(typeof module!=='undefined'&&module.exports)module.exports={summaryCard,changeReview,diffLines,priority};
})(typeof globalThis!=='undefined'?globalThis:this);
