"""Mock exams from his own past papers (asked for 2026-09-29, with the EU practice exams and the Property Law mock).

A past paper's questions are banked verbatim, with the official model answer kept locked until he has handed in.
The paper is sat as a paper: every question, the real time, the word limits. Marking is against the points the
model answer makes - hit, partly, missed - with a comment each and no total, as essay practice already does.
"""
import re

SOURCE_PREFIX = "Paper: "          # essay_questions.source for a banked past-paper question: "Paper: <paper> · Q<n>"
_POINTS = re.compile(r"(?i)\b(\d{1,3})\s*points?\b")
_MINUTES = re.compile(r"(?i)\b(\d{1,3})\s*min(?:ute)?s?\b")
_WORDS = re.compile(r"(?i)\b(?:max(?:imum)?\.?\s*(?:word count:?\s*)?)(\d{2,4})(?:\s*words?)?\b")
_ANSWERS = re.compile(r"(?i)\bmodel answers?\b|\banswers?\b")
STANDING = ("hit", "partly", "missed")
EXAM_NAME = re.compile(r"(?i)\b(practice exam|past (exam|paper)|mock exam|resit|model answers?)\b")


def looks_like_exam(name: str) -> bool:
    return bool(EXAM_NAME.search(name or ""))


def header(question: str) -> dict:
    """Points, minutes and word limit, read from the paper's own header line ('19 points; 25 minutes; max 300')."""
    head = (question or "").split("\n", 1)[0]
    grab = lambda rx: int(rx.search(head).group(1)) if rx.search(head) else None
    return {"points": grab(_POINTS), "minutes": grab(_MINUTES), "words": grab(_WORDS)}


def source(paper: str, number: int) -> str:
    return f"{SOURCE_PREFIX}{paper} · Q{number}"


def parse_source(src: str):
    """(paper, number) for a banked past-paper question, None for anything else."""
    m = re.match(re.escape(SOURCE_PREFIX) + r"(.+) · Q(\d+)$", src or "")
    return (m.group(1), int(m.group(2))) if m else None


def papers(questions: list) -> list:
    """Banked questions grouped into papers in question order, with the paper's total time.
    A paper whose questions state no time gets 30 minutes a question."""
    out = {}
    for q in questions:
        p = parse_source(q.get("source"))
        if not p:
            continue
        h = header(q.get("question"))
        out.setdefault(p[0], []).append({"id": q["id"], "number": p[1], "question": q["question"], **h})
    result = []
    for name in sorted(out):
        qs = sorted(out[name], key=lambda x: x["number"])
        result.append({"paper": name, "questions": qs, "minutes": sum(x["minutes"] or 30 for x in qs)})
    return result


def paper_title(filename: str) -> str:
    """'Practice exam 2 - Model answers.pdf' -> 'Practice exam 2'."""
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename or "")
    stem = re.sub(r"(?i)[\s\-–—:]*\(?model answers?\)?\s*$", "", stem)
    return re.sub(r"\s{2,}", " ", stem).strip(" -–—")


def pair_files(files: list) -> list:
    """[(paper title, question file, answers file or None)]: 'Practice exam 1' with 'Practice exam 1 Model answers'.
    A file that carries both (the Property Law 'Questions & Answers Mock Exam') is its own answers."""
    qs, ans = {}, {}
    for f in files:
        name = f.get("name") or ""
        title = paper_title(name)
        if re.search(r"(?i)model answers?", name):
            ans[title] = f
        else:
            qs[title] = f
    return [(t, qs[t], ans.get(t)) for t in sorted(qs)]


def within_limit(text: str, words) -> str:
    """The answer as the marker sees it: cut after the paper's word limit, line breaks kept. The page tells him
    only the first N words are marked, so the marker must not read past them."""
    if not words:
        return text
    m = list(re.finditer(r"\S+", text or ""))
    return text if len(m) <= words else text[:m[words - 1].end()]


def valid_grade(g) -> dict:
    """The marker's JSON, cut to shape: a list of the model answer's points with a standing and a comment each."""
    out = {"points": [], "missing": [], "overall": ""}
    if not isinstance(g, dict):
        return out
    for p in g.get("points") or []:
        if isinstance(p, dict) and str(p.get("point") or "").strip():
            st = str(p.get("standing") or "").lower()
            out["points"].append({"point": str(p["point"])[:300], "standing": st if st in STANDING else "missed",
                                  "comment": " ".join(str(p.get("comment") or "").split()[:50])})
    out["missing"] = [str(x)[:200] for x in (g.get("missing") or []) if str(x).strip()][:6]
    out["overall"] = " ".join(str(g.get("overall") or "").split()[:60])
    return out
