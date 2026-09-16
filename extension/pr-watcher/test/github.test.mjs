import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { loadStatuses, parseBody } from '../github.js';

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
