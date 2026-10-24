/** Workflow names, provider defaults and report helpers. */
export const roleNames = ['observer', 'builder', 'reviewer'];
export const defaultTeam = {
  name: 'Claude reviews · Codex builds',
  roles: Object.fromEntries(roleNames.map(role => [role, {
    provider: role === 'builder' ? 'codex' : 'claude',
    model: '',
    effort: '',
    instructions: ''
  }]))
};
export const sourceFindings = run => [run, ...[...(run.turns || [])].reverse()].find(turn => turn.findings?.length)?.findings || [];
export const modeNames = {
  observe: 'Observe only',
  plan: 'Plan only',
  build: 'Build & review'
};
export const providerLabel = name => name === 'claude' ? 'Claude' : 'Codex';
export const terminal = new Set(['done', 'needs_attention', 'failed', 'stopped', 'interrupted']);
export const labels = {
  queued: 'Queued',
  preparing: 'Preparing',
  observing: 'Observer working',
  awaiting_clarification: 'Waiting for your answers',
  awaiting_approval: 'Awaiting your approval',
  building: 'Builder working',
  reviewing: 'Reviewer working',
  fixing: 'Builder fixing',
  done: 'Approved',
  needs_attention: 'Needs your decision',
  failed: 'Could not finish',
  stopped: 'Stopped',
  interrupted: 'Interrupted'
};
