"""Local HTTP front end for the USD BRep modeler."""

from __future__ import annotations

import argparse
import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from modeler import EXAMPLE_SCRIPT, EXAMPLE_TEXT, apply_finish, evaluate, tessellate, to_glb

ROOT = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, value):
        self._reply(code, json.dumps(value).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        if self.path == "/":
            self._reply(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/app.js":
            self._reply(200, (ROOT / "app.js").read_bytes(), "text/javascript; charset=utf-8")
        elif self.path == "/status":
            try:
                import _smlib_core  # noqa: F401
                self._json(200, {"ready": True})
            except ImportError as exc:
                self._json(200, {"ready": False, "error": str(exc)})
        elif self.path == "/examples":
            self._json(200, {"python": EXAMPLE_SCRIPT, "text": EXAMPLE_TEXT,
                             "gallery": (ROOT / "examples" / "all_primitives_materials.txt").read_text(),
                             "sweeps": (ROOT / "examples" / "extrude_revolve.txt").read_text(),
                             "offsets": (ROOT / "examples" / "offset_shell.txt").read_text(),
                             "circular": (ROOT / "examples" / "circular_csg_array.txt").read_text()})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ("/preview", "/export"):
            self.send_error(404)
            return
        try:
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin", "")
            if host not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"):
                raise ValueError("Invalid Host header")
            if origin and origin not in (f"http://127.0.0.1:{self.server.server_port}",
                                         f"http://localhost:{self.server.server_port}"):
                raise ValueError("Cross-origin requests are not allowed")
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                raise ValueError("Content-Type must be application/json")
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 100_000:
                raise ValueError("Source must be between 1 and 100000 bytes")
            request = json.loads(self.rfile.read(length))
            source = request["source"]
            if not isinstance(source, str):
                raise ValueError("source must be text")
            import _smlib_core as sm
            objects, materials, log = evaluate(source, request.get("mode", "python"), sm)
            objects = apply_finish(objects, sm, request.get("finish", "none"), request.get("finishSize", 1))
            meshes = tessellate(objects, sm, float(request.get("chord", 0.08)),
                                angle=float(request.get("angle", 20)), materials=materials)
            if self.path == "/export":
                self.send_response(200)
                data = to_glb(meshes)
                self.send_header("Content-Type", "model/gltf-binary")
                self.send_header("Content-Disposition", 'attachment; filename="model.glb"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._json(200, {"meshes": meshes, "log": log})
        except Exception as exc:
            self._json(400, {"error": str(exc), "traceback": traceback.format_exc(limit=5)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Open http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
