"""End-to-end primitive coverage using the local SMLib extension when present."""

import json
import math
import struct
import unittest

from modeler import apply_finish, evaluate, tessellate, to_glb

try:
    import _smlib_core as sm
except ImportError:
    sm = None


@unittest.skipIf(sm is None, "_smlib_core has not been built for this Python")
class PrimitiveIntegrationTests(unittest.TestCase):
    CASES = (
        "cone shape 0 0 0 2 0 4",
        "torus shape 0 0 0 5 1",
        "pyramid shape 0 0 0 4 5",
        "cylindrical_box shape 0 0 0 5 2 4 0 120",
        "partial_sphere shape 0 0 0 3 0 120",
        "partial_cone shape 0 0 0 3 1 4 0 120",
        "partial_cylinder shape 0 0 0 3 4 0 120",
        "partial_torus shape 0 0 0 5 1 0 120",
        "ellipsoid shape 0 0 0 4 2 1",
        "sphere_no_pole shape 0 0 0 2",
        "plane shape 0 0 0 4 5",
        "planar_circle shape 0 0 0 3",
    )

    def test_group_transform_after_boolean_matches_preview_and_glb(self):
        source = ("group assembly\n"
                  "box body 0 0 0 4 4 4\n"
                  "sphere hole 2 2 2 0.5\n"
                  "subtract part body hole\n"
                  "scale 2 1 1\n"
                  "euler 0 0 90\n"
                  "position 10 0 0\n"
                  "end")
        objects, materials, _ = evaluate(source, "text", sm)
        meshes = tessellate(objects, sm, materials=materials)
        points = [meshes[0]["positions"][i:i + 3]
                  for i in range(0, len(meshes[0]["positions"]), 3)]
        for axis, low, high in ((0, 6, 10), (1, 0, 8), (2, 0, 4)):
            self.assertAlmostEqual(min(p[axis] for p in points), low, delta=0.05)
            self.assertAlmostEqual(max(p[axis] for p in points), high, delta=0.05)
        glb = to_glb(meshes)
        json_length = struct.unpack_from("<I", glb, 12)[0]
        doc = json.loads(glb[20:20 + json_length])
        self.assertEqual(doc["accessors"][0]["count"], len(points))

    def test_group_boolean_matches_explicit_union_of_disconnected_members(self):
        grouped = ("group moved\nposition 10 0 0\n"
                   "box a 0 0 0 2 2 2\nbox b 5 0 0 2 2 2\nend\n"
                   "group holes\ncylinder h1 11 1 -1 0.5 4\n"
                   "cylinder h2 16 1 -1 0.5 4\nend\n")
        explicit = ("box a 10 0 0 2 2 2\nbox b 15 0 0 2 2 2\nunion moved a b\n"
                    "cylinder h1 11 1 -1 0.5 4\ncylinder h2 16 1 -1 0.5 4\n"
                    "union holes h1 h2\n")
        for op in ("union", "subtract", "intersect"):
            with self.subTest(op=op):
                meshes = []
                for prefix in (grouped, explicit):
                    objects, materials, _ = evaluate(prefix + f"{op} result moved holes", "text", sm)
                    self.assertEqual(list(objects), ["result"])
                    mesh = tessellate(objects, sm, materials=materials)
                    self.assertTrue(mesh[0]["positions"])
                    self.assertEqual(to_glb(mesh)[:4], b"glTF")
                    meshes.append(mesh[0])
                self.assertEqual(meshes[0]["positions"], meshes[1]["positions"])
                self.assertEqual(meshes[0]["normals"], meshes[1]["normals"])

    def test_text_primitives_preview_and_glb(self):
        for source in self.CASES:
            with self.subTest(source=source):
                objects, materials, _ = evaluate(source, "text", sm)
                mesh = tessellate(objects, sm, materials=materials)
                self.assertGreater(len(mesh[0]["positions"]), 0)
                glb = to_glb(mesh)
                self.assertEqual(struct.unpack_from("<4sII", glb), (b"glTF", 2, len(glb)))
                json_length = struct.unpack_from("<I", glb, 12)[0]
                doc = json.loads(glb[20:20 + json_length])
                self.assertEqual(doc["accessors"][0]["count"], len(mesh[0]["positions"]) // 3)

    def test_ellipsoid_radii_and_boolean(self):
        body = sm.create_ellipsoid((0, 0, 0), 4, 3, 2)
        cutter = sm.create_cylinder((0, 0, -3), 0.7, 6)
        solid = sm.boolean_difference(body, cutter)
        points = sm.tessellate(solid, 0.08, 20, 20).to_numpy_arrays()["points"]
        for axis, radius in enumerate((4, 3, 2)):
            self.assertAlmostEqual(min(p[axis] for p in points), -radius, delta=0.05)
            self.assertAlmostEqual(max(p[axis] for p in points), radius, delta=0.05)

    def test_axial_primitives_and_direction(self):
        cases = (
            "cylinder shape 2 3 4 1 6 1 0 0",
            "cone shape 2 3 4 1 0 6 1 0 0",
            "torus shape 2 3 4 5 1 1 0 0",
            "pyramid shape 2 3 4 2 6 1 0 0",
            "cylindrical_box shape 2 3 4 6 1 2 0 90 1 0 0",
            "partial_sphere shape 2 3 4 2 0 90 1 0 0",
            "partial_cone shape 2 3 4 1 0 6 0 90 1 0 0",
            "partial_cylinder shape 2 3 4 1 6 0 90 1 0 0",
            "partial_torus shape 2 3 4 5 1 0 90 1 0 0",
        )
        for source in cases:
            with self.subTest(source=source):
                objects, materials, _ = evaluate(source, "text", sm)
                mesh = tessellate(objects, sm, materials=materials)
                self.assertGreater(len(mesh[0]["positions"]), 0)
                self.assertEqual(struct.unpack_from("<4s", to_glb(mesh)), (b"glTF",))

        cylinder = sm.create_cylinder((2, 3, 4), 1, 6, axis=(1, 0, 0))
        points = sm.tessellate(cylinder, 0.08, 20, 20).to_numpy_arrays()["points"]
        for coordinate, low, high in ((0, 2, 8), (1, 2, 4), (2, 3, 5)):
            self.assertAlmostEqual(min(p[coordinate] for p in points), low, delta=0.05)
            self.assertAlmostEqual(max(p[coordinate] for p in points), high, delta=0.05)

        downward = sm.create_cylinder((0, 0, 0), 1, 6, axis=(0, 0, -2))
        points = sm.tessellate(downward, 0.08, 20, 20).to_numpy_arrays()["points"]
        self.assertAlmostEqual(min(p[2] for p in points), -6, delta=0.05)
        self.assertAlmostEqual(max(p[2] for p in points), 0, delta=0.05)
        with self.assertRaisesRegex(ValueError, "axis must be nonzero"):
            sm.create_cylinder((0, 0, 0), 1, 6, axis=(0, 0, 0))

        source = ("box body -4 -4 -4 8 8 8\n"
                  "cylinder hole -5 0 0 1 10 1 0 0\n"
                  "subtract result body hole")
        objects, materials, _ = evaluate(source, "text", sm)
        self.assertGreater(len(tessellate(objects, sm, materials=materials)[0]["positions"]), 0)

    def test_invalid_primitive_parameters(self):
        for source in ("torus t 0 0 0 1 2", "cone c 0 0 0 0 0 2",
                       "partial_sphere s 0 0 0 2 180 90", "ellipsoid e 0 0 0 3 0 1"):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "Line 1"):
                evaluate(source, "text", sm)

    def test_whole_solid_chamfer_and_fillet_reach_preview_and_glb(self):
        for command in ("chamfer", "fillet"):
            with self.subTest(command=command):
                source = f"box body 0 0 0 10 10 10\n{command} body 1"
                objects, materials, _ = evaluate(source, "text", sm)
                mesh = tessellate(objects, sm, materials=materials)[0]
                self.assertGreater(len(mesh["positions"]) // 9, 12)
                vertices = {tuple(mesh["positions"][i:i + 3])
                            for i in range(0, len(mesh["positions"]), 3)}
                self.assertNotIn((0.0, 0.0, 0.0), vertices)
                glb = to_glb([mesh])
                json_length = struct.unpack_from("<I", glb, 12)[0]
                doc = json.loads(glb[20:20 + json_length])
                self.assertEqual(doc["accessors"][0]["count"], len(mesh["positions"]) // 3)

                objects, materials, _ = evaluate(
                    "box left 0 0 0 10 10 10\nbox right 15 0 0 10 10 10", "text", sm)
                apply_finish(objects, sm, command, 1)
                global_meshes = tessellate(objects, sm, materials=materials)
                self.assertEqual(len(global_meshes), 2)
                self.assertTrue(all(len(part["positions"]) // 9 > 12 for part in global_meshes))

        box = sm.create_box((0, 0, 0), 10, 10, 10)
        self.assertIs(sm.chamfer_fillet(box, radius=1), box)
        box = sm.create_box((0, 0, 0), 10, 10, 10)
        self.assertIs(sm.circular_fillet(box, radius=1), box)
        objects, materials, _ = evaluate(
            "result = sm.circular_fillet(sm.create_box((0, 0, 0), 10, 10, 10), radius=1)",
            "python", sm)
        self.assertGreater(len(tessellate(objects, sm, materials=materials)[0]["positions"]), 36)
        with self.assertRaisesRegex(ValueError, "positive"):
            sm.chamfer_fillet(box, radius=0)

    def test_curved_normals_are_smooth_and_box_edges_stay_sharp(self):
        sphere = sm.create_sphere((0, 0, 0), 4)
        mesh = tessellate({"sphere": sphere}, sm, chord=0.08)[0]
        for i in range(0, len(mesh["positions"]), 3):
            point = mesh["positions"][i:i + 3]
            normal = mesh["normals"][i:i + 3]
            self.assertAlmostEqual(sum(point[j] * normal[j] for j in range(3)) / 4, 1.0, delta=1e-5)
        box = sm.create_box((-2, -2, -2), 4, 4, 4)
        raw = sm.tessellate(box, 0.08, 20, 20).to_numpy_arrays()
        for face_normal, corners in zip(raw["face_normals"], raw["corner_normals"]):
            for normal in corners:
                self.assertAlmostEqual(math.dist(face_normal, normal), 0, delta=1e-5)


if __name__ == "__main__":
    unittest.main()
