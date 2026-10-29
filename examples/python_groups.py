# In the editor sm and Group are provided automatically.
# Outside the editor: import _smlib_core as sm; from modeler import Group
base = sm.create_box((-8, -6, 0), 16, 12, 2)
post = sm.create_cylinder((0, 0, 2), 2, 12)
cap = sm.create_sphere((0, 0, 14), 3)
objects = {
    "assembly": Group({
        "base": base,
        "mast": Group({"post": post, "cap": cap},
                      material={"baseColor": [0.8, 0.8, 0.85], "metallic": 0.8}),
    }, material={"baseColor": [0.2, 0.5, 0.8], "metallic": 0.4},
       euler=(0, 0, 25), position=(10, 0, 0)),
}
materials = {"cap": {"baseColor": [1, 0.3, 0.1], "roughness": 0.25}}
