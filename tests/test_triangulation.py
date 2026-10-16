"""Geometry checks for hole-free tessellation faces."""

from collections import Counter
import math
import unittest

from modeler import _improve_triangle_angles, _triangles


def minimum_angle(points, triangles):
    angles = []
    for triangle in triangles:
        for i, vertex in enumerate(triangle):
            a = [points[triangle[(i + 1) % 3]][j] - points[vertex][j] for j in range(3)]
            b = [points[triangle[(i + 2) % 3]][j] - points[vertex][j] for j in range(3)]
            cosine = sum(x*y for x, y in zip(a, b)) / (math.sqrt(sum(x*x for x in a))
                                                       * math.sqrt(sum(x*x for x in b)))
            angles.append(math.acos(max(-1, min(1, cosine))))
    return min(angles)


class TriangulationTests(unittest.TestCase):
    def check_polygon(self, polygon, axes=(0, 1), scale=1, reverse=False):
        points = []
        for x, y in polygon:
            p = [13 * scale, -7 * scale, 5 * scale]
            p[axes[0]] += x * scale
            p[axes[1]] += y * scale
            points.append(tuple(p))
        ids = list(range(len(points)))
        if reverse:
            ids.reverse()
        normal = [0, 0, 0]
        normal[3 - sum(axes)] = 1
        mesh = {"points": points, "faces": [len(ids), *ids], "face_normals": [normal]}
        triangles = list(_triangles(mesh))
        self.assertEqual(len(triangles), len(polygon) - 2)
        area = 0
        edges = Counter()

        def contains(q):
            inside = False
            for a, b in zip(polygon, polygon[1:] + polygon[:1]):
                cross = (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0])
                if (abs(cross) < 1e-9 and min(a[0], b[0]) - 1e-9 <= q[0] <= max(a[0], b[0]) + 1e-9
                        and min(a[1], b[1]) - 1e-9 <= q[1] <= max(a[1], b[1]) + 1e-9):
                    return True
                if (a[1] > q[1]) != (b[1] > q[1]):
                    if q[0] < a[0] + (q[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                        inside = not inside
            return inside

        for tri, normals in triangles:
            a, b, c = (polygon[i] for i in tri)
            area += abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2
            for weights in ((1/3, 1/3, 1/3), (0.5, 0.5, 0), (0, 0.5, 0.5), (0.5, 0, 0.5)):
                self.assertTrue(contains(tuple(sum(weights[i] * polygon[tri[i]][j] for i in range(3))
                                               for j in range(2))))
            self.assertEqual(normals, [tuple(normal)] * 3)
            for u, v in zip(tri, tri[1:] + tri[:1]):
                edges[tuple(sorted((u, v)))] += 1
        expected_area = abs(sum(a[0] * b[1] - b[0] * a[1]
                                for a, b in zip(polygon, polygon[1:] + polygon[:1]))) / 2
        self.assertAlmostEqual(area, expected_area)
        boundary = {tuple(sorted((i, (i + 1) % len(polygon)))) for i in range(len(polygon))}
        self.assertEqual({edge for edge, count in edges.items() if count == 1}, boundary)
        self.assertTrue(all(count == (1 if edge in boundary else 2) for edge, count in edges.items()))

    def test_concave_faces_in_all_coordinate_planes_and_windings(self):
        polygons = (
            [(0, 0), (3, 0), (3, 1), (1, 1), (1, 3), (0, 3)],
            [(0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (1, 1), (1, 4), (0, 4)],
        )
        for polygon in polygons:
            for axes in ((0, 1), (0, 2), (1, 2)):
                for scale in (1e-4, 1, 1e6):
                    for reverse in (False, True):
                        with self.subTest(polygon=polygon, axes=axes, scale=scale, reverse=reverse):
                            self.check_polygon(polygon, axes, scale, reverse)

    def test_convex_faces_preserve_geometry(self):
        for count in (3, 4, 8, 64):
            polygon = [(math.cos(i * 2 * math.pi / count), math.sin(i * 2 * math.pi / count))
                       for i in range(count)]
            for reverse in (False, True):
                with self.subTest(count=count, reverse=reverse):
                    self.check_polygon(polygon, reverse=reverse)

    def test_diagonal_flip_improves_minimum_angle_and_stops(self):
        polygon = [(0, 0), (4, 0), (3, 1), (0, 3)]
        for tilted in (False, True):
            points = [(x, y, x + y if tilted else 0) for x, y in polygon]

            def cross(a, b, c):
                return ((polygon[b][0] - polygon[a][0]) * (polygon[c][1] - polygon[a][1])
                        - (polygon[b][1] - polygon[a][1]) * (polygon[c][0] - polygon[a][0]))

            initial = [(3, 0, 1), (1, 2, 3)]
            improved = _improve_triangle_angles(initial.copy(), points, cross, 1, 1e-14)
            with self.subTest(tilted=tilted):
                self.assertGreater(minimum_angle(points, improved), minimum_angle(points, initial) + 0.01)
                self.assertEqual(_improve_triangle_angles(improved.copy(), points, cross, 1, 1e-14), improved)
                mesh = {"points": points, "faces": [4, 0, 1, 2, 3]}
                actual = [tri for tri, _ in _triangles(mesh)]
                self.assertAlmostEqual(minimum_angle(points, actual), minimum_angle(points, improved))
        self.check_polygon(polygon)

    def test_equal_quality_diagonal_is_stable(self):
        points = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]

        def cross(a, b, c):
            return ((points[b][0] - points[a][0]) * (points[c][1] - points[a][1])
                    - (points[b][1] - points[a][1]) * (points[c][0] - points[a][0]))

        for triangles in ([(0, 1, 2), (0, 2, 3)], [(3, 0, 1), (1, 2, 3)]):
            self.assertEqual(_improve_triangle_angles(triangles.copy(), points, cross, 1, 1e-14), triangles)

    def test_collinear_boundary_vertices_are_preserved(self):
        self.check_polygon([(0, 0), (1, 0), (2, 0), (2, 2), (0, 2)])

    def test_tilted_face_preserves_corner_normals_when_winding_is_corrected(self):
        polygon = [(0, 0), (3, 0), (3, 1), (1, 1), (1, 3), (0, 3)]
        points = [(x, y, x + y) for x, y in polygon]
        normals = [(i + 1, 2, 3) for i in range(len(points))]
        ids = list(reversed(range(len(points))))
        mesh = {"points": points, "faces": [len(ids), *ids], "face_normals": [(-1, -1, 1)],
                "corner_normals": [[normals[i] for i in ids]]}
        for tri, result_normals in _triangles(mesh):
            a, b, c = (points[i] for i in tri)
            cross_z = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            self.assertGreater(cross_z, 0)
            for index, normal in zip(tri, result_normals):
                length = math.sqrt(sum(x*x for x in normals[index]))
                self.assertEqual(normal, tuple(x / length for x in normals[index]))

    def test_untriangulatable_boundary_reports_error(self):
        mesh = {"points": [(0, 0, 0), (1, 1, 0), (0, 1, 0), (1, 0, 0)],
                "faces": [4, 0, 1, 2, 3]}
        with self.assertRaisesRegex(ValueError, "Cannot triangulate polygon"):
            list(_triangles(mesh))


if __name__ == "__main__":
    unittest.main()
