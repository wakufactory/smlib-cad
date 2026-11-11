"""USD BRep script/command evaluator and tessellation."""

from __future__ import annotations

import io
import json
import math
import re
from contextlib import redirect_stdout
from dataclasses import dataclass, field

from model_syntax import (IDENTIFIER, ExpansionBudget, ModelProgram, expression_arguments,
                          number_argument, quaternion_expression)
from transforms import _normalize_quaternion, _quaternion_euler


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

DEFAULT_MATERIAL = {"baseColor": [0.29, 0.68, 0.88], "metallic": 0.0, "roughness": 0.55, "opacity": 1.0}


def normalize_material(value):
    """Validate PBR color, surface properties and alpha-blend opacity."""
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
                            ("roughness", [result["roughness"]]),
                            ("opacity", [result["opacity"]])):
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or
               not math.isfinite(x) or not 0 <= x <= 1 for x in components):
            raise ValueError(f"{key} values must be finite numbers from 0 to 1")
    return {"baseColor": [float(x) for x in color],
            "metallic": float(result["metallic"]), "roughness": float(result["roughness"]),
            "opacity": float(result["opacity"])}


def normalize_materials(materials, objects):
    if not isinstance(materials, dict):
        raise ValueError("materials must be a dictionary keyed by solid name")
    unknown = set(materials) - set(objects)
    if unknown:
        raise ValueError(f"material references unknown solid: {', '.join(sorted(map(str, unknown)))}")
    return {name: normalize_material(value) for name, value in materials.items()}


class SolidObjects(dict):
    """Named BReps with meshing settings and recursive export group transforms."""

    def __init__(self):
        super().__init__()
        self.tessellation = {}
        self.top_groups = {}
        # Paths are relative to the current evaluation scope, outermost first.
        self.group_paths = {}


class Group:
    """Python model group. Children are a name -> Brep/Group dictionary.

    Transforms apply to completed solids, child first, during evaluate().
    Material inheritance replaces whole PBR materials, just like text groups.
    """

    def __init__(self, objects, *, material=None, scale=(1, 1, 1),
                 euler=(0, 0, 0), position=(0, 0, 0), invisible=False):
        self.objects = objects
        self.material = material
        self.scale = scale
        self.euler = euler
        self.position = position
        self.invisible = invisible


def _python_objects(roots, materials, sm):
    """Validate the entire tree before applying any native transforms."""
    objects = SolidObjects()
    names, solid_ids, active = set(), set(), set()
    groups, leaves, transforms = {}, [], []
    group_transforms = {}
    if not isinstance(materials, dict):
        raise ValueError("materials must be a dictionary keyed by solid or group name")
    overrides = {name: normalize_material(value) for name, value in materials.items()}

    def vector(value, field):
        if (not isinstance(value, (tuple, list)) or len(value) != 3 or
                any(isinstance(x, bool) or not isinstance(x, (int, float)) or
                    not math.isfinite(x) for x in value)):
            raise ValueError(f"group {field} must contain three finite numbers")
        if field == "scale" and any(x <= 0 for x in value):
            raise ValueError("group scale factors must be positive")
        return tuple(float(x) for x in value)

    def visit(children, ancestry):
        if not isinstance(children, dict):
            raise ValueError("objects must be a dictionary keyed by solid or group name")
        for name, value in children.items():
            if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
                raise ValueError("solid and group names must be valid identifiers")
            if name in names:
                raise ValueError(f"duplicate solid or group name: {name}")
            names.add(name)
            if isinstance(value, Group):
                if id(value) in active:
                    raise ValueError(f"cyclic group: {name}")
                transform = tuple(vector(getattr(value, field), field)
                                  for field in ("scale", "euler", "position"))
                group_transforms[name] = dict(name=name, scale=transform[0],
                                              euler=transform[1], position=transform[2])
                if not isinstance(value.invisible, bool):
                    raise ValueError("group invisible must be a boolean")
                if value.invisible:
                    group_transforms[name]["invisible"] = True
                groups[name] = (overrides.get(name) if name in overrides else
                                normalize_material(value.material) if value.material is not None else None)
                active.add(id(value))
                members = visit(value.objects, (*ancestry, name))
                active.remove(id(value))
                transforms.append((name, members, transform))
            elif isinstance(value, sm.Brep):
                if id(value) in solid_ids:
                    raise ValueError(f"Brep reused by multiple objects: {name}; create a fresh Brep")
                solid_ids.add(id(value))
                objects[name] = value
                leaves.append((name, ancestry))
                if ancestry:
                    objects.top_groups[name] = ancestry[0]
            else:
                raise ValueError(f"{name}: expected Brep or Group")
        return [name for name, path in leaves if path[:len(ancestry)] == ancestry]

    visit(roots, ())
    unknown = set(overrides) - names
    if unknown:
        raise ValueError(f"material references unknown solid or group: {', '.join(sorted(map(str, unknown)))}")
    if not objects:
        raise ValueError("No solid was created")
    resolved = {}
    for name, ancestry in leaves:
        objects.group_paths[name] = [group_transforms[group] for group in ancestry]
        material = overrides.get(name)
        if material is None:
            material = next((groups[group] for group in reversed(ancestry)
                             if groups[group] is not None), None)
        if material is not None:
            resolved[name] = material
    for group, members, transform in transforms:
        for name in members:
            try:
                sm.transform_brep(objects[name], *transform)
            except (ValueError, RuntimeError) as exc:
                raise ValueError(f"group {group}, solid {name}: {exc}") from exc
    return objects, resolved


@dataclass
class _CommandFrame:
    name: str | None = None
    depth: int = 0
    objects: SolidObjects = field(default_factory=SolidObjects)
    materials: dict = field(default_factory=dict)
    material_priority: dict = field(default_factory=dict)
    profiles: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)
    group_depths: dict = field(default_factory=dict)
    group_parents: dict = field(default_factory=dict)
    group_material: dict | None = None
    scale: tuple = (1.0, 1.0, 1.0)
    euler: tuple = (0.0, 0.0, 0.0)
    position: tuple = (0.0, 0.0, 0.0)
    quaternion: tuple | None = None
    rotation_command: str | None = None
    invisible: bool = False
    properties: dict = field(default_factory=dict)


@dataclass
class _ProfileBlock:
    name: str
    points: list | None = None
    kind: str | None = None


@dataclass
class _PartInstances:
    count: int = 0
    names: dict = field(default_factory=dict)


class _TextEvaluator:
    """Apply expanded commands in order to native BReps and their metadata."""

    def __init__(self, sm, program, budget, instances, *, stack=(), profiles=None):
        self.sm = sm
        self.program = program
        self.budget = budget
        self.instances = instances
        self.stack = stack
        self.inherited_profiles = {} if profiles is None else profiles
        self.frames = [_CommandFrame()]
        self.profile = None

    @property
    def frame(self):
        return self.frames[-1]

    def visible_profiles(self):
        profiles = dict(self.inherited_profiles)
        for frame in self.frames:
            profiles.update(frame.profiles)
        return profiles

    def check_solid_name(self, name, *, consumed=(), consumed_groups=()):
        if not IDENTIFIER.fullmatch(name):
            raise ValueError("output name must be a valid identifier")
        if name in self.frame.groups and name not in consumed_groups:
            raise ValueError(f"name already used by group: {name}")
        if name in self.frame.objects and name not in consumed:
            raise ValueError(f"duplicate solid name: {name}")

    def run(self, variables=()):
        part = self.stack[-1] if self.stack else None
        commands = self.program.expand(self.budget, part=part, inherited=variables)
        for command, scope in commands:
            try:
                if self.profile is not None:
                    self.profile_body(command, scope)
                else:
                    handler = _TEXT_HANDLERS.get(command.op)
                    if handler is None:
                        raise ValueError(f"unknown command: {command.op}")
                    handler(self, command, scope)
            except (ValueError, KeyError, RuntimeError) as exc:
                raise command.error(str(exc)) from exc
        objects, materials = self.frame.objects, self.frame.materials
        if not objects:
            raise ValueError("No solid was created")
        return objects, materials

    def profile_body(self, command, variables):
        op = command.op
        args = expression_arguments(command.tail)
        sm = self.sm
        frame = self.frame
        profile_block = self.profile
        if op == "polygon":
            if profile_block.points is not None or len(args) < 6 or len(args) % 2:
                raise ValueError("profile requires one polygon with at least three u v pairs")
            values = [number_argument(x, variables) for x in args]
            profile_block.points = list(zip(values[::2], values[1::2]))
            profile_block.kind = "polygon"
        elif op == "spline":
            if (profile_block.points is not None or len(args) < 10 or
                    args[0].lower() != "through" or args[-1].lower() != "closed" or
                    (len(args) - 2) % 2):
                raise ValueError("profile spline requires: spline through u1 v1 ... u4 v4 closed")
            values = [number_argument(x, variables) for x in args[1:-1]]
            profile_block.points = list(zip(values[::2], values[1::2]))
            profile_block.kind = "spline"
        elif op == "end" and not args:
            if profile_block.points is None:
                raise ValueError("profile requires a polygon or spline")
            constructor = sm.create_spline_profile if profile_block.kind == "spline" else sm.create_profile
            frame.profiles[profile_block.name] = constructor(profile_block.points)
            self.profile = None
        else:
            raise ValueError("only polygon, spline, and end are allowed inside a profile")

    def open_profile(self, command, _):
        args = command.tail.split()
        frame = self.frame
        if len(args) != 1 or not IDENTIFIER.fullmatch(args[0]):
            raise ValueError("profile: one valid profile name required")
        if args[0] in frame.profiles:
            raise ValueError(f"duplicate profile name: {args[0]}")
        self.profile = _ProfileBlock(args[0])

    def sweep(self, command, variables):
        op = command.op
        args = expression_arguments(command.tail)
        sm = self.sm
        objects = self.frame.objects
        has_draft = op == "extrude" and len(args) >= 2 and args[-2].lower() == "draft"
        sweep_args = args[:-2] if has_draft else args
        if len(sweep_args) not in (7, 10, 13):
            raise ValueError(f"{op}: name profile x y z start end [dx dy dz [ux uy uz]]"
                             + (" [draft angle] required" if op == "extrude" else " required"))
        self.check_solid_name(args[0])
        profiles = self.visible_profiles()
        if args[1] not in profiles:
            raise ValueError(f"unknown profile: {args[1]}")
        values = tuple(number_argument(x, variables) for x in sweep_args[2:])
        if not all(math.isfinite(x) for x in values):
            raise ValueError("coordinates, range, axis, and xdir must be finite")
        options = {}
        if len(values) >= 8:
            options["axis"] = values[5:8]
        if len(values) == 11:
            options["xdir"] = values[8:11]
        if has_draft:
            draft_angle = number_argument(args[-1], variables)
            if not math.isfinite(draft_angle) or abs(draft_angle) >= 90:
                raise ValueError("draft angle must be finite and between -90 and 90 degrees")
            options["draft_angle"] = draft_angle
        objects[args[0]] = getattr(sm, f"create_{op}")(
            profiles[args[1]], values[:3], values[3], values[4], **options)

    def use_part(self, command, variables):
        args = command.tail.split()
        frame = self.frame
        objects = frame.objects
        groups = frame.groups
        materials = frame.materials
        if len(args) not in (1, 2) or any(not IDENTIFIER.fullmatch(x) for x in args):
            raise ValueError("use: part name and optional instance name required")
        part_name = args[0]
        if part_name not in self.program.parts:
            raise ValueError(f"unknown part: {part_name}")
        if part_name in self.stack:
            raise ValueError(f"recursive part use: {' -> '.join((*self.stack, part_name))}")
        if len(self.stack) >= 32 or self.instances.count >= 512:
            raise ValueError("part expansion limit exceeded")
        self.instances.count += 1
        if len(args) == 2:
            instance_name = args[1]
        else:
            names_used = self.instances.names
            names_used[part_name] = names_used.get(part_name, 0) + 1
            instance_name = f"{part_name}_{names_used[part_name]}"
        profiles = self.visible_profiles()
        try:
            evaluator = _TextEvaluator(self.sm, self.program, self.budget, self.instances,
                                       stack=(*self.stack, part_name), profiles=profiles)
            members, member_materials = evaluator.run(variables)
        except ValueError as exc:
            raise ValueError(f"use {part_name}: {exc}") from exc
        names = {name: f"{instance_name}__{name}" for name in members}
        collisions = set(names.values()) & (set(objects) | set(groups))
        if collisions:
            raise ValueError(f"use {part_name}: duplicate solid name: {', '.join(sorted(collisions))}")
        objects.update((names[name], solid) for name, solid in members.items())
        objects.tessellation.update((names[name], settings)
                                    for name, settings in members.tessellation.items())
        objects.top_groups.update((names[name], f"{instance_name}__{group_name}")
                                  for name, group_name in members.top_groups.items())
        objects.group_paths.update(
            (names[name], [dict(group, name=f"{instance_name}__{group['name']}")
                           for group in path])
            for name, path in members.group_paths.items())
        materials.update((names[name], material) for name, material in member_materials.items())
        frame.material_priority.update((names[name], float("inf")) for name in member_materials)

    def include_group(self, command, _):
        args = command.tail.split()
        frame = self.frame
        objects = frame.objects
        groups = frame.groups
        materials = frame.materials
        frames = self.frames
        if len(frames) == 1 or len(args) != 1 or not IDENTIFIER.fullmatch(args[0]):
            raise ValueError("include: one existing group name inside a group required")
        name = args[0]
        if any(scope.name == name for scope in frames):
            raise ValueError(f"include: cannot include an open group: {name}")
        if name in groups:
            raise ValueError(f"include: group already belongs to this group: {name}")
        owner = next((scope for scope in reversed(frames[:-1]) if name in scope.groups), None)
        if owner is None:
            raise ValueError(f"include: unknown group: {name}")
        if owner.group_parents.get(name) is not None:
            raise ValueError(f"include: group must be directly inside an open scope: {name}")
        # Move the completed subtree. Its local transforms are already
        # baked into the BReps; the new parent's transform runs at end.
        moved_groups = {name}
        for candidate in owner.groups:
            ancestor = owner.group_parents.get(candidate)
            while ancestor is not None:
                if ancestor == name:
                    moved_groups.add(candidate)
                    break
                ancestor = owner.group_parents.get(ancestor)
        members = owner.groups[name]
        occupied = set(objects) | set(groups) | {scope.name for scope in frames[1:]}
        collisions = (members | moved_groups) & occupied
        if collisions:
            raise ValueError(f"include: duplicate solid or group name: {', '.join(sorted(collisions))}")
        depth_delta = frame.depth - owner.depth
        source_objects = owner.objects
        for member in list(source_objects):
            if member not in members:
                continue
            objects[member] = source_objects.pop(member)
            for field in ("tessellation", "group_paths"):
                source_values = getattr(source_objects, field)
                if member in source_values:
                    getattr(objects, field)[member] = source_values.pop(member)
            source_objects.top_groups.pop(member, None)
            if member in owner.materials:
                materials[member] = owner.materials.pop(member)
            if member in owner.material_priority:
                frame.material_priority[member] = owner.material_priority.pop(member) + depth_delta
        for group in moved_groups:
            groups[group] = owner.groups.pop(group)
            frame.group_depths[group] = owner.group_depths.pop(group) + depth_delta
            frame.group_parents[group] = owner.group_parents.pop(group)

    def open_group(self, command, _):
        args = command.tail.split()
        frame = self.frame
        objects = frame.objects
        groups = frame.groups
        frames = self.frames
        if len(args) != 1 or not IDENTIFIER.fullmatch(args[0]):
            raise ValueError("group: one valid group name required")
        if args[0] in objects or args[0] in groups:
            raise ValueError(f"duplicate group name: {args[0]}")
        frames.append(_CommandFrame(name=args[0], depth=len(frames)))

    def close_group(self, command, _):
        sm = self.sm
        frame = self.frame
        objects = frame.objects
        groups = frame.groups
        materials = frame.materials
        frames = self.frames
        parent = frames[-2]
        collisions = set(objects) & set(parent.objects)
        if collisions:
            raise ValueError(f"group {frame.name}: duplicate solid name: {', '.join(sorted(collisions))}")
        if (set(objects) & set(parent.groups) or
                (set(groups) | {frame.name}) & (set(parent.objects) | set(parent.groups)) or
                frame.name in objects or frame.name in groups):
            raise ValueError(f"group {frame.name}: duplicate group or solid name")
        for name, solid in objects.items():
            try:
                sm.transform_brep(solid, frame.scale, frame.euler, frame.position)
            except (ValueError, RuntimeError) as exc:
                raise ValueError(f"group {frame.name}, solid {name}: {exc}") from exc
        if frame.group_material is not None:
            for name in objects:
                if frame.material_priority.get(name, -1) <= frame.depth:
                    materials[name] = frame.group_material
                    frame.material_priority[name] = frame.depth
        frames.pop()
        parent.objects.update(objects)
        parent.objects.tessellation.update(objects.tessellation)
        transform = {key: getattr(frame, key) for key in ("name", "scale", "euler", "position")}
        if frame.quaternion is not None:
            transform["quaternion"] = frame.quaternion
        if frame.invisible:
            transform["invisible"] = True
        if frame.properties:
            transform["properties"] = dict(frame.properties)
        parent.objects.group_paths.update(
            (name, [transform, *objects.group_paths.get(name, [])]) for name in objects)
        parent.objects.top_groups.update(objects.top_groups)
        if len(frames) == 1:
            parent.objects.top_groups.update((name, frame.name) for name in objects)
        parent.materials.update(materials)
        parent.material_priority.update(frame.material_priority)
        parent.groups.update(groups)
        parent.groups[frame.name] = set(objects)
        parent.group_depths.update(frame.group_depths)
        parent.group_depths[frame.name] = frame.depth
        parent.group_parents.update(
            (name, ancestor if ancestor is not None else frame.name)
            for name, ancestor in frame.group_parents.items() if name in groups)
        parent.group_parents[frame.name] = None

    def set_property(self, command, _):
        frame = self.frame
        frames = self.frames
        fields = command.tail.split(None, 1)
        if len(frames) == 1 or len(fields) != 2:
            raise ValueError("property: key and value inside a group required")
        literal = fields[1]
        if literal.startswith("`"):
            if not literal.endswith("`") or literal.count("`") != 2:
                raise ValueError("property: expected a single backtick-delimited string")
            value = literal[1:-1]
        else:
            try:
                value = json.loads(literal)
                # json.loads accepts NaN/Infinity, but glTF requires JSON numbers.
                json.dumps(value, allow_nan=False)
            except (ValueError, OverflowError) as exc:
                raise ValueError("property: value must be valid JSON with finite numbers") from exc
        frame.properties[fields[0]] = value

    def set_invisible(self, command, _):
        args = command.tail.split()
        frame = self.frame
        frames = self.frames
        if len(frames) == 1 or args:
            raise ValueError("invisible: no arguments inside a group required")
        frame.invisible = True

    def set_quaternion(self, command, variables):
        args = expression_arguments(command.tail)
        frame = self.frame
        frames = self.frames
        expression = command.tail
        axis_angle = bool(re.match(r"dquaternion\s*\(", expression))
        if len(frames) == 1 or (not axis_angle and len(args) != 4):
            raise ValueError("quaternion: four numbers x y z w or dquaternion(x,y,z,degrees) inside a group required")
        if frame.rotation_command == "euler":
            raise ValueError("quaternion and euler are mutually exclusive in the same group")
        if axis_angle:
            values = quaternion_expression(expression, variables)
        else:
            try:
                components = tuple(number_argument(x, variables) for x in args)
            except ValueError as exc:
                raise ValueError(f"quaternion: {exc}") from exc
            values = _normalize_quaternion(components)
        frame.quaternion = values
        frame.euler = _quaternion_euler(values)
        frame.rotation_command = "quaternion"

    def set_transform(self, command, variables):
        op = command.op
        args = expression_arguments(command.tail)
        frame = self.frame
        frames = self.frames
        if len(frames) == 1 or len(args) != 3:
            raise ValueError(f"{op}: three numbers inside a group required")
        try:
            values = tuple(number_argument(x, variables) for x in args)
        except ValueError as exc:
            raise ValueError(f"{op}: {exc}") from exc
        if op == "scale" and any(x <= 0 for x in values):
            raise ValueError("scale: factors must be positive")
        if op == "euler":
            if frame.rotation_command == "quaternion":
                raise ValueError("quaternion and euler are mutually exclusive in the same group")
            frame.rotation_command = "euler"
        setattr(frame, op, values)

    def primitive(self, command, variables):
        op = command.op
        args = expression_arguments(command.tail)
        sm = self.sm
        objects = self.frame.objects
        count = PRIMITIVE_ARGUMENTS[op]
        allowed = (count + 1, count + 4) if op in AXIAL_PRIMITIVES else (count + 1,)
        if len(args) not in allowed:
            suffix = " (optionally followed by axis dx dy dz)" if op in AXIAL_PRIMITIVES else ""
            raise ValueError(f"{op}: name and {count} numbers required{suffix}")
        self.check_solid_name(args[0])
        values = tuple(number_argument(x, variables) for x in args[1:])
        if not all(math.isfinite(x) for x in values):
            raise ValueError("coordinates, dimensions, and axis must be finite")
        dimensions = values[:count]
        axis = values[count:]
        validate_primitive(op, dimensions)
        if axis and not any(axis):
            raise ValueError("axis must be nonzero")
        extra = (axis,) if axis else ()
        objects[args[0]] = getattr(sm, f"create_{op}")(dimensions[:3], *dimensions[3:], *extra)

    def boolean(self, command, _):
        op = command.op
        args = command.tail.split()
        sm = self.sm
        frame = self.frame
        objects = frame.objects
        groups = frame.groups
        materials = frame.materials
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
        self.check_solid_name(args[0], consumed=consumed, consumed_groups=args[1:])
        paths = [objects.group_paths.get(name, []) for name in consumed]
        common_path = []
        for entries in zip(*paths):
            if any(entry != entries[0] for entry in entries[1:]):
                break
            # A group explicitly used as an operand is consumed.
            if entries[0]["name"] in args[1:]:
                break
            common_path.append(entries[0])
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
            frame.material_priority.pop(name, None)
            objects.tessellation.pop(name, None)
            objects.top_groups.pop(name, None)
            objects.group_paths.pop(name, None)
        for name, members in list(groups.items()):
            if name in args[1:]:
                del groups[name]
            else:
                contained = consumed <= members
                members.difference_update(consumed)
                if contained:
                    members.add(args[0])
        objects[args[0]] = fn(left, right)
        objects.group_paths[args[0]] = common_path
        if common_path:
            objects.top_groups[args[0]] = common_path[0]["name"]

    def print_faces(self, command, _):
        args = command.tail.split()
        sm = self.sm
        objects = self.frame.objects
        if len(args) != 1 or args[0] not in objects:
            raise ValueError("faces: existing solid name required")
        print(f"{args[0]} faces: {json.dumps(sm.face_info(objects[args[0]]))}")

    def offset_or_shell(self, command, variables):
        op = command.op
        args = expression_arguments(command.tail)
        sm = self.sm
        objects = self.frame.objects
        if len(args) < 2 or args[0] not in objects or (op == "offset" and len(args) != 2):
            raise ValueError(f"{op}: existing solid name and distance"
                             + (" followed by optional face indices required" if op == "shell" else " required"))
        distance = number_argument(args[1], variables)
        if not math.isfinite(distance) or distance == 0:
            raise ValueError("distance must be finite and nonzero")
        options = {}
        if op == "shell":
            faces = [number_argument(x, variables) for x in args[2:]]
            if not all(face.is_integer() for face in faces):
                raise ValueError("shell: face indices must be integers")
            options["faces_to_shell"] = list(map(int, faces))
        objects[args[0]] = getattr(sm, f"{op}_brep")(objects[args[0]], distance, **options)

    def finish_edges(self, command, variables):
        op = command.op
        args = expression_arguments(command.tail)
        sm = self.sm
        objects = self.frame.objects
        if len(args) != 2 or args[0] not in objects:
            raise ValueError(f"{op}: existing solid name and positive width/radius required")
        size = number_argument(args[1], variables)
        if not math.isfinite(size) or size <= 0:
            raise ValueError(f"{op}: width/radius must be finite and positive")
        fn = sm.chamfer_fillet if op == "chamfer" else sm.circular_fillet
        objects[args[0]] = fn(objects[args[0]], size)

    def set_tessellation(self, command, variables):
        args = expression_arguments(command.tail)
        objects = self.frame.objects
        if len(args) != 3 or args[0] not in objects:
            raise ValueError("tessellation: existing solid name, chord and angle required")
        chord, angle = (None if value.lower() == "default" else number_argument(value, variables)
                        for value in args[1:])
        if chord is not None and not 0.001 <= chord <= 2:
            raise ValueError("chord must be between 0.001 and 2")
        if angle is not None and not 1 <= angle <= 90:
            raise ValueError("angle must be between 1 and 90 degrees")
        objects.tessellation[args[0]] = (chord, angle)

    def set_material(self, command, variables):
        args = expression_arguments(command.tail)
        frame = self.frame
        objects = frame.objects
        groups = frame.groups
        materials = frame.materials
        if len(args) not in (6, 7) or (args[0] not in objects and args[0] not in groups and
                               args[0] != frame.name):
            raise ValueError("material: existing solid or group name and five numbers required, with optional opacity")
        material = normalize_material({
            "baseColor": [number_argument(x, variables) for x in args[1:4]],
            "metallic": number_argument(args[4], variables), "roughness": number_argument(args[5], variables),
            "opacity": number_argument(args[6], variables) if len(args) == 7 else 1.0})
        if args[0] in objects:
            materials[args[0]] = material
            frame.material_priority[args[0]] = float("inf")
        elif args[0] == frame.name:
            frame.group_material = material
        else:
            depth = frame.group_depths[args[0]]
            for name in groups[args[0]]:
                if frame.material_priority.get(name, -1) <= depth:
                    materials[name] = material
                    frame.material_priority[name] = depth


_TEXT_HANDLERS = {
    "profile": _TextEvaluator.open_profile,
    "extrude": _TextEvaluator.sweep,
    "revolve": _TextEvaluator.sweep,
    "use": _TextEvaluator.use_part,
    "include": _TextEvaluator.include_group,
    "group": _TextEvaluator.open_group,
    "end": _TextEvaluator.close_group,
    "property": _TextEvaluator.set_property,
    "invisible": _TextEvaluator.set_invisible,
    "quaternion": _TextEvaluator.set_quaternion,
    "scale": _TextEvaluator.set_transform,
    "euler": _TextEvaluator.set_transform,
    "position": _TextEvaluator.set_transform,
    "union": _TextEvaluator.boolean,
    "subtract": _TextEvaluator.boolean,
    "intersect": _TextEvaluator.boolean,
    "faces": _TextEvaluator.print_faces,
    "offset": _TextEvaluator.offset_or_shell,
    "shell": _TextEvaluator.offset_or_shell,
    "chamfer": _TextEvaluator.finish_edges,
    "fillet": _TextEvaluator.finish_edges,
    "tessellation": _TextEvaluator.set_tessellation,
    "material": _TextEvaluator.set_material,
    **dict.fromkeys(PRIMITIVE_ARGUMENTS, _TextEvaluator.primitive),
}


def parse_commands(source: str | ModelProgram, sm, *, variables=()):
    """Evaluate a text model; every use builds fresh BReps from its part body."""
    program = ModelProgram(source) if isinstance(source, str) else source
    return _TextEvaluator(sm, program, ExpansionBudget(), _PartInstances()).run(variables)


def evaluate(source: str | ModelProgram, mode: str, sm, *, variables=()):
    if mode == "text":
        output = io.StringIO()
        with redirect_stdout(output):
            objects, materials = parse_commands(source, sm, variables=variables)
        return objects, materials, output.getvalue()
    if mode != "python":
        raise ValueError("mode must be text or python")
    # This is a local code editor. Python input has full local process access.
    namespace = {"sm": sm, "Group": Group, "__builtins__": __builtins__}
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(source, "<model>", "exec"), namespace)
    if "objects" in namespace or isinstance(namespace.get("result"), Group):
        roots = namespace["objects"] if "objects" in namespace else {"result": namespace["result"]}
        with redirect_stdout(output):
            objects, materials = _python_objects(roots, namespace.get("materials", {}), sm)
        return objects, materials, output.getvalue()
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
        if any(group.get("invisible", False)
               for group in getattr(objects, "group_paths", {}).get(name, [])):
            continue
        local_chord, local_angle = getattr(objects, "tessellation", {}).get(name, (None, None))
        effective_chord = chord if local_chord is None else local_chord
        effective_angle = angle if local_angle is None else local_angle
        poly = sm.tessellate(solid, chord_height_tolerance=effective_chord,
                             curve_angle_tolerance_deg=effective_angle,
                             surface_angle_tolerance_deg=effective_angle)
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
                       "material": materials.get(name, normalize_material({})),
                       "group": getattr(objects, "top_groups", {}).get(name, name),
                       "groupPath": getattr(objects, "group_paths", {}).get(name, [])})
    return output


# Compatibility entry points; serialization lives outside the model evaluator.
def to_glb(meshes, scale=1, animation_source=""):
    from model_export import to_glb as encode
    return encode(meshes, scale, animation_source)


def to_usdz(meshes, scale=1, animation_source="", animation_clip=None):
    from model_export import to_usdz as encode
    return encode(meshes, scale, animation_source, animation_clip)
