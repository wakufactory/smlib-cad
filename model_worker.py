"""Run one model request outside the long-lived HTTP server process."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from modeler import apply_finish, evaluate, tessellate, to_glb, to_usdz


def main(request_path: str, output_path: str, error_path: str) -> None:
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        import _smlib_core as sm

        objects, materials, log = evaluate(request["source"], request.get("mode", "python"), sm)
        objects = apply_finish(objects, sm, request.get("finish", "none"), request.get("finishSize", 1))
        meshes = tessellate(objects, sm, float(request.get("chord", 0.08)),
                            angle=float(request.get("angle", 20)), materials=materials)
        if request["path"] in ("/export/usdz", "/preview/usdz"):
            data = to_usdz(meshes)
        elif request["path"] == "/export":
            data = to_glb(meshes)
        else:
            data = json.dumps({"meshes": meshes, "log": log}).encode("utf-8")
        Path(output_path).write_bytes(data)
    except Exception as exc:
        Path(error_path).write_text(json.dumps({"error": str(exc),
                                               "traceback": traceback.format_exc(limit=5)}),
                                    encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:])
