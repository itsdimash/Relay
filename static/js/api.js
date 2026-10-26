import { state as appState } from './state.js';
export async function request(path, body) {
  // The list holds only summaries; the chat that is open is sent in full.
  if (path === '/api/state' && body === undefined && appState.selected) path += '?selected=' + encodeURIComponent(appState.selected);
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Relay-Token': appState.token
    },
    body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
