#!/usr/bin/env python3
"""Generate the statute book's two surface textures.

    python3 scripts/make_book_textures.py

Writes static/tex-leather.png and static/tex-paper.png.

Why. The book is a real six-faced object - preserve-3d, a spine, a fore-edge, head and tail -
and every face was a two-stop gradient. `linear-gradient(180deg,#6d1c1f,#3f0e10)` is the spine,
so a 26-pixel leather spine and a 200-pixel cover were the same perfectly smooth ramp. Nothing
told the eye how big anything was. That is the same fault the courtroom had on 2026-09-19:
geometry without material.

These are layered over the existing gradients with background-blend-mode, so the colours in
book.css stay exactly as they were and only the surface changes.

The noise tiles exactly: the value-noise lattice wraps with %cells, so no seam appears where a
128px tile repeats across a 264px cover. Written as sRGB bytes directly, because the browser
decodes a PNG as sRGB - the courtroom's first attempt wrote linear values into an sRGB file and
came out four times too dark.
"""
import pathlib

import numpy as np
from PIL import Image

OUT = pathlib.Path(__file__).resolve().parent.parent / "static"


def vnoise(n, cells, seed):
    """Tileable value noise: the lattice indices wrap, so the tile has no seam."""
    rng = np.random.default_rng(seed)
    g = rng.random((cells, cells))
    idx = np.arange(n) * cells / n
    i0 = np.floor(idx).astype(int) % cells
    i1 = (i0 + 1) % cells
    t = idx - np.floor(idx)
    t = t * t * (3 - 2 * t)
    a, b = g[np.ix_(i0, i0)], g[np.ix_(i0, i1)]
    c, d = g[np.ix_(i1, i0)], g[np.ix_(i1, i1)]
    tx, ty = t[None, :], t[:, None]
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty


def fbm(n, cells, octaves, seed):
    out, amp, norm = np.zeros((n, n)), 1.0, 0.0
    for o in range(octaves):
        out += amp * vnoise(n, cells * 2 ** o, seed + o)
        norm += amp
        amp *= 0.5
    return out / norm


def leather(n=128, seed=3):
    """Pebbled grain: clustered cells with fine speckle between them.

    Mid-grey so it can be blended as overlay - anything darker or lighter would shift the
    book's colour instead of only adding surface to it.
    """
    coarse = fbm(n, 10, 3, seed)
    grain = np.abs(coarse - 0.5) * 2          # creases where the cells meet
    fine = fbm(n, 40, 2, seed + 11) - 0.5
    v = 0.5 + 0.20 * (grain - 0.5) + 0.06 * fine
    return np.clip(v, 0, 1)


def paper(n=128, seed=7):
    """Laid paper: faint horizontal fibre over a soft mottle."""
    mottle = fbm(n, 6, 3, seed) - 0.5
    fibre = np.sin(np.linspace(0, 1, n, endpoint=False)[:, None] * n / 2 * 2 * np.pi) * 0.5
    speck = fbm(n, 48, 2, seed + 5) - 0.5
    v = 0.5 + 0.10 * mottle + 0.022 * fibre + 0.05 * speck
    return np.clip(v, 0, 1)


def write(name, grey):
    """Save as 8-bit greyscale sRGB. The values are already what the bytes should hold."""
    path = OUT / name
    Image.fromarray((grey * 255).round().astype(np.uint8), mode="L").save(path, optimize=True)
    return path, path.stat().st_size


def main():
    for name, grey in (("tex-leather.png", leather()), ("tex-paper.png", paper())):
        path, size = write(name, grey)
        lo, hi = (grey * 255).min(), (grey * 255).max()
        print("  %-18s %5d bytes  range %d-%d  (mid-grey, so overlay only adds surface)"
              % (path.name, size, lo, hi))


if __name__ == "__main__":
    main()
