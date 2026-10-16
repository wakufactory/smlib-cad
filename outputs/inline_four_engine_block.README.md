# Inline-four engine block CSG sample

`examples/inline_four_engine_block.json` is an editable `smlib-model` document in
`text` mode. It describes a stylized four-cylinder engine block in consistent,
arbitrary millimetre-like units. The main block is built with unions, then cut
with four cylinder bores, a longitudinal crankshaft tunnel, eight head-stud
wells, four side ports, and four flange mounting holes. A separate annular end
cover and stepped crank nose use contrasting PBR materials.

Regenerate from the workspace root:

```sh
make glb MODEL=examples/inline_four_engine_block.json GLB=outputs/inline_four_engine_block.glb
```

The output is glTF 2.0 binary. The JSON's source coordinates are Z-up; the GLB
is Y-up. With chord tolerance 0.18 and angle tolerance 18°, the generated file
contains four meshes, three materials, and 3,936 triangles. This is a visual
CSG example, not a dimensioned engine design.
