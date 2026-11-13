"""Gate C — Playability (headless playthrough).

Core logic is browser-free: it talks to a `PageProbe` (a duck-typed protocol),
so the acceptance test injects a fake probe and never launches Chromium. A real
driver (`playwright_probe`) is provided behind a lazy import; importing this
module never requires playwright.

Fail-closed: any console error OR any missing required selector → ok False. A
probe method that raises is also a failure (a broken probe must never read as a
clean page).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Iterator, Protocol


class PageProbe(Protocol):
    """What the gate needs from a page, real or fake."""

    def console_errors(self) -> list[str]:
        """Console/page errors collected during the run (empty = clean)."""
        ...

    def query(self, selector: str) -> bool:
        """True if at least one element matches `selector`."""
        ...

    def title(self) -> str:
        """Document title (used by the real driver / review card, not by ok)."""
        ...


@dataclass
class PlayabilityVerdict:
    ok: bool
    errors: list[str] = field(default_factory=list)
    missing_selectors: list[str] = field(default_factory=list)


def check_playability(
    probe: PageProbe,
    required_selectors: list[str],
) -> PlayabilityVerdict:
    """Fail-closed playthrough check.

    ok is True only when there are zero console errors and every required
    selector is present. Any exception from the probe is folded into errors,
    so a broken probe fails the gate rather than passing it.
    """
    errors: list[str] = []
    missing: list[str] = []

    try:
        errors = list(probe.console_errors())
    except Exception as exc:  # fail-closed: a broken probe is not a clean page
        errors = [f"probe failure: console_errors: {exc}"]

    for selector in required_selectors:
        try:
            present = probe.query(selector)
        except Exception as exc:  # fail-closed
            errors.append(f"probe failure: query({selector!r}): {exc}")
            missing.append(selector)
            continue
        if not present:
            missing.append(selector)

    ok = not errors and not missing
    return PlayabilityVerdict(ok=ok, errors=errors, missing_selectors=missing)


@contextlib.contextmanager
def playwright_probe(
    html_path: str,
    viewport: tuple[int, int] = (1440, 900),
) -> Iterator[PageProbe]:
    """Real headless-Chromium probe, yielded as a context manager.

    Yielded as a context manager because the browser must outlive the gate's
    query() calls — a plain function returning a probe after the
    `with sync_playwright()` block exits would hand back a dead page.

    Deterministic by construction: external requests are route-aborted (only
    file:// continues), animations/transitions are killed via an init script,
    the viewport is fixed, and both pageerror (covers unhandled promise
    rejections) and console type=="error" are buffered.

    playwright is imported lazily so importing this module never requires it.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised only without playwright
        raise ImportError(
            "playwright is required for playwright_probe(); install it with "
            "`pip install playwright && playwright install chromium`"
        ) from exc

    errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            width, height = viewport
            page = browser.new_page(viewport={"width": width, "height": height})

            # Deterministic: no animation/transition, no snap-away targets.
            page.add_init_script(
                "const s=document.createElement('style');"
                "s.textContent='*,*::before,*::after"
                "{transition:none !important;animation:none !important;"
                "scroll-behavior:auto !important;}';"
                "document.documentElement.appendChild(s);"
            )

            # Block the network: only local file:// is allowed through.
            def _route(route):
                url = route.request.url
                if url.startswith("file://"):
                    route.continue_()
                else:
                    route.abort()

            page.route("**/*", _route)

            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on(
                "console",
                lambda m: errors.append(f"console: {m.text}")
                if m.type == "error"
                else None,
            )

            # Network is blocked, so wait on load, not networkidle.
            page.goto(f"file://{html_path}", wait_until="load")

            class _Probe:
                def console_errors(self) -> list[str]:
                    return list(errors)

                def query(self, selector: str) -> bool:
                    return page.query_selector(selector) is not None

                def title(self) -> str:
                    return page.title()

            yield _Probe()
        finally:
            browser.close()
