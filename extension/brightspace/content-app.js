/* Runs inside a CognitioFlow tab. Uploads are same-origin, so your signed-in session does the talking
   and no key is stored anywhere. */
if (!window.__cfGrabber) {
  window.__cfGrabber = true;
  const toBlob = (base64, type) => {
    const bin = atob(base64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return new Blob([buf], { type });
  };

  const handlers = {
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
