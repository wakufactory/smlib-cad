"""Real-kernel geometry checks for polygon extrusion and revolution."""

from collections import Counter
import json
import math
from pathlib import Path
import struct
import unittest

from modeler import evaluate, tessellate, to_glb

try:
    import _smlib_core as sm
except ImportError:
    sm = None


def mesh_volume(mesh):
    xyz = mesh["positions"]
    volume = 0
    for i in range(0, len(xyz), 9):
        a, b, c = [xyz[j:j + 3] for j in (i, i + 3, i + 6)]
        volume += sum(a[j] * (b[(j + 1) % 3] * c[(j + 2) % 3]
                             - b[(j + 2) % 3] * c[(j + 1) % 3]) for j in range(3)) / 6
    return volume


@unittest.skipIf(sm is None, "_smlib_core has not been built for this Python")
class SweepIntegrationTests(unittest.TestCase):
    def check_solid(self, solid, expected_volume):
        self.assertTrue(solid.valid)
        mesh = tessellate({"shape": solid}, sm, chord=0.02, angle=12)[0]
        self.assertAlmostEqual(mesh_volume(mesh), expected_volume, delta=expected_volume * 0.015)
        xyz = mesh["positions"]
        edges = Counter()
        for i in range(0, len(xyz), 9):
            vertices = [tuple(round(v, 7) for v in xyz[j:j + 3]) for j in (i, i + 3, i + 6)]
            for a, b in zip(vertices, vertices[1:] + vertices[:1]):
                edges[tuple(sorted((a, b)))] += 1
        self.assertTrue(all(count == 2 for count in edges.values()), "mesh must be closed without cracks")
        glb = to_glb([mesh])
        length = struct.unpack_from("<I", glb, 12)[0]
        document = json.loads(glb[20:20 + length])
        self.assertEqual(document["accessors"][0]["count"], len(xyz) // 3)
        return mesh

    def test_concave_extrude_both_windings_and_signed_range(self):
        vertices = [(0, 0), (3, 0), (3, 1), (1, 1), (1, 3), (0, 3)]
        for reverse in (False, True):
            profile = sm.create_profile(vertices[::-1] if reverse else vertices)
            original = profile.points
            mesh = self.check_solid(sm.create_extrude(profile, (2, 3, 4), -1, 2), 15)
            self.assertEqual(profile.points, original)
            for axis, bounds in enumerate(((2, 5), (3, 6), (3, 6))):
                self.assertAlmostEqual(min(mesh["positions"][axis::3]), bounds[0])
                self.assertAlmostEqual(max(mesh["positions"][axis::3]), bounds[1])

    def test_extrude_axis_and_xdir_placement(self):
        profile = sm.create_profile([(0, 0), (2, 0), (2, 3), (0, 3)])
        for axis, xdir, bounds in (
            ((2, 0, 0), (0, 4, 0), ((8, 14), (20, 22), (30, 33))),
            ((0, 0, -2), None, ((10, 12), (17, 20), (26, 32))),
        ):
            with self.subTest(axis=axis):
                mesh = self.check_solid(sm.create_extrude(profile, (10, 20, 30), -2, 4,
                                                         axis=axis, xdir=xdir), 36)
                for j, (low, high) in enumerate(bounds):
                    self.assertAlmostEqual(min(mesh["positions"][j::3]), low)
                    self.assertAlmostEqual(max(mesh["positions"][j::3]), high)

    def test_full_and_partial_revolve_with_axis_contact(self):
        for inner in (0, 1):
            profile = sm.create_profile([(inner, 0), (2, 0), (2, 3), (inner, 3)])
            for start, end in ((0, 360), (30, 150), (-90, 0)):
                with self.subTest(inner=inner, start=start, end=end):
                    expected = math.pi * (4 - inner**2) * 3 * (end - start) / 360
                    self.check_solid(sm.create_revolve(profile, (1, 2, 3), start, end), expected)

    def test_revolve_zero_ray_and_arbitrary_axis(self):
        profile = sm.create_profile([(1, 0), (2, 0), (2, 3), (1, 3)])
        mesh = self.check_solid(sm.create_revolve(profile, (10, 20, 30), 0, 90,
                                                 axis=(2, 0, 0), xdir=(0, 1, 0)), 9 * math.pi / 4)
        for j, bounds in enumerate(((10, 13), (20, 22), (30, 32))):
            self.assertAlmostEqual(min(mesh["positions"][j::3]), bounds[0], delta=1e-7)
            self.assertAlmostEqual(max(mesh["positions"][j::3]), bounds[1], delta=1e-7)

    def test_revolve_cone_tip_has_directional_corner_normals(self):
        profile = sm.create_profile([(0, -2), (9, 2), (9, 10), (5, 12)])
        for axis, xdir in (((0, 0, 1), (1, 0, 0)), ((1, 0, 0), (0, 1, 0))):
            for start, end in ((0, 360), (30, 270)):
                origin = (0, 0, -5)
                solid = sm.create_revolve(profile, origin, start, end, axis=axis, xdir=xdir)
                mesh = tessellate({"shape": solid}, sm)[0]
                xyz, normals = mesh["positions"], mesh["normals"]
                counts = {"inner": 0, "bottom": 0}
                for i in range(0, len(xyz), 9):
                    points = [xyz[j:j + 3] for j in (i, i + 3, i + 6)]
                    relative = [[p[j] - origin[j] for j in range(3)] for p in points]
                    heights = [sum(p[j]*axis[j] for j in range(3)) for p in relative]
                    radial = [[p[j] - h*axis[j] for j in range(3)] for p, h in zip(relative, heights)]
                    radii = [math.sqrt(sum(x*x for x in p)) for p in radial]
                    if min(radii) > 1e-8:
                        continue
                    # Both conical sheets meet at the same apex but have
                    # different slopes and opposite material-facing normals.
                    for name, slope, sign in (("inner", 5/14, -1), ("bottom", 9/4, 1)):
                        if not all(abs(r - (h + 2)*slope) < 1e-6 for r, h in zip(radii, heights)):
                            continue
                        direction = [sum(v[j] for v, r in zip(radial, radii) if r > 1e-8) for j in range(3)]
                        length = math.sqrt(sum(v*v for v in direction))
                        for corner, r in enumerate(radii):
                            expected = [sign * ((direction[j]/length if r < 1e-8 else radial[corner][j]/r)
                                                - slope*axis[j]) / math.sqrt(1 + slope*slope) for j in range(3)]
                            actual = normals[i + corner*3:i + corner*3 + 3]
                            with self.subTest(axis=axis, start=start, face=name, apex=r < 1e-8):
                                self.assertGreater(sum(a*b for a, b in zip(expected, actual)), 0.99999)
                            if r < 1e-8:
                                counts[name] += 1
                self.assertTrue(all(count > 0 for count in counts.values()))
                self.assertAlmostEqual(mesh_volume(mesh), 740*math.pi*(end-start)/360,
                                       delta=740*math.pi*0.015)
                self.assertEqual(to_glb([mesh])[:4], b"glTF")

    def test_boolean_and_finishing(self):
        profile = sm.create_profile([(0, 0), (4, 0), (4, 3), (0, 3)])
        body = sm.create_extrude(profile, (0, 0, 0), 0, 2)
        cutter = sm.create_cylinder((2, 1.5, -1), 0.5, 4)
        self.check_solid(sm.boolean_difference(body, cutter), 24 - math.pi * 0.5**2 * 2)
        self.assertFalse(cutter.valid)
        body = sm.create_extrude(profile, (0, 0, 0), 0, 2)
        self.assertIs(sm.chamfer_fillet(body, 0.1), body)
        self.assertGreater(len(tessellate({"shape": body}, sm)[0]["positions"]), 0)

    def test_sample_and_python_mode(self):
        source = (Path(__file__).resolve().parents[1] / "examples/extrude_revolve.txt").read_text()
        objects, materials, _ = evaluate(source, "text", sm)
        self.assertEqual(list(objects), ["bracket", "sleeve", "sector"])
        meshes = tessellate(objects, sm, materials=materials)
        self.assertEqual(len(meshes), 3)
        self.assertEqual(to_glb(meshes)[:4], b"glTF")
        objects, _, _ = evaluate("p = sm.create_profile([(0,0), (2,0), (0,2)])\n"
                                 "result = sm.create_extrude(p, (0,0,0), 0, 3)", "python", sm)
        self.check_solid(objects["result"], 6)

    def test_invalid_profile_and_sweep_parameters(self):
        invalid = (
            [(0, 0), (1, 0)],
            [(0, 0), (1, 0), (2, 0)],
            [(0, 0), (1, 0), (1, 0), (0, 1)],
            [(0, 0), (2, 2), (0, 2), (2, 0)],
            [(0, 0), (2, 0), (1, 0), (1, 1)],
            [(0, 0), (1, 0), (0, float("nan"))],
        )
        for vertices in invalid:
            with self.subTest(vertices=vertices), self.assertRaises(ValueError):
                sm.create_profile(vertices)
        profile = sm.create_profile([(0, 0), (2, 0), (0, 2)])
        for operation, start, end in (("extrude", 0, 0), ("extrude", 2, 1),
                                       ("revolve", 0, 361), ("revolve", 0, float("inf"))):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                getattr(sm, f"create_{operation}")(profile, (0, 0, 0), start, end)
        for options in ({"axis": (0, 0, 0)}, {"xdir": (0, 0, 1)}, {"xdir": (0, 0, 0)}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                sm.create_extrude(profile, (0, 0, 0), 0, 2, **options)
        negative = sm.create_profile([(-1, 0), (2, 0), (2, 2), (-1, 2)])
        with self.assertRaisesRegex(ValueError, "non-negative"):
            sm.create_revolve(negative, (0, 0, 0), 0, 360)
        with self.assertRaisesRegex(ValueError, "Line 4.*start"):
            evaluate("profile p\npolygon 0 0 1 0 0 1\nend\nextrude a p 0 0 0 2 1", "text", sm)


if __name__ == "__main__":
    unittest.main()
