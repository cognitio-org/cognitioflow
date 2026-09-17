#!/usr/bin/env python3
"""
Fill a LOCAL development database with realistic fixture content, so every screen can be judged
at real density instead of rendering its empty state.

  make seed                       # the normal way in
  python3 scripts/seed_dev.py     # the same thing
  python3 scripts/seed_dev.py --clear     # remove the fixture rows again, leave real rows alone

What it writes, for both shipped courses:
  notes      12 notes from scripts/fixtures/notes/*.md, one of them 16k characters, exercising
             headings, nested lists, multi-column tables, a ```mermaid fence, *case names* in
             italics, every provenance tag, priority marks and callouts
  cards      new, due today, overdue, far-future and weak-ease, so Recall's queue, the ratings row
             and the queue-clear state are all reachable
  sessions   five weeks either side of today, both courses, done and not done
  files      per week, some ticked and some not, written through storage.py like any other upload

LOCAL ONLY. This is fabricated study content. CLAUDE.md forbids fabricated user content on Neon
branches, so the script refuses to run against anything that does not look like a local database,
and says why. Every row it writes has an id beginning `fix-`, so --clear can take them out again
without touching anything you wrote yourself.

Idempotent: running it twice leaves exactly the state of running it once.
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PREFIX = "fix-"                      # every fixture row id starts with this

# A database is local if it is reachable only from this machine or from the compose network.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "db", "postgres", "cf-db", "host.docker.internal"}
# ...and never local if it carries a managed provider's fingerprint, whatever the host resolves to.
REMOTE_MARKERS = ("neon.tech", "neon.build", "amazonaws.com", "googleapis.com", "cloudsql",
                  "azure.com", "supabase.", "render.com", "heroku", ".run.app")


class NotLocal(RuntimeError):
    pass


def assert_local(url: str) -> str:
    """Refuse anything that is not plainly a local database, and name the reason.

    Never prints the URL: it carries a password. The host alone is enough to explain the refusal.
    """
    if (os.environ.get("ENV") or "").strip().lower() == "production":
        raise NotLocal("ENV=production. Fixture content never goes near production.")
    host = (urlsplit(url).hostname or "").lower()
    low = url.lower()
    for marker in REMOTE_MARKERS:
        if marker in low:
            raise NotLocal(f"DATABASE_URL points at a managed host ({marker}). "
                           "Fixture content is for docker Postgres only — CLAUDE.md forbids seeding "
                           "fabricated notes into a Neon branch.")
    if host not in LOCAL_HOSTS:
        raise NotLocal(f"DATABASE_URL host is {host!r}, which is not a local host. "
                       f"Expected one of: {', '.join(sorted(LOCAL_HOSTS))}.")
    return host


# --------------------------------------------------------------------------- the fixture content

def notes_for(course_id: str) -> list:
    """(id, title, body) per markdown file, ordered so the rail has something to scroll."""
    out = []
    for path in sorted(FIXTURES.joinpath("notes").glob(f"{course_id}-*.md")):
        body = path.read_text(encoding="utf-8")
        title = body.lstrip().split("\n", 1)[0].lstrip("# ").strip()
        out.append((PREFIX + path.stem, title, body))
    return out


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


# (front, back, week, due offset in days, ease, interval, reps, state)
# state is FSRS's: None = never seen, 2 = in review. The spread is the point — every queue state
# the Recall screen can show needs at least one card sitting in it.
EU_CARDS = [
    ("What is the Dassonville formula?",
     "All trading rules enacted by Member States capable of hindering, directly or indirectly, actually or potentially, intra-Union trade.",
     "2", 0, 2.5, 6, 3, 2),
    ("Which measures may rely on the mandatory requirements?",
     "Only indistinctly applicable ones. A distinctly applicable measure is confined to the closed Art 36 list.",
     "2", 0, 2.5, 6, 3, 2),
    ("What did Keck carve out of Art 34?",
     "Selling arrangements — when, where and by whom goods may be sold — if they apply to all traders and bite equally in law and in fact.",
     "2", -6, 2.0, 3, 2, 2),
    ("Is an economic aim ever a justification?",
     "No. Never, on either list.",
     "2", -2, 2.1, 4, 2, 2),
    ("Name the two proportionality limbs, in order.",
     "Suitability, then necessity.",
     "3", 0, 2.5, 0, 0, None),
    ("What is the effect of Art 30 TFEU on a charge?",
     "Unlawful outright. There is no justification route.",
     "1", 0, 2.5, 0, 0, None),
    ("Which case requires the national court to disapply on its own motion?",
     "*Simmenthal*.",
     "1", 41, 2.7, 45, 6, 2),
    ("Can an unimplemented directive bind another private party?",
     "No — *Faccini Dori*. Go to consistent interpretation, then Francovich.",
     "1", 27, 2.6, 30, 5, 2),
    ("What does the CILFIT acte clair escape require?",
     "That the correct application is so obvious as to leave no scope for reasonable doubt, equally for the other Member States' courts and for the Court itself.",
     "5", -1, 2.3, 8, 3, 2),
    ("Which court may declare a Union act invalid?",
     "Only the Court of Justice — *Foto-Frost*. A national court may find an act valid, never invalid.",
     "5", 0, 2.5, 0, 0, None),
    ("What is the remedy under Art 110(2)?",
     "Removal of the protective effect, not equalisation of the tax.",
     "3", -11, 1.9, 2, 1, 2),
    ("What does Lawrie-Blum define?",
     "A worker: services of economic value, for and under another's direction, for remuneration.",
     "4", 13, 2.5, 15, 4, 2),
]

PROP_CARDS = [
    ("What are the three requirements for transfer under Art 3:84 BW?",
     "A valid title, delivery, and the transferor's power to dispose. Cumulative.",
     "2", 0, 2.5, 6, 3, 2),
    ("Is Dutch law causal or abstract on transfer?",
     "Causal — a defect in the title defeats the transfer, so ownership never left the transferor.",
     "2", 0, 2.5, 6, 3, 2),
    ("What does Art 3:86 BW protect?",
     "A good-faith acquirer for value of a movable, where the transferor lacked the power to dispose.",
     "2", -4, 2.2, 5, 2, 2),
    ("How long is the stolen-goods window in Art 3:86(3) BW?",
     "Three years from the theft, and it protects the dispossessed owner.",
     "2", -9, 2.0, 3, 2, 2),
    ("What does Art 5:1 BW say?",
     "Ownership is the most comprehensive right a person can have in a thing.",
     "1", 0, 2.5, 0, 0, None),
    ("Possession or detention: a tenant?",
     "Detention — holding for another. No prescription, no Art 3:86.",
     "1", 0, 2.5, 0, 0, None),
    ("What is prohibited by Art 3:235 BW?",
     "Toe-eigening: an agreement made before default that the creditor may simply keep the pledged thing. Void.",
     "3", -3, 2.3, 4, 2, 2),
    ("Does Art 3:105 BW require good faith?",
     "No. After twenty years the possessor becomes owner even in bad faith.",
     "3", 19, 2.6, 21, 5, 2),
    ("Can a co-owner's share be a physical part of the thing?",
     "No. A share is undivided. Exclusive use of a part comes from apartment rights or agreement.",
     "4", 34, 2.7, 38, 6, 2),
    ("How is a mortgage enforced?",
     "Public sale under Art 3:268 BW, unless the court permits otherwise.",
     "3", 0, 2.5, 0, 0, None),
]

# (topic, day offset, minutes, done)
EU_SESSIONS = [
    ("Read Schütze ch. 12 — customs union", -19, 60, 1),
    ("Drill Art 34 cards", -17, 30, 1),
    ("WG 3 preparation — Keck problem", -14, 90, 1),
    ("Rewrite week 2 notes from the lecture", -12, 75, 1),
    ("Drill the Art 36 case map", -8, 45, 1),
    ("Past paper 2024 — goods question", -5, 120, 1),
    ("Reconcile week 4 capture with the slides", -2, 60, 0),
    ("Drill cards due today", 0, 30, 0),
    ("WG 5 preparation — preliminary references", 1, 90, 0),
    ("Compare-and-contrast practice", 3, 60, 0),
    ("Past paper 2025 — full sitting", 6, 150, 0),
    ("Revise the master notes end to end", 11, 120, 0),
]

PROP_SESSIONS = [
    ("Book 5 BW — read Title 5.1", -16, 60, 1),
    ("Transfer problem set", -13, 75, 1),
    ("Drill Art 3:86 elements", -9, 30, 1),
    ("Security rights — read the reader", -6, 90, 1),
    ("Possession and prescription cards", -1, 30, 0),
    ("Co-ownership problem set", 0, 60, 0),
    ("WG 4 preparation", 2, 90, 0),
    ("Comparative section — German abstract system", 5, 60, 0),
    ("Mock exam — property", 9, 120, 0),
]

# (name, kind, week, selected, body)
EU_FILES = [
    ("Lecture 1 — foundations.txt", "text", "1", 1,
     "Supremacy: Costa v ENEL, Internationale Handelsgesellschaft, Simmenthal. Direct effect: Van Gend en Loos."),
    ("Lecture 2 — free movement of goods.txt", "text", "2", 1,
     "Dassonville formula. Cassis de Dijon: mutual recognition and mandatory requirements. Keck: selling arrangements."),
    ("WG 2 annotated notes.txt", "text", "2", 1,
     "Tutor: the in-fact limb of Keck is where most defences fail. Economic aims are never a mandatory requirement."),
    ("Slides week 2.txt", "text", "2", 1,
     "Slide 6: exam is one goods question plus compare-and-contrast. Slide 11 lists protecting a domestic industry (wrong)."),
    ("Lecture 3 — customs union.txt", "text", "3", 1,
     "Arts 28-30. Charges having equivalent effect. Art 110(1) similar goods, 110(2) competing goods."),
    ("Reader extract — Art 36 case law.txt", "text", "3", 0,
     "Henn and Darby, Conegate, Danish Bottles, Commission v Denmark, Schmidberger."),
    ("Lecture 4 — persons.txt", "text", "4", 0,
     "Lawrie-Blum, Levin, Kempf, Antonissen. Citizenship: Grzelczyk, Baumbast, Ruiz Zambrano."),
    ("Lecture 5 — preliminary references.txt", "text", "5", 0,
     "Art 267. CILFIT. Foto-Frost. Rheinmuhlen. Art 258 and Art 260 enforcement."),
    ("Past paper 2024.txt", "text", "", 0,
     "Question 1: a Member State bans energy drinks above 50mg caffeine per litre. Question 3: compare justification regimes."),
]

PROP_FILES = [
    ("Lecture 1 — ownership and possession.txt", "text", "1", 1,
     "Art 5:1 BW. Numerus clausus. Art 3:107 possession and detention. Interversie."),
    ("Lecture 2 — transfer.txt", "text", "2", 1,
     "Art 3:84 BW: title, delivery, power to dispose. Causal system. Art 3:86 good-faith acquisition."),
    ("WG 2 annotated notes.txt", "text", "2", 1,
     "Tutor: the three-year window in Art 3:86(3) protects the dispossessed owner, not the acquirer."),
    ("Lecture 3 — security rights.txt", "text", "3", 1,
     "Pledge and mortgage. Art 3:227. Possessory and non-possessory pledge. Art 3:235 toe-eigening."),
    ("Reader — comparative transfer systems.txt", "text", "2", 0,
     "German abstract system, French solo consensu, Dutch causal tradition."),
    ("Lecture 4 — co-ownership.txt", "text", "4", 0,
     "Title 3.7 BW. Art 3:166, 3:169, 3:175, 3:178. Apartment rights under Title 5.9."),
]

COURSES = {
    "eu": {"cards": EU_CARDS, "sessions": EU_SESSIONS, "files": EU_FILES},
    "prop": {"cards": PROP_CARDS, "sessions": PROP_SESSIONS, "files": PROP_FILES},
}


# ------------------------------------------------------------------------------------ the writing

def seed(quiet: bool = False) -> dict:
    """Write every fixture row. Safe to run repeatedly — each row is upserted on its own id."""
    import run                    # the db() / rows() seam, and the pool it owns
    import storage
    run.init()                    # migrate and seed the shipped courses, so this works on an empty DB
    now, counts = datetime.now().timestamp(), {"notes": 0, "cards": 0, "sessions": 0, "files": 0}

    with run.db() as d:
        known = {r["id"] for r in d.execute("SELECT id FROM courses").fetchall()}
        for cid, data in COURSES.items():
            if cid not in known:
                if not quiet:
                    print(f"  course {cid} is not in this database — skipped")
                continue

            for nid, title, body in notes_for(cid):
                d.execute("INSERT INTO notes(id,course_id,title,body,updated) VALUES(?,?,?,?,?) "
                          "ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title, body=EXCLUDED.body, updated=EXCLUDED.updated",
                          (nid, cid, title, body, now))
                counts["notes"] += 1

            for i, (front, back, week, due_off, ease, interval, reps, state) in enumerate(data["cards"]):
                d.execute(
                    "INSERT INTO cards(id,course_id,front,back,source,week,due,created,ease,interval,reps,state,"
                    "stability,difficulty,last_review) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT (id) DO UPDATE SET front=EXCLUDED.front, back=EXCLUDED.back, week=EXCLUDED.week, "
                    "due=EXCLUDED.due, ease=EXCLUDED.ease, interval=EXCLUDED.interval, reps=EXCLUDED.reps, "
                    "state=EXCLUDED.state, stability=EXCLUDED.stability, difficulty=EXCLUDED.difficulty, "
                    "last_review=EXCLUDED.last_review",
                    (f"{PREFIX}{cid}-card-{i:02d}", cid, front, back, "fixture", week, _day(due_off), now,
                     ease, interval, reps, state,
                     float(interval) * 1.4 if state else None,      # plausible FSRS memory state
                     5.2 if state else None,
                     now - 86400 * max(1, interval) if state else None))
                counts["cards"] += 1

            for i, (topic, day_off, minutes, done) in enumerate(data["sessions"]):
                d.execute("INSERT INTO sessions(id,course_id,day,topic,minutes,done) VALUES(?,?,?,?,?,?) "
                          "ON CONFLICT (id) DO UPDATE SET day=EXCLUDED.day, topic=EXCLUDED.topic, "
                          "minutes=EXCLUDED.minutes, done=EXCLUDED.done",
                          (f"{PREFIX}{cid}-sess-{i:02d}", cid, _day(day_off), topic, minutes, done))
                counts["sessions"] += 1

            for i, (name, kind, week, selected, body) in enumerate(data["files"]):
                fid = f"{PREFIX}{cid}-file-{i:02d}"
                key = f"courses/{cid}/files/{fid}/{storage.safe_name(name)}"
                storage.put(key, body.encode("utf-8"), "text/plain; charset=utf-8")
                d.execute("INSERT INTO files(id,course_id,name,kind,key,text,chars,selected,status,week,created) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                          "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, key=EXCLUDED.key, text=EXCLUDED.text, "
                          "chars=EXCLUDED.chars, selected=EXCLUDED.selected, week=EXCLUDED.week",
                          (fid, cid, name, kind, key, body, len(body), selected, "indexed", week, now))
                counts["files"] += 1
    return counts


def clear(quiet: bool = False) -> dict:
    """Remove every row this script wrote. Rows you made yourself have no `fix-` prefix."""
    import run
    counts = {}
    with run.db() as d:
        for table in ("note_versions", "notes", "cards", "sessions", "files"):
            col = "note_id" if table == "note_versions" else "id"
            cur = d.execute(f"DELETE FROM {table} WHERE {col} LIKE '{PREFIX}%'")
            counts[table] = cur.rowcount
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed a local development database with fixture content.")
    ap.add_argument("--clear", action="store_true", help="remove the fixture rows instead of writing them")
    ap.add_argument("--quiet", action="store_true", help="only print the summary line")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env.local", override=True)
        load_dotenv()
    except ImportError:
        pass

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is not set. Copy .env.local.example to .env.local first.", file=sys.stderr)
        return 2
    try:
        host = assert_local(url)
    except NotLocal as e:
        print(f"Refusing to run: {e}", file=sys.stderr)
        return 2

    if args.clear:
        counts = clear(args.quiet)
        print("Cleared fixture rows on " + host + ": "
              + ", ".join(f"{v} {k}" for k, v in counts.items() if v))
        return 0

    counts = seed(args.quiet)
    print(f"Seeded {host}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    print("Fixture content, not real coursework. Remove it with: python3 scripts/seed_dev.py --clear")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
