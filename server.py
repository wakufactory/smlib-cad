"""Local HTTP front end for the USD BRep modeler."""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
import tempfile
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from modeler import EXAMPLE_SCRIPT, EXAMPLE_TEXT

ROOT = Path(__file__).resolve().parent


class ModelError(Exception):
    def __init__(self, error: str, details: str = ""):
        super().__init__(error)
        self.details = details


def run_model_request(request: dict, path: str) -> bytes:
    """Keep native kernel faults in a disposable process for each request."""
    with tempfile.TemporaryDirectory(prefix="cad-model-") as directory:
        work = Path(directory)
        request_path, output_path, error_path = (work / name for name in ("request.json", "output", "error.json"))
        request_path.write_text(json.dumps({**request, "path": path}), encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, str(ROOT / "model_worker.py"), str(request_path), str(output_path), str(error_path)],
                capture_output=True, timeout=120, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ModelError("形状計算が時間内に完了しませんでした") from exc
        if error_path.exists():
            failure = json.loads(error_path.read_text(encoding="utf-8"))
            raise ModelError(failure["error"], failure["traceback"])
        if completed.returncode or not output_path.exists():
            hint = "全体加工の幅/半径を小さくして再試行してください。" if request.get("finish") != "none" else "入力形状を確認してください。"
            raise ModelError(f"形状計算が異常終了しました。{hint}")
        return output_path.read_bytes()


def allowed_host(host_header: str, bind_host: str, port: int) -> bool:
    name, separator, request_port = host_header.rpartition(":")
    if not separator or request_port != str(port):
        return False
    if name == "localhost":
        return bind_host in ("127.0.0.1", "0.0.0.0")
    try:
        address = ipaddress.IPv4Address(name)
    except ipaddress.AddressValueError:
        return False
    if bind_host == "0.0.0.0":
        return (address.is_private or address.is_loopback or address.is_link_local) and not (
            address.is_unspecified or address.is_multicast or address.is_reserved
        )
    return name == bind_host


def allowed_origin(origin: str, host_header: str) -> bool:
    return not origin or origin == f"http://{host_header}"


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
        if self.path not in ("/preview", "/export", "/export/usdz"):
            self.send_error(404)
            return
        try:
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin", "")
            if not allowed_host(host, self.server.server_address[0], self.server.server_port):
                raise ValueError("Invalid Host header")
            if not allowed_origin(origin, host):
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
            data = run_model_request(request, self.path)
            if self.path in ("/export", "/export/usdz"):
                usdz = self.path == "/export/usdz"
                self.send_response(200)
                self.send_header("Content-Type", "model/vnd.usdz+zip" if usdz else "model/gltf-binary")
                self.send_header("Content-Disposition", 'attachment; filename="model.usdz"' if usdz else 'attachment; filename="model.glb"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._reply(200, data, "application/json; charset=utf-8")
        except ModelError as exc:
            self._json(400, {"error": str(exc), "traceback": exc.details})
        except Exception as exc:
            self._json(400, {"error": str(exc), "traceback": traceback.format_exc(limit=5)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="IPv4 listen address (default: 0.0.0.0; use 127.0.0.1 for local only)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        ipaddress.IPv4Address(args.host)
    except ipaddress.AddressValueError:
        parser.error("--host must be an IPv4 address")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    if args.host == "0.0.0.0":
        print(f"Listening on all IPv4 interfaces, port {args.port}. Open http://<this Mac's LAN IPv4>:{args.port}", flush=True)
    else:
        print(f"Open http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
