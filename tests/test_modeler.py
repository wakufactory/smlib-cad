import json
import struct
import unittest

from modeler import apply_finish, evaluate, tessellate, to_glb


class Solid:
    def faces(self): pass
    def edges(self): pass
    def vertices(self): pass


class Poly:
    def to_numpy_arrays(self):
        return {"points": [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                "faces": [4, 0, 1, 2, 3], "face_normals": [(0, 0, 1)]}


class FakeBrep:
    Brep = Solid
    def __init__(self):
        self.transforms = []
        self.booleans = []
    def create_box(self, origin, w, d, h): return Solid()
    def create_sphere(self, center, r): return Solid()
    def offset_brep(self, solid, distance):
        self.last_offset = (solid, distance)
        return Solid()
    def shell_brep(self, solid, distance, faces_to_shell=()):
        self.last_shell = (solid, distance, faces_to_shell)
        return Solid()
    def face_info(self, solid): return [{"index": 0, "bounds": [[0, 0, 0], [1, 1, 0]]}]
    def create_cylinder(self, center, r, h, axis=None):
        self.last_cylinder_axis = axis
        return Solid()
    def create_profile(self, points): return tuple(points)
    def create_spline_profile(self, points): return ("spline", tuple(points))
    def create_extrude(self, profile, origin, start, end, **options):
        self.last_sweep = (profile, origin, start, end, options)
        return Solid()
    create_revolve = create_extrude
    def boolean_difference(self, a, b):
        self.booleans.append(("subtract", a, b))
        return Solid()
    def boolean_union(self, a, b):
        self.booleans.append(("union", a, b))
        return Solid()
    def boolean_intersection(self, a, b):
        self.booleans.append(("intersect", a, b))
        return Solid()
    def chamfer_fillet(self, solid, radius):
        self.last_chamfer = (solid, radius)
        return solid
    def circular_fillet(self, solid, radius):
        self.last_fillet = (solid, radius)
        return solid
    def transform_brep(self, solid, scale, euler, position):
        self.transforms.append((solid, scale, euler, position))
        return solid
    def tessellate(self, solid, **kwargs):
        self.last_tessellation = kwargs
        return Poly()


class ModelerTests(unittest.TestCase):
    def test_per_solid_tessellation(self):
        sm = FakeBrep()
        calls = []
        sm.tessellate = lambda solid, **kw: (calls.append(kw) or Poly())
        objects, materials, _ = evaluate(
            "sphere fine 0 0 0 4\ntessellation fine 0.01 5\n"
            "sphere normal 10 0 0 4\nsphere partial 20 0 0 4\n"
            "tessellation partial default 10", "text", sm)
        objects = apply_finish(objects, sm, "fillet", 0.1)
        tessellate(objects, sm, 0.08, 20, materials)
        self.assertEqual([(c["chord_height_tolerance"], c["curve_angle_tolerance_deg"],
                           c["surface_angle_tolerance_deg"]) for c in calls],
                         [(0.01, 5, 5), (0.08, 20, 20), (0.08, 10, 10)])

    def test_tessellation_scope_and_boolean(self):
        sm = FakeBrep()
        objects, _, _ = evaluate(
            "part ball\nsphere a 0 0 0 4\ntessellation a 0.01 5\nend\n"
            "group assembly\nuse ball left\nend\nuse ball right", "text", sm)
        self.assertEqual(objects.tessellation,
                         {"left__a": (0.01, 5), "right__a": (0.01, 5)})
        objects, _, _ = evaluate(
            "sphere a 0 0 0 4\ntessellation a 0.01 5\nsphere b 2 0 0 4\n"
            "union a a b", "text", sm)
        self.assertEqual(objects.tessellation, {})
        objects, _, _ = evaluate(
            "sphere a 0 0 0 4\ntessellation a 0.01 5\n"
            "tessellation a default default", "text", sm)
        self.assertEqual(objects.tessellation["a"], (None, None))

    def test_invalid_tessellation(self):
        for command in ("tessellation missing 0.01 5", "tessellation a 0.01",
                        "tessellation a 0 5", "tessellation a 0.01 91",
                        "tessellation a nan 5", "tessellation a 0.01 inf"):
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, "Line 2"):
                evaluate("sphere a 0 0 0 4\n" + command, "text", FakeBrep())

    def test_offset_shell_and_face_log(self):
        sm = FakeBrep()
        objects, materials, log = evaluate(
            "box a 0 0 0 10 10 10\nmaterial a 1 0 0 0 0.5\nfaces a\noffset a 1\nshell a -1 0 1", "text", sm)
        self.assertEqual(sm.last_offset[1], 1)
        self.assertEqual(sm.last_shell[1:], (-1, [0, 1]))
        self.assertIn('a faces:', log)
        self.assertIn('"index": 0', log)
        self.assertIn("a", objects)
        self.assertEqual(materials["a"]["baseColor"], [1, 0, 0])
        for command in ("offset a 0", "offset missing 1", "offset a 1 0", "shell a nan",
                        "shell a 1 1.5", "faces missing", "faces a extra"):
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, "Line 2"):
                evaluate("box a 0 0 0 10 10 10\n" + command, "text", sm)

    def test_profile_reuse_in_parts_and_groups(self):
        source = ("profile root\npolygon 1 0 2 0 2 3 1 3\nend\n"
                  "part piece\nprofile local\npolygon 0 0 1 0 0 1\nend\n"
                  "extrude a local 0 0 0 -2 2\nrevolve b root 0 0 0 10 90\nend\n"
                  "use piece left\ngroup shifted\nposition 10 0 0\nuse piece right\nend\n"
                  "extrude oriented root 1 2 3 -1 4 1 0 0 0 1 0")
        sm = FakeBrep()
        objects, _, _ = evaluate(source, "text", sm)
        self.assertEqual(list(objects), ["left__a", "left__b", "right__a", "right__b", "oriented"])
        self.assertIsNot(objects["left__a"], objects["right__a"])
        self.assertEqual(sm.last_sweep, (((1., 0.), (2., 0.), (2., 3.), (1., 3.)),
                                         (1., 2., 3.), -1., 4.,
                                         {"axis": (1., 0., 0.), "xdir": (0., 1., 0.)}))

    def test_profile_syntax_errors(self):
        definition = "profile p\npolygon 0 0 1 0 0 1\nend\n"
        cases = (
            ("profile p\npolygon 0 0 1 0 0 1", "profile p has no end"),
            ("profile p\nend", "profile requires a polygon"),
            ("profile p\npolygon 0 0 1 0 0\nend", "three u v pairs"),
            (definition + definition, "duplicate profile"),
            ("extrude a missing 0 0 0 0 1", "unknown profile"),
            (definition + "extrude a p 0 0 0 0", "extrude:"),
            (definition + "revolve a p 0 0 0 0 nan", "finite"),
            (definition + "extrude a p 0 0 0 0 1\nextrude a p 0 0 0 0 1", "duplicate solid"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, message):
                evaluate(source, "text", FakeBrep())

    def test_spline_profile_uses_existing_sweeps(self):
        source = ("profile curved\n"
                  "spline through 2 0 4 0 5 1 5 3 4 4 2 4 1 3 1 1 closed\n"
                  "end\nextrude raised curved 0 0 0 0 2\n"
                  "revolve turned curved 10 0 0 0 180\n")
        sm = FakeBrep()
        objects, _, _ = evaluate(source, "text", sm)
        self.assertEqual(list(objects), ["raised", "turned"])
        self.assertEqual(sm.last_sweep[0][0], "spline")
        for definition in ("spline through 0 0 1 0 1 1 closed",
                           "spline 0 0 1 0 1 1 0 1 closed",
                           "spline through 0 0 1 0 1 1 0 1"):
            with self.subTest(definition=definition), self.assertRaisesRegex(ValueError, "Line 2"):
                evaluate(f"profile bad\n{definition}\nend", "text", sm)

    def test_part_use_builds_distinct_solids_and_namespaces_materials(self):
        source = ("use clamp left\n"
                  "group moved\n"
                  "  position 12 0 0\n"
                  "  use clamp right\n"
                  "  material right__result 0 0 1 0 0.5\n"
                  "end\n"
                  "part clamp\n"
                  "  box body 0 0 0 4 4 4\n"
                  "  cylinder hole 2 2 -1 1 6\n"
                  "  subtract result body hole\n"
                  "  material result 1 0 0 0 0.5\n"
                  "end")
        sm = FakeBrep()
        objects, materials, _ = evaluate(source, "text", sm)
        self.assertEqual(list(objects), ["left__result", "right__result"])
        self.assertIsNot(objects["left__result"], objects["right__result"])
        self.assertEqual(materials["left__result"]["baseColor"], [1, 0, 0])
        self.assertEqual(materials["right__result"]["baseColor"], [0, 0, 1])
        self.assertEqual(sm.transforms[-1][0], objects["right__result"])
        self.assertEqual(sm.transforms[-1][3], (12.0, 0.0, 0.0))

    def test_part_use_errors(self):
        cases = (
            ("use missing", "unknown part"),
            ("part a\nbox x 0 0 0 1 1 1", "part a has no end"),
            ("part a\nbox x 0 0 0 1 1 1\nend\npart a\nend", "duplicate part name"),
            ("group g\npart p\nbox x 0 0 0 1 1 1\nend\nend", "root level"),
            ("part a\nuse a\nend\nuse a", "recursive part use"),
            ("part a\nuse b\nend\npart b\nuse a\nend\nuse a", "recursive part use"),
            ("part a\nbox x 0 0 0 1 1 1\nend\nuse a same\nuse a same", "duplicate solid name"),
        )
        for source, error in cases:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, error):
                evaluate(source, "text", FakeBrep())

    def test_nested_parts_with_groups_and_automatic_names(self):
        source = ("part shifted\n"
                  "  group local\n"
                  "    position 2 0 0\n"
                  "    box result 0 0 0 1 1 1\n"
                  "  end\n"
                  "end\n"
                  "part assembly\n"
                  "  use shifted inside\n"
                  "end\n"
                  "use assembly\nuse assembly")
        sm = FakeBrep()
        objects, _, _ = evaluate(source, "text", sm)
        self.assertEqual(list(objects), ["assembly_1__inside__result", "assembly_2__inside__result"])
        self.assertIsNot(*objects.values())
        self.assertEqual([call[3] for call in sm.transforms], [(2.0, 0.0, 0.0)] * 2)

    def test_text_variables_loops_and_part_use_scope(self):
        source = ("let count = 3\nlet radius = 12\n"
                  "part piece\nbox body 0 0 0 ${size} 2 2\nend\n"
                  "for i in range(count)\n"
                  "  let size = i + 1\n"
                  "  group station_${i}\n"
                  "    euler 0 0 ${i * 360 / count}\n"
                  "    group offset_${i}\n"
                  "      position ${radius} 0 0\n"
                  "      use piece item_${i}\n"
                  "    end\n"
                  "  end\n"
                  "end\n")
        sm = FakeBrep()
        objects, _, _ = evaluate(source, "text", sm)
        self.assertEqual(list(objects), ["item_0__body", "item_1__body", "item_2__body"])
        self.assertEqual([call[2][2] for call in sm.transforms[1::2]], [0, 120, 240])
        self.assertEqual([call[3][0] for call in sm.transforms[::2]], [12, 12, 12])

    def test_nested_range_and_local_variables(self):
        source = ("let width = 4\n"
                  "for row in range(1, 3)\n"
                  "  for col in range(2, -1, -1)\n"
                  "    box cell_${row}_${col} ${row * width} ${col} 0 1 1 1\n"
                  "  end\n"
                  "end\n"
                  "box computed_${width / 2} 0 0 0 1 1 1\n"
                  "box last ${width} 0 0 1 1 1 # ${ignored} is a comment\n")
        objects, _, _ = evaluate(source, "text", FakeBrep())
        self.assertEqual(list(objects), ["cell_1_2", "cell_1_1", "cell_1_0",
                                         "cell_2_2", "cell_2_1", "cell_2_0", "computed_2", "last"])

    def test_text_expression_and_loop_errors(self):
        cases = (
            ("box a 0 0 0 ${missing} 1 1", "Line 1: unknown variable"),
            ("let n = 1\nlet n = 2\nbox a 0 0 0 1 1 1", "Line 2: duplicate variable"),
            ("let n = 1 / 0\nbox a 0 0 0 1 1 1", "Line 1: invalid arithmetic"),
            ("box a 0 0 0 ${__import__('os')} 1 1", "only numbers"),
            ("for i in range(513)\nbox a_${i} 0 0 0 1 1 1\nend", "iteration limit"),
            ("for i in range(2)\nbox a 0 0 0 1 1 1", "for has no end"),
            ("for i in range(2)\nbox a_${i} 0 0 0 1 1 1\nend\nbox b 0 0 0 ${i} 1 1",
             "unknown variable: i"),
            ("group g\nlet local = 2\nbox a 0 0 0 1 1 1\nend\nbox b ${local} 0 0 1 1 1",
             "unknown variable: local"),
            ("for i in range(0, 3, 0)\nbox a 0 0 0 1 1 1\nend", "step must not be zero"),
            ("part p\nbox a 0 0 0 ${size} 1 1\nend\nuse p", "Line 2: unknown variable: size"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, message):
                evaluate(source, "text", FakeBrep())

    def test_nested_groups_transform_boolean_results(self):
        sm = FakeBrep()
        source = ("group parent\n"
                  "position 10 0 0\n"
                  "group child\n"
                  "box body 0 0 0 4 4 4\n"
                  "sphere hole 2 2 2 1\n"
                  "subtract part body hole\n"
                  "material part 1 0 0 0 0.5\n"
                  "scale 2 1 1\n"
                  "end\n"
                  "euler 0 0 90\n"
                  "end")
        objects, materials, _ = evaluate(source, "text", sm)
        self.assertEqual(list(objects), ["part"])
        self.assertIn("part", materials)
        self.assertEqual(sm.transforms, [
            (objects["part"], (2.0, 1.0, 1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            (objects["part"], (1.0, 1.0, 1.0), (0.0, 0.0, 90.0), (10.0, 0.0, 0.0)),
        ])
        tessellate(objects, sm, materials=materials)

    def test_group_errors(self):
        prefix = "group g\nbox a 0 0 0 1 1 1\n"
        cases = (("end\nend", "Line 4"),
                 ("scale 0 1 1\nend", "Line 3: scale"),
                 ("euler nan 0 0\nend", "Line 3: euler"),
                 ("position 0 0\nend", "Line 3: position"),
                 ("", "group g has no end"))
        for suffix, message in cases:
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, message):
                evaluate(prefix + suffix, "text", FakeBrep())
        with self.assertRaisesRegex(ValueError, "duplicate solid name"):
            evaluate("box a 0 0 0 1 1 1\n" + prefix + "end", "text", FakeBrep())

    def test_boolean_group_operands(self):
        for op in ("union", "subtract", "intersect"):
            sm = FakeBrep()
            source = ("group moved\nposition 10 0 0\n"
                      "group child\nbox a 0 0 0 2 2 2\nend\n"
                      "box b 5 0 0 2 2 2\nmaterial a 1 0 0 0 0.5\nend\n"
                      "group cutters\ncylinder h1 11 1 -1 0.5 4\n"
                      "cylinder h2 16 1 -1 0.5 4\nend\n"
                      f"{op} result moved cutters")
            objects, materials, _ = evaluate(source, "text", sm)
            self.assertEqual(list(objects), ["result"])
            self.assertEqual(materials, {})
            self.assertEqual([call[0] for call in sm.booleans], ["union", "union", op])
            # The group members supplied to union have already been transformed.
            self.assertEqual(sm.transforms[1][3], (10., 0., 0.))
            self.assertIs(sm.booleans[0][1], sm.transforms[1][0])

    def test_group_members_follow_boolean_replacement(self):
        source = ("group outer\ngroup inner\nbox a 0 0 0 2 2 2\n"
                  "box b 1 0 0 2 2 2\nend\nunion merged a b\nend\n"
                  "sphere hole 1 1 1 0.5\nsubtract result inner hole")
        objects, _, _ = evaluate(source, "text", FakeBrep())
        self.assertEqual(list(objects), ["result"])
        # A use inside a group also contributes its generated solids.
        objects, _, _ = evaluate("part p\nbox a 0 0 0 2 2 2\nend\n"
                                 "group moved\nuse p instance\nend\n"
                                 "sphere hole 1 1 1 0.5\nsubtract moved moved hole",
                                 "text", FakeBrep())
        self.assertEqual(list(objects), ["moved"])

    def test_boolean_group_errors(self):
        group = "group g\nbox a 0 0 0 2 2 2\nend\n"
        cases = (
            (group + "subtract result g a", "share group members"),
            (group + "union result g g", "must differ"),
            ("group empty\nend\n" + group + "subtract result g empty", "must not be empty"),
            (group + "group g\nend", "duplicate group name"),
            (group + "box g 0 0 0 1 1 1", "already used by group"),
            ("group g\nbox g 0 0 0 1 1 1\nend", "duplicate group or solid"),
            (group + "sphere h 1 1 1 1\nsubtract r g h\nsphere j 0 0 0 1\nunion r g j",
             "existing object or group"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, message):
                evaluate(source, "text", FakeBrep())

    def test_tessellation_angle_reaches_kernel(self):
        sm = FakeBrep()
        tessellate({"box": Solid()}, sm, chord=0.2, angle=30)
        self.assertEqual(sm.last_tessellation, {
            "chord_height_tolerance": 0.2,
            "curve_angle_tolerance_deg": 30,
            "surface_angle_tolerance_deg": 30,
        })
        for angle in (0, 91, float("nan")):
            with self.subTest(angle=angle), self.assertRaisesRegex(ValueError, "angle"):
                tessellate({"box": Solid()}, sm, chord=0.2, angle=angle)

    def test_text_to_glb(self):
        sm = FakeBrep()
        objects, materials, _ = evaluate("box body 0 0 0 2 2 2\nsphere hole 1 1 1 0.5\nsubtract result body hole", "text", sm)
        self.assertEqual(list(objects), ["result"])
        meshes = tessellate(objects, sm, materials=materials)
        self.assertEqual(len(meshes[0]["positions"]), 18)
        data = to_glb(meshes)
        magic, version, length = struct.unpack_from("<4sII", data)
        self.assertEqual((magic, version, length), (b"glTF", 2, len(data)))
        json_length = struct.unpack_from("<I", data, 12)[0]
        doc = json.loads(data[20:20 + json_length])
        self.assertEqual(doc["asset"]["version"], "2.0")
        self.assertEqual(doc["accessors"][0]["count"], 6)
        self.assertEqual(doc["scenes"][0]["nodes"], [0])

    def test_python_and_errors(self):
        sm = FakeBrep()
        objects, _, _ = evaluate("result = sm.create_box((0,0,0), 1, 2, 3)", "python", sm)
        self.assertEqual(list(objects), ["result"])
        cylinder, _, _ = evaluate("cylinder post 0 0 0 1 4", "text", sm)
        self.assertEqual(list(cylinder), ["post"])
        self.assertIsNone(sm.last_cylinder_axis)
        evaluate("cylinder post 0 0 0 1 4 1 0 0", "text", sm)
        self.assertEqual(sm.last_cylinder_axis, (1.0, 0.0, 0.0))
        with self.assertRaisesRegex(ValueError, "Line 1: axis must be nonzero"):
            evaluate("cylinder post 0 0 0 1 4 0 0 0", "text", sm)
        with self.assertRaisesRegex(ValueError, "Line 1"):
            evaluate("box b 0 0 0 -1 2 3", "text", sm)
        with self.assertRaisesRegex(ValueError, "Line 1"):
            evaluate("subtract r missing b", "text", sm)

    def test_two_solid_materials_reach_preview_and_glb(self):
        source = ("box red 0 0 0 2 2 2\n"
                  "box steel 4 0 0 2 2 2\n"
                  "material red 0.8 0.1 0.05 0 0.8\n"
                  "material steel 0.5 0.6 0.7 1 0.2")
        objects, materials, _ = evaluate(source, "text", FakeBrep())
        meshes = tessellate(objects, FakeBrep(), materials=materials)
        self.assertEqual(meshes[0]["material"]["baseColor"], [0.8, 0.1, 0.05])
        self.assertEqual(meshes[1]["material"]["metallic"], 1.0)
        data = to_glb(meshes)
        json_length = struct.unpack_from("<I", data, 12)[0]
        doc = json.loads(data[20:20 + json_length])
        self.assertEqual(len(doc["materials"]), 2)
        self.assertEqual([m["primitives"][0]["material"] for m in doc["meshes"]], [0, 1])
        self.assertEqual(doc["materials"][0]["pbrMetallicRoughness"], {
            "baseColorFactor": [0.8, 0.1, 0.05, 1.0],
            "metallicFactor": 0.0, "roughnessFactor": 0.8})
        self.assertEqual(doc["materials"][1]["pbrMetallicRoughness"]["roughnessFactor"], 0.2)

    def test_whole_solid_chamfer_and_fillet_commands(self):
        sm = FakeBrep()
        source = ("box a 0 0 0 10 10 10\n"
                  "box b 15 0 0 10 10 10\n"
                  "material a 0.8 0.1 0.1 0 0.5\n"
                  "chamfer a 1\nfillet b 0.5")
        objects, materials, _ = evaluate(source, "text", sm)
        self.assertIs(sm.last_chamfer[0], objects["a"])
        self.assertEqual(sm.last_chamfer[1], 1)
        self.assertIs(sm.last_fillet[0], objects["b"])
        self.assertEqual(sm.last_fillet[1], 0.5)
        self.assertEqual(materials["a"]["baseColor"], [0.8, 0.1, 0.1])
        for command in ("chamfer missing 1", "chamfer a 0", "fillet a -1", "fillet a nan"):
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, "Line 2"):
                evaluate("box a 0 0 0 10 10 10\n" + command, "text", sm)

        objects, _, _ = evaluate("box a 0 0 0 10 10 10\nbox b 15 0 0 10 10 10", "text", sm)
        original = tuple(objects.values())
        self.assertIs(apply_finish(objects, sm, "none", 0), objects)
        self.assertEqual(tuple(objects.values()), original)
        self.assertIs(apply_finish(objects, sm, "fillet", 0.5), objects)
        self.assertEqual(tuple(objects.values()), original)
        self.assertEqual(sm.last_fillet[1], 0.5)
        for finish, size in (("unknown", 1), ("chamfer", 0), ("fillet", float("nan"))):
            with self.subTest(finish=finish, size=size), self.assertRaises(ValueError):
                apply_finish(objects, sm, finish, size)

    def test_python_material_and_invalid_values(self):
        source = ("result = sm.create_box((0,0,0), 1, 2, 3)\n"
                  "materials = {'result': {'baseColor': (0.2, 0.4, 0.6), "
                  "'metallic': 0.7, 'roughness': 0.25}}")
        objects, materials, _ = evaluate(source, "python", FakeBrep())
        self.assertEqual(materials["result"], {"baseColor": [0.2, 0.4, 0.6],
                                                "metallic": 0.7, "roughness": 0.25})
        self.assertEqual(tessellate(objects, FakeBrep(), materials=materials)[0]["material"],
                         materials["result"])
        with self.assertRaisesRegex(ValueError, "Line 2: roughness"):
            evaluate("box a 0 0 0 1 1 1\nmaterial a 1 0 0 0 1.1", "text", FakeBrep())
        with self.assertRaisesRegex(ValueError, "unknown solid"):
            evaluate(source.replace("'result':", "'missing':"), "python", FakeBrep())


if __name__ == "__main__":
    unittest.main()
