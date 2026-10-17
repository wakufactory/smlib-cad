"""USD BRep script/command evaluator and mesh exporters."""

from __future__ import annotations

import io
import json
import math
import re
import struct
import zipfile
from contextlib import redirect_stdout


EXAMPLE_SCRIPT = """# _smlib_core is available as sm. Assign the finished solid to result.
body = sm.create_box((-10, -10, 0), 20, 20, 8)
hole = sm.create_sphere((0, 0, 8), 7)
result = sm.boolean_difference(body, hole)
materials = {"result": {"baseColor": [0.85, 0.24, 0.12], "metallic": 0.65, "roughness": 0.3}}
"""

EXAMPLE_TEXT = """# Group coordinates are local; its transform also moves Boolean results.
group assembly
  position 12 0 0
  euler 0 0 20
  box body -10 -10 0 20 20 8
  sphere hole 0 0 8 7
  subtract result body hole
  material result 0.85 0.24 0.12 0.65 0.3
end
"""

PRIMITIVE_ARGUMENTS = {
    "box": 6, "sphere": 4, "cylinder": 5, "cone": 6, "torus": 5,
    "pyramid": 5, "cylindrical_box": 8, "partial_sphere": 6,
    "partial_cone": 8, "partial_cylinder": 7, "partial_torus": 7,
    "ellipsoid": 6, "sphere_no_pole": 4, "plane": 5, "planar_circle": 4,
}
AXIAL_PRIMITIVES = {
    "cylinder", "cone", "torus", "pyramid", "cylindrical_box",
    "partial_sphere", "partial_cone", "partial_cylinder", "partial_torus",
}


def validate_primitive(op, values):
    """Reject invalid text arguments before passing them to SMLib."""
    if not all(math.isfinite(x) for x in values):
        raise ValueError("coordinates and dimensions must be finite")
    dimensions = values[3:]
    if op in ("box", "sphere", "cylinder", "pyramid", "ellipsoid",
              "sphere_no_pole", "plane", "planar_circle"):
        if any(x <= 0 for x in dimensions):
            raise ValueError("dimensions must be positive")
    elif op in ("cone", "partial_cone"):
        base, top, height = dimensions[:3]
        if base < 0 or top < 0 or base + top <= 0 or height <= 0:
            raise ValueError("cone radii must be non-negative with one positive, and height positive")
    elif op in ("torus", "partial_torus"):
        major, minor = dimensions[:2]
        if minor <= 0 or major <= minor:
            raise ValueError("torus requires major radius > minor radius > 0")
    elif op == "cylindrical_box":
        length, inner, outer = dimensions[:3]
        if length <= 0 or inner <= 0 or outer <= inner:
            raise ValueError("cylindrical_box requires length > 0 and outside radius > inside radius > 0")
    elif op in ("partial_sphere", "partial_cylinder"):
        if any(x <= 0 for x in dimensions[:-2]):
            raise ValueError("dimensions must be positive")
    if op.startswith("partial_") or op == "cylindrical_box":
        start, end = values[-2:]
        if end <= start or end - start > 360:
            raise ValueError("angle range must be greater than 0 and at most 360 degrees")

DEFAULT_MATERIAL = {"baseColor": [0.29, 0.68, 0.88], "metallic": 0.0, "roughness": 0.55}


def normalize_material(value):
    """Validate the three opaque PBR properties shared by preview and glTF."""
    if not isinstance(value, dict):
        raise ValueError("material must be a dictionary")
    unknown = set(value) - set(DEFAULT_MATERIAL)
    if unknown:
        raise ValueError(f"unknown material property: {', '.join(sorted(map(str, unknown)))}")
    result = {**DEFAULT_MATERIAL, **value}
    color = result["baseColor"]
    if not isinstance(color, (list, tuple)) or len(color) != 3:
        raise ValueError("baseColor must contain three RGB values")
    for key, components in (("baseColor", color), ("metallic", [result["metallic"]]),
                            ("roughness", [result["roughness"]])):
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or
               not math.isfinite(x) or not 0 <= x <= 1 for x in components):
            raise ValueError(f"{key} values must be finite numbers from 0 to 1")
    return {"baseColor": [float(x) for x in color],
            "metallic": float(result["metallic"]), "roughness": float(result["roughness"])}


def normalize_materials(materials, objects):
    if not isinstance(materials, dict):
        raise ValueError("materials must be a dictionary keyed by solid name")
    unknown = set(materials) - set(objects)
    if unknown:
        raise ValueError(f"material references unknown solid: {', '.join(sorted(map(str, unknown)))}")
    return {name: normalize_material(value) for name, value in materials.items()}


def _extract_parts(lines, parts, line_offset, in_part):
    """Collect root-level part bodies while keeping original line numbers."""
    commands = list(lines)
    group_depth = 0
    index = 0
    while index < len(lines):
        words = lines[index].partition("#")[0].split()
        op = words[0].lower() if words else ""
        if op in ("group", "profile"):
            group_depth += 1
        elif op == "end":
            group_depth -= 1
        elif op == "part":
            line_number = line_offset + index + 1
            if in_part or group_depth != 0:
                raise ValueError(f"Line {line_number}: part definitions must be at the root level")
            if len(words) != 2 or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", words[1]):
                raise ValueError(f"Line {line_number}: part: one valid part name required")
            name = words[1]
            if name in parts:
                raise ValueError(f"Line {line_number}: duplicate part name: {name}")
            end = index + 1
            nested_groups = 0
            while end < len(lines):
                inner_words = lines[end].partition("#")[0].split()
                inner_op = inner_words[0].lower() if inner_words else ""
                if inner_op == "part":
                    raise ValueError(f"Line {line_offset + end + 1}: part definitions cannot be nested")
                if inner_op in ("group", "profile"):
                    nested_groups += 1
                elif inner_op == "end":
                    if nested_groups == 0:
                        if len(inner_words) != 1:
                            raise ValueError(f"Line {line_offset + end + 1}: end takes no arguments")
                        break
                    nested_groups -= 1
                end += 1
            if end == len(lines):
                raise ValueError(f"Line {line_number}: part {name} has no end")
            parts[name] = ("\n".join(lines[index + 1:end]), line_number)
            commands[index:end + 1] = [""] * (end - index + 1)
            index = end
        index += 1
    return commands


def parse_commands(source: str, sm, _parts=None, _stack=(), _counter=None, _line_offset=0, _profiles=None):
    """Evaluate text commands; each use builds fresh BReps from a part body."""
    parts = {} if _parts is None else _parts
    counter = {"expansions": 0, "names": {}} if _counter is None else _counter
    commands = _extract_parts(source.splitlines(), parts, _line_offset, bool(_stack))
    frames = [{"name": None, "line": 0, "objects": {}, "materials": {}, "profiles": {}, "groups": {},
               "scale": (1.0, 1.0, 1.0), "euler": (0.0, 0.0, 0.0),
               "position": (0.0, 0.0, 0.0)}]
    profile_block = None
    inherited_profiles = {} if _profiles is None else _profiles
    for line_number, raw in enumerate(commands, _line_offset + 1):
        line = raw.partition("#")[0].strip()
        if not line:
            continue
        words = line.split()
        op, args = words[0].lower(), words[1:]
        frame = frames[-1]
        objects, materials = frame["objects"], frame["materials"]
        groups = frame["groups"]
        try:
            if op in (*PRIMITIVE_ARGUMENTS, "extrude", "revolve") and args and args[0] in groups:
                raise ValueError(f"name already used by group: {args[0]}")
            if profile_block is not None:
                if op == "polygon":
                    if profile_block["points"] is not None or len(args) < 6 or len(args) % 2:
                        raise ValueError("profile requires one polygon with at least three u v pairs")
                    values = [float(x) for x in args]
                    profile_block["points"] = list(zip(values[::2], values[1::2]))
                elif op == "end" and not args:
                    if profile_block["points"] is None:
                        raise ValueError("profile requires a polygon")
                    frame["profiles"][profile_block["name"]] = sm.create_profile(profile_block["points"])
                    profile_block = None
                else:
                    raise ValueError("only polygon and end are allowed inside a profile")
            elif op == "profile":
                if len(args) != 1 or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", args[0]):
                    raise ValueError("profile: one valid profile name required")
                if args[0] in frame["profiles"]:
                    raise ValueError(f"duplicate profile name: {args[0]}")
                profile_block = {"name": args[0], "line": line_number, "points": None}
            elif op in ("extrude", "revolve"):
                if len(args) not in (7, 10, 13) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", args[0]):
                    raise ValueError(f"{op}: name profile x y z start end [dx dy dz [ux uy uz]] required")
                if args[0] in objects:
                    raise ValueError(f"duplicate solid name: {args[0]}")
                profiles = dict(inherited_profiles)
                for scope in frames:
                    profiles.update(scope["profiles"])
                if args[1] not in profiles:
                    raise ValueError(f"unknown profile: {args[1]}")
                values = tuple(float(x) for x in args[2:])
                if not all(math.isfinite(x) for x in values):
                    raise ValueError("coordinates, range, axis, and xdir must be finite")
                options = {}
                if len(values) >= 8:
                    options["axis"] = values[5:8]
                if len(values) == 11:
                    options["xdir"] = values[8:11]
                objects[args[0]] = getattr(sm, f"create_{op}")(
                    profiles[args[1]], values[:3], values[3], values[4], **options)
            elif op == "use":
                if len(args) not in (1, 2) or any(not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", x) for x in args):
                    raise ValueError("use: part name and optional instance name required")
                part_name = args[0]
                if part_name not in parts:
                    raise ValueError(f"unknown part: {part_name}")
                if part_name in _stack:
                    raise ValueError(f"recursive part use: {' -> '.join((*_stack, part_name))}")
                if len(_stack) >= 32 or counter["expansions"] >= 512:
                    raise ValueError("part expansion limit exceeded")
                counter["expansions"] += 1
                if len(args) == 2:
                    instance_name = args[1]
                else:
                    names_used = counter["names"]
                    names_used[part_name] = names_used.get(part_name, 0) + 1
                    instance_name = f"{part_name}_{names_used[part_name]}"
                body, part_line = parts[part_name]
                profiles = dict(inherited_profiles)
                for scope in frames:
                    profiles.update(scope["profiles"])
                try:
                    members, member_materials = parse_commands(
                        body, sm, parts, (*_stack, part_name), counter, part_line, profiles)
                except ValueError as exc:
                    raise ValueError(f"use {part_name}: {exc}") from exc
                names = {name: f"{instance_name}__{name}" for name in members}
                collisions = set(names.values()) & (set(objects) | set(groups))
                if collisions:
                    raise ValueError(f"use {part_name}: duplicate solid name: {', '.join(sorted(collisions))}")
                objects.update((names[name], solid) for name, solid in members.items())
                materials.update((names[name], material) for name, material in member_materials.items())
            elif op == "group":
                if len(args) != 1 or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", args[0]):
                    raise ValueError("group: one valid group name required")
                if args[0] in objects or args[0] in groups:
                    raise ValueError(f"duplicate group name: {args[0]}")
                frames.append({"name": args[0], "line": line_number, "objects": {}, "materials": {}, "profiles": {}, "groups": {},
                               "scale": (1.0, 1.0, 1.0), "euler": (0.0, 0.0, 0.0),
                               "position": (0.0, 0.0, 0.0)})
            elif op == "end":
                if args or len(frames) == 1:
                    raise ValueError("end: no arguments and an open group required")
                parent = frames[-2]
                collisions = set(objects) & set(parent["objects"])
                if collisions:
                    raise ValueError(f"group {frame['name']}: duplicate solid name: {', '.join(sorted(collisions))}")
                if (set(objects) & set(parent["groups"]) or
                        (set(groups) | {frame["name"]}) & (set(parent["objects"]) | set(parent["groups"])) or
                        frame["name"] in objects or frame["name"] in groups):
                    raise ValueError(f"group {frame['name']}: duplicate group or solid name")
                for name, solid in objects.items():
                    try:
                        sm.transform_brep(solid, frame["scale"], frame["euler"], frame["position"])
                    except (ValueError, RuntimeError) as exc:
                        raise ValueError(f"group {frame['name']}, solid {name}: {exc}") from exc
                frames.pop()
                parent["objects"].update(objects)
                parent["materials"].update(materials)
                parent["groups"].update(groups)
                parent["groups"][frame["name"]] = set(objects)
            elif op in ("scale", "euler", "position"):
                if len(frames) == 1 or len(args) != 3:
                    raise ValueError(f"{op}: three numbers inside a group required")
                values = tuple(float(x) for x in args)
                if not all(math.isfinite(x) for x in values):
                    raise ValueError(f"{op}: values must be finite")
                if op == "scale" and any(x <= 0 for x in values):
                    raise ValueError("scale: factors must be positive")
                frame[op] = values
            elif op in PRIMITIVE_ARGUMENTS:
                count = PRIMITIVE_ARGUMENTS[op]
                allowed = (count + 1, count + 4) if op in AXIAL_PRIMITIVES else (count + 1,)
                if len(args) not in allowed or not args or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", args[0]):
                    suffix = " (optionally followed by axis dx dy dz)" if op in AXIAL_PRIMITIVES else ""
                    raise ValueError(f"{op}: name and {count} numbers required{suffix}")
                values = tuple(float(x) for x in args[1:])
                if not all(math.isfinite(x) for x in values):
                    raise ValueError("coordinates, dimensions, and axis must be finite")
                dimensions = values[:count]
                axis = values[count:]
                validate_primitive(op, dimensions)
                if axis and not any(axis):
                    raise ValueError("axis must be nonzero")
                extra = (axis,) if axis else ()
                objects[args[0]] = getattr(sm, f"create_{op}")(dimensions[:3], *dimensions[3:], *extra)
            elif op in ("union", "subtract", "intersect"):
                if len(args) != 3 or any(name not in objects and name not in groups for name in args[1:]):
                    raise ValueError(f"{op}: output and two existing object or group names required")
                if args[1] == args[2]:
                    raise ValueError("Boolean operands must differ")
                operands = [{name} if name in objects else set(groups[name]) for name in args[1:]]
                if not all(operands):
                    raise ValueError("Boolean group operands must not be empty")
                if operands[0] & operands[1]:
                    raise ValueError("Boolean operands must not share group members")
                consumed = operands[0] | operands[1]
                if args[0] in groups and args[0] not in args[1:]:
                    raise ValueError(f"output name already used by group: {args[0]}")
                if args[0] in objects and args[0] not in consumed:
                    raise ValueError(f"duplicate solid name: {args[0]}")
                fn = {"union": sm.boolean_union, "subtract": sm.boolean_difference,
                      "intersect": sm.boolean_intersection}[op]
                def take_operand(members):
                    names = [name for name in objects if name in members]
                    solid = objects.pop(names[0])
                    for name in names[1:]:
                        solid = sm.boolean_union(solid, objects.pop(name))
                    return solid
                left, right = (take_operand(members) for members in operands)
                for name in consumed:
                    materials.pop(name, None)
                for name, members in list(groups.items()):
                    if name in args[1:]:
                        del groups[name]
                    else:
                        contained = consumed <= members
                        members.difference_update(consumed)
                        if contained:
                            members.add(args[0])
                objects[args[0]] = fn(left, right)
            elif op == "faces":
                if len(args) != 1 or args[0] not in objects:
                    raise ValueError("faces: existing solid name required")
                print(f"{args[0]} faces: {json.dumps(sm.face_info(objects[args[0]]))}")
            elif op in ("offset", "shell"):
                if len(args) < 2 or args[0] not in objects or (op == "offset" and len(args) != 2):
                    raise ValueError(f"{op}: existing solid name and distance"
                                     + (" followed by optional face indices required" if op == "shell" else " required"))
                distance = float(args[1])
                if not math.isfinite(distance) or distance == 0:
                    raise ValueError("distance must be finite and nonzero")
                options = {"faces_to_shell": [int(x) for x in args[2:]]} if op == "shell" else {}
                objects[args[0]] = getattr(sm, f"{op}_brep")(objects[args[0]], distance, **options)
            elif op in ("chamfer", "fillet"):
                if len(args) != 2 or args[0] not in objects:
                    raise ValueError(f"{op}: existing solid name and positive width/radius required")
                size = float(args[1])
                if not math.isfinite(size) or size <= 0:
                    raise ValueError(f"{op}: width/radius must be finite and positive")
                fn = sm.chamfer_fillet if op == "chamfer" else sm.circular_fillet
                objects[args[0]] = fn(objects[args[0]], size)
            elif op == "material":
                if len(args) != 6 or args[0] not in objects:
                    raise ValueError("material: existing solid name and five numbers required")
                materials[args[0]] = normalize_material({
                    "baseColor": [float(x) for x in args[1:4]],
                    "metallic": float(args[4]), "roughness": float(args[5])})
            else:
                raise ValueError(f"unknown command: {op}")
        except (ValueError, KeyError, RuntimeError) as exc:
            raise ValueError(f"Line {line_number}: {exc}") from exc
    if profile_block is not None:
        raise ValueError(f"Line {profile_block['line']}: profile {profile_block['name']} has no end")
    if len(frames) != 1:
        frame = frames[-1]
        raise ValueError(f"Line {frame['line']}: group {frame['name']} has no end")
    objects, materials = frames[0]["objects"], frames[0]["materials"]
    if not objects:
        raise ValueError("No solid was created")
    return objects, materials


def evaluate(source: str, mode: str, sm):
    if mode == "text":
        output = io.StringIO()
        with redirect_stdout(output):
            objects, materials = parse_commands(source, sm)
        return objects, materials, output.getvalue()
    if mode != "python":
        raise ValueError("mode must be text or python")
    # This is a local code editor. Python input has full local process access.
    namespace = {"sm": sm, "__builtins__": __builtins__}
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(source, "<model>", "exec"), namespace)
    candidates = {name: value for name, value in namespace.items()
                  if name != "sm" and isinstance(value, sm.Brep)}
    if "result" in candidates:
        objects = {"result": candidates["result"]}
        return objects, normalize_materials(namespace.get("materials", {}), objects), output.getvalue()
    if not candidates:
        raise ValueError("Assign a Brep to result (or another variable)")
    # Boolean inputs can be consumed by the native API. The last surviving
    # assignment is the useful result for most scripts.
    name = next(reversed(candidates))
    objects = {name: candidates[name]}
    return objects, normalize_materials(namespace.get("materials", {}), objects), output.getvalue()


def apply_finish(objects, sm, finish: str = "none", size: float = 1.0):
    """Apply one all-edge operation to every result solid before tessellation."""
    if finish == "none":
        return objects
    if finish not in ("chamfer", "fillet"):
        raise ValueError("finish must be none, chamfer, or fillet")
    if isinstance(size, bool) or not isinstance(size, (int, float)) or not math.isfinite(size) or size <= 0:
        raise ValueError("finish width/radius must be finite and positive")
    fn = sm.chamfer_fillet if finish == "chamfer" else sm.circular_fillet
    for name, solid in objects.items():
        try:
            objects[name] = fn(solid, float(size))
        except RuntimeError as exc:
            raise RuntimeError(f"{name}: {exc}") from exc
    return objects


def _improve_triangle_angles(triangles, points, cross, winding, eps):
    """Flip interior diagonals only when the pair's smallest 3D angle grows.

    points are normalized face-local 3D coordinates. Projection is used only
    for topology, so tilted faces are judged by their actual triangle angles.
    Boundary edges have one owner and are never flipped. Strict improvement
    leaves equal-quality diagonals stable and prevents flip-back oscillation.
    """
    def min_angle(triangle):
        angles = []
        for i, vertex in enumerate(triangle):
            a = [points[triangle[(i + 1) % 3]][j] - points[vertex][j] for j in range(3)]
            b = [points[triangle[(i + 2) % 3]][j] - points[vertex][j] for j in range(3)]
            normal = [a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]]
            angles.append(math.atan2(math.sqrt(sum(x*x for x in normal)), sum(x*y for x, y in zip(a, b))))
        return min(angles)

    def edges(triangle):
        return [tuple(sorted((triangle[i - 1], triangle[i]))) for i in range(3)]

    owners = {}
    for index, triangle in enumerate(triangles):
        for edge in edges(triangle):
            owners.setdefault(edge, set()).add(index)
    pending = list(sorted(owners))
    quality = [min_angle(t) for t in triangles]
    while pending:
        edge = pending.pop()
        adjacent = owners.get(edge, set())
        if len(adjacent) != 2:
            continue
        left, right = sorted(adjacent)
        a, b = edge
        c = next(v for v in triangles[left] if v not in edge)
        d = next(v for v in triangles[right] if v not in edge)
        # Both diagonals must be strictly inside the quadrilateral. Do not
        # cross concave boundaries or remove collinear boundary vertices.
        sides = [cross(c, d, a), cross(c, d, b)]
        if not (min(sides) < -eps and max(sides) > eps):
            continue
        sides = [cross(a, b, c), cross(a, b, d)]
        if not (min(sides) < -eps and max(sides) > eps):
            continue
        replacement = [(c, d, a), (d, c, b)]
        replacement = [t if winding * cross(*t) > 0 else (t[0], t[2], t[1]) for t in replacement]
        new_quality = [min_angle(t) for t in replacement]
        if min(new_quality) <= min(quality[left], quality[right]) + 1e-12:
            continue
        for index in (left, right):
            for old_edge in edges(triangles[index]):
                owners[old_edge].remove(index)
                if not owners[old_edge]:
                    del owners[old_edge]
        for index, triangle, angle in zip((left, right), replacement, new_quality):
            triangles[index], quality[index] = triangle, angle
            for new_edge in edges(triangle):
                owners.setdefault(new_edge, set()).add(index)
                pending.append(new_edge)
    return triangles


def _polygon_triangles(points, ids):
    """Return face-local corner indices for a simple polygon without holes.

    Project along the dominant Newell normal. Work in normalized coordinates
    so the orientation tolerance does not depend on model size or position.
    Ear clipping handles convex and concave faces alike; diagonal flips then
    improve minimum angles without adding vertices. Original corner indices
    preserve the tessellator's per-corner normals.
    """
    if len(ids) == 3:
        return [(0, 1, 2)]
    origin = points[ids[0]]
    local = [tuple(p[j] - origin[j] for j in range(3)) for p in (points[i] for i in ids)]
    scale = max(abs(x) for p in local for x in p)
    if scale == 0:
        return []
    local = [tuple(x / scale for x in p) for p in local]
    normal = [sum(a[(j + 1) % 3] * b[(j + 2) % 3] - a[(j + 2) % 3] * b[(j + 1) % 3]
                  for a, b in zip(local, local[1:] + local[:1])) for j in range(3)]
    drop = max(range(3), key=lambda j: abs(normal[j]))
    axes = [j for j in range(3) if j != drop]
    xy = [(p[axes[0]], p[axes[1]]) for p in local]
    eps = 1e-14

    def cross(a, b, c):
        return ((xy[b][0] - xy[a][0]) * (xy[c][1] - xy[a][1])
                - (xy[b][1] - xy[a][1]) * (xy[c][0] - xy[a][0]))

    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(xy, xy[1:] + xy[:1]))
    if abs(area) <= eps:
        raise ValueError("Cannot triangulate polygon: zero projected area")
    winding = 1 if area > 0 else -1
    remaining = list(range(len(ids)))
    result = []
    while len(remaining) > 3:
        for i, b in enumerate(remaining):
            a, c = remaining[i - 1], remaining[(i + 1) % len(remaining)]
            if winding * cross(a, b, c) <= eps:
                continue
            # Boundary points block the ear too, avoiding a diagonal through
            # another vertex and preserving collinear boundary subdivisions.
            if any(all(winding * cross(u, v, p) >= -eps for u, v in ((a, b), (b, c), (c, a)))
                   for p in remaining if p not in (a, b, c)):
                continue
            result.append((a, b, c))
            del remaining[i]
            break
        else:
            raise ValueError("Cannot triangulate polygon: expected a simple boundary without holes")
    result.append(tuple(remaining))
    return _improve_triangle_angles(result, local, cross, winding, eps)


def _triangles(mesh):
    points = mesh["points"]
    faces = mesh["faces"]
    face_normals = mesh.get("face_normals")
    corner_normals = mesh.get("corner_normals")
    offset = face_index = 0
    while offset < len(faces):
        count = int(faces[offset])
        end = offset + 1 + count
        if count < 3 or end > len(faces):
            raise ValueError("Invalid tessellation face stream")
        ids = [int(i) for i in faces[offset + 1:end]]
        if any(i < 0 or i >= len(points) for i in ids):
            raise ValueError("Tessellation index outside point array")
        smooth = corner_normals[face_index] if corner_normals is not None else None
        if smooth is not None and len(smooth) != count:
            raise ValueError("Tessellation corner normal count differs from face size")
        for triangle in _polygon_triangles(points, ids):
            corners = list(triangle)
            tri = [ids[i] for i in corners]
            a, b, c = (points[i] for i in tri)
            u = [b[j] - a[j] for j in range(3)]
            v = [c[j] - a[j] for j in range(3)]
            normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
            length = math.sqrt(sum(x*x for x in normal))
            if length < 1e-12:
                continue
            if face_normals is not None and face_index < len(face_normals):
                target = face_normals[face_index]
                if sum(normal[j]*target[j] for j in range(3)) < 0:
                    tri[1], tri[2] = tri[2], tri[1]
                    corners[1], corners[2] = corners[2], corners[1]
                    normal = tuple(-x for x in normal)
            flat = tuple(x/length for x in normal)
            normals = []
            for corner in corners:
                candidate = smooth[corner] if smooth is not None else flat
                magnitude = math.sqrt(sum(float(x)*float(x) for x in candidate))
                if magnitude < 1e-12:
                    normals.append(flat)
                else:
                    normals.append(tuple(float(x)/magnitude for x in candidate))
            yield tri, normals
        offset, face_index = end, face_index + 1


def tessellate(objects, sm, chord: float = 0.08, angle: float = 20, materials=None):
    if not 0.001 <= chord <= 2:
        raise ValueError("chord must be between 0.001 and 2")
    if not 1 <= angle <= 90:
        raise ValueError("angle must be between 1 and 90 degrees")
    materials = normalize_materials({} if materials is None else materials, objects)
    output = []
    for name, solid in objects.items():
        poly = sm.tessellate(solid, chord_height_tolerance=chord,
                             curve_angle_tolerance_deg=angle,
                             surface_angle_tolerance_deg=angle)
        if poly is None:
            raise ValueError(f"{name}: tessellation returned no mesh")
        raw = poly.to_numpy_arrays()
        positions, normals = [], []
        for tri, corner_normals in _triangles(raw):
            for index, normal in zip(tri, corner_normals):
                positions.extend(float(x) for x in raw["points"][index])
                normals.extend(normal)
        if not positions:
            raise ValueError(f"{name}: empty mesh")
        if len(positions) > 3_000_000:
            raise ValueError("Mesh exceeds the 1 million vertex preview limit")
        output.append({"name": name, "positions": positions, "normals": normals,
                       "material": materials.get(name, normalize_material({}))})
    return output


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


def to_glb(meshes, scale=1):
    """Encode the exact preview triangles as a glTF 2.0 binary scene."""
    scale = _export_scale(scale)
    blob = bytearray()
    doc = {"asset": {"version": "2.0", "generator": "USD BRep Modeler"},
           "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
           "buffers": [], "bufferViews": [], "accessors": [], "materials": []}
    material_indices = {}

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
        # The editor uses Z up; glTF requires Y up. This mapping preserves handedness.
        def y_up(v):
            return [item for i in range(0, len(v), 3)
                    for item in (v[i], v[i+2], -v[i+1])]
        p = accessor(y_up(_scaled_positions(mesh["positions"], scale)), "POSITION", 34962)
        n = accessor(y_up(mesh["normals"]), "NORMAL", 34962)
        index = len(doc["meshes"])
        doc["meshes"].append({"primitives": [{"attributes": {"POSITION": p, "NORMAL": n},
                                               "material": material_indices[material_key], "mode": 4}]})
        doc["nodes"].append({"name": mesh["name"], "mesh": index})
        doc["scenes"][0]["nodes"].append(index)
    doc["buffers"].append({"byteLength": len(blob)})
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob.extend(b"\0" * (-len(blob) % 4))
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<4sII", b"glTF", 2, total) +
            struct.pack("<I4s", len(js), b"JSON") + js +
            struct.pack("<I4s", len(blob), b"BIN\0") + blob)


def to_usdz(meshes, scale=1):
    """Package preview triangles and PBR materials as a Z-up USD stage."""
    scale = _export_scale(scale)
    def triples(values):
        if len(values) % 3 or not all(math.isfinite(float(v)) for v in values):
            raise ValueError("Mesh vectors must contain finite triples")
        return "[" + ", ".join(
            "(" + ", ".join(format(float(v), ".9g") for v in values[i:i + 3]) + ")"
            for i in range(0, len(values), 3)) + "]"

    lines = ["#usda 1.0", "(", '    defaultPrim = "Model"', '    metersPerUnit = 1', '    upAxis = "Z"', ")",
             'def Xform "Model"', "{", '    def Scope "Materials"', "    {"]
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
    for index, mesh in enumerate(meshes):
        positions, normals = mesh["positions"], mesh["normals"]
        if not positions or len(positions) != len(normals) or len(positions) % 9:
            raise ValueError("Mesh positions and normals must contain matching triangles")
        positions = _scaled_positions(positions, scale)
        material = normalize_material(mesh.get("material", {}))
        key = (tuple(material["baseColor"]), material["metallic"], material["roughness"])
        count = len(positions) // 3
        bounds = [(min(positions[i::3]), max(positions[i::3])) for i in range(3)]
        extent = triples([bounds[i][j] for j in range(2) for i in range(3)])
        lines.extend([
            f'        def Mesh "Mesh_{index}" (',
            '            prepend apiSchemas = ["MaterialBindingAPI"]',
            "        )", "        {",
            f'            custom string sourceName = {json.dumps(mesh["name"], ensure_ascii=False)}',
            f'            int[] faceVertexCounts = [{", ".join(["3"] * (count // 3))}]',
            f'            int[] faceVertexIndices = [{", ".join(map(str, range(count)))}]',
            f'            normal3f[] normals = {triples(normals)} (',
            '                interpolation = "vertex"', "            )",
            f'            point3f[] points = {triples(positions)}',
            f'            float3[] extent = {extent}',
            '            uniform token subdivisionScheme = "none"',
            f'            rel material:binding = </Model/Materials/Material_{material_indices[key]}>',
            "        }",
        ])
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
