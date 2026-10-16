# Primitive and material gallery

The source is `examples/all_primitives_materials.txt`. The GLB contains 15
separate nodes, meshes, and PBR materials. Each material is assigned to one
primitive, so colors and metallic/roughness values can be inspected separately
in a glTF viewer. The full numeric mapping and triangle counts are in
`manifest.json`.

| Row | Left to right |
| --- | --- |
| 1 | box, sphere, cylinder, cone, torus |
| 2 | pyramid, cylindrical_box, partial_sphere, partial_cone, partial_cylinder |
| 3 | partial_torus, ellipsoid, sphere_no_pole, plane, planar_circle |

The last two entries are surfaces without thickness. The GLB uses Y up; the
source model uses Z up. Regenerate it from the workspace root with:

```sh
PYTHONPATH=.build/smlib-core:. .packman-cache/python/3.12.14-macos-aarch64/bin/python3.12 examples/export_primitive_gallery.py
```
