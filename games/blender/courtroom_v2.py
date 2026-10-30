"""Headless Blender: a purpose-built courtroom (no kitbashed furniture).

Builds the RECOGNISABLE anatomy of a court — panelled walls with wainscoting, a raised
panelled judge's bench with a reredos + EU emblem, counsel tables, a witness box, a clerk's
desk, a lectern, the bar rail, and rows of public gallery pews — from clean primitives with
dignified materials (oak, walnut, oxblood leather, EU blue, brass). Exports GLB for three.js.

Coords: Blender Z-up, metres. Bench at back (-Y), entrance/gallery at front (+Y). export_yup
maps Blender +Y -> glTF -Z, so in-engine the bench is at +Z and the entrance at -Z (unchanged
from the games' existing player convention).

Run: /Applications/Blender.app/Contents/MacOS/Blender --background --python courtroom_v2.py
     PREVIEW=1 ... also renders courtroom_v2_preview.png
"""
import bpy, math, os
from mathutils import Vector

OUT = os.environ.get("OUT", "/Users/matejmonteleone/dev/cognitioflow/games/assets/courtroom_cc0.glb")
PREVIEW_PNG = "/Users/matejmonteleone/dev/cognitioflow/games/assets/courtroom_v2_preview.png"

bpy.ops.wm.read_factory_settings(use_empty=True)
C, D = bpy.context, bpy.data

# ---------------- materials ----------------
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

OAK     = mat("Oak",     (.38,.26,.14), .55)     # wainscoting, pews, tables, bench body
WALNUT  = mat("Walnut",  (.17,.10,.05), .45)     # trim, rails, panel frames, bench front
WALLUP  = mat("WallUp",  (.17,.25,.47), .8)      # muted EU-blue upper walls
CEIL    = mat("Ceiling", (.80,.79,.74), .85)     # warm plaster ceiling
CARPET  = mat("Carpet",  (.11,.16,.34), .95)     # deep blue carpet
RUNNER  = mat("Runner",  (.33,.09,.11), .95)     # oxblood central aisle runner
LEATHER = mat("Leather", (.30,.07,.09), .5)      # oxblood desk tops / seat pads
BRASS   = mat("Brass",   (.83,.63,.28), .3, .9, emit=(.9,.68,.3), emit_str=.6)
STONE   = mat("Stone",   (.80,.78,.72), .7)      # pilaster caps/bases
GLOWM   = mat("Glow",    (1,.93,.72), .4, 0, emit=(1,.92,.72), emit_str=5)
EUFIELD = mat("EUField", (.09,.16,.45), .55)     # emblem panel (flag field)

def box(name, size, loc, m):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = C.active_object; o.name = name
    o.scale = (size[0]/2, size[1]/2, size[2]/2)
    bpy.ops.object.transform_apply(scale=True)
    o.data.materials.append(m); return o

def star(name, cx, cy, cz, R, m, depth=.05):
    verts = []; n = 5
    for i in range(2*n):
        a = math.pi/2 + i*math.pi/n
        rr = R if i % 2 == 0 else R*0.40
        verts.append((cx+rr*math.cos(a), cy, cz+rr*math.sin(a)))
    me = D.meshes.new(name); me.from_pydata(verts, [], [list(range(2*n))])
    o = D.objects.new(name, me); C.scene.collection.objects.link(o)
    o.data.materials.append(m)
    o.modifiers.new("s", "SOLIDIFY").thickness = depth
    return o

# ---------------- room envelope ----------------
RX, YB, YF, RZ = 6.0, -10.0, 10.0, 5.6
WAINS = 1.35                                   # wainscoting height
box("Floor",   (2*RX, YF-YB, .25), (0, (YB+YF)/2, -.125), CARPET)
box("Ceiling", (2*RX, YF-YB, .3),  (0, (YB+YF)/2, RZ+.15), CEIL)
# central aisle runner (bench->entrance)
box("Runner",  (1.8, YF-YB-1.0, .03), (0, (YB+YF)/2, .02), RUNNER)

def panelled_wall(name, length, centre, horiz, side):
    """A wall as wainscoting (oak) + chair rail + blue upper, with pilasters.
    horiz True -> wall runs along X at y=centre; else along Y at x=centre. side = inward normal sign."""
    if horiz:   # back/front wall, spans X
        cx, cy = 0, centre
        box(f"{name}_up",  (length, .3, RZ-WAINS), (cx, cy, WAINS+(RZ-WAINS)/2), WALLUP)
        box(f"{name}_wns", (length, .34, WAINS),   (cx, cy-side*.02, WAINS/2),  OAK)
        box(f"{name}_rail",(length, .40, .10),     (cx, cy-side*.03, WAINS),    WALNUT)
        box(f"{name}_base",(length, .40, .12),     (cx, cy-side*.03, .06),      WALNUT)
        n = int(length//2.0)
        for i in range(n+1):
            x = -length/2 + i*(length/(n if n else 1))
            box(f"{name}_pil{i}", (.28,.18,RZ), (x, cy-side*.06, RZ/2), OAK)
    else:       # side wall, spans Y
        cx, cy = centre, 0
        box(f"{name}_up",  (.3, YF-YB, RZ-WAINS), (cx, cy, WAINS+(RZ-WAINS)/2), WALLUP)
        box(f"{name}_wns", (.34, YF-YB, WAINS),   (cx-side*.02, cy, WAINS/2),  OAK)
        box(f"{name}_rail",(.40, YF-YB, .10),     (cx-side*.03, cy, WAINS),    WALNUT)
        box(f"{name}_base",(.40, YF-YB, .12),     (cx-side*.03, cy, .06),      WALNUT)
        n = int((YF-YB)//2.2)
        for i in range(n+1):
            y = YB + i*((YF-YB)/(n if n else 1))
            box(f"{name}_pil{i}", (.18,.28,RZ), (cx-side*.06, y, RZ/2), OAK)

panelled_wall("BackWall",  2*RX, YB, True,  +1)
panelled_wall("FrontWall", 2*RX, YF, True,  -1)
panelled_wall("LW", 0, -RX-.15, False, +1)   # length ignored for side walls (spans YF-YB)
panelled_wall("RW", 0,  RX+.15, False, -1)

# ---------------- reredos (tall panelled wall behind the bench) + EU emblem ----------------
box("Reredos",   (7.6, .28, 4.6), (0, YB+.5, 2.3), OAK)
box("ReredosTrim",(8.0, .20, .14),(0, YB+.42, 4.55), WALNUT)
for sx in (-3.4, 3.4):
    box(f"Rered_col{sx}", (.34,.30,4.4), (sx, YB+.46, 2.2), WALNUT)
# EU emblem: gold stars on a blue field, centred on the reredos
box("EmblemField", (2.9, .10, 2.0), (0, YB+.66, 2.9), EUFIELD)
box("EmblemFrame", (3.2, .08, .10), (0, YB+.62, 3.95), BRASS)
box("EmblemFrameB",(3.2, .08, .10), (0, YB+.62, 1.85), BRASS)
for k in range(12):
    a = math.pi/2 + k*(2*math.pi/12)
    sx = 0.95*math.cos(a); sz = 2.9 + 0.62*math.sin(a)
    star(f"Star{k}", sx, YB+.72, sz, .17, BRASS)

# ---------------- raised judge's bench ----------------
box("Dais1", (10.5, 3.2, .45), (0, -7.9, .225), OAK)      # lower platform
box("Dais2", (8.6, 2.2, .35),  (0, -8.3, .45+.175), OAK)  # upper platform
# the bench desk: panelled front + top + returns, elevated on the dais
BY = -7.7; BTOP = .45+1.12
box("BenchFront", (7.4, .55, 1.12), (0, BY, .45+.56), WALNUT)
# raised panel insets on the bench front
for i,px in enumerate((-2.4,-0.8,0.8,2.4)):
    box(f"BenchPanel{i}", (1.25,.12,.74), (px, BY-.30, .45+.56), OAK)
box("BenchTop",   (7.9, 1.05, .12), (0, BY-.25, BTOP), WALNUT)
box("BenchDesk",  (7.0, .80, .04),  (0, BY-.45, BTOP+.02), LEATHER)
# three judges' high-back chairs behind the bench
for cx in (-2.2, 0, 2.2):
    box(f"JSeat{cx}", (.78,.70,.10), (cx, -8.55, .45+.62), LEATHER)
    box(f"JBack{cx}", (.84,.14,1.5), (cx, -8.9, .45+1.2), WALNUT)
    box(f"JArmL{cx}", (.10,.66,.40), (cx-.40,-8.55,.45+.92), WALNUT)
    box(f"JArmR{cx}", (.10,.66,.40), (cx+.40,-8.55,.45+.92), WALNUT)

# ---------------- clerk's desk (low, centre, in front of the bench) ----------------
box("ClerkDesk", (3.2, 1.1, .78), (0, -6.0, .39), OAK)
box("ClerkTop",  (3.4, 1.3, .06), (0, -6.0, .80), LEATHER)

# ---------------- witness box (raised, right of the bench) ----------------
box("WitFloor", (1.7,1.7,.30), (3.3,-6.6,.15), OAK)
for (dx,dy,sx,sy) in [(-.8,0,.14,1.7),(.8,0,.14,1.7),(0,-.8,1.7,.14),(0,.8,1.7,.14)]:
    box(f"WitRail{dx}{dy}", (sx,sy,.95), (3.3+dx,-6.6+dy,.30+.47), WALNUT)
box("WitCap", (1.8,1.8,.08), (3.3,-6.6,.30+.95), OAK)
box("WitSeat",(.7,.6,.08), (3.3,-6.9,.30+.45), LEATHER)

# ---------------- counsel tables (facing the bench) + chairs ----------------
def counsel(name, x):
    box(f"{name}Top",  (3.0,1.1,.08), (x,-4.0,.78), LEATHER)
    box(f"{name}Mod",  (3.0,.08,.70), (x,-3.45,.40), OAK)   # modesty panel (gallery side)
    for ex in (-1.4,1.4):
        box(f"{name}End{ex}", (.08,1.0,.78), (x+ex,-4.0,.39), OAK)
    for cx in (-0.8,0.8):
        box(f"{name}CS{cx}", (.52,.5,.08), (x+cx,-3.3,.48), LEATHER)
        box(f"{name}CB{cx}", (.56,.08,.9), (x+cx,-3.08,.9), OAK)
        for lx in (-.22,.22):
            for ly in (-.22,.22):
                box(f"{name}L{cx}{lx}{ly}", (.06,.06,.48),(x+cx+lx,-3.3+ly,.24),WALNUT)
counsel("Claimant", -2.3)
counsel("Respondent", 2.3)

# ---------------- lectern / rostrum (centre of the well) ----------------
box("LectBase", (.7,.7,.95), (0,-2.6,.475), WALNUT)
box("LectTop",  (.85,.6,.08),(0,-2.6,1.0), OAK)
box("LectSlope",(.8,.5,.04), (0,-2.75,1.06), WALNUT)

# ---------------- the bar (railing separating the well from the gallery) ----------------
box("BarRailL", (4.2,.10,.12), (-2.9,-1.4,1.0), WALNUT)
box("BarRailR", (4.2,.10,.12), ( 2.9,-1.4,1.0), WALNUT)
for bx in (-5.0,-0.9,0.9,5.0):
    box(f"BarPost{bx}", (.12,.12,1.0), (bx,-1.4,.5), WALNUT)
for bx in (-4.0,-3.0,-2.0,2.0,3.0,4.0):
    box(f"BarBaluster{bx}", (.06,.06,.9), (bx,-1.4,.5), OAK)

# ---------------- public gallery: rows of pews facing the bench ----------------
def pew(name, x, w, y):
    box(f"{name}seat", (w,.42,.08), (x,y,.48), OAK)
    box(f"{name}back", (w,.10,.55), (x,y+.30,.72), OAK)
    box(f"{name}pad",  (w-.1,.38,.04),(x,y,.53), LEATHER)
    for ex in (-w/2+.05, w/2-.05):
        box(f"{name}end{ex:.1f}", (.08,.7,.95),(x+ex,y,.48), OAK)
for r in range(5):
    y = 0.4 + r*1.5
    pew(f"GalL{r}", -2.5, 4.4, y)
    pew(f"GalR{r}",  2.5, 4.4, y)

# ---------------- pilaster caps + sconces + ceiling coffers/lights ----------------
for x in (-RX+.2, RX-.2):
    for y in (-8,-4,0,4,8):
        box(f"Sconce{x}_{y}", (.1,.3,.5), (x, y, 3.0), GLOWM)
# coffered ceiling beams + recessed light strips
for i in range(7):
    x = -RX+1 + i*((2*RX-2)/6)
    box(f"Beam{i}", (.2,YF-YB,.18), (x,(YB+YF)/2,RZ-.1), OAK)
for j in range(5):
    y = -7 + j*3.5
    box(f"CeilLight{j}", (2*RX-2.4,.5,.06), (0,y,RZ-.08), GLOWM)

# ---------------- export ----------------
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB', export_apply=True,
                          export_yup=True, use_selection=False)
print("EXPORTED", OUT)

# ---------------- preview ----------------
if os.environ.get("PREVIEW") == "1":
    sc = C.scene
    sc.world = D.worlds.new("W"); sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes["Background"]; bg.inputs[0].default_value=(.04,.05,.09,1); bg.inputs[1].default_value=.4
    tgt = D.objects.new("T", None); tgt.location=(0,-5.5,1.3); sc.collection.objects.link(tgt)
    cam_d = D.cameras.new("C"); cam = D.objects.new("C", cam_d); sc.collection.objects.link(cam)
    cam.location=(4.6,6.8,3.9); cam_d.lens=20; sc.camera=cam
    con=cam.constraints.new('TRACK_TO'); con.target=tgt; con.track_axis='TRACK_NEGATIVE_Z'; con.up_axis='UP_Z'
    def L(kind,loc,e,c=(1,1,1),sz=6,t=None):
        l=D.lights.new("L",kind); l.energy=e; l.color=c
        if kind=='AREA': l.size=sz
        if kind=='SPOT': l.spot_size=math.radians(90); l.spot_blend=.5
        o=D.objects.new("L",l); o.location=loc; sc.collection.objects.link(o)
        if kind in('SPOT','SUN') and t:
            cc=o.constraints.new('TRACK_TO'); cc.target=t; cc.track_axis='TRACK_NEGATIVE_Z'; cc.up_axis='UP_Z'
        return o
    L('AREA',(0,2,5),400,(1,.96,.9),sz=10)
    L('SPOT',(0,-4,5.2),2500,(1,.95,.85),t=tgt)
    L('AREA',(-5,0,4),180,(1,.8,.6)); L('AREA',(5,0,4),180,(.7,.8,1))
    eng=[e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
    sc.render.engine='BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in eng else ('BLENDER_EEVEE' if 'BLENDER_EEVEE' in eng else sc.render.engine)
    try: sc.view_settings.look='AgX - Medium High Contrast'
    except Exception: pass
    sc.render.resolution_x=1280; sc.render.resolution_y=720; sc.render.filepath=PREVIEW_PNG
    bpy.ops.render.render(write_still=True); print("RENDERED", PREVIEW_PNG)
