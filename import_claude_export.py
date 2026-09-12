#!/usr/bin/env python3
"""
Turn a claude.ai account export into files CognitioFlow can read.

  Get the export: claude.ai → Settings → Privacy → Export data → zip arrives by email.

  python import_claude_export.py ~/Downloads/data-2026-09-07.zip "European Law" --match "EU law,Dassonville,Article 34,Schütze,Cassis,Keck,direct effect"

Writes one Markdown file per matching conversation into  data/watch/<Course>/claude-chats/
and, if the export carries project documents, one file per document into  .../claude-project-docs/.
Then press "Import new files" in the app. Re-running skips files that already exist.
"""
import argparse, json, re, sys, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

def load(zpath: Path) -> dict:
    out = {}
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            base = n.rsplit("/", 1)[-1]
            if base in ("conversations.json", "projects.json"):
                out[base] = json.loads(z.read(n).decode("utf-8", "replace"))
    return out

def safe(s: str, n: int = 80) -> str:
    s = re.sub(r"[^\w\s-]", "", s or "").strip() or "untitled"
    return re.sub(r"\s+", " ", s)[:n]

def msg_text(m: dict) -> str:
    if m.get("text"): return m["text"]
    parts = m.get("content") or []
    return "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")

def conv_to_md(c: dict) -> str:
    lines = [f"# {c.get('name') or 'Untitled chat'}", f"_Claude chat · {str(c.get('created_at',''))[:10]}_", ""]
    for m in c.get("chat_messages") or []:
        who = "You" if (m.get("sender") == "human") else "Claude"
        t = msg_text(m).strip()
        if t: lines += [f"## {who}", t, ""]
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zip"); ap.add_argument("course")
    ap.add_argument("--match", default="", help="comma-separated keywords; a chat is kept if any appears in its title or text (case-insensitive). Empty = keep all.")
    ap.add_argument("--project", default="", help="only project docs from projects whose name contains this")
    a = ap.parse_args()

    data = load(Path(a.zip).expanduser())
    if not data: sys.exit("No conversations.json / projects.json found in that zip.")
    kws = [k.strip().lower() for k in a.match.split(",") if k.strip()]
    root = HERE / "data" / "watch" / a.course
    chats = root / "claude-chats"; docs = root / "claude-project-docs"
    chats.mkdir(parents=True, exist_ok=True)

    kept = skipped = 0
    for c in data.get("conversations.json", []):
        md = conv_to_md(c)
        if kws and not any(k in md.lower() for k in kws): continue
        fn = chats / f"{str(c.get('created_at',''))[:10]} {safe(c.get('name'))}.md"
        if fn.exists(): skipped += 1; continue
        fn.write_text(md, encoding="utf-8"); kept += 1
    print(f"chats: {kept} written, {skipped} already present → {chats}")

    n = 0
    for p in data.get("projects.json", []) or []:
        if a.project and a.project.lower() not in (p.get("name") or "").lower(): continue
        for d in p.get("docs") or []:
            docs.mkdir(parents=True, exist_ok=True)
            fn = docs / f"{safe(p.get('name'),30)} - {safe(d.get('filename'))}.md"
            if fn.exists() or not d.get("content"): continue
            fn.write_text(d["content"], encoding="utf-8"); n += 1
        if p.get("prompt_template"):
            fn = docs / f"{safe(p.get('name'),30)} - project instructions.md"
            if not fn.exists(): fn.write_text(p["prompt_template"], encoding="utf-8"); n += 1
    if n: print(f"project docs: {n} written → {docs}")
    print("Now open the app → Files → Import new files.")

if __name__ == "__main__":
    main()
