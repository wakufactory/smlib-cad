import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from json_to_glb import build_usdz
from modeler import to_usdz
from test_modeler import FakeBrep


ROOT = Path(__file__).resolve().parents[1]
MODEL = {
    "format": "smlib-model", "version": 1, "mode": "text",
    "source": "box red 0 0 0 1 1 1\nbox blue 2 0 0 1 1 1\nmaterial red 0.8 0.1 0.1 0 0.5\nmaterial blue 0.1 0.2 0.8 1 0.2\n",
    "parameters": {"chord": 0.02, "angle": 12, "finish": "none", "finishSize": 1},
}


class UsdzTests(unittest.TestCase):
    def test_document_exports_aligned_usd_with_meshes_and_materials(self):
        sm = FakeBrep()
        data = build_usdz(MODEL, sm)
        self.assertEqual(sm.last_tessellation["curve_angle_tolerance_deg"], 12)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(archive.namelist(), ["model.usda"])
            info = archive.infolist()[0]
            self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
            self.assertEqual(info.flag_bits & 1, 0)
            name_len, extra_len = struct.unpack_from("<HH", data, info.header_offset + 26)
            self.assertEqual((info.header_offset + 30 + name_len + extra_len) % 64, 0)
            stage = archive.read(info).decode("utf-8")
        self.assertIn('defaultPrim = "Model"', stage)
        self.assertIn('upAxis = "Z"', stage)
        self.assertIn('metersPerUnit = 1', stage)
        self.assertEqual(stage.count('def Mesh "Mesh_'), 2)
        self.assertIn('sourceName = "red"', stage)
        self.assertIn('sourceName = "blue"', stage)
        self.assertIn('color3f inputs:diffuseColor = (0.8, 0.1, 0.1)', stage)
        self.assertIn('float inputs:metallic = 1', stage)
        self.assertIn('uniform token subdivisionScheme = "none"', stage)
        self.assertIn('rel material:binding = </Model/Materials/Material_1>', stage)

    def test_invalid_mesh_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "matching triangles"):
            to_usdz([{"name": "bad", "positions": [0, 0, 0], "normals": []}])

    def test_top_level_groups_become_separate_meshes(self):
        model = {**MODEL, "source": (
            "group left\nbox a 0 0 0 1 1 1\nbox b 2 0 0 1 1 1\nend\n"
            "group right\nbox c 4 0 0 1 1 1\nend\n")}
        with zipfile.ZipFile(io.BytesIO(build_usdz(model, FakeBrep()))) as archive:
            stage = archive.read("model.usda").decode("utf-8")
        self.assertEqual(stage.count('def Mesh "Mesh_'), 2)
        self.assertIn('sourceName = "left"', stage)
        self.assertIn('sourceName = "right"', stage)
        self.assertIn('sourceSolids = ["a", "b"]', stage)
        self.assertNotIn('def GeomSubset', stage)

    def test_multiple_materials_share_group_mesh_with_face_subsets(self):
        model = {**MODEL, "source": (
            "group assembly\n"
            "box red 0 0 0 1 1 1\nbox blue 2 0 0 1 1 1\n"
            "material red 1 0 0 0 0.5\nmaterial blue 0 0 1 0 0.5\nend\n")}
        with zipfile.ZipFile(io.BytesIO(build_usdz(model, FakeBrep()))) as archive:
            stage = archive.read("model.usda").decode("utf-8")
        self.assertEqual(stage.count('def Mesh "Mesh_'), 1)
        self.assertEqual(stage.count('def GeomSubset "MaterialSubset_'), 2)
        self.assertIn('subsetFamily:materialBind:familyType = "partition"', stage)
        self.assertIn('familyName = "materialBind"', stage)
        self.assertIn('indices = [0, 1]', stage)
        self.assertIn('indices = [2, 3]', stage)

    @unittest.skipUnless((ROOT / ".build" / "smlib-core").exists(), "_smlib_core not built")
    def test_cli_creates_usdz_and_preserves_existing_output_on_error(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "sample.json"
            output = Path(directory) / "result.usdz"
            model.write_text(json.dumps(MODEL), encoding="utf-8")
            command = [sys.executable, str(ROOT / "json_to_usdz.py"), str(model), "-o", str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), ["model.usda"])
            model.write_text("{bad", encoding="utf-8")
            original = output.read_bytes()
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
