import { prStatus } from './lib.js';

const API = 'https://api.github.com';

/** JSON when it parses, plain text otherwise (the diff endpoint). Content-type headers are not always set. */
export function parseBody(text) {
  if (!text) return null;
  try { return JSON.parse(text); } catch { return text; }
}

async function gh(token, path, options = {}) {
  const res = await fetch(API + path, {
    ...options,
    headers: { Accept: 'application/vnd.github+json', Authorization: `Bearer ${token}`, 'X-GitHub-Api-Version': '2022-11-28', ...(options.headers || {}) },
  });
  if (res.status === 204) return null;
  const body = parseBody(await res.text());
  if (!res.ok) {
    const error = new Error((body && body.message) || `GitHub answered ${res.status}`);
    error.status = res.status;
    throw error;
  }
  return body;
}

export async function loadStatuses(token, repo) {
  const pulls = await gh(token, `/repos/${repo}/pulls?state=open&per_page=30`);
  const rows = await Promise.all(pulls.map(async (p) => {
    const [pull, checks, comments, reviews] = await Promise.all([
      gh(token, `/repos/${repo}/pulls/${p.number}`),
      gh(token, `/repos/${repo}/commits/${p.head.sha}/check-runs?per_page=50`),
      gh(token, `/repos/${repo}/issues/${p.number}/comments?per_page=100`),
      gh(token, `/repos/${repo}/pulls/${p.number}/reviews?per_page=100`),
    ]);
    return prStatus({ pull, checkRuns: checks.check_runs, comments, reviews });
  }));
  return rows.sort((a, b) => b.number - a.number);
}

/** Merge exactly the commit that was shown (GitHub refuses if the branch moved), then delete the branch. */
export async function mergePull(token, repo, number, sha, branch) {
  await gh(token, `/repos/${repo}/pulls/${number}/merge`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ merge_method: 'merge', sha }),
  });
  if (branch) {
    const ref = branch.split('/').map(encodeURIComponent).join('/');
    try { await gh(token, `/repos/${repo}/git/refs/heads/${ref}`, { method: 'DELETE' }); } catch { /* already gone or protected */ }
  }
}

export function pullDiff(token, repo, number) {
  return gh(token, `/repos/${repo}/pulls/${number}`, { headers: { Accept: 'application/vnd.github.diff' } });
}
