"""Run one model request outside the long-lived HTTP server process."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from modeler import apply_finish, evaluate, tessellate
from model_export import to_glb, to_usdz
from animation import prepare_animation, resolve_animation_source, select_clip


def main(request_path: str, output_path: str, error_path: str) -> None:
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        if request["path"] == "/animation/resolve":
            animation_source = resolve_animation_source(request.get("animationSource", ""),
                request["source"], request.get("mode", "python"), request.get("animationGroups", []))
            Path(output_path).write_text(json.dumps({"resolvedAnimationSource": animation_source}), encoding="utf-8")
            return
        import _smlib_core as sm

        objects, materials, log = evaluate(request["source"], request.get("mode", "python"), sm)
        objects = apply_finish(objects, sm, request.get("finish", "none"), request.get("finishSize", 1))
        meshes = tessellate(objects, sm, float(request.get("chord", 0.08)),
                            angle=float(request.get("angle", 20)), materials=materials)
        animation_source = resolve_animation_source(request.get("animationSource", ""),
            request["source"], request.get("mode", "python"), meshes)
        animation, _ = prepare_animation(animation_source, meshes)
        if request["path"] in ("/export/usdz", "/preview/usdz"):
            data = to_usdz(meshes, scale=request.get("exportScale", 1), animation_source=animation_source, animation_clip=request.get("animationClip"))
        elif request["path"] == "/export":
            data = to_glb(meshes, scale=request.get("exportScale", 1), animation_source=animation_source)
        else:
            data = json.dumps({"meshes": meshes, "log": log, "resolvedAnimationSource": animation_source}).encode("utf-8")
        if request["path"] == "/preview/usdz":
            # Keep the USDZ response binary; pass small UI metadata separately.
            selected = select_clip(animation, request.get("animationClip"))
            metadata = {"animationClips": [{"name": clip["name"]} for clip in animation["clips"]] if animation else [],
                "animationClip": selected["name"] if selected else "", "objects": [
                {"name": mesh["name"], "groupPath": [{"name": group["name"]}
                 for group in mesh.get("groupPath", [])]} for mesh in meshes]}
            Path(output_path + ".json").write_text(json.dumps(metadata), encoding="utf-8")
        Path(output_path).write_bytes(data)
    except Exception as exc:
        Path(error_path).write_text(json.dumps({"error": str(exc),
                                               "traceback": traceback.format_exc(limit=5)}),
                                    encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:])
