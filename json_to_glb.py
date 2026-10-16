"""Convert a saved SMLib Modeler JSON document to a GLB file."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from modeler import apply_finish, evaluate, tessellate, to_glb


ROOT = Path(__file__).resolve().parent


def _number(value, name: str, minimum: float, maximum: float = math.inf) -> float:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or not minimum <= value <= maximum):
        limit = f"{minimum} to {maximum}" if math.isfinite(maximum) else f"at least {minimum}"
        raise ValueError(f"{name} must be a finite number {limit}")
    return float(value)


def validate_document(document: object) -> tuple[str, str, dict]:
    """Validate the version 1 document written by the browser editor."""
    if not isinstance(document, dict):
        raise ValueError("model JSON must be an object")
    if (document.get("format") != "smlib-model" or type(document.get("version")) is not int
            or document["version"] != 1 or document.get("mode") not in ("text", "python")):
        raise ValueError("unsupported model format, version, or mode")
    source = document.get("source")
    if not isinstance(source, str):
        raise ValueError("source must be text")
    parameters = document.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    finish = parameters.get("finish")
    if finish not in ("none", "chamfer", "fillet"):
        raise ValueError("finish must be none, chamfer, or fillet")
    return source, document["mode"], {
        "chord": _number(parameters.get("chord"), "chord", 0.001, 2),
        "angle": _number(parameters.get("angle"), "angle", 1, 90),
        "finish": finish,
        "finishSize": _number(parameters.get("finishSize"), "finishSize", 0.001),
    }


def build_glb(document: object, sm) -> bytes:
    source, mode, parameters = validate_document(document)
    objects, materials, _ = evaluate(source, mode, sm)
    objects = apply_finish(objects, sm, parameters["finish"], parameters["finishSize"])
    meshes = tessellate(objects, sm, parameters["chord"], parameters["angle"], materials)
    return to_glb(meshes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON model saved by the browser editor")
    parser.add_argument("-o", "--output", type=Path, help="output GLB path (default: input name with .glb)")
    args = parser.parse_args(argv)
    output = args.output or args.input.with_suffix(".glb")
    try:
        if output.resolve() == args.input.resolve():
            raise ValueError("input and output paths must differ")
        document = json.loads(args.input.read_text(encoding="utf-8"))
        validate_document(document)
        sys.path.insert(0, str(ROOT / ".build" / "smlib-core"))
        try:
            import _smlib_core as sm
        except ImportError as exc:
            raise RuntimeError("_smlib_core is unavailable; run make in the CAD directory") from exc
        data = build_glb(document, sm)
        output.write_bytes(data)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {output} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
