/** A waiting brief always needs an explicit start; history only renders saved events. */
export function createActivity({ doc = document, post, openRun }) {
  const $ = id => doc.getElementById(id);
  let next = null, starting = false, canStart = false, historyKey = '';
  function update(queue, run) {
    if (next?.id !== queue?.items?.[0]?.id) delete $('notchQueueError').dataset.requestError;
    next = queue?.items?.[0] || null;
    canStart = !!queue?.can_start;
    $('notchQueue').hidden = !next && !queue?.error;
    $('notchQueueError').textContent = queue?.error || $('notchQueueError').dataset.requestError || '';
    if (next) {
      $('notchQueueTitle').textContent = 'Next · ' + next.task;
      $('notchQueueCount').textContent = queue.items.length;
      $('notchQueueBrief').textContent = next.task;
      const project = next.project.split('/').filter(Boolean).pop() || next.project;
      const mode = next.mode === 'build' ? 'Build & review' : next.mode === 'plan' ? 'Plan only' : 'Observe only';
      $('notchQueueMeta').textContent = `${project} · ${mode} · ${next.team?.name || 'Saved team'} · ${next.minutes ? next.minutes + ' min' : 'No time limit'}${next.mode === 'build' ? ` · ${next.rounds ? next.rounds + ' review rounds' : 'No round limit'}` : ''}${next.image_count ? ` · ${next.image_count} images` : ''}`;
      $('notchQueueNotice').textContent = canStart ? 'Starts only when you press Start task. Builds still require plan approval.' : 'Waiting for the current task to finish. Nothing starts automatically.';
    } else {
      $('notchQueueTitle').textContent = 'Task queue';
      $('notchQueueCount').textContent = '';
      $('notchQueueBrief').textContent = '';
      $('notchQueueMeta').textContent = '';
      $('notchQueueNotice').textContent = '';
    }
    $('startNextTask').disabled = !next || !canStart || starting;
    const events = run?.recent_events || [];
    const key = JSON.stringify([run?.id, events]);
    if (key === historyKey) return;
    historyKey = key;
    $('notchHistoryCount').textContent = events.length;
    $('notchHistoryEmpty').hidden = !!events.length;
    $('notchHistoryList').replaceChildren(...events.map(event => {
      const li = doc.createElement('li');
      const head = doc.createElement('div');
      const who = doc.createElement('strong');
      who.textContent = event.role ? event.role.charAt(0).toUpperCase() + event.role.slice(1) + (event.agent && event.agent.toLowerCase() !== event.role ? ` · ${event.agent}` : '') : event.agent || 'Relay';
      const time = doc.createElement('time');
      const date = new Date(event.time);
      time.textContent = Number.isFinite(date.getTime()) ? date.toLocaleTimeString(globalThis.relayI18n?.locale(), {hour:'2-digit',minute:'2-digit'}) : '';
      time.dateTime = event.time || '';
      const message = doc.createElement('p');
      message.textContent = event.message;
      li.dataset.kind = event.kind;
      head.append(who, time);
      li.append(head, message);
      return li;
    }));
  }
  $('startNextTask').addEventListener('click', async () => {
    if (!next || starting || !canStart) return;
    starting = true;
    $('startNextTask').disabled = true;
    $('notchQueueError').textContent = '';
    delete $('notchQueueError').dataset.requestError;
    try {
      const result = await post('/api/queue/start', {id: next.id});
      update(result.queue, null);
      openRun({runId:result.id,tab:'feed',step:'inspect'});
    } catch (error) {
      $('notchQueueError').dataset.requestError = error.message;
      $('notchQueueError').textContent = error.message;
    } finally {
      starting = false;
      $('startNextTask').disabled = !next || !canStart;
    }
  });
  for (const [id, flag] of [['notchQueue','data-queue-open'],['notchHistory','data-history-open']]) {
    $(id).addEventListener('toggle', () => {
      if ($(id).open) $(id === 'notchQueue' ? 'notchHistory' : 'notchQueue').open = false;
      $('panel').toggleAttribute(flag, $(id).open);
    });
  }
  return {update};
}
