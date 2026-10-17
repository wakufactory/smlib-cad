import importlib.util
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server import Handler, ModelError, allowed_host, allowed_origin, run_model_request


class LanAccessTests(unittest.TestCase):
    def test_lan_and_explicit_localhost_hosts(self):
        port = 8765
        self.assertTrue(allowed_host("127.0.0.1:8765", "127.0.0.1", port))
        self.assertTrue(allowed_host("localhost:8765", "127.0.0.1", port))
        self.assertFalse(allowed_host("192.168.1.20:8765", "127.0.0.1", port))

        for host in ("localhost", "127.0.0.1", "192.168.1.20", "10.3.4.5", "172.20.0.8"):
            with self.subTest(host=host):
                self.assertTrue(allowed_host(f"{host}:8765", "0.0.0.0", port))

        for host in (
            "evil.example:8765", "8.8.8.8:8765", "0.0.0.0:8765",
            "192.168.1.20:8766", "192.168.1.20", "192.168.1.999:8765",
        ):
            with self.subTest(host=host):
                self.assertFalse(allowed_host(host, "0.0.0.0", port))

    def test_origin_must_match_browser_address(self):
        host = "192.168.1.20:8765"
        self.assertTrue(allowed_origin(f"http://{host}", host))
        self.assertTrue(allowed_origin("", host))
        self.assertFalse(allowed_origin("http://192.168.1.21:8765", host))
        self.assertFalse(allowed_origin("https://192.168.1.20:8765", host))


class ModelProcessTests(unittest.TestCase):
    def post(self, request):
        body = json.dumps(request).encode()
        handler = object.__new__(Handler)
        handler.path = "/preview"
        handler.headers = {"Host": "127.0.0.1:8765", "Content-Type": "application/json",
                           "Content-Length": str(len(body))}
        handler.server = SimpleNamespace(server_address=("127.0.0.1", 8765), server_port=8765)
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        responses = []
        handler.send_response = responses.append
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.do_POST()
        return responses[0], json.loads(handler.wfile.getvalue())

    def test_worker_crash_becomes_request_error(self):
        with patch("server.subprocess.run") as run:
            run.return_value.returncode = -11
            with self.assertRaisesRegex(ModelError, "異常終了"):
                run_model_request({"source": "box body 0 0 0 10 10 10",
                                   "mode": "text", "finish": "chamfer", "finishSize": 10}, "/preview")

    @unittest.skipUnless(importlib.util.find_spec("_smlib_core"), "native binding unavailable")
    def test_bad_finish_does_not_prevent_next_preview(self):
        request = {"source": "box body 0 0 0 10 10 10", "mode": "text",
                   "finish": "chamfer", "finishSize": 10}
        status, failure = self.post(request)
        self.assertEqual(status, 400)
        self.assertIn("異常終了", failure["error"])
        request["finishSize"] = 1
        status, result = self.post(request)
        self.assertEqual(status, 200)
        self.assertEqual(len(result["meshes"]), 1)
        self.assertGreater(len(result["meshes"][0]["positions"]), 0)
        self.assertEqual(run_model_request(request, "/export")[:4], b"glTF")
        self.assertEqual(run_model_request(request, "/export/usdz")[:2], b"PK")


if __name__ == "__main__":
    unittest.main()
