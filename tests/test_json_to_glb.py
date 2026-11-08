import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from json_to_glb import build_glb, build_usdz, validate_document
from test_modeler import FakeBrep


ROOT = Path(__file__).resolve().parents[1]
MODEL = {
    "format": "smlib-model", "version": 1, "mode": "text",
    "source": "box body 0 0 0 10 10 10\nmaterial body 0.8 0.2 0.1 0.5 0.3\n",
    "parameters": {"chord": 0.02, "angle": 12, "finish": "chamfer", "finishSize": 0.5},
}


class JsonToGlbTests(unittest.TestCase):
    def test_model_calculations_in_animation_export(self):
        source = ('let rpm = 120\nfn angle(t) = 360 * rpm * t / 60\n'
                  'group rotor\nbox body 0 0 0 1 1 1\nend\n')
        animation = ('animation main loop 4\ntrack rotor\nkey 0 euler 0 0 0\n'
                     'key 4 euler 0 0 ${angle(4)}\nend\nend')
        document = {**MODEL, 'source': source, 'animationSource': animation}
        numeric = {**document, 'animationSource': animation.replace('${angle(4)}', '2880')}
        self.assertEqual(build_glb(document, FakeBrep()), build_glb(numeric, FakeBrep()))
        self.assertEqual(build_usdz(document, FakeBrep()), build_usdz(numeric, FakeBrep()))

    def test_saved_object_tree_is_optional_metadata_for_cli_export(self):
        with_tree = {**MODEL, "objectTree": [
            {"type": "group", "name": "previous_preview", "children": [
                {"type": "solid", "name": "previous_solid"}]}]}
        self.assertEqual(build_glb(with_tree, FakeBrep()), build_glb(MODEL, FakeBrep()))

    def test_document_parameters_reach_kernel_and_glb(self):
        sm = FakeBrep()
        glb = build_glb(MODEL, sm)
        self.assertFalse(hasattr(sm, "last_chamfer"))
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
        self.assertFalse(hasattr(sm, "last_chamfer"))
        json_length = struct.unpack_from("<I", glb, 12)[0]
        scene = json.loads(glb[20:20 + json_length])
        self.assertEqual(scene["nodes"][0]["name"], "result")
        self.assertEqual(scene["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"],
                         [0.2, 0.4, 0.6, 1.0])

    def test_export_scale_from_document_changes_positions(self):
        scaled = {**MODEL, "parameters": {**MODEL["parameters"], "exportScale": 0.5}}
        self.assertEqual(validate_document(MODEL)[2]["exportScale"], 1)
        default_glb = build_glb(MODEL, FakeBrep())
        scaled_glb = build_glb(scaled, FakeBrep())

        def first_position(data):
            json_length = struct.unpack_from("<I", data, 12)[0]
            scene = json.loads(data[20:20 + json_length])
            index = scene["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
            accessor = scene["accessors"][index]
            view = scene["bufferViews"][accessor["bufferView"]]
            return struct.unpack_from("<3f", data, 20 + json_length + 8 + view["byteOffset"])

        original = first_position(default_glb)
        self.assertEqual(first_position(scaled_glb), tuple(value * 0.5 for value in original))

    def test_legacy_finish_parameters_are_ignored(self):
        clean = {**MODEL, "parameters": {"chord": 0.02, "angle": 12}}
        for finish, size in (("fillet", 1000), ("other", None), ({}, True)):
            legacy = {**MODEL, "parameters": {**clean["parameters"], "finish": finish, "finishSize": size}}
            self.assertEqual(validate_document(legacy), validate_document(clean))
            for build in (build_glb, build_usdz):
                self.assertEqual(build(legacy, FakeBrep()), build(clean, FakeBrep()))

    def test_invalid_documents_are_rejected(self):
        cases = [
            {**MODEL, "version": 2},
            {**MODEL, "mode": "other"},
            {**MODEL, "source": 10},
            {**MODEL, "parameters": {**MODEL["parameters"], "chord": 0}},
            {**MODEL, "parameters": {**MODEL["parameters"], "angle": 91}},
            {**MODEL, "parameters": {**MODEL["parameters"], "exportScale": 0}},
            {**MODEL, "parameters": {**MODEL["parameters"], "exportScale": "2"}},
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
            command = [sys.executable, str(ROOT / "server" / "json_to_glb.py"), str(model), "-o", str(output)]
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
