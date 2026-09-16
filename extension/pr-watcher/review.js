import { PROVIDERS, REVIEW_SYSTEM, parseReview, reviewPrompt } from './lib.js';

const HAIKU_USD_PER_TOKEN = { in: 1 / 1e6, out: 5 / 1e6 };  // list price, only used when the model is Haiku 4.5

export async function reviewDiff({ provider, model, key }, title, diff) {
  const prompt = reviewPrompt(title, diff);
  if (provider === 'anthropic') {
    const chosen = model || PROVIDERS.anthropic.model;
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json', 'anthropic-dangerous-direct-browser-access': 'true' },
      body: JSON.stringify({ model: chosen, max_tokens: 400, system: REVIEW_SYSTEM, messages: [{ role: 'user', content: prompt }] }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || `Claude answered ${res.status}`);
    const usage = data.usage || {};
    const cost = chosen.startsWith('claude-haiku-4-5') ? (usage.input_tokens || 0) * HAIKU_USD_PER_TOKEN.in + (usage.output_tokens || 0) * HAIKU_USD_PER_TOKEN.out : null;
    return { ...parseReview((data.content || []).map((b) => b.text || '').join('')), model: data.model || chosen, cost };
  }
  const chosen = model || PROVIDERS.openrouter.model;
  const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'content-type': 'application/json', 'HTTP-Referer': 'https://github.com/cognitio-org/cognitioflow', 'X-Title': 'CognitioFlow PR watcher' },
    body: JSON.stringify({
      model: chosen, max_tokens: 800, reasoning: { effort: 'low', exclude: true }, usage: { include: true },
      messages: [{ role: 'system', content: REVIEW_SYSTEM }, { role: 'user', content: prompt }],
    }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error?.message || `OpenRouter answered ${res.status}`);
  return { ...parseReview(data.choices?.[0]?.message?.content || ''), model: data.model || chosen, cost: data.usage?.cost ?? null };
}
