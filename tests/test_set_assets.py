"""What the exported sets must actually contain.

Two faults shipped in courtroom.glb and neither was visible from the code:

  * the .blend had three AREA lights, and glTF's KHR_lights_punctual carries only point,
    spot and directional, so the export dropped all three silently. The set loaded clean
    with no lights at all and fell through to a single hard-coded fallback.
  * every cam_* anchor resolved to "straight up", so the shots were framed on the ceiling.
    That one was in the reader, not the asset: sets.js took a Blender empty's aim from its
    local -Z, but the exporter bakes the +Y-up conversion into each node's own rotation, so
    -Z arrives rotated and the aim is the local -Y. Nothing here can catch that - it needs a
    test on sets.js, and the player has no JS harness yet. What is below is the weaker
    neighbouring guard: no camera in a set may be aimed at the floor or the ceiling.

Both times the file parsed, the markers were present, and every existing check passed. The
lights test does fail on the .glb that shipped; the aim test would not have.
"""
import json
import math
import struct
from pathlib import Path

import pytest

SETS = Path(__file__).resolve().parent.parent / "play" / "player" / "assets-v1" / "sets"


def gltf(path):
    """The JSON chunk of a .glb."""
    raw = path.read_bytes()
    assert raw[:4] == b"glTF", f"{path.name} is not a .glb"
    return json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])


def aim(node):
    """Where a Blender empty points, in world space, per the convention in sets.js.

    Blender's exporter bakes the +Y-up conversion into each node's own rotation rather than a
    root, so an empty's Blender -Z arrives as the node's local -Y.
    """
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    vx, vy, vz = 0.0, -1.0, 0.0
    # q * v * q^-1, written out to keep this file dependency-free
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx))


def set_files():
    return sorted(SETS.glob("*.glb"))


def test_there_is_at_least_one_exported_set():
    assert set_files(), f"no .glb under {SETS} - run blender/export_sets.py"


@pytest.mark.parametrize("path", set_files(), ids=lambda p: p.stem)
def test_a_set_ships_its_own_lights(path):
    """A set with no punctual lights renders on sets.js's one-light fallback."""
    j = gltf(path)
    lights = j.get("extensions", {}).get("KHR_lights_punctual", {}).get("lights", [])
    assert lights, (
        f"{path.name} carries no KHR_lights_punctual. Area lights do not export - "
        "use point, spot or sun, and keep export_lights on in blender/export_sets.py."
    )
    for light in lights:
        assert light["type"] in {"point", "spot", "directional"}
        assert light.get("intensity", 0) > 0, f"{light.get('name')} exports at zero intensity"


@pytest.mark.parametrize("path", set_files(), ids=lambda p: p.stem)
def test_every_camera_anchor_is_aimed(path):
    """No shot may be framed at the floor or the ceiling.

    This does not catch the -Z/-Y reader bug - an unrotated empty reads as horizontal under
    the correct convention, so it passes on the broken asset too. It catches the other way in:
    an empty rotated to point at nothing.
    """
    j = gltf(path)
    cams = [n for n in j.get("nodes", []) if (n.get("name") or "").lower().startswith("cam_")]
    assert cams, f"{path.name} has no cam_* anchors"
    for node in cams:
        _, up, _ = aim(node)
        assert abs(up) < 0.9, (
            f"{path.name}: {node['name']} points {math.degrees(math.asin(max(-1, min(1, up)))):.0f} "
            "degrees off horizontal - the empty was never rotated to face its subject."
        )
