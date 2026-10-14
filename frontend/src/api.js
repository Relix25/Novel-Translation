/**
 * Same-origin JSON transport for the local server. Never retry a mutation:
 * a timeout can arrive after the server has committed it. Refresh and inspect
 * the current fingerprint before the user attempts it again.
 */
async function request(path, options, timeout) {
  if (!path.startsWith('/api/')) throw new Error('Expected a local API path.');
  const response = await fetch(path, {
    ...options,
    signal: AbortSignal.timeout(timeout),
    credentials: 'same-origin',
    redirect: 'error',
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(`Local server returned invalid JSON (HTTP ${response.status}).`);
  }
  if (!response.ok)
    throw new Error(data?.error || `Local request failed (HTTP ${response.status}).`);
  return data;
}

export function get(path) {
  return request(path, {}, 15000);
}

export function postAction(value, csrf) {
  if (!csrf) return Promise.reject(new Error('Refresh Novel before submitting an action.'));
  return request(
    '/api/action',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Novel-CSRF': csrf },
      body: JSON.stringify(value),
    },
    30000,
  );
}
