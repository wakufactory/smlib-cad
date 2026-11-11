import io
import json
import struct
import unittest
import zipfile
from pathlib import Path

from modeler import evaluate, normalize_material, tessellate, to_glb, to_usdz
from test_modeler import FakeBrep


class MaterialOpacityTests(unittest.TestCase):
    def test_validation_and_default(self):
        self.assertEqual(normalize_material({})['opacity'], 1)
        for value in (0, 0.35, 1):
            self.assertEqual(normalize_material({'opacity': value})['opacity'], value)
        for value in (-0.1, 1.1, float('nan'), float('inf'), True, '0.5', None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'opacity'):
                normalize_material({'opacity': value})
        for tail in ('-0.1', '1.1'):
            with self.assertRaisesRegex(ValueError, 'Line 2: opacity'):
                evaluate('box a 0 0 0 1 1 1\nmaterial a 1 0 0 0 0.5 ' + tail,
                         'text', FakeBrep())

    def test_text_python_samples_match_and_export(self):
        results = []
        for mode, suffix in [('text', 'txt'), ('python', 'py')]:
            source = (Path(__file__).resolve().parents[1] / 'examples' /
                      ('material_opacity.' + suffix)).read_text()
            sm = FakeBrep()
            objects, materials, _ = evaluate(source, mode, sm)
            self.assertEqual(materials['cover']['opacity'], 0.25)
            self.assertEqual(materials['core']['opacity'], 1)
            results.append(materials)
            meshes = tessellate(objects, sm, materials=materials)
            data = to_glb(meshes)
            length = struct.unpack_from('<I', data, 12)[0]
            doc = json.loads(data[20:20+length])
            transparent = [m for m in doc['materials'] if m.get('alphaMode') == 'BLEND']
            self.assertEqual(len(transparent), 1)
            self.assertEqual(transparent[0]['pbrMetallicRoughness']['baseColorFactor'][3], 0.25)
            self.assertTrue(all(m.get('alphaMode', 'OPAQUE') == 'OPAQUE'
                                for m in doc['materials'] if m not in transparent))
            with zipfile.ZipFile(io.BytesIO(to_usdz(meshes))) as archive:
                stage = archive.read('model.usda').decode()
            self.assertIn('float inputs:opacity = 0.25', stage)
            self.assertIn('float inputs:opacityThreshold = 0', stage)
        self.assertEqual(*results)

    def test_opacity_distinguishes_materials_and_merged_meshes(self):
        source = ('group g\nbox a 0 0 0 1 1 1\nbox b 2 0 0 1 1 1\n'
                  'box c 4 0 0 1 1 1\nmaterial a 1 0 0 0 0.5 0\n'
                  'material b 1 0 0 0 0.5 0.5\nmaterial c 1 0 0 0 0.5\nend')
        sm = FakeBrep()
        objects, materials, _ = evaluate(source, 'text', sm)
        meshes = tessellate(objects, sm, materials=materials)
        data = to_glb(meshes)
        length = struct.unpack_from('<I', data, 12)[0]
        doc = json.loads(data[20:20+length])
        self.assertEqual(len(doc['materials']), 3)
        self.assertEqual(len(doc['meshes']), 3)
        self.assertEqual([m['pbrMetallicRoughness']['baseColorFactor'][3]
                          for m in doc['materials']], [0, 0.5, 1])
        with zipfile.ZipFile(io.BytesIO(to_usdz(meshes))) as archive:
            stage = archive.read('model.usda').decode()
        self.assertEqual(stage.count('def Material '), 3)
        self.assertEqual(stage.count('def Mesh '), 3)
