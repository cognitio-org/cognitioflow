import bpy, math, os
bpy.ops.wm.read_factory_settings(use_empty=True)
glb=os.environ.get("GLB","/Users/matejmonteleone/dev/cognitioflow/games/assets/courtroom.glb")
bpy.ops.import_scene.gltf(filepath=glb)
sc=bpy.context.scene

# world: deep blue ambient so empties aren't dead black
sc.world=bpy.data.worlds.new("W"); sc.world.use_nodes=True
sc.world.node_tree.nodes["Background"].inputs[0].default_value=(0.02,0.03,0.07,1)
sc.world.node_tree.nodes["Background"].inputs[1].default_value=0.5

# camera: front-on from the gallery, looking at the bench + arch
cam_d=bpy.data.cameras.new("Cam"); cam=bpy.data.objects.new("Cam",cam_d); sc.collection.objects.link(cam)
cam.location=(0.5,12.5,5.0); cam.rotation_euler=(math.radians(82),0,0); cam_d.lens=34
sc.camera=cam

def light(kind,loc,energy,color=(1,1,1),size=6,rot=(0,0,0)):
    l=bpy.data.lights.new("L",kind); l.energy=energy; l.color=color
    if kind=='AREA': l.size=size
    if kind=='SPOT': l.spot_size=math.radians(90); l.spot_blend=.6
    o=bpy.data.objects.new("L",l); o.location=loc; o.rotation_euler=rot; sc.collection.objects.link(o); return o
light('SPOT',(0,-2,12.5),9000,(1,.93,.82),rot=(math.radians(8),0,0))   # key on the bench
light('AREA',(-9,4,7),900,(1,.55,.3),size=8)                            # warm rim L
light('AREA',(9,5,7),950,(.4,.6,1),size=8)                              # cool rim R
light('AREA',(0,11,8),500,(.7,.8,1),size=16)                           # soft front fill
light('AREA',(0,-8,12),700,(1,.85,.6),size=10)                        # arch uplight

eng=[e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
sc.render.engine='BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in eng else ('BLENDER_EEVEE' if 'BLENDER_EEVEE' in eng else sc.render.engine)
try: sc.view_settings.look='AgX - Medium High Contrast'
except Exception:
    try: sc.view_settings.look='Medium High Contrast'
    except Exception: pass
sc.render.resolution_x=1280; sc.render.resolution_y=720
sc.render.filepath=os.environ.get("PNG","/Users/matejmonteleone/dev/cognitioflow/games/assets/courtroom_preview.png")
bpy.ops.render.render(write_still=True)
print("RENDERED", sc.render.filepath)
