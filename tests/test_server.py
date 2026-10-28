import importlib.util
import io
import json
import ssl
import subprocess
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch

from server import Handler, ModelError, ModelHTTPServer, PreviewStore, allowed_host, allowed_origin, run_model_request


class LanAccessTests(unittest.TestCase):
    def test_only_certificate_rejection_logs_are_suppressed(self):
        server = object.__new__(ModelHTTPServer)
        with patch.object(ThreadingHTTPServer, "handle_error") as parent:
            for reason in ("SSLV3_ALERT_CERTIFICATE_UNKNOWN", "TLSV1_ALERT_UNKNOWN_CA"):
                error = ssl.SSLError(1, reason)
                error.reason = reason
                try:
                    raise error
                except ssl.SSLError:
                    server.handle_error(None, ("127.0.0.1", 1234))
            parent.assert_not_called()

            error = ssl.SSLError(1, "WRONG_VERSION_NUMBER")
            error.reason = "WRONG_VERSION_NUMBER"
            try:
                raise error
            except ssl.SSLError:
                server.handle_error(None, ("127.0.0.1", 1234))
            parent.assert_called_once()

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
        self.assertTrue(allowed_origin("https://192.168.1.20:8765", host, "https"))
        self.assertFalse(allowed_origin("http://192.168.1.20:8765", host, "https"))

    def test_preview_store_uses_bounded_opaque_urls(self):
        store = PreviewStore(limit=2)
        first = store.put(b"first")
        second = store.put(b"second")
        self.assertNotEqual(first, second)
        self.assertEqual(store.get(first.split("/")[-1][:-5]), b"first")
        store.put(b"third")
        self.assertIsNone(store.get(first.split("/")[-1][:-5]))


class ChatRouteTests(unittest.TestCase):
    def handler(self, path, request=None, headers=None):
        handler = object.__new__(Handler)
        body = json.dumps(request or {}).encode()
        handler.path = path
        handler.headers = {"Host": "127.0.0.1:8765", "Content-Type": "application/json",
                           "Content-Length": str(len(body)), **(headers or {})}
        handler.server = SimpleNamespace(server_address=("127.0.0.1", 8765), server_port=8765, chat=Mock())
        handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
        handler.responses = []
        handler.send_response = handler.responses.append
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        return handler

    def test_chat_routes_do_not_require_model_source_except_send(self):
        for action, method in (("login", "login_start"), ("send", "send"), ("poll", "poll"),
                               ("cancel", "cancel"), ("reset", "reset")):
            with self.subTest(action=action):
                handler = self.handler("/chat/" + action, {"sessionId": "browser"})
                target = getattr(handler.server.chat, method)
                target.return_value = {"ok": True}
                handler.do_POST()
                self.assertEqual(handler.responses, [200])
                self.assertEqual(json.loads(handler.wfile.getvalue()), {"ok": True})
                target.assert_called_once()

    def test_chat_status_and_mutations_keep_host_origin_guards(self):
        for path in ("/chat/status", "/chat/login", "/chat/send"):
            for headers in ({"Host": "evil.example:8765"}, {"Origin": "https://evil.example"}):
                handler = self.handler(path, headers=headers)
                (handler.do_GET if path == "/chat/status" else handler.do_POST)()
                self.assertEqual(handler.responses, [400])
                self.assertFalse(handler.server.chat.mock_calls)
        handler = self.handler("/chat/status")
        handler.server.chat.status.return_value = {"ready": False}
        handler.do_GET()
        self.assertEqual(handler.responses, [200])

    def test_chat_requires_json_and_session_id(self):
        for path, headers in (("/chat/poll", {}), ("/chat/login", {"Content-Type": "text/plain"})):
            handler = self.handler(path, headers=headers)
            handler.do_POST()
            self.assertEqual(handler.responses, [400])
            self.assertFalse(handler.server.chat.mock_calls)


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

    def test_worker_timeout_returns_error_after_ten_seconds(self):
        with patch("server.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 10)) as run:
            status, failure = self.post({"source": "import time; time.sleep(15)", "mode": "python"})
        self.assertEqual(status, 400)
        self.assertIn("10秒以内", failure["error"])
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

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
        self.assertEqual(run_model_request(request, "/preview/usdz")[:2], b"PK")
        original_glb = run_model_request(request, "/export")
        original_preview = run_model_request(request, "/preview/usdz")
        request["exportScale"] = 0.5
        scaled_glb = run_model_request(request, "/export")
        self.assertNotEqual(scaled_glb, original_glb)
        scaled_usdz = run_model_request(request, "/export/usdz")
        self.assertNotEqual(scaled_usdz, original_preview)
        self.assertEqual(run_model_request(request, "/preview/usdz"), scaled_usdz)
        self.assertEqual(run_model_request(request, "/preview"), run_model_request({**request, "exportScale": 1}, "/preview"))


if __name__ == "__main__":
    unittest.main()
