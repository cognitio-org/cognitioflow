import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { badge, changes, parseReview, parseVerdict, prStatus, testsState } from '../lib.js';

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
