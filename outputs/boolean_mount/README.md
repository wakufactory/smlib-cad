# Boolean mount GLB samples

The source model is a 48 x 32 x 6 box plate united with a sphere (radius 8),
then cut by four cylindrical bolt holes (radius 2.5) and one central through
bore (radius 3). All four GLBs come from the same BRep; only the tessellation
tolerances change. Coordinates in the source are Z up; the GLBs are Y up.

| Chord tolerance | Angle tolerance | Triangles | GLB |
| ---: | ---: | ---: | --- |
| 1.5 | 45° | 458 | `boolean_mount_chord_1p5_angle_45.glb` |
| 0.5 | 30° | 512 | `boolean_mount_chord_0p5_angle_30.glb` |
| 0.1 | 15° | 1,248 | `boolean_mount_chord_0p1_angle_15.glb` |
| 0.02 | 7.5° | 3,616 | `boolean_mount_chord_0p02_angle_7p5.glb` |

From the workspace root, regenerate with:

```sh
make
PYTHONPATH=.build/smlib-core:. .packman-cache/python/3.12.14-macos-aarch64/bin/python3.12 examples/export_boolean_mount.py
```

The exact output sizes and triangle counts are also recorded in `manifest.json`.
