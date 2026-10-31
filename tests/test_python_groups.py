import io
import json
import struct
import unittest
import zipfile
from pathlib import Path

from modeler import apply_finish, evaluate, tessellate, to_glb, to_usdz
from test_modeler import FakeBrep

try:
    import _smlib_core as native_sm
except ImportError:
    native_sm = None


SOURCE = """
body = sm.create_box((0, 0, 0), 2, 3, 4)
bolt = sm.create_sphere((1, 1, 4), 0.5)
plain = sm.create_box((10, 0, 0), 1, 1, 1)
objects = {'assembly': Group({
    'body': body,
    'detail': Group({'bolt': bolt}, material={'baseColor': [0, 0, 1]},
                    position=(0, 0, 2))},
    material={'baseColor': [1, 0, 0]}, scale=(2, 1, 1),
    euler=(0, 0, 90), position=(10, 0, 0)), 'plain': plain}
"""


class PythonGroupTests(unittest.TestCase):
    def test_invisible_groups_keep_computed_solids_and_filter_both_exports(self):
        for source in (SOURCE.replace("position=(0, 0, 2)", "position=(0, 0, 2), invisible=True"),
                       SOURCE.replace("position=(10, 0, 0)", "position=(10, 0, 0), invisible=True")):
            sm = FakeBrep()
            objects, materials, _ = evaluate(source, 'python', sm)
            self.assertEqual(set(objects), {'body', 'bolt', 'plain'})
            self.assertEqual(len(sm.transforms), 3)
            meshes = tessellate(objects, sm, materials=materials)
            names = [m['name'] for m in meshes]
            self.assertNotIn('bolt', names)
            self.assertIn('plain', names)
            data = to_glb(meshes)
            length = struct.unpack_from('<I', data, 12)[0]
            self.assertEqual([m['name'] for m in json.loads(data[20:20 + length])['meshes']], names)
            with zipfile.ZipFile(io.BytesIO(to_usdz(meshes))) as archive:
                stage = archive.read('model.usda').decode()
            self.assertEqual(stage.count('def Mesh '), len(names))
            self.assertNotIn('def Mesh "bolt"', stage)

    def test_all_invisible_is_an_empty_render(self):
        source = "objects = {'g': Group({'a': sm.create_box((0,0,0),1,1,1)}, invisible=True)}"
        objects, _, _ = evaluate(source, 'python', FakeBrep())
        self.assertIn('a', objects)
        meshes = tessellate(objects, FakeBrep())
        self.assertEqual(meshes, [])
        data = to_glb(meshes)
        self.assertEqual(data[:4], b'glTF')
        self.assertEqual(struct.unpack_from('<I', data, 8)[0], len(data))
        length = struct.unpack_from('<I', data, 12)[0]
        doc = json.loads(data[20:20 + length])
        self.assertNotIn('buffers', doc)
        self.assertEqual(doc['scenes'], [{}])
        with zipfile.ZipFile(io.BytesIO(to_usdz(meshes))) as archive:
            self.assertNotIn('def Mesh ', archive.read('model.usda').decode())

    @unittest.skipIf(native_sm is None, '_smlib_core has not been built for this Python')
    def test_native_invisible_boolean_and_hidden_tool(self):
        source = ('group helper\ninvisible\nposition 1 0 0\n'
                  'box a 0 0 0 2 2 2\nbox b 1 0 0 2 2 2\n'
                  'union tool a b\nend\nbox body 0 0 0 5 5 5\n')
        objects, _, _ = evaluate(source, 'text', native_sm)
        self.assertEqual(set(objects), {'tool', 'body'})
        self.assertTrue(native_sm.face_info(objects['tool']))
        self.assertEqual([m['name'] for m in tessellate(objects, native_sm)], ['body'])
        objects, _, _ = evaluate(source + 'subtract result body helper', 'text', native_sm)
        self.assertEqual(set(objects), {'result'})
        self.assertEqual([m['name'] for m in tessellate(objects, native_sm)], ['result'])

    @unittest.skipIf(native_sm is None, '_smlib_core has not been built for this Python')
    def test_native_nested_groups_match_text_geometry(self):
        python = """
objects = {'assembly': Group({
    'detail': Group({'body': sm.create_box((0,0,0), 2,3,4)},
                    position=(3,0,0))},
    scale=(2,1,1), euler=(0,0,90), position=(10,0,0))}
materials = {'assembly': {'baseColor': [1,0,0], 'metallic': 0.5}}
"""
        text = ('group assembly\nscale 2 1 1\neuler 0 0 90\nposition 10 0 0\n'
                'group detail\nposition 3 0 0\nbox body 0 0 0 2 3 4\nend\n'
                'material assembly 1 0 0 0.5 0.55\nend')
        results = []
        for source, mode in ((python, 'python'), (text, 'text')):
            objects, materials, _ = evaluate(source, mode, native_sm)
            results.append(tessellate(objects, native_sm, materials=materials))
        self.assertEqual(results[0], results[1])
        points = results[0][0]['positions']
        for axis, low, high in ((0, 7, 10), (1, 6, 10), (2, 0, 4)):
            self.assertAlmostEqual(min(points[axis::3]), low, places=5)
            self.assertAlmostEqual(max(points[axis::3]), high, places=5)

    def test_nested_transforms_materials_and_export_boundaries(self):
        sm = FakeBrep()
        objects, materials, _ = evaluate(SOURCE, 'python', sm)
        self.assertEqual(list(objects), ['body', 'bolt', 'plain'])
        self.assertEqual(objects.top_groups, {'body': 'assembly', 'bolt': 'assembly'})
        self.assertEqual(materials['body']['baseColor'], [1, 0, 0])
        self.assertEqual(materials['bolt']['baseColor'], [0, 0, 1])
        self.assertNotIn('plain', materials)
        self.assertEqual(sm.transforms, [
            (objects['bolt'], (1, 1, 1), (0, 0, 0), (0, 0, 2)),
            (objects['body'], (2, 1, 1), (0, 0, 90), (10, 0, 0)),
            (objects['bolt'], (2, 1, 1), (0, 0, 90), (10, 0, 0))])
        apply_finish(objects, sm, 'fillet', 0.1)
        meshes = tessellate(objects, sm, materials=materials)
        self.assertEqual([mesh['group'] for mesh in meshes], ['assembly', 'assembly', 'plain'])
        data = to_glb(meshes)
        length = struct.unpack_from('<I', data, 12)[0]
        doc = json.loads(data[20:20 + length])
        self.assertEqual([mesh['name'] for mesh in doc['meshes']], ['body', 'bolt', 'plain'])
        nodes = {node['name']: node for node in doc['nodes']}
        self.assertEqual(nodes['assembly']['translation'], [10, 0, 0])
        self.assertEqual(nodes['assembly']['scale'], [2, 1, 1])
        self.assertEqual(nodes['detail']['translation'], [0, 2, 0])
        with zipfile.ZipFile(io.BytesIO(to_usdz(meshes))) as archive:
            stage = archive.read('model.usda').decode()
        self.assertEqual(stage.count('def Mesh '), 3)
        self.assertEqual(stage.count('def GeomSubset '), 0)
        self.assertIn('def Xform "assembly"', stage)
        self.assertIn('def Xform "detail"', stage)

    def test_overrides_are_independent_of_dictionary_order(self):
        for overrides in (
            "{'assembly': {'baseColor': [0, 1, 0]}, 'bolt': {'baseColor': [1, 1, 0]}}",
            "{'bolt': {'baseColor': [1, 1, 0]}, 'assembly': {'baseColor': [0, 1, 0]}}",
        ):
            _, materials, _ = evaluate(SOURCE + '\nmaterials = ' + overrides, 'python', FakeBrep())
            self.assertEqual(materials['body']['baseColor'], [0, 1, 0])
            self.assertEqual(materials['bolt']['baseColor'], [1, 1, 0])
        _, materials, _ = evaluate(SOURCE + "\nmaterials = {'assembly': {'metallic': 1}}", 'python', FakeBrep())
        self.assertEqual(materials['bolt']['baseColor'], [0, 0, 1])
        self.assertEqual(materials['body']['metallic'], 1)

    def test_result_group_and_explicit_selection(self):
        objects, _, _ = evaluate("a = sm.create_box((0,0,0),1,1,1)\nresult = Group({'a': a})", 'python', FakeBrep())
        self.assertEqual(objects.top_groups, {'a': 'result'})
        objects, _, _ = evaluate("result = sm.create_box((0,0,0),1,1,1)\nobjects = {'chosen': sm.create_sphere((0,0,0),1)}", 'python', FakeBrep())
        self.assertEqual(list(objects), ['chosen'])

    def test_invalid_tree_fails_before_transforms(self):
        cases = [
            "objects = []", "objects = {}", "objects = {'bad-name': a}",
            "objects = {'a': a, 'b': a}", "objects = {'g': Group({'x': 3})}",
            "objects = {'g': Group({'g': a})}",
            "objects = {'g': Group({'a': a}, scale=(0,1,1))}",
            "objects = {'g': Group({'a': a}, invisible='true')}",
            "objects = {'g': Group({'a': a}, position=(0,0,float('nan')))}",
            "objects = {'g': Group({'a': a}, material={'metallic': 2})}",
            "objects = {'g': Group({'a': a})}\nmaterials = {'missing': {}}",
            "objects = {'g': Group({'a': a})}\nmaterials = []",
            "g = Group({})\ng.objects['child'] = g\nobjects = {'g': g}",
            "objects = {'g': Group([])}",
        ]
        for case in cases:
            sm = FakeBrep()
            with self.subTest(case=case), self.assertRaises(ValueError):
                evaluate("a = sm.create_box((0,0,0),1,1,1)\n" + case, 'python', sm)
            self.assertEqual(sm.transforms, [])

    def test_editable_example(self):
        root = Path(__file__).resolve().parents[1]
        document = json.loads((root / 'examples/python_groups.json').read_text())
        self.assertEqual(document['source'], (root / 'examples/python_groups.py').read_text())
        objects, materials, _ = evaluate(document['source'], 'python', FakeBrep())
        self.assertEqual(objects.top_groups, {'base': 'assembly', 'post': 'assembly', 'cap': 'assembly'})
        self.assertEqual(len(materials), 3)


if __name__ == '__main__':
    unittest.main()
