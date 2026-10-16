"""Export the all-primitives material example to a reproducible GLB."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import _smlib_core as sm

from modeler import evaluate, tessellate, to_glb


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "all_primitives_materials.txt"
OUTPUT = ROOT / "outputs" / "primitive_gallery"


def main():
    source = SOURCE.read_text()
    objects, materials, _ = evaluate(source, "text", sm)
    meshes = tessellate(objects, sm, chord=0.08, angle=20, materials=materials)
    glb = to_glb(meshes)
    json_length = struct.unpack_from("<I", glb, 12)[0]
    doc = json.loads(glb[20:20 + json_length])
    if len(meshes) != 15 or len(doc["meshes"]) != 15 or len(doc["materials"]) != 15:
        raise ValueError("Expected 15 meshes and 15 distinct materials")
    items = []
    for mesh, gltf_mesh in zip(meshes, doc["meshes"]):
        material_index = gltf_mesh["primitives"][0]["material"]
        pbr = doc["materials"][material_index]["pbrMetallicRoughness"]
        expected = mesh["material"]
        if (pbr["baseColorFactor"] != [*expected["baseColor"], 1.0] or
                pbr["metallicFactor"] != expected["metallic"] or
                pbr["roughnessFactor"] != expected["roughness"]):
            raise ValueError(f"Material mismatch on {mesh['name']}")
        items.append({"name": mesh["name"], "triangles": len(mesh["positions"]) // 9,
                      "material": expected, "gltf_material_index": material_index})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_primitives_materials.glb").write_bytes(glb)
    (OUTPUT / "manifest.json").write_text(json.dumps({
        "source": str(SOURCE.relative_to(ROOT)), "chord_tolerance": 0.08,
        "angle_tolerance_deg": 20, "triangles": sum(x["triangles"] for x in items),
        "glb_bytes": len(glb), "objects": items}, indent=2) + "\n")
    print(f"{len(items)} primitives, {sum(x['triangles'] for x in items)} triangles, "
          f"{len(glb)} GLB bytes")


if __name__ == "__main__":
    main()
