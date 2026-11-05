"""Headless Blender: a grand EU-style courtroom built from REAL CC0 models
(PolyHaven wooden table / chair / gothic cabinet / classic console / book set)
plus procedural architecture (room shell, judge's dais, emblem crest, columns).

This replaces courtroom.py's all-primitive blockout: furniture is now real,
textured geometry. Exports GLB for three.js; PREVIEW=1 also renders a PNG.

Run: /Applications/Blender.app/Contents/MacOS/Blender --background --python courtroom_cc0.py
     PREVIEW=1 ... (also writes courtroom_cc0_preview.png)
Coordinates: Blender Z-up, metres. Player enters from +Y; bench at back (-Y).
"""
import bpy, math, os
from mathutils import Vector

MODELS = "/Users/matejmonteleone/dev/cognitioflow/games/assets/cc0/models"
OUT    = os.environ.get("OUT", "/Users/matejmonteleone/dev/cognitioflow/games/assets/courtroom_cc0.glb")
PREVIEW_PNG = "/Users/matejmonteleone/dev/cognitioflow/games/assets/courtroom_cc0_preview.png"

bpy.ops.wm.read_factory_settings(use_empty=True)
C, D = bpy.context, bpy.data

# ---------- materials for architecture ----------
def mat(name, rgb, rough=.6, metal=0.0, emit=None, emit_str=2.0):
    m = D.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit is not None:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = emit_str
    return m

# ---- CJEU Grand Chamber palette: EU blue + gold anodized ceiling ----
NAVY   = mat("EUBlue", (.07,.13,.31), .8)              # CJEU blue walls
FLOOR  = mat("Floor",  (.09,.12,.22), .5, .05)         # blue-grey floor
STONE  = mat("Stone",  (.82,.82,.86), .7)              # pale columns / dais trim
MARBLE = mat("Marble", (.78,.76,.70), .35, .05)
BRASS  = mat("Gold",   (.84,.66,.30), .25, .95, emit=(.95,.75,.33), emit_str=.9)   # EU stars / trim
GLOW   = mat("Glow",   (1,.86,.52), .4, 0, emit=(1,.83,.46), emit_str=7)
CARPET = mat("Carpet", (.11,.22,.46), .95)             # EU-blue runner
GOLDMESH = mat("GoldMesh", (.82,.64,.28), .35, .9, emit=(.9,.70,.30), emit_str=1.5) # ceiling canopy
WOODPANEL = mat("EUPanel", (.09,.17,.46), .55)         # deep royal-blue emblem panel (EU flag field)
DAISMAT  = mat("DaisStone", (.24,.20,.16), .6)          # dark warm stone dais (not white)

def box(name, size, loc, m):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = C.active_object; o.name = name
    o.scale = (size[0]/2, size[1]/2, size[2]/2)
    bpy.ops.object.transform_apply(scale=True)
    o.data.materials.append(m); return o

def cyl(name, r, h, loc, m, verts=28):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=h, location=loc, vertices=verts)
    o = C.active_object; o.name = name; o.data.materials.append(m); return o

def star(name, cx, cy, cz, R, m, depth=.05):
    """A flat 5-point star in the X-Z plane (faces -Y, i.e. out from the back wall)."""
    verts=[]; n=5
    for i in range(2*n):
        ang=math.pi/2 + i*math.pi/n
        rr=R if i%2==0 else R*0.40
        verts.append((cx+rr*math.cos(ang), cy, cz+rr*math.sin(ang)))
    me=D.meshes.new(name); me.from_pydata(verts, [], [list(range(2*n))])
    o=D.objects.new(name, me); C.scene.collection.objects.link(o)
    o.data.materials.append(m)
    md=o.modifiers.new("Sol","SOLIDIFY"); md.thickness=depth
    return o

# ---------- CC0 model loader ----------
def load_model(rel, want=None, exclude=()):
    """Append mesh objects from a .blend, join into one object, return it."""
    path = os.path.join(MODELS, rel)
    with D.libraries.load(path, link=False) as (src, dst):
        names = [n for n in src.objects
                 if (want is None or n in want) and not any(e in n for e in exclude)]
        dst.objects = names
    meshes = []
    for o in dst.objects:
        if o is None: continue
        C.scene.collection.objects.link(o)
        if o.type == 'MESH':
            meshes.append(o)
    if not meshes:
        return None
    for o in C.selected_objects: o.select_set(False)
    for o in meshes: o.select_set(True)
    C.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = C.active_object
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    return obj

def world_bbox(o):
    C.view_layer.update()
    cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
    mn = Vector((min(c.x for c in cs), min(c.y for c in cs), min(c.z for c in cs)))
    mx = Vector((max(c.x for c in cs), max(c.y for c in cs), max(c.z for c in cs)))
    return mn, mx

def place(obj, name, loc_xy, base_z=0.0, target_h=None, rot_z=0.0):
    """Scale to target height (by Z extent), rotate about Z, seat base at base_z,
    centre on loc_xy."""
    if obj is None: return None
    obj.name = name
    obj.rotation_euler = (0, 0, rot_z)
    C.view_layer.update()
    mn, mx = world_bbox(obj)
    h = max(1e-4, mx.z - mn.z)
    if target_h:
        s = target_h / h
        obj.scale = (obj.scale[0]*s, obj.scale[1]*s, obj.scale[2]*s)
        C.view_layer.update()
        mn, mx = world_bbox(obj)
    cx = (mn.x + mx.x)/2; cy = (mn.y + mx.y)/2
    obj.location.x += loc_xy[0] - cx
    obj.location.y += loc_xy[1] - cy
    obj.location.z += base_z - mn.z
    return obj

# ---------- room shell ----------
RX, RYb, RYf, RZ = 7.0, -10.0, 8.0, 6.2          # half-width, back Y, front Y, height
box("Floor",   (2*RX, RYf-RYb, .3), (0, (RYb+RYf)/2, -.15), FLOOR)
box("Ceiling", (2*RX, RYf-RYb, .3), (0, (RYb+RYf)/2, RZ+.15), NAVY)
box("BackWall",(2*RX, .4, RZ),      (0, RYb-.2, RZ/2), NAVY)
box("FrontWall",(2*RX,.4, RZ),      (0, RYf+.2, RZ/2), NAVY)
box("LWall",   (.4, RYf-RYb, RZ),   (-RX-.2, (RYb+RYf)/2, RZ/2), NAVY)
box("RWall",   (.4, RYf-RYb, RZ),   ( RX+.2, (RYb+RYf)/2, RZ/2), NAVY)
box("Runner",  (2.2, RYf-RYb-1, .02),(0, (RYb+RYf)/2, .01), CARPET)

# ---- gold anodized ceiling canopy (the CJEU signature) ----
for i in range(13):                                   # gold slats running front-to-back
    gx = -6 + i*1.0
    box(f"Canopy_{i}", (.10, RYf-RYb-1.4, .12), (gx, (RYb+RYf)/2, RZ-.25), GOLDMESH)
for i in range(4):                                    # warm light strips embedded in the canopy
    gy = -7 + i*4.2
    box(f"CeilLight_{i}", (2*RX-2.2, .45, .05), (0, gy, RZ-.42), GLOW)

# ---------- judge's dais + emblem ----------
box("Dais",    (9, 3.6, .55), (0, -7.6, .275), DAISMAT)
box("DaisStep",(11, .6, .28), (0, -5.9, .14),  DAISMAT)
# a walnut feature wall behind the bench, framing the emblem (stops the back wall blowing out white)
box("BackPanel", (6.4, .18, 4.6), (0, RYb+.12, 4.1), WOODPANEL)
box("PanelTrim", (6.9, .10, .18), (0, RYb+.06, 6.5), BRASS)   # a gold rail across the top
# EU emblem: circle of 12 gold stars on the walnut panel (the Union flag)
for k in range(12):
    ang = math.pi/2 + k*(2*math.pi/12)
    sx = 1.35*math.cos(ang); sz = 4.3 + 1.35*math.sin(ang)
    star(f"Star_{k}", sx, RYb+.30, sz, .24, BRASS)

# ---------- columns flanking the dais ----------
for x in (-5.6, 5.6):
    for y in (-9.2, -5.2):
        cyl(f"Col_{x}_{y}", .35, RZ, (x, y, RZ/2), MARBLE)
        box(f"Cap_{x}_{y}", (1.0,1.0,.35), (x, y, RZ-.1), BRASS)

# ---------- sconces (emissive; real lights live in-engine) ----------
for x in (-RX+.3, RX-.3):
    for y in (-8, -2, 4):
        box(f"Sconce_{x}_{y}", (.12,.4,.9), (x, y, 3.4), GLOW)

# ======================================================================
#  REAL CC0 FURNITURE
# ======================================================================
DAIS_TOP = .55

# Judge's bench — the ornate classic console, wide and imposing, centred on the dais
bench = load_model("ClassicConsole_01/ClassicConsole_01_1k.blend")
place(bench, "JudgeBench", (0, -7.9), base_z=DAIS_TOP, target_h=1.15, rot_z=0)
# scale it wider on X so it reads as a long bench
bench.scale.x *= 1.9; C.view_layer.update()
# Judge's chair, behind the bench on the dais
jchair = load_model("WoodenChair_01/WoodenChair_01_1k.blend")
place(jchair, "JudgeChair", (0, -8.8), base_z=DAIS_TOP, target_h=1.2, rot_z=0)

# Gothic cabinets flanking the back wall for grandeur
for s,nm in ((-1,"CabinetL"),(1,"CabinetR")):
    cab = load_model("GothicCabinet_01/GothicCabinet_01_1k.blend")
    place(cab, nm, (s*4.6, -9.1), base_z=0, target_h=2.4, rot_z=0)

# Clerk's desk — wooden table in front of the dais, set to one side to keep the aisle clear
clerk = load_model("WoodenTable_02/WoodenTable_02_1k.blend")
place(clerk, "ClerkDesk", (-2.4, -4.9), base_z=0, target_h=.78, rot_z=math.pi)

# Two counsel tables (wooden table), left = Claimant, right = Respondent
for i,(x,nm) in enumerate(((-3.1,"ClaimantTable"),(3.1,"RespondentTable"))):
    t = load_model("WoodenTable_02/WoodenTable_02_1k.blend")
    place(t, nm, (x, -1.2), base_z=0, target_h=.78, rot_z=0)
    ch = load_model("WoodenChair_01/WoodenChair_01_1k.blend")
    place(ch, nm+"Chair", (x, -.2), base_z=0, target_h=1.0, rot_z=math.pi)

# Witness box — console + chair, right of the bench
wbox = load_model("ClassicConsole_01/ClassicConsole_01_1k.blend")
place(wbox, "WitnessBox", (4.6, -5.4), base_z=0, target_h=1.05, rot_z=-math.pi/2)
wch = load_model("WoodenChair_01/WoodenChair_01_1k.blend")
place(wch, "WitnessChair", (5.4, -5.4), base_z=0, target_h=1.0, rot_z=-math.pi/2)

# Gallery — rows of chairs near the player entrance (+Y)
for r in range(2):
    y = 4.6 + r*1.4
    for c in range(5):
        x = -4.0 + c*2.0
        ch = load_model("WoodenChair_01/WoodenChair_01_1k.blend")
        place(ch, f"Gallery_{r}_{c}", (x, y), base_z=0, target_h=1.0, rot_z=0)

# Books as dressing on tables
for nm,(x,y,z) in (("BooksClaimant",(-3.1,-1.2,.78)),
                   ("BooksRespondent",(3.1,-1.2,.78)),
                   ("BooksBench",(1.1,-7.9,DAIS_TOP+1.15))):
    bk = load_model("book_encyclopedia_set_01/book_encyclopedia_set_01_1k.blend", exclude=("stash",))
    place(bk, nm, (x, y), base_z=z, target_h=.22, rot_z=0)

# ---------- export GLB ----------
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB', export_apply=True,
                          export_yup=True, use_selection=False)
print("EXPORTED", OUT)

# ---------- optional preview ----------
if os.environ.get("PREVIEW") == "1":
    sc = C.scene
    sc.world = D.worlds.new("W"); sc.world.use_nodes = True
    bgn = sc.world.node_tree.nodes["Background"]
    bgn.inputs[0].default_value = (0.02,0.03,0.06,1); bgn.inputs[1].default_value = .35
    tgt = D.objects.new("Tgt", None); tgt.location=(0,-5.5,1.6); sc.collection.objects.link(tgt)
    cam_d = D.cameras.new("Cam"); cam = D.objects.new("Cam", cam_d); sc.collection.objects.link(cam)
    cam.location=(0, 6.5, 2.0); cam_d.lens=26; sc.camera=cam
    con = cam.constraints.new('TRACK_TO'); con.target=tgt; con.track_axis='TRACK_NEGATIVE_Z'; con.up_axis='UP_Y'
    def L(kind, loc, e, col=(1,1,1), size=6, tgtobj=None):
        l = D.lights.new("L", kind); l.energy=e; l.color=col
        if kind=='AREA': l.size=size
        if kind=='SPOT': l.spot_size=math.radians(110); l.spot_blend=.5
        o = D.objects.new("L", l); o.location=loc; sc.collection.objects.link(o)
        if kind in ('SPOT','SUN') and tgtobj is not None:
            cc=o.constraints.new('TRACK_TO'); cc.target=tgtobj; cc.track_axis='TRACK_NEGATIVE_Z'; cc.up_axis='UP_Y'
        return o
    L('SPOT',(0,2,5.8),9000,(1,.93,.82),tgtobj=tgt)
    L('AREA',(-5,0,4),500,(1,.55,.3))
    L('AREA',(5,2,4),600,(.5,.62,1))
    L('AREA',(0,6,5),300,(.8,.85,1),size=14)
    L('SPOT',(0,-6,5.5),2200,(1,.86,.6),tgtobj=tgt)
    eng=[e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
    sc.render.engine='BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in eng else ('BLENDER_EEVEE' if 'BLENDER_EEVEE' in eng else sc.render.engine)
    try: sc.view_settings.look='AgX - Medium High Contrast'
    except Exception: pass
    sc.render.resolution_x=1280; sc.render.resolution_y=720
    sc.render.filepath=PREVIEW_PNG
    bpy.ops.render.render(write_still=True)
    print("RENDERED", PREVIEW_PNG)
    if os.environ.get("TURNTABLE") == "1":
        S="/private/tmp/claude-501/-Users-matejmonteleone/052b845d-a675-4d85-845b-11d5c7a196bf/scratchpad/"
        sc.render.resolution_x=800; sc.render.resolution_y=560
        tgt.location=(0,-4,1.3)
        for nm,loc in (("A_frontright",(6.2,6,4.6)),("B_leftlow",(-6.2,1.5,1.5)),("C_behindbench",(2.6,-9.2,3.2))):
            cam.location=loc; sc.render.filepath=S+"tt_"+nm+".png"
            bpy.ops.render.render(write_still=True); print("TT", nm)
