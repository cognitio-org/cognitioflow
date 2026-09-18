import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { loadRunnerHealth, loadStatuses, parseBody } from '../github.js';

const fx = JSON.parse(readFileSync(new URL('./fixtures.json', import.meta.url)));

test('a body is JSON when it parses, text when it does not', () => {
  assert.deepEqual(parseBody('[]'), []);
  assert.deepEqual(parseBody('{"a": 1}'), { a: 1 });
  assert.equal(parseBody('diff --git a/x b/x'), 'diff --git a/x b/x');
  assert.equal(parseBody(''), null);
});

test('statuses load even when the server sends no content-type', async () => {
  const answers = {
    '/pulls?': [{ number: 22, head: { sha: fx['22'].pull.head.sha } }],
    '/pulls/22?': fx['22'].pull, '/pulls/22': fx['22'].pull,
    '/check-runs': { check_runs: fx['22'].checkRuns },
    '/issues/22/comments': fx['22'].comments,
    '/pulls/22/reviews': fx['22'].reviews,
  };
  globalThis.fetch = async (url) => {
    const key = Object.keys(answers).find((k) => url.includes(k.split('?')[0]) && (!k.endsWith('?') || url.includes('?')));
    const body = url.includes('/reviews') ? answers['/pulls/22/reviews']
      : url.includes('/comments') ? answers['/issues/22/comments']
      : url.includes('/check-runs') ? answers['/check-runs']
      : url.includes('/pulls/22') ? answers['/pulls/22']
      : answers['/pulls?'];
    return { ok: true, status: 200, headers: new Headers(), text: async () => JSON.stringify(body ?? (key && answers[key])) };
  };
  const [row] = await loadStatuses('t', 'o/r');
  assert.equal(row.number, 22);
  assert.equal(row.state, 'ready');
  assert.equal(row.botApproved, true);
});

test('a failing call carries GitHub\'s message', async () => {
  globalThis.fetch = async () => ({ ok: false, status: 401, headers: new Headers(), text: async () => JSON.stringify({ message: 'Bad credentials' }) });
  await assert.rejects(loadStatuses('bad', 'o/r'), /Bad credentials/);
});

test('runner health reads the newest run, and billing only once something is wrong', async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    const body = url.includes('/actions/runs?') ? { workflow_runs: [{ id: 77, created_at: '2026-09-18T08:34:30Z', head_branch: 'main' }] }
      : url.includes('/actions/runs/77/jobs') ? { jobs: [
          { name: 'ALLMS Python tests', status: 'completed', conclusion: 'failure', runner_id: 0, runner_name: '',
            started_at: '2026-09-18T08:34:35Z', completed_at: '2026-09-18T08:34:37Z' }] }
      : { total_minutes_used: 3000, included_minutes: 3000, total_paid_minutes_used: 0 };
    return { ok: true, status: 200, headers: new Headers(), text: async () => JSON.stringify(body) };
  };
  const health = await loadRunnerHealth('t', 'cognitio-org/ALLMS');
  assert.equal(health.state, 'starved');
  assert.equal(health.billing.exhausted, true);
  assert.equal(health.billingKind, 'org');
  assert.ok(calls.some((u) => u.includes('/orgs/cognitio-org/settings/billing/actions')));
});

test('healthy CI never spends a call on billing', async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    const body = url.includes('/actions/runs?') ? { workflow_runs: [{ id: 5, created_at: 'x', head_branch: 'main' }] }
      : { jobs: [{ name: 'test', status: 'completed', conclusion: 'success', runner_id: 9, runner_name: 'GH 1',
                   steps: [{ name: 'Set up job' }], started_at: '2026-09-18T08:00:00Z', completed_at: '2026-09-18T08:03:00Z' }] };
    return { ok: true, status: 200, headers: new Headers(), text: async () => JSON.stringify(body) };
  };
  const health = await loadRunnerHealth('t', 'o/r');
  assert.equal(health.state, 'ok');
  assert.equal(calls.filter((u) => u.includes('billing')).length, 0);
});

test('a token that cannot read billing still gets the runner answer', async () => {
  globalThis.fetch = async (url) => {
    if (url.includes('billing')) return { ok: false, status: 403, headers: new Headers(), text: async () => JSON.stringify({ message: 'Resource not accessible' }) };
    const body = url.includes('/actions/runs?') ? { workflow_runs: [{ id: 9, created_at: 'x', head_branch: 'main' }] }
      : { jobs: [{ name: 'gate', status: 'completed', conclusion: 'failure', runner_id: 0, runner_name: '',
                   started_at: '2026-09-18T08:34:35Z', completed_at: '2026-09-18T08:34:37Z' }] };
    return { ok: true, status: 200, headers: new Headers(), text: async () => JSON.stringify(body) };
  };
  const health = await loadRunnerHealth('t', 'cognitio-org/ALLMS');
  assert.equal(health.state, 'starved', 'the runner answer must survive a billing refusal');
  assert.match(health.billingError, /org admin scope/);
  assert.equal(health.billing, undefined);
});

test('a repository with no completed runs is unknown, not broken', async () => {
  globalThis.fetch = async () => ({ ok: true, status: 200, headers: new Headers(), text: async () => JSON.stringify({ workflow_runs: [] }) });
  const health = await loadRunnerHealth('t', 'o/r');
  assert.equal(health.state, 'unknown');
});
