import { loadRunnerHealth, loadStatuses, mergePull, pullDiff } from './github.js';
import { badge, billingUrl, changes, ciNotice } from './lib.js';
import { reviewDiff } from './review.js';

// ciRepos is separate from `repo` on purpose: the repository whose CI is broken is
// often not the one whose pull requests you are reading.
const DEFAULTS = { repo: 'cognitio-org/cognitioflow', ciRepos: '', token: '', provider: 'openrouter', openrouterKey: '', anthropicKey: '', model: '' };
const settings = async () => ({ ...DEFAULTS, ...(await chrome.storage.local.get(Object.keys(DEFAULTS))) });

async function setBadge({ text, color }) {
  await chrome.action.setBadgeText({ text });
  await chrome.action.setBadgeBackgroundColor({ color });
}

async function refresh() {
  const s = await settings();
  if (!s.token) {
    await setBadge({ text: '?', color: '#5c5b55' });
    await chrome.storage.local.set({ statuses: [], error: 'Add a GitHub token in Options to start watching.', checkedAt: Date.now() });
    return;
  }
  try {
    const statuses = await loadStatuses(s.token, s.repo);
    const { statuses: previous = [], ci: previousCi = null } = await chrome.storage.local.get(['statuses', 'ci']);
    for (const n of changes(previous, statuses)) {
      chrome.notifications.create(`pr-${n.number}-${Date.now()}`, { type: 'basic', iconUrl: 'icons/128.png', title: n.title, message: n.message, priority: 1 });
    }

    // A CI outage never fails the refresh: a broken runner pool must not also cost
    // you the pull request list.
    const ci = await checkCi(s);
    if (ci && ci.state !== previousCi?.state && (ci.state === 'starved' || ci.state === 'degraded')) {
      chrome.notifications.create(`ci-${ci.repo}-${Date.now()}`, {
        type: 'basic', iconUrl: 'icons/128.png', priority: 2,
        title: `${ci.repo}: CI is not getting runners`,
        message: ciNotice(ci) || 'Jobs are being rejected before a runner is allocated.',
      });
    }

    await setBadge(badge(statuses, ci));
    await chrome.storage.local.set({ statuses, ci, error: '', checkedAt: Date.now() });
  } catch (e) {
    await setBadge({ text: '×', color: '#a4541f' });
    const error = e.status === 401 ? 'GitHub rejected the token. Check it in Options.' : `Couldn't reach GitHub: ${e.message}`;
    await chrome.storage.local.set({ error, checkedAt: Date.now() });
  }
}

/** Runner health for the configured CI repositories; the worst answer wins. */
async function checkCi(s) {
  const repos = (s.ciRepos || s.repo || '').split(',').map((r) => r.trim()).filter(Boolean);
  const rank = { starved: 3, degraded: 2, unknown: 1, ok: 0 };
  let worst = null;
  for (const repo of repos) {
    try {
      const health = await loadRunnerHealth(s.token, repo);
      if (!worst || rank[health.state] > rank[worst.state]) worst = health;
    } catch (e) {
      if (!worst) worst = { repo, state: 'unknown', rejected: 0, completed: 0, billingError: e.message };
    }
  }
  return worst;
}

function schedule() {
  chrome.alarms.create('refresh', { periodInMinutes: 1 });
  refresh();
}
chrome.runtime.onInstalled.addListener(schedule);
chrome.runtime.onStartup.addListener(schedule);
chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === 'refresh') refresh(); });
chrome.notifications.onClicked.addListener(async (id) => {
  if (id.startsWith('ci-')) {
    const { ci } = await chrome.storage.local.get('ci');
    const owner = (ci?.repo || '').split('/')[0];
    chrome.tabs.create({ url: billingUrl(owner, ci?.billingKind === 'user' ? 'user' : 'org') });
    return;
  }
  const { repo } = await settings();
  chrome.tabs.create({ url: `https://github.com/${repo}/pull/${id.split('-')[1]}` });
});

async function handle(message) {
  const s = await settings();
  if (message.type === 'refresh') { await refresh(); return {}; }
  if (message.type === 'merge') {
    await mergePull(s.token, s.repo, message.number, message.sha, message.branch);
    await refresh();
    return {};
  }
  if (message.type === 'review') {
    const key = s.provider === 'anthropic' ? s.anthropicKey : s.openrouterKey;
    if (!key) throw new Error(`Add a ${s.provider === 'anthropic' ? 'Claude' : 'OpenRouter'} key in Options to re-review.`);
    const diff = await pullDiff(s.token, s.repo, message.number);
    const result = await reviewDiff({ provider: s.provider, model: s.model, key }, message.title, diff);
    const { reviews = {} } = await chrome.storage.local.get('reviews');
    reviews[message.number] = { ...result, sha: message.sha, at: Date.now() };
    await chrome.storage.local.set({ reviews });
    return { result };
  }
  throw new Error(`Unknown request: ${message.type}`);
}

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  handle(message).then((out) => reply({ ok: true, ...out }), (e) => reply({ ok: false, error: e.message }));
  return true;
});
