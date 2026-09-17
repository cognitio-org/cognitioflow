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
      });
    }
  }
  return out;
}

/** HTML topics hold most of Property Law's PDFs as plain links, so they have to be read too. */
export function pages(toc, org) {
  const out = [];
  for (const mod of walk(toc))
    for (const t of mod.Topics || []) {
      if (t.TypeIdentifier === "File" && isPage(t.Url))
        out.push({ topicId: t.TopicId, title: t.Title || "", week: weekOf(mod.Title), module: mod.Title || "", url: encodePath(t.Url) });
    }
  return out;
}

export const moduleIds = (toc) => walk(toc).map((m) => ({ id: m.ModuleId, title: m.Title || "", week: weekOf(m.Title) }));

/** Pull document links out of a page's HTML; relative hrefs resolve against the enforced folder. */
export function linksIn(html, folder, context = {}) {
  const out = [];
  const seen = new Set();
  const re = /<a\b[^>]*?href\s*=\s*("([^"]*)"|'([^']*)')/gi;
  let m;
  while ((m = re.exec(html || ""))) {
    const href = (m[2] ?? m[3] ?? "").trim();
    if (!href || /^(https?:|mailto:|#|javascript:)/i.test(href)) continue;
    if (href.includes("/d2l/")) continue;               // quickLinks are indirections, not files
    if (!isDocument(href)) continue;
    const path = href.startsWith("/") ? href : `/content/enforced/${folder}/${href}`;
    const url = encodePath(path);
    if (seen.has(url)) continue;
    seen.add(url);
    out.push({ key: `f:${decodeSafe(path)}`, kind: "link", title: basename(path), name: basename(path), week: context.week || "", module: context.module || "", url, path: decodeSafe(path) });
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
