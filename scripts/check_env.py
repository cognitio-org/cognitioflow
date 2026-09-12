#!/usr/bin/env python3
"""
List missing or unsafe environment configuration; exit non-zero if anything is wrong.

    python3 scripts/check_env.py        # reads .env.local / .env the same way run.py does

Secrets (Secret Manager in cloud, mounted as env vars): ANTHROPIC_API_KEY, DATABASE_URL,
SESSION_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET. Plain env: ENV, AUTH, ALLOWED_EMAILS, MATEJ_EMAIL.

run.py calls enforce() at startup. With ENV=production every problem is fatal (including AUTH=off).
In dev only problems that make the app unusable are fatal; the rest print as warnings, so a
docker-only checkout boots before the Google OAuth client exists.
"""
import os
import sys


def problems(env=None) -> list:
    """[(message, fatal_in_dev)] for the given environment (default os.environ)."""
    env = os.environ if env is None else env
    get = lambda k: (env.get(k) or "").strip()
    prod, off = get("ENV").lower() == "production", get("AUTH").lower() == "off"
    out = []
    def need(name, fatal=True):
        if not get(name): out.append((f"{name} is not set", fatal))
    need("DATABASE_URL")
    if prod:
        if off: out.append(("AUTH=off is not allowed when ENV=production", True))
        need("ANTHROPIC_API_KEY")
    if off and not prod:
        need("MATEJ_EMAIL")
    else:
        need("SESSION_SECRET")
        if 0 < len(get("SESSION_SECRET")) < 32: out.append(("SESSION_SECRET is shorter than 32 characters", False))
        for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ALLOWED_EMAILS"): need(name, fatal=False)
    return out


def enforce(env=None) -> None:
    """Raise RuntimeError on fatal problems; print the rest as warnings."""
    env = os.environ if env is None else env
    prod = (env.get("ENV") or "").strip().lower() == "production"
    found = problems(env)
    for msg, fatal in found:
        if not (fatal or prod): print(f"[check_env] warning: {msg}", file=sys.stderr)
    fatal = [msg for msg, f in found if f or prod]
    if fatal: raise RuntimeError("CognitioFlow refuses to start: " + "; ".join(fatal))


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(".env.local", override=True); load_dotenv()
    except ImportError:
        pass
    found = problems()
    for msg, _ in found: print(msg)
    if not found: print("environment OK")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
