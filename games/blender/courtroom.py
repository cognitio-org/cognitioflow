"""Headless Blender: model a stylized cinematic courtroom and export glTF.
Run: /Applications/Blender.app/Contents/MacOS/Blender --background --python courtroom.py
Geometry + materials only; cinematic lighting + post happen in PlayCanvas. Stylized, clean, dramatic."""
import bpy, math, os

# ---- clean slate ----
bpy.ops.wm.read_factory_settings(use_empty=True)
C, D = bpy.context, bpy.data

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

WOOD   = mat("Wood",   (.20,.11,.06), .55)
DARK   = mat("DarkWood",(.10,.06,.04), .5)
STONE  = mat("Stone",  (.46,.46,.52), .8)
MARBLE = mat("Marble", (.72,.72,.80), .35, .1)
FLOOR  = mat("Floor",  (.08,.09,.14), .35, .3)
BRASS  = mat("Brass",  (.78,.56,.22), .3, .9, emit=(.9,.65,.25), emit_str=1.2)
FELT   = mat("Felt",   (.30,.10,.14), .9)
GLOW   = mat("Glow",   (1,.78,.33), .4, 0, emit=(1,.75,.3), emit_str=5)

def box(name, size, loc, m):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = C.active_object; o.name = name; o.scale = (size[0]/2, size[1]/2, size[2]/2)
    bpy.ops.object.transform_apply(scale=True)
    o.data.materials.append(m); return o

def cyl(name, r, h, loc, m, verts=24):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=h, location=loc, vertices=verts)
    o = C.active_object; o.name = name; o.data.materials.append(m); return o

# ---- room shell ----
box("Floor", (26,22,.3), (0,0,-.15), FLOOR)
box("BackWall", (26,.6,14), (0,-10.5,7), STONE)
box("LWall", (.6,22,14), (-12.7,0,7), STONE)
box("RWall", (.6,22,14), (12.7,0,7), STONE)
box("Ceiling",(26,22,.4),(0,0,13.8), DARK)

# ---- judge's dais + bench (raised, back-center) ----
box("Dais", (10,4,1.4), (0,-7.5,.7), DARK)
box("Bench", (8,2.4,2.6), (0,-7.2,2.3), WOOD)
box("BenchTop",(8.6,2.9,.3),(0,-7.0,3.7), BRASS)
box("JudgeChair",(1.4,1.2,2.4),(0,-8.4,3.0), FELT)

# ---- grand emblem arch behind the bench ----
bpy.ops.mesh.primitive_torus_add(location=(0,-10.1,8.5), major_radius=3.2, minor_radius=.35,
    major_segments=48, minor_segments=14)
a = C.active_object; a.name="Arch"; a.rotation_euler=(math.pi/2,0,0)
bpy.ops.object.transform_apply(rotation=True); a.data.materials.append(BRASS)
cyl("Scale_Stem", .08, 2.2, (0,-10.0,7.0), BRASS)
box("Scale_Bar", (2.6,.12,.12), (0,-10.0,8.0), BRASS)
for s in (-1,1):
    bpy.ops.mesh.primitive_torus_add(location=(s*1.25,-10.0,7.3), major_radius=.5, minor_radius=.06,
        major_segments=24, minor_segments=8)
    p=C.active_object; p.rotation_euler=(math.pi/2,0,0); bpy.ops.object.transform_apply(rotation=True); p.data.materials.append(BRASS)

# ---- columns flanking the dais ----
for x in (-9.5, 9.5):
    for y in (-9.5, -4):
        cyl(f"Col_{x}_{y}", .55, 13, (x, y, 6.5), MARBLE)
        box(f"Cap_{x}_{y}", (1.5,1.5,.5), (x,y,13), BRASS)

# ---- witness stand (right of bench) ----
box("WitnessBase",(2.6,2.2,1.4),(5.6,-5.4,.7), DARK)
box("WitnessRail",(2.6,.2,1.3),(5.6,-4.4,2.0), WOOD)
box("WitnessChair",(1.1,1.0,1.8),(5.6,-6.0,1.9), FELT)

# ---- two counsel tables (foreground) ----
for i,x in enumerate((-4.2, 4.2)):
    box(f"Desk{i}",(4.2,1.8,.3),(x,3.5,2.2), WOOD)
    for lx in (-1.8,1.8):
        for ly in (-.7,.7):
            cyl(f"Leg{i}_{lx}_{ly}", .12, 2.2, (x+lx, 3.5+ly, 1.1), DARK)

# ---- gallery benches (far foreground) ----
for row in range(3):
    y = 6.5 + row*1.6
    box(f"Gallery{row}", (16,1.1,.9), (0, y, .45), WOOD)
    box(f"GalleryBack{row}", (16,.2,1.4), (0, y-.5, 1.3), WOOD)

# ---- subtle emissive sconces for grounding (real lights added in PlayCanvas) ----
for x in (-8,8):
    for y in (-9,0,8):
        box(f"Sconce_{x}_{y}", (.3,.3,1.2), (x if x<0 else x, y, 5), GLOW)

# ---- export ----
out = os.path.join(os.path.dirname(bpy.data.filepath) or os.getcwd(),
                   os.environ.get("OUT","/Users/matejmonteleone/dev/cognitioflow/games/assets/courtroom.glb"))
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_apply=True,
                          export_yup=True, use_selection=False)
print("EXPORTED", out)

# ---- optional preview render (PREVIEW=1), in original Z-up coords, auto-aimed ----
if os.environ.get("PREVIEW")=="1":
    sc=bpy.context.scene
    sc.world=bpy.data.worlds.new("W"); sc.world.use_nodes=True
    sc.world.node_tree.nodes["Background"].inputs[0].default_value=(0.03,0.04,0.09,1)
    sc.world.node_tree.nodes["Background"].inputs[1].default_value=0.6
    tgt=bpy.data.objects.new("Tgt",None); tgt.location=(0,-6.5,4.0); sc.collection.objects.link(tgt)
    cam_d=bpy.data.cameras.new("Cam"); cam=bpy.data.objects.new("Cam",cam_d); sc.collection.objects.link(cam)
    cam.location=(1.0,11.5,5.2); cam_d.lens=32; sc.camera=cam
    con=cam.constraints.new('TRACK_TO'); con.target=tgt; con.track_axis='TRACK_NEGATIVE_Z'; con.up_axis='UP_Y'
    def L(kind,loc,e,c=(1,1,1),size=7):
        l=bpy.data.lights.new("L",kind); l.energy=e; l.color=c
        if kind=='AREA': l.size=size
        if kind=='SPOT': l.spot_size=math.radians(100); l.spot_blend=.6
        o=bpy.data.objects.new("L",l); o.location=loc; sc.collection.objects.link(o)
        if kind in('SPOT','SUN'):
            t=cam.constraints and None
            c2=o.constraints.new('TRACK_TO'); c2.target=tgt; c2.track_axis='TRACK_NEGATIVE_Z'; c2.up_axis='UP_Y'
        return o
    L('SPOT',(0,3,12.8),12000,(1,.93,.82))
    L('AREA',(-10,2,7),1200,(1,.5,.28))
    L('AREA',(10,4,7),1300,(.42,.6,1))
    L('AREA',(0,11,9),700,(.75,.82,1),size=18)
    L('SPOT',(0,-6,12),2500,(1,.85,.6))
    eng=[e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
    sc.render.engine='BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in eng else ('BLENDER_EEVEE' if 'BLENDER_EEVEE' in eng else sc.render.engine)
    try: sc.view_settings.look='AgX - Medium High Contrast'
    except Exception: pass
    sc.render.resolution_x=1280; sc.render.resolution_y=720
    sc.render.filepath="/Users/matejmonteleone/dev/cognitioflow/games/assets/courtroom_preview.png"
    bpy.ops.render.render(write_still=True)
    print("RENDERED", sc.render.filepath)
