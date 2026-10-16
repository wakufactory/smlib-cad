"""Build a boolean mount and export several GLB mesh densities.

Run from the repository root with the SMLib extension on PYTHONPATH.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import _smlib_core as sm

from modeler import tessellate, to_glb


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "boolean_mount"
DETAIL_LEVELS = ((1.5, 45), (0.5, 30), (0.1, 15), (0.02, 7.5))


def build_mount():
    """Box plate + spherical boss, with four bolt holes and a through bore."""
    plate = sm.create_box((-24, -16, 0), 48, 32, 6)
    boss = sm.create_sphere((0, 0, 10), 8)
    body = sm.boolean_union(plate, boss)

    for x in (-18, 18):
        for y in (-10, 10):
            hole = sm.create_cylinder((x, y, -1), 2.5, 8)
            body = sm.boolean_difference(body, hole)

    bore = sm.create_cylinder((0, 0, -1), 3, 21)
    return sm.boolean_difference(body, bore)


def glb_triangle_count(glb: bytes) -> int:
    """Read the glTF accessors independently of the exporter mesh lists."""
    magic, version, length = struct.unpack_from("<4sII", glb)
    if (magic, version, length) != (b"glTF", 2, len(glb)):
        raise ValueError("Invalid GLB header")
    json_length, chunk_type = struct.unpack_from("<I4s", glb, 12)
    if chunk_type != b"JSON":
        raise ValueError("Missing GLB JSON chunk")
    doc = json.loads(glb[20:20 + json_length])
    return sum(
        doc["accessors"][primitive["attributes"]["POSITION"]]["count"] // 3
        for mesh in doc["meshes"]
        for primitive in mesh["primitives"]
    )


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    solid = build_mount()
    variants = []
    for chord, angle in DETAIL_LEVELS:
        mesh = tessellate({"boolean_mount": solid}, sm, chord=chord, angle=angle)
        triangles = sum(len(part["positions"]) // 9 for part in mesh)
        glb = to_glb(mesh)
        if glb_triangle_count(glb) != triangles:
            raise ValueError("Exported GLB triangle count differs from tessellation")
        path = OUTPUT / f"boolean_mount_chord_{str(chord).replace('.', 'p')}_angle_{str(angle).replace('.', 'p')}.glb"
        path.write_bytes(glb)
        variants.append({"file": path.name, "chord_tolerance": chord,
                         "angle_tolerance_deg": angle,
                         "triangles": triangles, "bytes": len(glb)})
    (OUTPUT / "manifest.json").write_text(
        json.dumps({"model": "boolean_mount", "units": "model units",
                    "variants": variants}, indent=2) + "\n"
    )
    for item in variants:
        print(f"{item['file']}: {item['triangles']} triangles, {item['bytes']} bytes")


if __name__ == "__main__":
    main()
