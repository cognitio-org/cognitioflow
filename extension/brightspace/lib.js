/* Pure helpers for reading a Brightspace (D2L) course. No chrome APIs here, so `node --test` can run them.
   Shapes come from /d2l/api/le/1.97/{orgUnitId}/content/toc:
   { Modules: [ { ModuleId, Title, Topics: [ { TopicId, Title, TypeIdentifier: "File"|"Link", Url } ], Modules: [] } ] } */

const DOCUMENT = /\.(pdf|pptx?|docx?|odt|odp|rtf|txt|csv|xlsx?)$/i;
const PAGE = /\.html?$/i;

/** "Week 4: EU Citizenship…" -> "4". Anything else -> "". */
export function weekOf(title) {
  const m = /^\s*week\s+(\d{1,2})\b/i.exec(title || "");
  return m ? m[1] : "";
}

/** Modules are flat today, but walk nested ones anyway. */
export function walk(toc) {
  const out = [];
  const visit = (mods) => (mods || []).forEach((m) => {
    out.push(m);
    visit(m.Modules);
  });
  visit(toc && toc.Modules);
  return out;
}

/** The /content/enforced/{orgUnitId}-{courseCode}/ folder — read from a topic Url, never guessed. */
export function enforcedFolder(toc) {
  for (const mod of walk(toc))
    for (const t of mod.Topics || []) {
      const m = /^\/content\/enforced\/([^/]+)\//.exec(t.Url || "");
      if (m) return m[1];
    }
  return "";
}

export const basename = (url) => {
  const clean = String(url || "").split(/[?#]/)[0];
  const last = clean.slice(clean.lastIndexOf("/") + 1);
  try { return decodeURIComponent(last); } catch { return last; }
};

export const isDocument = (url) => DOCUMENT.test(basename(url));
export const isPage = (url) => PAGE.test(basename(url));

/** Direct bytes for a File topic — one GET, no viewer, no extra click. */
export const downloadUrl = (org, topicId) =>
  `/d2l/le/content/${org}/topics/files/download/${topicId}/DirectFileTopicDownload`;

/** Encode a raw /content/enforced/… path (the TOC stores it unencoded, spaces and all). */
export const encodePath = (path) =>
  String(path || "").split("/").map((seg) => encodeURIComponent(decodeSafe(seg))).join("/");

const decodeSafe = (s) => { try { return decodeURIComponent(s); } catch { return s; } };

/** One row per thing worth taking. `key` is what we remember, so a re-scan adds nothing twice. */
export function documents(toc, org) {
  const out = [];
  for (const mod of walk(toc)) {
    const week = weekOf(mod.Title);
    for (const t of mod.Topics || []) {
      if (t.TypeIdentifier !== "File" || !isDocument(t.Url)) continue;
      out.push({
        key: `t:${t.TopicId}`,
        kind: "topic",
        title: t.Title || basename(t.Url),
        name: basename(t.Url),
        week,
        module: mod.Title || "",
        url: downloadUrl(org, t.TopicId),
        path: decodeSafe(t.Url || ""),
        lastModified: t.LastModifiedDate || "",
      });
    }
  }
  return out;
}

/** HTML topics hold most of Property Law's PDFs as plain links, so they have to be read too.
    Only pages inside this course's own /content/enforced/{org}-…/ folder are listed (same check as a
    document link): a TOC Url that is not a plain path there ("…evil.example/x.html", another course's
    folder, "../") is never read with the session. Its title goes into `refused`, if given. */
export function pages(toc, org, refused = []) {
  const out = [];
  for (const mod of walk(toc))
    for (const t of mod.Topics || []) {
      if (t.TypeIdentifier !== "File" || !isPage(t.Url)) continue;
      const path = insideCourse(decodeSafe(String(t.Url || "")), String(org));
      if (!path) { refused.push(t.Title || String(t.Url || "")); continue; }
      out.push({ topicId: t.TopicId, title: t.Title || "", week: weekOf(mod.Title), module: mod.Title || "", url: encodePath(path),
                 dir: dirOf(path) });
    }
  return out;
}

/** Popup / Options line for pages or module descriptions the last scan could not read ("" if none). */
export function readErrorsNote(status) {
  const errs = (status && status.readErrors) || [];
  const n = errs.length;
  if (!n) return "";
  return `${n} page${n === 1 ? "" : "s"} could not be read (${errs.slice(0, 3).join(", ")}${n > 3 ? ", …" : ""}); ` +
    `${n === 1 ? "its" : "their"} files are not listed yet, and the first review finishes only after a clean re-check`;
}

export const moduleIds = (toc) => walk(toc).map((m) => ({ id: m.ModuleId, title: m.Title || "", week: weekOf(m.Title) }));

export const BRIGHTSPACE_HOST = "brightspace.rug.nl";

/** The folder a page lives in, so a relative link inside it resolves the way the browser would. */
export const dirOf = (url) => {
  const clean = String(url || "").split(/[?#]/)[0];
  return clean.slice(0, clean.lastIndexOf("/") + 1);
};

const ATTR = /\b(href|src|data|data-src|data-href|data-file|data-url|data-pdf|data-document)\s*=\s*("([^"]*)"|'([^']*)')/gi;
const TAG = /<[a-z][a-z0-9-]*\b[^>]*>/gi;   // any tag: viewers hang data-* off plain <div>s; isDocument() does the filtering
const unescapeHtml = (s) => s.replace(/&amp;/g, "&").replace(/&#x2F;|&#47;/gi, "/").replace(/&quot;/g, '"');

/** The org a /content/enforced/{org}-{code} folder belongs to ("564701-RGBIR…" -> "564701"), or "". */
export const orgOfFolder = (folder) => { const m = /^(\d+)-/.exec(String(folder || "")); return m ? m[1] : ""; };

/** `path` (already decoded) if it sits inside /content/enforced/{org}-…/ and has no tricks in it, else "".
    Segments must be plain: no "." / "..", no backslash, no control characters, and nothing that still
    decodes to something else (a double-encoded "%2F" or "%2e%2e" would be undone by the server). */
function insideCourse(path, org) {
  if (!org) return "";
  const segs = String(path).split("/");
  if (segs.length < 5 || segs[0] !== "" || segs[1] !== "content" || segs[2] !== "enforced") return "";
  if (!segs[3].startsWith(`${org}-`) || segs[3].length <= org.length + 1) return "";
  for (const seg of segs.slice(3)) {
    if (!seg || seg === "." || seg === ".." || /[\\\u0000-\u001f]/.test(seg) || decodeSafe(seg) !== seg) return "";
  }
  // what fetch() will actually ask for must be the same path, not a normalised neighbour
  const fetched = decodeSafe(new URL(`https://${BRIGHTSPACE_HOST}${encodePath(path)}`).pathname);
  return fetched === path ? path : "";
}

/** Turn one attribute value into a /content/enforced/… path, or "" if it is not a course document.
    Handles relative paths, root paths, absolute https://brightspace.rug.nl/… URLs, a viewer's ?file=…
    parameter (pdf.js style) and D2L "coursefile" quickLinks (…?type=coursefile&fileId=…).
    Only paths under /content/enforced/{org}-…/ are accepted; `org` defaults to the one in `folder`. */
export function documentPath(raw, folder, pageDir = "", org = orgOfFolder(folder)) {
  let href = unescapeHtml(String(raw || "").trim());
  if (!href || /^(mailto:|#|javascript:|data:|tel:)/i.test(href)) return "";
  if (/^https?:/i.test(href) || href.startsWith("//")) {
    let u;
    try { u = new URL(href, `https://${BRIGHTSPACE_HOST}/`); } catch { return ""; }
    if (u.hostname !== BRIGHTSPACE_HOST) return "";        // only ever the course's own host
    href = u.pathname + u.search;
  }
  const q = href.indexOf("?");
  if (q >= 0) {
    const params = new URLSearchParams(href.slice(q + 1));
    for (const name of ["file", "fileId", "url", "src", "path"]) {
      const v = params.get(name);
      if (v && (isDocument(v) || v.startsWith("/content/enforced/"))) {
        const inner = documentPath(v, folder, name === "fileId" ? "" : pageDir, org);   // coursefile ids are folder-relative
        if (inner) return inner;
      }
    }
  }
  if (href.includes("/d2l/")) return "";                   // any other quickLink is an indirection, not a file
  if (!isDocument(href)) return "";                        // documents only: never the .html wrapper itself
  let path;
  if (href.startsWith("/")) path = href.split(/[?#]/)[0];
  else if (pageDir) path = new URL(href.split(/[?#]/)[0], `https://${BRIGHTSPACE_HOST}${encodePath(pageDir)}`).pathname;
  else if (folder) path = `/content/enforced/${folder}/${href.split(/[?#]/)[0]}`;
  else return "";
  return insideCourse(decodeSafe(path), org);              // never leave this course's content tree
}

/** The CognitioFlow origin a key may be sent to: https anywhere, plain http only on this computer. "" otherwise. */
export function appOrigin(appUrl) {
  let u;
  try { u = new URL(String(appUrl || "")); } catch { return ""; }
  if (u.protocol === "https:") return u.origin;
  if (u.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(u.hostname)) return u.origin;
  return "";
}

/** Pull document links out of a page's HTML. Reads href / src / data and the data-* attributes viewers
    use, on any tag (<a>, <iframe>, <embed>, <object>, a viewer <div>), absolute same-host URLs and ?file= viewers. */
export function linksIn(html, folder, context = {}) {
  const out = [];
  const seen = new Set();
  let t;
  TAG.lastIndex = 0;
  while ((t = TAG.exec(html || ""))) {
    let a;
    ATTR.lastIndex = 0;
    while ((a = ATTR.exec(t[0]))) {
      const path = documentPath(a[3] ?? a[4] ?? "", folder, context.dir || "", context.org ? String(context.org) : orgOfFolder(folder));
      if (!path) continue;
      const url = encodePath(path);
      if (seen.has(url)) continue;
      seen.add(url);
      out.push({ key: `f:${path}`, kind: "link", title: basename(path), name: basename(path), week: context.week || "",
                 module: context.module || "", url, path, lastModified: "" });
    }
  }
  return out;
}

/** A File topic and a link inside a page or module description can point at the same file (same
    /content/enforced/… path) with different keys ("t:" vs "f:"), so `unseen`'s key-based dedup never
    catches them and both would be uploaded. Collapse those to one entry, preferring the topic (a
    stable TopicId beats a path that can be re-pointed by editing the page). Order is stable. */
export function dedupe(items) {
  const winner = new Map();  // path -> the item that should represent it
  for (const it of items) {
    if (!it.path) continue;
    const cur = winner.get(it.path);
    if (!cur || (cur.kind !== "topic" && it.kind === "topic")) winner.set(it.path, it);
  }
  const out = [];
  const used = new Set();
  for (const it of items) {
    if (!it.path) { out.push(it); continue; }
    if (winner.get(it.path) !== it) continue;   // a duplicate that lost to the winner
    if (used.has(it.path)) continue;             // the winner itself, but seen twice (e.g. same topic twice)
    used.add(it.path);
    out.push(it);
  }
  return out;
}

/** Everything not taken before. Order is stable so the list reads like the course. */
export function unseen(items, seen) {
  const have = new Set(seen || []);
  const out = [];
  const dup = new Set();
  for (const it of items) {
    if (have.has(it.key) || dup.has(it.key)) continue;
    dup.add(it.key);
    out.push(it);
  }
  return out;
}

/** The change signal we can get without downloading: the TOC date for a topic, ETag/Last-Modified/size
    from a HEAD for a linked file. "" when there is none. */
export const signalOf = (item) => String((item && (item.lastModified || item.etag || item.size)) || "");

/** What to do with one item.
    - "upload": never handled before.
    - "adopt": handled before (manual Add/Remember, or a ledger entry with no signal yet) — record the
      signal we see now, upload nothing. This is what keeps hand-added material (PIL Lecture 1) single.
    - "skip": handled and the signal is unchanged (or there is no signal to compare).
    - "check": handled, but the signal changed — download, hash, and compare. */
export function decide(item, { seen = [], entry = null } = {}) {
  const handled = seen.includes(item.key) || !!entry;
  if (!handled) return "upload";
  const now = signalOf(item);
  if (!entry || !entry.signal) return now ? "adopt" : "skip";
  if (!now || now === entry.signal) return "skip";
  return "check";
}

/** Bytes that are really the document, not a login page that came back with 200. */
export function looksLikeDocument(name, contentType, bytes) {
  const ct = String(contentType || "").toLowerCase();
  if (ct.includes("text/html") && !isPage(name)) return false;
  const head = bytes && bytes.length >= 4 ? String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]) : "";
  if (/\.pdf$/i.test(name)) return head === "%PDF";
  if (/\.(docx|pptx|xlsx|odt|odp)$/i.test(name)) return head.startsWith("PK");
  const sniff = bytes ? String.fromCharCode(...bytes.slice(0, 64)).toLowerCase() : "";
  return !/<!doctype html|<html/.test(sniff);
}

/** A redirect / status / host that means "the Brightspace session is gone", not "the file is missing". */
export function isLoginResponse(res, expectHost = BRIGHTSPACE_HOST) {
  if (!res) return true;
  if (res.type === "opaqueredirect" || res.status === 0) return true;
  if (res.status === 401 || res.status === 403) return true;
  if (res.status >= 300 && res.status < 400) return true;
  let host = expectHost;
  let path = "";
  try { const u = new URL(res.url); host = u.hostname; path = u.pathname; } catch {}
  if (host !== expectHost) return true;                       // bounced to the SSO / IdP host
  return /^\/d2l\/(login|lp\/auth)/i.test(path);
}

/** sha256 of the bytes, hex. crypto.subtle exists in the worker and in node. */
export async function sha256(bytes) {
  const d = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Name normalised for "is this already in CognitioFlow" matching during a baseline. */
export const sameName = (a, b) => {
  const n = (s) => basename(s).toLowerCase().replace(/\s+/g, " ").trim();
  return n(a) === n(b);
};
