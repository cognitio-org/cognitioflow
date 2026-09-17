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
