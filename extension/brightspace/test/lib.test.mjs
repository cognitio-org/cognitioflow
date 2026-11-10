import { test } from "node:test";
import assert from "node:assert/strict";
import { weekOf, enforcedFolder, basename, isDocument, isPage, downloadUrl, encodePath, documents, pages, moduleIds, linksIn, unseen, dedupe } from "../lib.js";

const TOC = {
  Modules: [
    { ModuleId: 1, Title: "Course information", Topics: [
      { TopicId: 5918043, Title: "Syllabus 2026_2027", TypeIdentifier: "File", Url: "/content/enforced/564706-RGBPR50305.2026-2027.1/Syllabus 2026_2027__001.pdf" },
      { TopicId: 5918044, Title: "Go to Ocasys", TypeIdentifier: "Link", Url: "https://ocasys.rug.nl/" },
      { TopicId: 5918045, Title: "I-R-A-C Method", TypeIdentifier: "File", Url: "/content/enforced/564706-RGBPR50305.2026-2027.1/IRAC.html" },
    ], Modules: [] },
    { ModuleId: 2, Title: "Week 4: EU Citizenship, Fundamental Rights and Non-discrimination", Topics: [
      { TopicId: 61, Title: "Slides Lecture 7 EU Citizenship", TypeIdentifier: "File", Url: "/content/enforced/564706-RGBPR50305.2026-2027.1/Slides 7.pptx" },
    ], Modules: [] },
  ],
};

test("week comes from the module title, full word only", () => {
  assert.equal(weekOf("Week 4: EU Citizenship"), "4");
  assert.equal(weekOf("Week 10"), "10");
  assert.equal(weekOf("Weekly reading"), "");
  assert.equal(weekOf("Practice exam"), "");
});

test("the enforced folder is read from a topic, never guessed", () => {
  assert.equal(enforcedFolder(TOC), "564706-RGBPR50305.2026-2027.1");
  assert.equal(enforcedFolder({ Modules: [] }), "");
});

test("file names are decoded, and only documents count", () => {
  assert.equal(basename("/content/enforced/x/260909%20PL2%20week%202%20-%20Production.pdf"), "260909 PL2 week 2 - Production.pdf");
  assert.ok(isDocument("a/b/Slides.pptx"));
  assert.ok(!isDocument("/d2l/le/lessons/1"));
  assert.ok(isPage("Week 1. Preparation.html"));
});

test("documents skips links and html pages, and carries the week", () => {
  const d = documents(TOC, 564706);
  assert.deepEqual(d.map((x) => x.title), ["Syllabus 2026_2027", "Slides Lecture 7 EU Citizenship"]);
  assert.equal(d[0].url, downloadUrl(564706, 5918043));
  assert.equal(d[0].key, "t:5918043");
  assert.equal(d[1].week, "4");
  assert.equal(d[0].week, "");
});

test("html topics are listed separately so their links can be read", () => {
  const p = pages(TOC, 564706);
  assert.equal(p.length, 1);
  assert.equal(p[0].title, "I-R-A-C Method");
  assert.equal(moduleIds(TOC).length, 2);
});

test("spaces in a path are encoded once, not twice", () => {
  assert.equal(encodePath("/content/enforced/a b/Syllabus 2026_2027__001.pdf"), "/content/enforced/a%20b/Syllabus%202026_2027__001.pdf");
  assert.equal(encodePath("/content/enforced/a/260909%20PL2.pdf"), "/content/enforced/a/260909%20PL2.pdf");
});

test("links inside a page resolve against the course folder; external and d2l links are left alone", () => {
  const html = `<a href="260909%20PL2%20week%202%20-%20Production.pdf">Production</a>
    <a href='https://degruyter.com/book'>DCFR</a>
    <a href="/d2l/common/dialogs/quickLink/quickLink.d2l?ou=1">video</a>
    <a href="/content/enforced/564706-RGBPR50305.2026-2027.1/Q&A Mock Exam.pdf">Mock</a>
    <a href="260909%20PL2%20week%202%20-%20Production.pdf">same again</a>`;
  const out = linksIn(html, "564706-RGBPR50305.2026-2027.1", { week: "2", module: "Week 2" });
  assert.deepEqual(out.map((o) => o.name), ["260909 PL2 week 2 - Production.pdf", "Q&A Mock Exam.pdf"]);
  assert.equal(out[0].url, "/content/enforced/564706-RGBPR50305.2026-2027.1/260909%20PL2%20week%202%20-%20Production.pdf");
  assert.equal(out[1].url, "/content/enforced/564706-RGBPR50305.2026-2027.1/Q%26A%20Mock%20Exam.pdf");
  assert.equal(out[0].week, "2");
});

test("a second scan offers nothing that was already taken", () => {
  const items = documents(TOC, 564706);
  assert.equal(unseen(items, []).length, 2);
  assert.equal(unseen(items, ["t:5918043"]).length, 1);
  assert.equal(unseen([...items, ...items], []).length, 2, "the same file found twice is offered once");
});

test("a File topic and a link to the same path collapse to one entry, the topic wins", () => {
  const topic = documents(TOC, 564706)[0]; // key "t:5918043", path ".../Syllabus 2026_2027__001.pdf"
  const html = `<a href="Syllabus 2026_2027__001.pdf">Syllabus (again, as a link)</a>`;
  const link = linksIn(html, "564706-RGBPR50305.2026-2027.1", { week: "", module: "Course information" })[0];
  assert.equal(link.path, topic.path, "the link resolves to the same underlying file as the topic");
  const out = dedupe([topic, link]);
  assert.equal(out.length, 1, "only one of the two survives");
  assert.equal(out[0].kind, "topic", "the topic (stable TopicId) wins over the link");

  // order shouldn't matter
  const out2 = dedupe([link, topic]);
  assert.equal(out2.length, 1);
  assert.equal(out2[0].kind, "topic");
});

test("dedupe leaves unrelated items and items without a path untouched", () => {
  const items = documents(TOC, 564706);
  assert.equal(dedupe(items).length, items.length);
  assert.equal(dedupe([{ key: "x", kind: "link" }, { key: "y", kind: "link" }]).length, 2);
});

/* ---- wider wrapper parsing (PIL smart-curriculum pages), decide(), and the login sniffing ---- */
import { readFileSync } from "node:fs";
import { documentPath, decide, looksLikeDocument, isLoginResponse, dirOf } from "../lib.js";

const PIL = "564701-RGBIR50010.2026-2027.1";
const WRAP = readFileSync(new URL("./fixtures/pil-wrapper.synthetic.html", import.meta.url), "utf8");

test("a wrapper page yields its iframe viewer ?file=, absolute same-host link and <object data>, never itself", () => {
  const got = linksIn(WRAP, PIL, { week: "2", dir: `/content/enforced/${PIL}/Week 2/` }).map((x) => x.path).sort();
  assert.deepEqual(got, [
    `/content/enforced/${PIL}/Readings/Reading week 2.pdf`,
    `/content/enforced/${PIL}/Week 2/Handout 2.docx`,
    `/content/enforced/${PIL}/Week 2/Lecture 2 slides.pdf`,
  ]);
});

test("documentPath: embed/data-* attributes, coursefile quickLinks, and everything that must be refused", () => {
  const html = `<embed src="Slides%203.pdf"><div data-src="/content/enforced/${PIL}/x/Notes.pptx"></div>
    <a href="/d2l/common/dialogs/quickLink/quickLink.d2l?ou=564701&type=coursefile&fileId=Week%203%2FSlides%203b.pdf">ql</a>`;
  const got = linksIn(html, PIL, {}).map((x) => x.path).sort();
  assert.deepEqual(got, [
    `/content/enforced/${PIL}/Slides 3.pdf`,
    `/content/enforced/${PIL}/Week 3/Slides 3b.pdf`,
    `/content/enforced/${PIL}/x/Notes.pptx`,
  ]);
  assert.equal(documentPath("https://example.org/a.pdf", PIL), "", "another host");
  assert.equal(documentPath("//evil.example/a.pdf", PIL), "", "protocol-relative other host");
  assert.equal(documentPath("Lecture 2.html", PIL), "", "the wrapper itself");
  assert.equal(documentPath("/d2l/le/content/564701/viewContent/1/View", PIL), "", "a D2L view link");
  assert.equal(documentPath("../../../etc/a.pdf", PIL, `/content/enforced/${PIL}/`), "", "never leaves the content tree");
  assert.equal(dirOf(`/content/enforced/${PIL}/Week 2/Lecture 2.html`), `/content/enforced/${PIL}/Week 2/`);
});

test("decide: new -> upload, handled with no signal -> adopt, same -> skip, changed -> check", () => {
  const it = { key: "t:1", lastModified: "2026-11-03" };
  assert.equal(decide(it, {}), "upload");
  assert.equal(decide(it, { seen: ["t:1"] }), "adopt");
  assert.equal(decide({ key: "t:1" }, { seen: ["t:1"] }), "skip", "no date anywhere: never re-download");
  assert.equal(decide(it, { entry: { signal: "2026-11-03" } }), "skip");
  assert.equal(decide(it, { entry: { signal: "2026-10-01" } }), "check");
  assert.equal(decide({ key: "t:1" }, { entry: { signal: "2026-10-01" } }), "skip", "a missing date is not a change");
});

test("login pages are not documents, and login answers are recognised", () => {
  const enc = (s) => new TextEncoder().encode(s);
  assert.ok(looksLikeDocument("a.pdf", "application/pdf", enc("%PDF-1.7")));
  assert.ok(!looksLikeDocument("a.pdf", "text/html", enc("<!doctype html>")));
  assert.ok(!looksLikeDocument("a.pdf", "application/octet-stream", enc("<html>login")));
  assert.ok(looksLikeDocument("a.docx", "", new Uint8Array([0x50, 0x4b, 3, 4])));
  const r = (status, url, type = "basic") => ({ status, url, type });
  assert.ok(isLoginResponse(r(401, "https://brightspace.rug.nl/x")));
  assert.ok(isLoginResponse(r(302, "https://brightspace.rug.nl/x")));
  assert.ok(isLoginResponse(r(0, "", "opaqueredirect")));
  assert.ok(isLoginResponse(r(200, "https://signon.rug.nl/sso")));
  assert.ok(isLoginResponse(r(200, "https://brightspace.rug.nl/d2l/login?x")));
  assert.ok(!isLoginResponse(r(200, "https://brightspace.rug.nl/d2l/api/le/1.97/1/content/toc")));
  assert.ok(!isLoginResponse(r(404, "https://brightspace.rug.nl/x")), "a missing file is not a login");
});

/* ---- adversarial-review finding 3: course-folder enforcement and normalisation ---- */
import * as lib from "../lib.js";

test("documentPath accepts the course's own enforced folder in every embed form (the live PIL wrapper shape)", () => {
  const name = "PIL Lecture 1 - 2026-2027-FINAL.pdf";
  const dir = `/content/enforced/${PIL}/`;
  const want = `/content/enforced/${PIL}/${name}`;
  for (const raw of [
    name, encodeURIComponent(name), `/content/enforced/${PIL}/${name}`,
    `https://brightspace.rug.nl/content/enforced/${PIL}/${encodeURIComponent(name)}`,
  ]) assert.equal(documentPath(raw, PIL, dir), want, raw);
  const html = `<iframe src="${encodeURIComponent(name)}"></iframe><embed src="${name}"><object data="${name}"></object><a href="${name}">x</a>`;
  assert.deepEqual(linksIn(html, PIL, { dir }).map((x) => x.path), [want]);
  // the TOC-derived folder can differ from where the wrapper lives (another offering of the same org)
  assert.equal(documentPath(`/content/enforced/564701-RGBIR50010.2025-2026.1/${name}`, PIL, dir), `/content/enforced/564701-RGBIR50010.2025-2026.1/${name}`);
});

test("documentPath never leaves /content/enforced/<org>-*/ (probe3)", () => {
  const dir = `/content/enforced/${PIL}/Week 2/`;
  for (const raw of [
    "/content/enforced/999999-OTHERCOURSE/exam-answers.pdf",
    "https://brightspace.rug.nl/content/enforced/999999-OTHERCOURSE/exam-answers.pdf",
    "/content/enforced/x/..%2F..%2Fshared%2Fother.pdf",
    "/content/enforced/x/..%2F..%2Fd2l%2Fle%2Fsecret.pdf",
    `/content/enforced/${PIL}/..%2F..%2Fshared%2Fother.pdf`,
    `/content/enforced/${PIL}/%252e%252e%252fshared.pdf`,
    `/content/enforced/${PIL}/a\\..\\..\\b.pdf`,
    "/content/enforced/../../shared/other.pdf",
    "https://brightspace.rug.nl/content/enforced/..%2f..%2fd2l/x.pdf",
    "viewer.html?file=/content/enforced/x/../../../d2l/y.pdf",
    "/content/enforced/564701/flat.pdf",
    "/content/enforced/5647010-OTHER/x.pdf",
    "../../999999-OTHER/x.pdf",
  ]) assert.equal(documentPath(raw, PIL, dir), "", raw);
  assert.equal(documentPath("loose.pdf", "", ""), "", "no folder and no org: nothing can be verified, so nothing is accepted");
});

test("appOrigin: https anywhere, http only for localhost", () => {
  assert.equal(typeof lib.appOrigin, "function");
  assert.equal(lib.appOrigin("https://app.cognitioflow.ai/x"), "https://app.cognitioflow.ai");
  assert.equal(lib.appOrigin("http://localhost:8000"), "http://localhost:8000");
  assert.equal(lib.appOrigin("http://127.0.0.1:8000/"), "http://127.0.0.1:8000");
  assert.equal(lib.appOrigin("http://app.cognitioflow.ai"), "");
  assert.equal(lib.appOrigin("ftp://x"), "");
  assert.equal(lib.appOrigin("not a url"), "");
});

test("red-team B3: a page Url outside this course's enforced folder is not listed", async () => {
  const { pages: pagesOf, readErrorsNote } = await import("../lib.js");
  const toc = { Modules: [{ ModuleId: 1, Title: "Week 1", Modules: [], Topics: [
    { TopicId: 1, Title: "evil", TypeIdentifier: "File", Url: ".evil.example/x.html" },
    { TopicId: 2, Title: "other", TypeIdentifier: "File", Url: "/content/enforced/999999-OTHER/secret.html" },
    { TopicId: 3, Title: "up", TypeIdentifier: "File", Url: "/content/enforced/564706-A/../999999-OTHER/x.html" },
    { TopicId: 4, Title: "abs", TypeIdentifier: "File", Url: "https://evil.example/content/enforced/564706-A/x.html" },
    { TopicId: 5, Title: "ok", TypeIdentifier: "File", Url: "/content/enforced/564706-A/Week 1/ok.html" }] }] };
  assert.deepEqual(pagesOf(toc, 564706).map((p) => p.title), ["ok"]);
  assert.equal(readErrorsNote({ readErrors: ["Lecture 2 (500)"] }),
    "1 page could not be read (Lecture 2 (500)); its files are not listed yet. The first review finishes after a check that reads every page — or run a baseline in Options if a page stays broken");
  assert.equal(readErrorsNote({ readErrors: ["Lecture 2 (500)"] }, true), "1 page could not be read (Lecture 2 (500)); its files are not listed yet");
  assert.equal(readErrorsNote({ state: "ok" }), "");
});

test("red-team round 3: a first-review file the last scan did not find says so in the popup", async () => {
  const { pendingNote } = await import("../lib.js");
  assert.equal(typeof pendingNote, "function");
  assert.equal(pendingNote({ key: "t:1", name: "a.pdf" }), "");
  assert.equal(pendingNote({ key: "t:1", name: "a.pdf", missing: true }), "not on Brightspace at the last check — still needs a choice");
});
