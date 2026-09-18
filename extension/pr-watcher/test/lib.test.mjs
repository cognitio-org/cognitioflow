import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { badge, billingPressure, billingUrl, changes, ciNotice, parseReview, parseVerdict, prStatus, runnerHealth, runnerRejected, testsState } from '../lib.js';

const fx = JSON.parse(readFileSync(new URL('./fixtures.json', import.meta.url)));
const status = (n) => prStatus(fx[n]);

test('reads the checker comment on real PRs', () => {
  const hold = parseVerdict(fx['23'].comments.at(-1).body);
  assert.equal(hold.decision, 'hold');
  assert.equal(hold.security, 68);
  assert.match(hold.sha, /^[0-9a-f]{7}$/);
  const approve = parseVerdict(fx['22'].comments.at(-1).body);
  assert.deepEqual([approve.decision, approve.security], ['approve', 92]);
  assert.equal(parseVerdict('just a comment'), null);
});

test('real PRs map to the right states', () => {
  assert.equal(status('22').state, 'ready');
  assert.equal(status('22').botApproved, true);
  assert.equal(status('22').canMerge, true);
  assert.equal(status('23').state, 'held');
  assert.equal(status('23').canMerge, true);   // merge stays possible, behind a stronger confirm
  assert.equal(status('5').state, 'no-tests');
  assert.equal(status('5').canMerge, false);
});

test('a verdict for an older commit is not shown as current', () => {
  const moved = structuredClone(fx['22']);
  moved.pull.head.sha = 'ffffffffffffffffffffffffffffffffffffffff';
  const s = prStatus(moved);
  assert.equal(s.verdict, null);
  assert.equal(s.staleVerdict.decision, 'approve');
  assert.equal(s.botApproved, false);
  assert.equal(s.state, 'awaiting');
});

test('tests state from the test job', () => {
  assert.equal(testsState([{ name: 'test', status: 'in_progress', conclusion: null }]), 'running');
  assert.equal(testsState([{ name: 'test', status: 'completed', conclusion: 'failure' }]), 'failed');
  assert.equal(testsState([{ name: 'deploy', status: 'completed', conclusion: 'skipped' }]), 'none');
});

test('badge shows failures first, then ready count', () => {
  assert.deepEqual(badge([status('22'), status('23')]), { text: '1', color: '#2e6b4a' });
  assert.equal(badge([{ state: 'failed' }, status('22')]).text, '!');
  assert.equal(badge([{ state: 'testing' }]).text, '…');
  assert.equal(badge([]).text, '');
});

test('notifies when tests finish and when a verdict arrives', () => {
  const before = [{ ...status('22'), tests: 'running', verdict: null }];
  const out = changes(before, [status('22')]);
  assert.deepEqual(out.map((n) => n.title), ['#22 tests passed', '#22 Approve · security 92%']);
  assert.deepEqual(changes([status('22')], [status('22')]), []);
});

test('model replies are parsed and clamped', () => {
  assert.deepEqual(parseReview('Here you go: {"verdict": "APPROVE", "security": 140, "explanation": "Docs only."}'),
    { decision: 'approve', security: 100, explanation: 'Docs only.' });
  assert.throws(() => parseReview('no json'));
});

// ---------------------------------------------------------------- CI runner health
// The rejected-job fixture is the real shape returned for cognitio-org/ALLMS during
// the September outage: no runner, no steps, two seconds from start to finish.
const REJECTED = {
  name: 'ALLMS Python tests', status: 'completed', conclusion: 'failure',
  runner_id: 0, runner_name: '', runner_group_id: 0, runner_group_name: '',
  created_at: '2026-09-18T08:34:35Z', started_at: '2026-09-18T08:34:35Z', completed_at: '2026-09-18T08:34:37Z',
};
const REAL_FAILURE = {
  name: 'tests', status: 'completed', conclusion: 'failure',
  runner_id: 42, runner_name: 'GitHub Actions 7',
  steps: [{ name: 'Set up job', conclusion: 'success' }, { name: 'Run pytest', conclusion: 'failure' }],
  started_at: '2026-09-18T08:00:00Z', completed_at: '2026-09-18T08:04:11Z',
};
const PASSED = { ...REAL_FAILURE, conclusion: 'success' };

test('a job rejected before a runner was allocated is not a test failure', () => {
  assert.equal(runnerRejected(REJECTED), true);
});

test('a job that genuinely failed is never mistaken for a rejection', () => {
  assert.equal(runnerRejected(REAL_FAILURE), false);
  assert.equal(runnerRejected(PASSED), false);
});

test('a runner id, a runner name, or any recorded step rules a rejection out', () => {
  assert.equal(runnerRejected({ ...REJECTED, runner_id: 9 }), false);
  assert.equal(runnerRejected({ ...REJECTED, runner_name: 'GitHub Actions 3' }), false);
  assert.equal(runnerRejected({ ...REJECTED, steps: [{ name: 'Set up job' }] }), false);
});

test('a slow failure is not a rejection however empty it looks', () => {
  // Rejection is about never starting. A job that burned four minutes started.
  assert.equal(runnerRejected({ ...REJECTED, completed_at: '2026-09-18T08:38:35Z' }), false);
});

test('a job still running, and one with unparseable timestamps, are not rejections', () => {
  assert.equal(runnerRejected({ ...REJECTED, status: 'in_progress', conclusion: null }), false);
  assert.equal(runnerRejected({ ...REJECTED, started_at: null, completed_at: null }), false);
  assert.equal(runnerRejected(null), false);
});

test('every completed job rejected means the repository is starved of runners', () => {
  const h = runnerHealth([REJECTED, { ...REJECTED, name: 'JavaScript quality' }]);
  assert.equal(h.state, 'starved');
  assert.equal(h.rejected, 2);
  assert.equal(h.completed, 2);
  assert.equal(h.sample, 'ALLMS Python tests');
});

test('one odd job among real ones is degraded, not an outage', () => {
  assert.equal(runnerHealth([REJECTED, REAL_FAILURE, PASSED]).state, 'degraded');
});

test('jobs that all ran are ok, and no completed jobs is unknown', () => {
  assert.equal(runnerHealth([PASSED, REAL_FAILURE]).state, 'ok');
  assert.equal(runnerHealth([]).state, 'unknown');
  assert.equal(runnerHealth([{ status: 'in_progress' }]).state, 'unknown');
});

test('a queued-but-not-finished run does not report starved', () => {
  // The dangerous false positive: calling an outage while CI is merely slow.
  assert.equal(runnerHealth([{ status: 'queued' }, { status: 'in_progress' }]).state, 'unknown');
});

test('billing pressure reads the numbers a decision needs', () => {
  const b = billingPressure({ total_minutes_used: 3000, included_minutes: 3000, total_paid_minutes_used: 0 });
  assert.equal(b.remaining, 0);
  assert.equal(b.percent, 100);
  assert.equal(b.exhausted, true, 'included minutes gone with nothing billed beyond them');
});

test('paying past the included minutes is not exhaustion', () => {
  const b = billingPressure({ total_minutes_used: 4000, included_minutes: 3000, total_paid_minutes_used: 1000 });
  assert.equal(b.exhausted, false);
});

test('billing that did not come back is null rather than a guess', () => {
  assert.equal(billingPressure(null), null);
  assert.equal(billingPressure({}), null);
});

test('the billing link differs for an organisation and a personal account', () => {
  assert.equal(billingUrl('cognitio-org'), 'https://github.com/organizations/cognitio-org/settings/billing');
  assert.equal(billingUrl('matej', 'user'), 'https://github.com/settings/billing');
});

test('the notice says what broke, and says so without billing when it cannot read it', () => {
  const base = { repo: 'cognitio-org/ALLMS', state: 'starved', rejected: 8, completed: 8 };
  const withMoney = ciNotice({ ...base, billing: billingPressure({ total_minutes_used: 3000, included_minutes: 3000, total_paid_minutes_used: 0 }) });
  assert.match(withMoney, /cognitio-org\/ALLMS/);
  assert.match(withMoney, /8 of 8/);
  assert.match(withMoney, /spending limit of zero/);

  const noScope = ciNotice({ ...base, billingError: 'the token cannot read it (needs an org admin scope)' });
  assert.match(noScope, /8 of 8/, 'the runner answer survives a billing refusal');
  assert.match(noScope, /org admin scope/);
});

test('a healthy or unknown repository says nothing at all', () => {
  assert.equal(ciNotice({ state: 'ok' }), null);
  assert.equal(ciNotice({ state: 'unknown' }), null);
  assert.equal(ciNotice(null), null);
});

test('the badge puts a CI outage above everything in the list', () => {
  const ready = [{ state: 'ready' }, { state: 'ready' }];
  assert.equal(badge(ready).text, '2');
  assert.equal(badge(ready, { state: 'starved' }).text, 'CI');
  assert.equal(badge(ready, { state: 'ok' }).text, '2');
});
