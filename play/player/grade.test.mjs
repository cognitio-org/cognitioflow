// Unit tests for the produce-type grading math. Run: `node --test play/player/grade.test.mjs`.
// grade.js is the exact code that grades in the browser; it has no DOM/network imports, so this
// proves the real play-time grading, not a re-implementation.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { gradeSpot, gradeOrder, gradeSlot, gradeProduce, spanJaccard, normTag } from './grade.js';

// ---- helpers ----
const spotKey = {
  issues: [
    { id: 'state-liability', spans: [[10, 40]] },
    { id: 'direct-effect', spans: [[60, 95]] },
  ],
  decoys: [[120, 140]],
  taxonomy: [{ id: 'state-liability' }, { id: 'direct-effect' }, { id: 'proportionality' }],
  threshold: 0.7,
};

test('spanJaccard: identical, disjoint, partial', () => {
  assert.equal(spanJaccard([0, 10], [0, 10]), 1);
  assert.equal(spanJaccard([0, 10], [20, 30]), 0);
  assert.equal(spanJaccard([0, 10], [5, 15]), 5 / 15); // inter 5, union 15
});

test('normTag normalises case/whitespace', () => {
  assert.equal(normTag('  State Liability '), 'state liability');
});

test('spot: exact spans + correct tags scores 1 and is correct', () => {
  const r = gradeSpot({ selections: [
    { span: [10, 40], tag: 'state-liability' },
    { span: [60, 95], tag: 'direct-effect' },
  ] }, spotKey);
  assert.equal(r.score, 1);
  assert.equal(r.correct, true);
  assert.equal(r.detail.recalled, 2);
  assert.equal(r.detail.falsePositives, 0);
});

test('spot: right span but wrong tag does not recall the issue', () => {
  const r = gradeSpot({ selections: [{ span: [10, 40], tag: 'proportionality' }] }, spotKey);
  assert.equal(r.detail.recalled, 0);
  assert.equal(r.detail.falsePositives, 1); // tag matches no issue -> FP
  assert.equal(r.score, 0);
});

test('spot ADVERSARIAL: selecting the whole passage with every tag does not win', () => {
  // Attack: one giant span tagged with each taxonomy id, hoping overlap carries it.
  const whole = [0, 200];
  const r = gradeSpot({ selections: [
    { span: whole, tag: 'state-liability' },
    { span: whole, tag: 'direct-effect' },
    { span: whole, tag: 'proportionality' },
  ] }, spotKey);
  // Giant span vs a 30-char issue span: Jaccard ~0.15 << 0.7, so nothing is recalled; 3 FPs.
  assert.equal(r.detail.recalled, 0);
  assert.equal(r.score, 0);
  assert.equal(r.correct, false);
});

test('spot ADVERSARIAL: real issues found but also tagging a decoy costs a false positive', () => {
  const r = gradeSpot({ selections: [
    { span: [10, 40], tag: 'state-liability' },
    { span: [60, 95], tag: 'direct-effect' },
    { span: [120, 140], tag: 'proportionality' }, // decoy range + spurious tag
  ] }, spotKey);
  // recalled 2, FP 1, total 2 -> (2-1)/2 = 0.5
  assert.equal(r.detail.recalled, 2);
  assert.equal(r.detail.falsePositives, 1);
  assert.equal(r.score, 0.5);
});

test('order: exact sequence scores 1', () => {
  const key = { sequence: ['e1', 'e2', 'e3'], bank: [{ id: 'e1' }, { id: 'e2' }, { id: 'e3' }] };
  const r = gradeOrder({ order: ['e1', 'e2', 'e3'] }, key);
  assert.equal(r.score, 1);
  assert.equal(r.correct, true);
});

test('order ADVERSARIAL: a single swap earns only the positions it keeps, never the whole mark', () => {
  const key = { sequence: ['e1', 'e2', 'e3'] };
  const r = gradeOrder({ order: ['e2', 'e1', 'e3'] }, key); // only e3 in place
  assert.equal(r.score, 1 / 3);
  assert.equal(r.correct, false);
});

test('order: unordered (bag) key credits set membership regardless of order', () => {
  const key = { sequence: ['a', 'b', 'c'], unordered: true };
  assert.equal(gradeOrder({ order: ['c', 'a', 'b'] }, key).score, 1);
  assert.equal(gradeOrder({ order: ['c', 'a'] }, key).score, 2 / 3); // missing one
});

test('slot: all facts mapped correctly scores 1', () => {
  const key = { key: { f1: 'e1', f2: 'e2', f3: 'e3' } };
  const r = gradeSlot({ assignments: { f1: 'e1', f2: 'e2', f3: 'e3' } }, key);
  assert.equal(r.score, 1);
  assert.equal(r.correct, true);
});

test('slot ADVERSARIAL: shotgunning every fact to one element is punished by FPs', () => {
  const key = { key: { f1: 'e1', f2: 'e2', f3: 'e3' } };
  const r = gradeSlot({ assignments: { f1: 'e1', f2: 'e1', f3: 'e1' } }, key);
  // TP 1 (f1), FP 2 (f2,f3) -> (1-2)/3 clamped to 0
  assert.equal(r.detail.tp, 1);
  assert.equal(r.detail.fp, 2);
  assert.equal(r.score, 0);
});

test('slot: unassigned facts are missed, not penalised as wrong', () => {
  const key = { key: { f1: 'e1', f2: 'e2', f3: 'e3' } };
  const r = gradeSlot({ assignments: { f1: 'e1' } }, key); // only one answered, correctly
  // TP 1, FP 0 -> 1/3
  assert.equal(r.score, 1 / 3);
});

test('gradeProduce dispatches by kind', () => {
  assert.equal(gradeProduce('order', { order: ['a'] }, { sequence: ['a'] }).score, 1);
  assert.equal(gradeProduce('nope', {}, {}).score, 0);
});
