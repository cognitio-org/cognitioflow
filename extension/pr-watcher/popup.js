import { PROVIDERS, billingUrl, ciNotice, timeAgo } from './lib.js';

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ask = (message) => new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));

const TESTS = { passed: ['Tests passed', 'good'], failed: ['Tests failed', 'bad'], running: ['Tests running', 'busy'], none: ['No tests yet', ''], skipped: ['Tests skipped', ''], cancelled: ['Tests cancelled', 'bad'] };

function row(s, review, provider) {
  const [testLabel, testTone] = TESTS[s.tests] || [s.tests, ''];
  const chips = [`<span class="chip ${testTone}">${testLabel}</span>`];
  if (s.verdict) chips.push(`<span class="chip ${s.verdict.decision === 'approve' ? 'good' : 'bad'}">${s.verdict.decision === 'approve' ? 'Approve' : 'Hold'} · ${s.verdict.security}%</span>`);
  else if (s.tests === 'passed') chips.push('<span class="chip">Waiting for the checker</span>');
  if (s.botApproved) chips.push('<span class="chip good">Bot approved</span>');
  if (!s.mergeable && s.tests === 'passed') chips.push(`<span class="chip bad">Can't merge (${esc(s.mergeableState)})</span>`);
  const current = review && review.sha === s.sha;
  const reviewHtml = current ? `<p class="review"><span><b>${review.decision === 'approve' ? 'Approve' : 'Hold'} · ${review.security}%</b> — ${esc(review.explanation)}</span>
      <span class="src">Re-reviewed by ${esc(review.model)}${review.cost != null ? ` · $${review.cost.toFixed(4)}` : ''} · ${timeAgo(review.at)}</span></p>` : '';
  const mergeLabel = s.verdict?.decision === 'approve' ? 'Merge' : 'Merge anyway';
  return `<li class="pr" data-number="${s.number}">
    <div class="top"><a class="num" href="${esc(s.url)}" target="_blank">#${s.number}</a><span class="title">${esc(s.title)}</span></div>
    <div class="chips">${chips.join('')}</div>
    ${s.verdict?.explanation ? `<p class="why">${esc(s.verdict.explanation)}</p>` : ''}
    ${reviewHtml}
    <div class="actions">
      <button class="btn ghost" type="button" data-act="review" title="Ask ${esc(PROVIDERS[provider]?.label || provider)} for a second opinion">Re-review</button>
      <button class="btn ${s.verdict?.decision === 'approve' ? 'primary' : ''}" type="button" data-act="merge" ${s.canMerge ? '' : 'disabled'}>${mergeLabel}</button>
    </div>
  </li>`;
}

async function render() {
  const { statuses = [], reviews = {}, error = '', checkedAt = 0, provider = 'openrouter', ci = null } =
    await chrome.storage.local.get(['statuses', 'reviews', 'error', 'checkedAt', 'provider', 'ci']);
  $('#meta').textContent = checkedAt ? `Checked ${timeAgo(checkedAt)} · refreshes every minute` : 'Not checked yet';
  $('#notice').hidden = !error;
  $('#notice').textContent = error;

  // The CI banner sits above the list because it changes what the list means: while
  // runners are being refused, every red row is red for a reason that is not the code.
  const notice = ciNotice(ci);
  $('#ci').hidden = !notice;
  if (notice) {
    const owner = (ci.repo || '').split('/')[0];
    $('#ci').innerHTML = `${esc(notice)} <a href="${esc(billingUrl(owner, ci.billingKind === 'user' ? 'user' : 'org'))}" target="_blank">Open billing settings</a>`;
  }
  $('#list').innerHTML = statuses.length
    ? statuses.map((s) => row(s, reviews[s.number], provider)).join('')
    : (error ? '' : '<li class="empty"><b>No open pull requests</b>New ones appear here within a minute.</li>');
}

$('#refresh').addEventListener('click', async () => {
  $('#refresh').disabled = true; $('#refresh').textContent = 'Checking…';
  await ask({ type: 'refresh' });
  $('#refresh').disabled = false; $('#refresh').textContent = 'Refresh';
});

$('#list').addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-act]');
  if (!button) return;
  const number = Number(button.closest('.pr').dataset.number);
  const { statuses = [] } = await chrome.storage.local.get('statuses');
  const s = statuses.find((x) => x.number === number);
  if (!s) return;
  if (button.dataset.act === 'merge') {
    const held = s.verdict?.decision !== 'approve'
      ? `\n\nThe checker ${s.verdict ? `says Hold (${s.verdict.security}%): ${s.verdict.explanation}` : 'has not given a verdict for this commit.'}` : '';
    if (!confirm(`Merge #${s.number} "${s.title}" into main?\n\nThis deploys to the live app.${held}`)) return;
    button.disabled = true; button.textContent = 'Merging…';
    const out = await ask({ type: 'merge', number: s.number, sha: s.sha, branch: s.branch });
    if (!out?.ok) { alert(`Merge failed: ${out?.error || 'no answer'}`); button.disabled = false; button.textContent = 'Merge'; }
  } else {
    button.disabled = true; button.textContent = 'Reviewing…';
    const out = await ask({ type: 'review', number: s.number, sha: s.sha, title: s.title });
    if (!out?.ok) alert(out?.error || 'Re-review failed.');
    button.disabled = false; button.textContent = 'Re-review';
  }
});

chrome.storage.onChanged.addListener(render);
render();
ask({ type: 'refresh' });
