import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from json_to_glb import build_glb, validate_document
from test_modeler import FakeBrep


ROOT = Path(__file__).resolve().parents[1]
MODEL = {
    "format": "smlib-model", "version": 1, "mode": "text",
    "source": "box body 0 0 0 10 10 10\nmaterial body 0.8 0.2 0.1 0.5 0.3\n",
    "parameters": {"chord": 0.02, "angle": 12, "finish": "chamfer", "finishSize": 0.5},
}


class JsonToGlbTests(unittest.TestCase):
    def test_document_parameters_reach_kernel_and_glb(self):
        sm = FakeBrep()
        glb = build_glb(MODEL, sm)
        self.assertEqual(sm.last_chamfer[1], 0.5)
        self.assertEqual(sm.last_tessellation, {
            "chord_height_tolerance": 0.02,
            "curve_angle_tolerance_deg": 12,
            "surface_angle_tolerance_deg": 12,
        })
        self.assertEqual(glb[:4], b"glTF")
        json_length = struct.unpack_from("<I", glb, 12)[0]
        scene = json.loads(glb[20:20 + json_length])
        self.assertEqual(scene["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"],
                         [0.8, 0.2, 0.1, 1.0])

    def test_python_document_reaches_glb(self):
        python_model = {
            **MODEL, "mode": "python",
            "source": ("result = sm.create_box((0, 0, 0), 10, 10, 10)\n"
                       "materials = {'result': {'baseColor': [0.2, 0.4, 0.6]}}\n"),
        }
        sm = FakeBrep()
        glb = build_glb(python_model, sm)
        self.assertEqual(glb[:4], b"glTF")
        self.assertEqual(sm.last_chamfer[1], 0.5)
        json_length = struct.unpack_from("<I", glb, 12)[0]
        scene = json.loads(glb[20:20 + json_length])
        self.assertEqual(scene["nodes"][0]["name"], "result")
        self.assertEqual(scene["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"],
                         [0.2, 0.4, 0.6, 1.0])

    def test_invalid_documents_are_rejected(self):
        cases = [
            {**MODEL, "version": 2},
            {**MODEL, "mode": "other"},
            {**MODEL, "source": 10},
            {**MODEL, "parameters": {**MODEL["parameters"], "chord": 0}},
            {**MODEL, "parameters": {**MODEL["parameters"], "angle": 91}},
            {**MODEL, "parameters": {**MODEL["parameters"], "finish": "other"}},
            {**MODEL, "parameters": {**MODEL["parameters"], "finishSize": True}},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                validate_document(case)

    @unittest.skipUnless((ROOT / ".build" / "smlib-core").exists(), "_smlib_core not built")
    def test_cli_creates_glb_and_keeps_output_on_bad_input(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "sample.json"
            output = Path(directory) / "result.glb"
            model.write_text(json.dumps(MODEL), encoding="utf-8")
            command = [sys.executable, str(ROOT / "json_to_glb.py"), str(model), "-o", str(output)]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(output.read_bytes()[:4], b"glTF")
            default = subprocess.run(command[:-2], capture_output=True, text=True, check=False)
            self.assertEqual(default.returncode, 0, default.stderr)
            self.assertEqual(model.with_suffix(".glb").read_bytes()[:4], b"glTF")
            model.write_text(json.dumps({**MODEL, "mode": "python",
                                         "source": "result = sm.create_box((0, 0, 0), 2, 2, 2)\n"}),
                             encoding="utf-8")
            python = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(python.returncode, 0, python.stderr)
            self.assertEqual(output.read_bytes()[:4], b"glTF")
            original = output.read_bytes()
            model.write_text("{bad", encoding="utf-8")
            failed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
