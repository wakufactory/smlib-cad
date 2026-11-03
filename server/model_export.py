"""GLB/USDZ mesh serialization, independent of the native modeling kernel."""

import io
import json
import math
import struct
import zipfile

from modeler import normalize_material
from transforms import _group_quaternion, _group_rotation
from animation import prepare_animation, animation_meshes, sample_times, sample_track


def _export_scale(scale):
    if (isinstance(scale, bool) or not isinstance(scale, (int, float))
            or not math.isfinite(scale) or scale <= 0):
        raise ValueError("Export scale must be a positive finite number")
    return float(scale)


def _scaled_positions(positions, scale):
    scaled = [float(value) * scale for value in positions]
    # Both file formats store mesh points as 32-bit floats.
    if not all(math.isfinite(value) and abs(value) <= 3.402823466e38 for value in scaled):
        raise ValueError("Scaled coordinates exceed the exportable range")
    return scaled


def _export_meshes(meshes):
    """Keep preview/native geometry baked; recover local vertices only for export.

    Inverting each ancestor separately preserves nested nonuniform scale and
    rotation (including the shear their composition can produce). Normals use
    the transpose of the forward linear map, then are normalized.
    Legacy callers without groupPath retain their explicit mesh aggregation.
    """
    output = []
    for mesh in meshes:
        if "groupPath" not in mesh:
            output.append(mesh)
            continue
        positions, normals = list(mesh["positions"]), list(mesh["normals"])
        for group in mesh["groupPath"]:
            rotation = _group_rotation(group)
            factors, offset = group["scale"], group["position"]
            for i in range(0, len(positions), 3):
                point = [positions[i+j] - offset[j] for j in range(3)]
                normal = normals[i:i+3]
                positions[i:i+3] = [sum(rotation[k][j]*point[k] for k in range(3)) / factors[j]
                                    for j in range(3)]
                normals[i:i+3] = [sum(rotation[k][j]*normal[k] for k in range(3)) * factors[j]
                                  for j in range(3)]
        for i in range(0, len(normals), 3):
            length = math.hypot(*normals[i:i+3])
            if length:
                normals[i:i+3] = [value / length for value in normals[i:i+3]]
        output.append(dict(mesh, positions=positions, normals=normals, group=mesh["name"]))
    return output


def to_glb(meshes, scale=1, animation_source=""):
    """Encode recursive group TRS and individually selectable solid meshes."""
    scale = _export_scale(scale)
    animation, bound = prepare_animation(animation_source, meshes)
    meshes = animation_meshes(_export_meshes(meshes), bound) if bound else _export_meshes(meshes)
    if not meshes:
        doc = {"asset": {"version": "2.0", "generator": "USD BRep Modeler"},
               "scene": 0, "scenes": [{}]}
        js = json.dumps(doc, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        return (struct.pack("<4sII", b"glTF", 2, 20 + len(js)) +
                struct.pack("<I4s", len(js), b"JSON") + js)
    blob = bytearray()
    doc = {"asset": {"version": "2.0", "generator": "USD BRep Modeler"},
           "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
           "buffers": [], "bufferViews": [], "accessors": [], "materials": []}
    material_indices = {}
    groups = {}

    def accessor(values, kind, target):
        while len(blob) % 4:
            blob.append(0)
        offset = len(blob)
        blob.extend(struct.pack("<" + "f" * len(values), *values))
        view = len(doc["bufferViews"])
        doc["bufferViews"].append({"buffer": 0, "byteOffset": offset,
                                   "byteLength": len(values)*4, "target": target})
        acc = {"bufferView": view, "componentType": 5126, "count": len(values)//3,
               "type": "VEC3"}
        if kind == "POSITION":
            triples = [values[i:i+3] for i in range(0, len(values), 3)]
            acc["min"] = [min(v[j] for v in triples) for j in range(3)]
            acc["max"] = [max(v[j] for v in triples) for j in range(3)]
        doc["accessors"].append(acc)
        return len(doc["accessors"]) - 1

    for mesh in meshes:
        material = normalize_material(mesh.get("material", {}))
        material_key = (tuple(material["baseColor"]), material["metallic"], material["roughness"])
        if material_key not in material_indices:
            material_indices[material_key] = len(doc["materials"])
            doc["materials"].append({"pbrMetallicRoughness": {
                "baseColorFactor": [*material["baseColor"], 1.0],
                "metallicFactor": material["metallic"],
                "roughnessFactor": material["roughness"]}, "doubleSided": True})
        group_name = mesh.get("group", mesh["name"])
        if group_name not in groups:
            groups[group_name] = {"materials": {}, "names": [], "path": mesh.get("groupPath", [])}
        group = groups[group_name]
        group["materials"].setdefault(material_key, []).append(mesh)
        group["names"].append(mesh["name"])

    # The editor uses Z up; glTF requires Y up. This mapping preserves handedness.
    def y_up(v):
        return [item for i in range(0, len(v), 3)
                for item in (v[i], v[i+2], -v[i+1])]

    group_nodes = {}
    animated_nodes = []

    def parent_children(path):
        children = doc["scenes"][0]["nodes"]
        prefix = ()
        for entry in path:
            prefix += (entry["name"],)
            if prefix not in group_nodes:
                x, y, z, w = _group_quaternion(entry)
                factors = entry["scale"]
                node = {"name": entry["name"], "children": [],
                        "translation": y_up(_scaled_positions(entry["position"], scale)),
                        "rotation": [x, z, -y, w],
                        "scale": [factors[0], factors[2], factors[1]]}
                if entry.get("properties"):
                    node["extras"] = dict(entry["properties"])
                index = len(doc["nodes"])
                group_nodes[prefix] = index
                children.append(index)
                doc["nodes"].append(node)
                if "animation" in entry:
                    animated_nodes.append((index, entry["animation"]))
            children = doc["nodes"][group_nodes[prefix]]["children"]
        return children

    for group_name, group in groups.items():
        children = parent_children(group["path"])
        primitives = []
        for material_key, members in group["materials"].items():
            positions, normals = [], []
            for mesh in members:
                positions.extend(y_up(_scaled_positions(mesh["positions"], scale)))
                normals.extend(y_up(mesh["normals"]))
            p = accessor(positions, "POSITION", 34962)
            n = accessor(normals, "NORMAL", 34962)
            primitives.append({"attributes": {"POSITION": p, "NORMAL": n},
                               "material": material_indices[material_key], "mode": 4})
        index = len(doc["meshes"])
        doc["meshes"].append({"name": group_name, "primitives": primitives})
        node = {"name": group_name, "mesh": index}
        if len(group["names"]) > 1:
            node["extras"] = {"sourceSolids": group["names"]}
        children.append(len(doc["nodes"]))
        doc["nodes"].append(node)
    if animated_nodes:
        clip = {"name": "Loop", "channels": [], "samplers": [],
                "extras": {"loop": True, "duration": animation["duration"]}}

        def animation_accessor(values, width):
            blob.extend(b"\0" * (-len(blob) % 4))
            view = len(doc["bufferViews"])
            doc["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(values)*4})
            blob.extend(struct.pack("<" + "f" * len(values), *values))
            item = {"bufferView": view, "componentType": 5126, "count": len(values)//width,
                    "type": {1: "SCALAR", 3: "VEC3", 4: "VEC4"}[width]}
            if width == 1:
                item.update(min=[min(values)], max=[max(values)])
            doc["accessors"].append(item)
            return len(doc["accessors"])-1

        for index, track in animated_nodes:
            times = sample_times(track, animation["duration"])
            # glTF uses float32 times. Reject colliding keys rather than emit invalid samplers.
            packed_times = struct.unpack("<" + "f"*len(times), struct.pack("<" + "f"*len(times), *times))
            if any(b <= a for a, b in zip(packed_times, packed_times[1:])):
                raise ValueError("Animation key times are too close for GLB float32 precision")
            time_accessor = animation_accessor(times, 1)
            poses = [sample_track(track, time) for time in times]
            # Write defaults for unused channels too, so the first pose is explicit.
            for channel, target in (("position", "translation"), ("euler", "rotation"), ("scale", "scale")):
                values = []
                previous = None
                for pose in poses:
                    if channel == "euler":
                        x, y, z, w = _group_quaternion(pose)
                        value = [x, z, -y, w]
                        if previous is not None and sum(a*b for a, b in zip(value, previous)) < 0:
                            value = [-v for v in value]
                        previous = value
                    elif channel == "position":
                        value = y_up(_scaled_positions(pose[channel], scale))
                    else:
                        x, y, z = pose[channel]
                        value = [x, z, y]
                    values.extend(value)
                output = animation_accessor(values, 4 if channel == "euler" else 3)
                sampler = len(clip["samplers"])
                clip["samplers"].append({"input": time_accessor, "output": output, "interpolation": "LINEAR"})
                clip["channels"].append({"sampler": sampler, "target": {"node": index, "path": target}})
                first = poses[0]
                if channel == "euler":
                    x, y, z, w = _group_quaternion(first)
                    doc["nodes"][index][target] = [x, z, -y, w]
                elif channel == "position":
                    doc["nodes"][index][target] = y_up(_scaled_positions(first[channel], scale))
                else:
                    x, y, z = first[channel]
                    doc["nodes"][index][target] = [x, z, y]
        doc["animations"] = [clip]
    doc["buffers"].append({"byteLength": len(blob)})
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob.extend(b"\0" * (-len(blob) % 4))
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<4sII", b"glTF", 2, total) +
            struct.pack("<I4s", len(js), b"JSON") + js +
            struct.pack("<I4s", len(blob), b"BIN\0") + blob)


def to_usdz(meshes, scale=1, animation_source=""):
    """Package recursive Xforms and solid meshes as a Z-up USD stage."""
    scale = _export_scale(scale)
    animation, bound = prepare_animation(animation_source, meshes)
    meshes = animation_meshes(_export_meshes(meshes), bound) if bound else _export_meshes(meshes)
    def triples(values):
        if len(values) % 3 or not all(math.isfinite(float(v)) for v in values):
            raise ValueError("Mesh vectors must contain finite triples")
        return "[" + ", ".join(
            "(" + ", ".join(format(float(v), ".9g") for v in values[i:i + 3]) + ")"
            for i in range(0, len(values), 3)) + "]"

    lines = ["#usda 1.0", "(", '    defaultPrim = "Model"', '    metersPerUnit = 1', '    upAxis = "Z"', ")",
             'def Xform "Model"', "{", '    def Scope "Materials"', "    {"]
    if animation:
        lines[2:2] = ["    startTimeCode = 0", f'    endTimeCode = {animation["duration"]*60:.17g}',
                      "    timeCodesPerSecond = 60", "    framesPerSecond = 60",
                      "    autoPlay = true", '    playbackMode = "loop"']
    material_indices = {}
    for mesh in meshes:
        material = normalize_material(mesh.get("material", {}))
        key = (tuple(material["baseColor"]), material["metallic"], material["roughness"])
        if key in material_indices:
            continue
        index = len(material_indices)
        material_indices[key] = index
        color = "(" + ", ".join(format(v, ".9g") for v in material["baseColor"]) + ")"
        lines.extend([
            f'        def Material "Material_{index}"', "        {",
            f'            token outputs:surface.connect = </Model/Materials/Material_{index}/PBR.outputs:surface>',
            '            def Shader "PBR"', "            {",
            '                uniform token info:id = "UsdPreviewSurface"',
            f'                color3f inputs:diffuseColor = {color}',
            f'                float inputs:metallic = {material["metallic"]:.9g}',
            f'                float inputs:roughness = {material["roughness"]:.9g}',
            '                token outputs:surface', "            }", "        }",
        ])
    lines.extend(["    }", '    def Xform "Geometry"', "    {"])
    groups = {}
    for mesh in meshes:
        positions, normals = mesh["positions"], mesh["normals"]
        if not positions or len(positions) != len(normals) or len(positions) % 9:
            raise ValueError("Mesh positions and normals must contain matching triangles")
        material = normalize_material(mesh.get("material", {}))
        key = (tuple(material["baseColor"]), material["metallic"], material["roughness"])
        group_name = mesh.get("group", mesh["name"])
        if group_name not in groups:
            groups[group_name] = {"positions": [], "normals": [], "names": [], "faces": {},
                                  "path": mesh.get("groupPath", []),
                                  "hierarchical": "groupPath" in mesh}
        group = groups[group_name]
        first_face = len(group["positions"]) // 9
        group["positions"].extend(_scaled_positions(positions, scale))
        group["normals"].extend(normals)
        group["names"].append(mesh["name"])
        group["faces"].setdefault(key, []).extend(range(first_face, first_face + len(positions) // 9))

    geometry_lines = lines
    tree = {}
    for index, (group_name, group) in enumerate(groups.items()):
        lines = []
        positions, normals = group["positions"], group["normals"]
        count = len(positions) // 3
        bounds = [(min(positions[i::3]), max(positions[i::3])) for i in range(3)]
        extent = triples([bounds[i][j] for j in range(2) for i in range(3)])
        names = group["names"]
        lines.extend([
            f'        def Mesh "{group_name if group["hierarchical"] else f"Mesh_{index}"}" (',
            '            prepend apiSchemas = ["MaterialBindingAPI"]',
            "        )", "        {",
            f'            custom string sourceName = {json.dumps(group_name, ensure_ascii=False)}',
            *([f'            custom string[] sourceSolids = {json.dumps(names, ensure_ascii=False)}']
              if len(names) > 1 else []),
            f'            int[] faceVertexCounts = [{", ".join(["3"] * (count // 3))}]',
            f'            int[] faceVertexIndices = [{", ".join(map(str, range(count)))}]',
            f'            normal3f[] normals = {triples(normals)} (',
            '                interpolation = "vertex"', "            )",
            f'            point3f[] points = {triples(positions)}',
            f'            float3[] extent = {extent}',
            '            uniform token subdivisionScheme = "none"',
        ])
        if len(group["faces"]) == 1:
            key = next(iter(group["faces"]))
            lines.append(f'            rel material:binding = </Model/Materials/Material_{material_indices[key]}>')
        else:
            lines.append('            uniform token subsetFamily:materialBind:familyType = "partition"')
            for subset_index, (key, face_indices) in enumerate(group["faces"].items()):
                lines.extend([
                    f'            def GeomSubset "MaterialSubset_{subset_index}" (',
                    '                prepend apiSchemas = ["MaterialBindingAPI"]',
                    '            )',
                    '            {',
                    '                uniform token elementType = "face"',
                    '                uniform token familyName = "materialBind"',
                    f'                int[] indices = [{", ".join(map(str, face_indices))}]',
                    f'                rel material:binding = </Model/Materials/Material_{material_indices[key]}>',
                    '            }',
                ])
        lines.append("        }")
        branch = tree
        for entry in group["path"]:
            branch = branch.setdefault(("group", entry["name"]), {"transform": entry, "children": {}})["children"]
        branch[("mesh", group_name)] = {"lines": lines}

    def emit_tree(branch, indent):
        reserved = {name for _, name in branch}
        for (_, name), item in branch.items():
            if "lines" in item:
                block = item["lines"]
                # Part-internal groups are not exposed as text-language names;
                # a legal sibling solid can therefore have the same name.
                if ("group", name) in branch:
                    prim_name = name + "__mesh"
                    while prim_name in reserved:
                        prim_name += "_"
                    reserved.add(prim_name)
                    block = [block[0].replace(f'"{name}"', f'"{prim_name}"', 1),
                             f'            displayName = {json.dumps(name)}', *block[1:]]
                geometry_lines.extend(indent + line[8:] for line in block)
                continue
            entry = item["transform"]
            def vector(values):
                return "(" + ", ".join(format(v, ".17g") for v in values) + ")"
            rotation_op = "orient" if "quaternion" in entry else "rotateXYZ"
            if rotation_op == "orient":
                x, y, z, w = _group_quaternion(entry)
                rotation_line = f'quatd xformOp:orient = {vector((w, x, y, z))}'
            else:
                rotation_line = f'double3 xformOp:rotateXYZ = {vector(entry["euler"])}'
            group_start = len(geometry_lines)
            geometry_lines.extend([
                f'{indent}def Xform "{name}"', indent + "{",
                f'{indent}    double3 xformOp:translate = {vector(_scaled_positions(entry["position"], scale))}',
                f'{indent}    {rotation_line}',
                f'{indent}    double3 xformOp:scale = {vector(entry["scale"])}',
                f'{indent}    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:{rotation_op}", "xformOp:scale"]',
            ])
            if "animation" in entry:
                track = entry["animation"]
                times = sample_times(track, animation["duration"])
                poses = [sample_track(track, time) for time in times]
                for field, op in (("position", "translate"), ("euler", "rotateXYZ"), ("scale", "scale")):
                    value = poses[0][field]
                    if field == "position":
                        value = _scaled_positions(value, scale)
                    # Default values are the first key, also for non-animated viewers.
                    for i in range(group_start, len(geometry_lines)):
                        if f"xformOp:{op} =" in geometry_lines[i]:
                            geometry_lines[i] = f'{indent}    double3 xformOp:{op} = {vector(value)}'
                    geometry_lines.append(f'{indent}    double3 xformOp:{op}.timeSamples = {{')
                    for time, pose in zip(times, poses):
                        value = pose[field]
                        if field == "position":
                            value = _scaled_positions(value, scale)
                        geometry_lines.append(f'{indent}        {time*60:.17g}: {vector(value)},')
                    geometry_lines.append(indent + "    }")
            emit_tree(item["children"], indent + "    ")
            geometry_lines.append(indent + "}")

    # Keep a static container above animated objects. Avoid the exact name
    # "Scene": an iOS Quick Look animation issue with that name is reported at
    # https://developer.apple.com/forums/thread/775184.
    if animation:
        geometry_lines.extend(['        def Xform "ModelContent"', '        {'])
    emit_tree(tree, "            " if animation else "        ")
    lines = geometry_lines
    if animation:
        lines.append("        }")
    lines.extend(["    }", "}", ""])
    stage = "\n".join(lines).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        entry = zipfile.ZipInfo("model.usda")
        entry.compress_type = zipfile.ZIP_STORED
        # ZIP local header: 30 bytes + filename + extra. Align the file data.
        padding = (-30 - len(entry.filename.encode("utf-8"))) % 64
        if padding < 4:
            padding += 64
        entry.extra = struct.pack("<HH", 0, padding - 4) + bytes(padding - 4)
        archive.writestr(entry, stage)
    return buffer.getvalue()
