/* Runs inside a CognitioFlow tab, injected on demand. Everything here is same-origin, so your signed-in
   session does the talking. Three jobs: the manual upload path for a course with no sync key, reading a
   course's file names (for the first-run baseline), and minting a course's write key (Options) — the key
   is handed straight back to the extension page that asked and is never kept here. */
if (!window.__cfGrabber) {
  window.__cfGrabber = true;
  const toBlob = (base64, type) => {
    const bin = atob(base64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return new Blob([buf], { type });
  };

  const handlers = {
    files: async ({ cid }) => {
      const r = await fetch(`/api/courses/${encodeURIComponent(cid)}/files`, { credentials: "same-origin", headers: { accept: "application/json" } });
      if (r.status === 401) throw new Error("sign in to CognitioFlow first");
      if (!r.ok) throw new Error(`${r.status} from the file list`);
      return (await r.json()).map((f) => f.name);
    },
    /** A write key bound to ONE course (POST /api/tokens, owner session only). TTL is clamped server-side to 1-90 days. */
    mintKey: async ({ cid, ttlDays }) => {
      const r = await fetch("/api/tokens", {
        method: "POST", credentials: "same-origin",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify({ scope: "write", course_id: cid, ttl_days: ttlDays || 90 }),
      });
      if (r.status === 401) throw new Error("sign in to CognitioFlow first");
      if (r.status === 403) throw new Error("only the owner's signed-in session can make keys");
      if (r.status === 404) throw new Error(`CognitioFlow has no course "${cid}"`);
      if (!r.ok) throw new Error(`${r.status} making the key`);
      const k = await r.json();
      if (!k || !String(k.token || "").startsWith("cfw_") || k.course_id !== cid) throw new Error("unexpected answer making the key");
      return { token: k.token, id: k.id, courseId: k.course_id, expires: Math.round(Number(k.expires) * 1000) };
    },
    /** Kill a key server-side (owner session). Used when Options removes or replaces a key. */
    revokeKey: async ({ id }) => {
      const r = await fetch(`/api/tokens/${encodeURIComponent(id)}`, { method: "DELETE", credentials: "same-origin" });
      if (!r.ok) throw new Error(`${r.status} revoking the old key`);
      return true;
    },
    courses: async () => {
      const r = await fetch("/api/courses", { credentials: "same-origin", headers: { accept: "application/json" } });
      if (r.status === 401) throw new Error("sign in to CognitioFlow first");
      if (!r.ok) throw new Error(`${r.status} from /api/courses`);
      return r.json();
    },
    upload: async ({ cid, name, week, base64, type }) => {
      const form = new FormData();
      form.append("file", toBlob(base64, type), name);
      form.append("week", week || "");
      const r = await fetch(`/api/courses/${encodeURIComponent(cid)}/files`, { method: "POST", credentials: "same-origin", body: form });
      if (r.status === 401) throw new Error("sign in to CognitioFlow first");
      if (!r.ok) throw new Error(`${r.status} uploading ${name}`);
      return r.json();
    },
  };

  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    const fn = handlers[msg && msg.type];
    if (!fn) return false;
    Promise.resolve(fn(msg)).then((data) => reply({ ok: true, data }), (e) => reply({ ok: false, error: String(e.message || e) }));
    return true;
  });
}
