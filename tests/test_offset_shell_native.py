"""Signed dimensions, wall volume, openings and source lifetime at the native boundary."""

from pathlib import Path
import unittest

from modeler import evaluate, tessellate, to_glb
from test_sweeps_native import mesh_volume, sm


@unittest.skipIf(sm is None, "_smlib_core has not been built for this Python")
class OffsetShellTests(unittest.TestCase):
    def mesh(self, solid):
        return tessellate({"result": solid}, sm)[0]

    def test_signed_offsets_preserve_source(self):
        box = sm.create_box((0, 0, 0), 10, 10, 10)
        before = self.mesh(box)
        for distance, low, high, volume in ((1, -1, 11, 1728), (-1, 1, 9, 512)):
            result = sm.offset_brep(box, distance)
            mesh = self.mesh(result)
            self.assertIsNot(result, box)
            self.assertAlmostEqual(mesh_volume(mesh), volume)
            for axis in range(3):
                self.assertAlmostEqual(min(mesh["positions"][axis::3]), low)
                self.assertAlmostEqual(max(mesh["positions"][axis::3]), high)
            self.assertTrue(box.valid)
            self.assertEqual(self.mesh(box), before)

    def test_closed_and_open_walls_preserve_source(self):
        box = sm.create_box((0, 0, 0), 10, 10, 10)
        before = self.mesh(box)
        info = sm.face_info(box)
        top = next(f["index"] for f in info if f["bounds"][0][2] == f["bounds"][1][2] == 10)
        bottom = next(f["index"] for f in info if f["bounds"][0][2] == f["bounds"][1][2] == 0)
        for distance, faces, volume in ((-1, [], 488), (1, [], 728),
                                         (-1, [top], 424), (1, [top], 584),
                                         (-1, [top, bottom], 360)):
            with self.subTest(distance=distance, faces=faces):
                result = sm.shell_brep(box, distance, faces_to_shell=faces)
                mesh = self.mesh(result)
                self.assertAlmostEqual(mesh_volume(mesh), volume)
                self.assertEqual(to_glb([mesh])[:4], b"glTF")
                # Mesh triangles on the opening plane must not cover its center.
                if top in faces:
                    xyz = mesh["positions"]
                    for i in range(0, len(xyz), 9):
                        tri = [xyz[j:j + 3] for j in (i, i + 3, i + 6)]
                        if all(abs(p[2] - 10) < 1e-8 for p in tri):
                            def cross(a, b):
                                return (b[0]-a[0])*(5-a[1]) - (b[1]-a[1])*(5-a[0])
                            signs = [cross(tri[j-1], tri[j]) for j in range(3)]
                            self.assertFalse(min(signs) >= 0 or max(signs) <= 0)
                self.assertTrue(box.valid)
                self.assertEqual(self.mesh(box), before)
                self.assertEqual(sm.face_info(box), info)

    def test_invalid_parameters_and_consumed_inputs(self):
        box = sm.create_box((0, 0, 0), 10, 10, 10)
        before = self.mesh(box)
        for operation in (sm.offset_brep, sm.shell_brep):
            for distance in (0, float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    operation(box, distance)
        for faces in ([-1], [6], [0, 0]):
            with self.assertRaises(ValueError):
                sm.shell_brep(box, -1, faces_to_shell=faces)
        self.assertEqual(self.mesh(box), before)
        cutter = sm.create_box((2, 2, 2), 1, 1, 1)
        sm.boolean_difference(box, cutter)
        for operation in (sm.offset_brep, sm.shell_brep):
            with self.assertRaisesRegex(ValueError, "consumed"):
                operation(cutter, 1)

    def test_text_and_sample_to_glb(self):
        source = "box cup 0 0 0 10 10 10\nfaces cup\nshell cup -1 1"
        objects, _, log = evaluate(source, "text", sm)
        self.assertIn('cup faces:', log)
        self.assertAlmostEqual(mesh_volume(self.mesh(objects["cup"])), 424)
        path = Path(__file__).resolve().parents[1] / "examples/offset_shell.txt"
        objects, materials, _ = evaluate(path.read_text(), "text", sm)
        meshes = tessellate(objects, sm, materials=materials)
        self.assertEqual(len(meshes), 3)
        self.assertEqual(to_glb(meshes)[:4], b"glTF")


if __name__ == "__main__":
    unittest.main()
