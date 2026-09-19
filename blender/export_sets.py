"""Export every blender/*.blend to play/player/assets-v1/sets/<name>.glb.

Run headless, from the repo root:

    /Applications/Blender.app/Contents/MacOS/Blender --background --python blender/export_sets.py

Why this file exists: courtroom.glb was exported by hand, and the hand-run left
Punctual Lights off. The .blend has three lights (key, fill, bench); the .glb that
shipped had none, so sets.js fell through to its one-DirectionalLight fallback and
every render was flat. The set was not underlit - the lights never made the trip.

Named empties (spawn_, door_trigger, cam_, mark_) are the contract sets.js reads, so
cameras stay off: cam_* are empties, and exporting real cameras would add a second,
conflicting set of anchors.
"""
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "play" / "player" / "assets-v1" / "sets"

WANT = {
    "export_format": "GLB",
    "export_lights": True,      # the whole point
    "export_cameras": False,    # cam_* empties are the anchors
    "export_extras": True,      # custom props survive
    "export_apply": True,       # modifiers baked
    "export_yup": True,
    "use_visible": True,
    "export_normals": True,
}


def kwargs_the_build_accepts():
    """Only pass properties this Blender's exporter actually has.

    The glTF operator renames properties between releases. Passing an unknown one
    raises; silently dropping a known one is worse, so a dropped key is printed.
    """
    known = bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
    ok = {k: v for k, v in WANT.items() if k in known}
    for k in WANT.keys() - ok.keys():
        print("  ! %s: this Blender has no such export option" % k)
    return ok


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    opts = kwargs_the_build_accepts()
    failed = []
    for blend in sorted((ROOT / "blender").glob("*.blend")):
        bpy.ops.wm.open_mainfile(filepath=str(blend))
        lights = [o.name for o in bpy.data.objects if o.type == "LIGHT"]
        target = OUT / (blend.stem + ".glb")
        bpy.ops.export_scene.gltf(filepath=str(target), **opts)
        kb = target.stat().st_size // 1024 if target.exists() else 0
        print("  %-16s -> %-28s %4d KB  lights in scene: %s"
              % (blend.name, target.name, kb, ", ".join(lights) or "none"))
        if not target.exists():
            failed.append(blend.name)
    if failed:
        sys.exit("export produced no file for: " + ", ".join(failed))


main()
