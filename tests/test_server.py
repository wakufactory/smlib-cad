import importlib.util
import io
import json
import ssl
import subprocess
import tempfile
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch

from server import Handler, ModelError, ModelHTTPServer, PreviewStore, allowed_host, allowed_origin, run_model_request, load_examples, main


class LanAccessTests(unittest.TestCase):
    def test_startup_save_directory_is_optional_and_created(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'new' / '保存 folder'
            for options, expected in (([], None), (['--save-dir', str(directory)], directory)):
                with patch('sys.argv', ['server.py', *options]), patch('server.ModelHTTPServer') as factory, patch('builtins.print'):
                    main()
                self.assertEqual(factory.return_value.save_dir, expected.resolve() if expected else None)
                factory.return_value.serve_forever.assert_called_once()
                factory.return_value.server_close.assert_called_once()
            self.assertTrue(directory.is_dir())

    def test_animation_resolution_worker_does_not_execute_geometry(self):
        request = {'mode': 'text', 'source': 'let rpm = 120\nfn angle(t) = 360*rpm*t/60\nnot_a_geometry_command\n',
                   'animationSource': 'animation main loop 4\ntrack rotor\nkey 0 euler 0 0 0\nkey 4 euler 0 0 ${angle(4)}\nend\nend'}
        data = json.loads(run_model_request(request, '/animation/resolve'))
        self.assertIn('key 4 euler 0 0 2880', data['resolvedAnimationSource'])
        request['mode'] = 'python'
        request['source'] = 'raise RuntimeError("Python must not execute")'
        request['animationSource'] = request['animationSource'].replace('${angle(4)}', '360')
        self.assertIn('key 4 euler 0 0 360', json.loads(run_model_request(request, '/animation/resolve'))['resolvedAnimationSource'])

    def test_sample_variants_include_python_groups_and_optional_python_files(self):
        from pathlib import Path
        import tempfile
        examples = load_examples()
        self.assertIn("Group(", examples["variants"]["groups"]["python"])
        self.assertEqual(examples["gallery"], examples["variants"]["gallery"]["text"])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'examples').mkdir()
            (root / 'examples' / 'all_primitives_materials.py').write_text('python gallery')
            with patch('server.ROOT', root):
                self.assertEqual(load_examples()['variants']['gallery'], {'python': 'python gallery'})

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

    def test_json_download_is_stored_exactly_and_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            for content in ('{"source":"初回"}\n', '{"source":"更新", "chat": {}}\n'):
                handler = self.handler('/save/json', {'filename': '設計 model.json', 'content': content})
                handler.server.save_dir = Path(folder)
                with patch('server.run_model_request') as worker:
                    handler.do_POST()
                worker.assert_not_called()
                self.assertEqual(handler.responses, [200])
                self.assertEqual((Path(folder) / '設計 model.json').read_bytes(), content.encode())
                self.assertEqual((Path(folder) / '設計 model.json').stat().st_mode & 0o777, 0o644)
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_json_save_without_directory_and_invalid_requests(self):
        handler = self.handler('/save/json', {'filename': 'model.json', 'content': '{}'})
        handler.do_POST()
        self.assertEqual(json.loads(handler.wfile.getvalue()), {'saved': False})
        handler = self.handler('/save/json', {'filename': 'large.json', 'content': json.dumps({'source': 'x' * 200_000})})
        handler.do_POST()
        self.assertEqual(handler.responses, [200])
        for name in ('../escape.json', '/tmp/escape.json', 'folder\\escape.json', 'a.glb', '', '..json'):
            handler = self.handler('/save/json', {'filename': name, 'content': '{}'})
            handler.do_POST()
            self.assertEqual(handler.responses, [400], name)
        for content in ('broken json', '[]', None):
            handler = self.handler('/save/json', {'filename': 'model.json', 'content': content})
            handler.do_POST()
            self.assertEqual(handler.responses, [400])
        for headers in ({'Origin': 'https://evil.example'}, {'Host': 'evil.example:8765'}):
            handler = self.handler('/save/json', {'filename': 'model.json', 'content': '{}'}, headers)
            handler.do_POST()
            self.assertEqual(handler.responses, [400])

    def test_save_failure_returns_error_and_symlink_is_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root / 'outside.json'
            outside.write_text('original')
            directory = root / 'downloads'
            directory.mkdir()
            (directory / 'model.json').symlink_to(outside)
            handler = self.handler('/save/json', {'filename': 'model.json', 'content': '{}'})
            handler.server.save_dir = directory
            handler.do_POST()
            self.assertEqual(handler.responses, [200])
            self.assertEqual(outside.read_text(), 'original')
            self.assertFalse((directory / 'model.json').is_symlink())
            handler = self.handler('/save/json', {'filename': 'model.json', 'content': '{}'})
            handler.server.save_dir = directory
            with patch('server.store_download', side_effect=OSError('disk full')):
                handler.do_POST()
            self.assertEqual(handler.responses, [400])
            self.assertIn('disk full', json.loads(handler.wfile.getvalue())['error'])

    def test_client_assets_are_served_from_html_directory(self):
        from pathlib import Path
        html_dir = Path(__file__).resolve().parents[1] / "html"
        for route, name in (("/", "index.html"), ("/app.js", "app.js"),
                            ("/animation.js", "animation.js"), ("/chat.js", "chat.js"),
                            ("/command-reference.js", "command-reference.js")):
            with self.subTest(route=route):
                handler = self.handler(route)
                headers = {}
                handler.send_header = headers.__setitem__
                handler.do_GET()
                self.assertEqual(handler.responses, [200])
                self.assertEqual(handler.wfile.getvalue(), (html_dir / name).read_bytes())
                self.assertIn("text/html" if name.endswith(".html") else "text/javascript",
                              headers["Content-Type"])

    def test_export_headers_count_meshes_and_deduplicated_materials(self):
        from modeler import evaluate, tessellate, to_glb, to_usdz
        from test_modeler import FakeBrep
        sm = FakeBrep()
        objects, materials, _ = evaluate(
            "group outer\ngroup inner\nbox a 0 0 0 1 1 1\nend\n"
            "box b 2 0 0 1 1 1\nend\n", "text", sm)
        meshes = tessellate(objects, sm, materials=materials)
        for path, encode in (("/export", to_glb), ("/export/usdz", to_usdz)):
            with self.subTest(path=path):
                data = encode(meshes)
                handler = self.handler(path, {"source": "test"})
                headers = {}
                handler.send_header = headers.__setitem__
                with patch("server.run_model_request", return_value=data):
                    handler.do_POST()
                self.assertEqual(handler.responses, [200])
                self.assertEqual(headers["X-Mesh-Count"], "2")
                self.assertEqual(headers["X-Material-Count"], "1")
                self.assertEqual(handler.wfile.getvalue(), data)
                with tempfile.TemporaryDirectory() as folder:
                    name = '設計 model' + ('.usdz' if path.endswith('usdz') else '.glb')
                    target = Path(folder) / name
                    target.write_bytes(b'old')
                    target.chmod(0o600)
                    handler = self.handler(path, {'source': 'test', 'filename': name})
                    handler.server.save_dir = Path(folder)
                    with patch('server.run_model_request', return_value=data):
                        handler.do_POST()
                    self.assertEqual(handler.responses, [200])
                    self.assertEqual(target.read_bytes(), handler.wfile.getvalue())
                    self.assertEqual(target.read_bytes(), data)
                    self.assertEqual(target.stat().st_mode & 0o777, 0o644)

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
    def post(self, request, path="/preview"):
        body = json.dumps(request).encode()
        handler = object.__new__(Handler)
        handler.path = path
        handler.headers = {"Host": "127.0.0.1:8765", "Content-Type": "application/json",
                           "Content-Length": str(len(body))}
        handler.server = SimpleNamespace(server_address=("127.0.0.1", 8765), server_port=8765,
                                         preview_store=PreviewStore())
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        responses = []
        handler.send_response = responses.append
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.do_POST()
        return responses[0], json.loads(handler.wfile.getvalue())

    def test_animation_resolver_http_route(self):
        status, data = self.post({'mode': 'text', 'source': 'let turns = 2',
                                  'animationSource': 'animation main loop 4\ntrack rotor\nkey 0 euler 0 0 0\nkey 4 euler 0 0 ${turns*360}\nend\nend'},
                                 '/animation/resolve')
        self.assertEqual(status, 200)
        self.assertIn('key 4 euler 0 0 720', data['resolvedAnimationSource'])

    @unittest.skipUnless(importlib.util.find_spec("_smlib_core"), "native binding unavailable")
    def test_animation_model_references_reach_preview_and_exports(self):
        request = {'mode': 'text', 'source': 'let turns = 2\ngroup rotor\nbox body 0 0 0 1 1 1\nend',
                   'animationSource': 'animation main loop 4\ntrack rotor\nkey 0 euler 0 0 0\nkey 4 euler 0 0 ${turns*360}\nend\nend'}
        status, data = self.post(request)
        self.assertEqual(status, 200)
        self.assertEqual(len(data['meshes']), 1)
        self.assertIn('key 4 euler 0 0 720', data['resolvedAnimationSource'])
        for path in ('/export', '/export/usdz'):
            self.assertEqual(run_model_request(request, path), run_model_request({**request, 'animationSource': data['resolvedAnimationSource']}, path))

    @unittest.skipUnless(importlib.util.find_spec("_smlib_core"), "native binding unavailable")
    def test_usdz_preview_returns_names_without_mesh_arrays(self):
        source = ("group assembly\ngroup detail\nbox body 0 0 0 2 2 2\nend\nend\n"
                  "box plain 4 0 0 1 1 1")
        status, result = self.post({"source": source, "mode": "text"}, "/preview/usdz")
        self.assertEqual(status, 200)
        self.assertTrue(result["url"].endswith(".usdz"))
        self.assertEqual(result["objects"], [
            {"name": "body", "groupPath": [{"name": "assembly"}, {"name": "detail"}]},
            {"name": "plain", "groupPath": []},
        ])

    def test_worker_crash_becomes_request_error(self):
        with patch("server.subprocess.run") as run:
            run.return_value.returncode = -11
            with self.assertRaisesRegex(ModelError, "異常終了"):
                run_model_request({"source": "box body 0 0 0 10 10 10",
                                   "mode": "text", "finish": "chamfer", "finishSize": 10}, "/preview")

    def test_worker_timeout_returns_error_after_sixty_seconds(self):
        with patch("server.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 60)) as run:
            status, failure = self.post({"source": "import time; time.sleep(65)", "mode": "python"})
        self.assertEqual(status, 400)
        self.assertIn("60秒以内", failure["error"])
        self.assertEqual(run.call_args.kwargs["timeout"], 60)

    @unittest.skipUnless(importlib.util.find_spec("_smlib_core"), "native binding unavailable")
    def test_legacy_finish_is_ignored(self):
        request = {"source": "box body 0 0 0 10 10 10", "mode": "text",
                   "finish": "chamfer", "finishSize": 10}
        status, legacy = self.post(request)
        self.assertEqual(status, 200)
        del request["finish"]
        del request["finishSize"]
        status, result = self.post(request)
        self.assertEqual(status, 200)
        self.assertEqual(legacy, result)
        for path in ("/export", "/export/usdz", "/preview/usdz"):
            self.assertEqual(run_model_request({**request, "finish": "fillet", "finishSize": None}, path),
                             run_model_request(request, path))
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
