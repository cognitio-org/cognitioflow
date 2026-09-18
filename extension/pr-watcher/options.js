const FIELDS = ['repo', 'ciRepos', 'token', 'provider', 'openrouterKey', 'anthropicKey', 'model'];
const DEFAULTS = { repo: 'cognitio-org/cognitioflow', provider: 'openrouter' };
const $ = (id) => document.getElementById(id);

chrome.storage.local.get(FIELDS).then((saved) => {
  for (const f of FIELDS) $(f).value = saved[f] ?? DEFAULTS[f] ?? '';
});

$('save').addEventListener('click', async () => {
  const values = Object.fromEntries(FIELDS.map((f) => [f, $(f).value.trim()]));
  if (!/^[\w.-]+\/[\w.-]+$/.test(values.repo)) { $('status').textContent = 'Repository must look like owner/name.'; return; }
  const ciRepos = values.ciRepos.split(',').map((r) => r.trim()).filter(Boolean);
  if (ciRepos.some((r) => !/^[\w.-]+\/[\w.-]+$/.test(r))) { $('status').textContent = 'Each CI repository must look like owner/name.'; return; }
  await chrome.storage.local.set(values);
  $('status').textContent = 'Saved. Checking GitHub…';
  const out = await new Promise((resolve) => chrome.runtime.sendMessage({ type: 'refresh' }, resolve));
  const { error = '', statuses = [] } = await chrome.storage.local.get(['error', 'statuses']);
  $('status').textContent = !out?.ok || error ? (error || out?.error || 'Check failed.') : `Connected: ${statuses.length} open pull request${statuses.length === 1 ? '' : 's'}.`;
});
