# sm and Group are provided by the editor.
objects = {
    "display": Group({
        "base": sm.create_box((-10, -8, -2), 20, 16, 2),
        "core": sm.create_sphere((0, 0, 5), 4),
        "cover": sm.create_box((-7, -6, 0), 14, 12, 12),
    }, material={"baseColor": [0.2, 0.6, 0.9], "roughness": 0.25, "opacity": 0.25}),
}
materials = {
    "core": {"baseColor": [1, 0.25, 0.05], "metallic": 0.2, "roughness": 0.35},
    "base": {"baseColor": [0.3, 0.35, 0.4], "metallic": 0.6, "roughness": 0.4},
}
