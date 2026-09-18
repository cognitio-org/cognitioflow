import { billingPressure, prStatus, runnerHealth } from './lib.js';

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

/**
 * Is this repository getting runners, and what do the Actions billing numbers say?
 *
 * Two cheap calls for the runner answer (newest workflow run, then its jobs), which
 * needs no scope beyond reading the repo. Billing is a third call that often 403s —
 * it needs an org-admin scope the PR-watching token does not have to have — so a
 * refusal there is reported, never allowed to hide the runner answer.
 */
export async function loadRunnerHealth(token, repo) {
  const owner = repo.split('/')[0];
  const runs = await gh(token, `/repos/${repo}/actions/runs?per_page=1&status=completed`);
  const run = (runs && runs.workflow_runs && runs.workflow_runs[0]) || null;
  if (!run) return { repo, state: 'unknown', rejected: 0, completed: 0, checkedRun: null };

  const jobs = await gh(token, `/repos/${repo}/actions/runs/${run.id}/jobs?per_page=30`);
  const health = runnerHealth(jobs && jobs.jobs);
  const out = { repo, ...health, checkedRun: run.id, checkedAt: run.created_at, branch: run.head_branch };
  if (health.state === 'ok' || health.state === 'unknown') return out;

  // Only ask about money once something is actually wrong.
  try {
    const billing = await gh(token, `/orgs/${owner}/settings/billing/actions`);
    return { ...out, billing: billingPressure(billing), billingKind: 'org' };
  } catch (orgError) {
    try {
      const billing = await gh(token, `/users/${owner}/settings/billing/actions`);
      return { ...out, billing: billingPressure(billing), billingKind: 'user' };
    } catch (userError) {
      const status = orgError.status || userError.status;
      const reason = status === 403 || status === 404
        ? 'the token cannot read it (needs an org admin scope)'
        : userError.message;
      return { ...out, billingError: reason };
    }
  }
}
