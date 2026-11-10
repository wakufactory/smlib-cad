"""Run one model request outside the long-lived HTTP server process."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from modeler import evaluate, tessellate
from model_export import to_glb, to_usdz
from animation import ModelAnimationSources, animation_text, prepare_animation, select_clip


def main(request_path: str, output_path: str, error_path: str) -> None:
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        mode = request.get("mode", "python")
        sources = ModelAnimationSources(request["source"], mode, request.get("animationSource", ""))
        if request["path"] == "/animation/resolve":
            animation = sources.resolve(request.get("animationGroups", []))
            Path(output_path).write_text(json.dumps({"resolvedAnimationSource": animation_text(animation)}),
                                         encoding="utf-8")
            return
        import _smlib_core as sm

        objects, materials, log = evaluate(sources.model, mode, sm, variables=sources.model_variables())
        meshes = tessellate(objects, sm, float(request.get("chord", 0.08)),
                            angle=float(request.get("angle", 20)), materials=materials)
        animation = sources.resolve(meshes)
        if request["path"] in ("/export/usdz", "/preview/usdz"):
            data = to_usdz(meshes, scale=request.get("exportScale", 1), resolved_animation=animation,
                           animation_clip=request.get("animationClip"))
        elif request["path"] == "/export":
            data = to_glb(meshes, scale=request.get("exportScale", 1), resolved_animation=animation)
        else:
            prepare_animation("", meshes, resolved=animation)  # Validate targets before returning the preview.
            data = json.dumps({"meshes": meshes, "log": log,
                               "resolvedAnimationSource": animation_text(animation)}).encode("utf-8")
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
