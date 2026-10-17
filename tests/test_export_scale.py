import io
import json
import struct
import unittest
import zipfile

from modeler import to_glb, to_usdz


MESH = [{
    "name": "triangle",
    "positions": [1, 2, 3, 2, 2, 3, 1, 3, 3],
    "normals": [0, 0, 1] * 3,
}]


class ExportScaleTests(unittest.TestCase):
    def test_glb_scales_positions_and_bounds_but_not_normals(self):
        data = to_glb(MESH, scale=2)
        json_length = struct.unpack_from("<I", data, 12)[0]
        scene = json.loads(data[20:20 + json_length])
        binary_offset = 20 + json_length + 8
        attributes = scene["meshes"][0]["primitives"][0]["attributes"]

        def values(name):
            accessor = scene["accessors"][attributes[name]]
            view = scene["bufferViews"][accessor["bufferView"]]
            offset = binary_offset + view["byteOffset"]
            return accessor, struct.unpack_from("<9f", data, offset)

        position, points = values("POSITION")
        normal, directions = values("NORMAL")
        self.assertEqual(points[:3], (2, 6, -4))  # source Z-up -> glTF Y-up
        self.assertEqual(position["min"], [2, 6, -6])
        self.assertEqual(position["max"], [4, 6, -4])
        self.assertEqual(directions[:3], (0, 1, 0))
        self.assertNotIn("min", normal)

    def test_usdz_scales_points_and_extent_but_not_normals(self):
        with zipfile.ZipFile(io.BytesIO(to_usdz(MESH, scale=2))) as archive:
            stage = archive.read("model.usda").decode()
        self.assertIn("point3f[] points = [(2, 4, 6), (4, 4, 6), (2, 6, 6)]", stage)
        self.assertIn("float3[] extent = [(2, 4, 6), (4, 6, 6)]", stage)
        self.assertIn("normal3f[] normals = [(0, 0, 1)", stage)

    def test_invalid_scale_and_overflow_are_rejected(self):
        for value in (0, -1, float("nan"), float("inf"), True, "2"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Export scale"):
                to_glb(MESH, scale=value)
        with self.assertRaisesRegex(ValueError, "exportable range"):
            to_usdz(MESH, scale=1e40)


if __name__ == "__main__":
    unittest.main()
