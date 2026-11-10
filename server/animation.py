"""Bounded TRS loop language and sampling shared by mesh export entry points.

Named clips overwrite a group's local transform channels. Euler values are
unwrapped degrees, interpolated component by component.
No native geometry is evaluated here.
"""

import math
import re
import struct
from dataclasses import dataclass

from model_syntax import (ExpressionScope, ModelProgram, SharedCalculations, argument_expression,
                          bounded_range, command_records, expression_arguments, interpolate, loop_header,
                          number_argument, range_expressions, validate_interpolation, validate_number_expression)

DEFAULTS = {"position": [0., 0., 0.], "euler": [0., 0., 0.], "scale": [1., 1., 1.]}
MAX_SAMPLES = 120_000
_BASE_COMPONENT = re.compile(r"\bbase\.(position|euler|scale)\.([xyz])\b")
_CLIP_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9-]*")


def _group_paths(meshes):
    groups = {}
    for mesh in meshes:
        path = ()
        for entry in mesh.get("groupPath", []):
            path += (entry["name"],)
            groups[path] = entry
    return groups


def _matching_paths(target, paths):
    if "/" in target:
        return [path for path in paths if "/".join(path) == target.removeprefix("/")]
    return [path for path in paths if path[-1] == target]


def _error(line, message):
    return ValueError(f"Animation line {line}: {message}")


def _fail(line, message):
    raise _error(line, message)


@dataclass
class _Block:
    line: int
    fields: list[str]
    body: list
    end: int
    looped: bool


@dataclass
class _Loop:
    line: int
    name: str
    arguments: str
    body: list


class AnimationProgram:
    """Read authored blocks once. A loop generates statements at its own level."""

    def __init__(self, source):
        if not isinstance(source, str) or len(source) > 100_000:
            raise ValueError("animationSource must be text (at most 100000 characters)")
        self.globals = []
        self.body = self._read(iter(command_records(source, line_error=lambda cmd, text: _error(cmd.line, text))))

    def _read(self, records, context="root", opener=None, depth=0, in_loop=False):
        body = []
        for command in records:
            line, op = command.line, command.op
            if not op:
                continue
            if op == "end":
                if opener is None or command.tail:
                    _fail(line, "end takes no arguments and requires an open block")
                return body, line
            if op == "let":
                if context != "root" or in_loop:
                    _fail(line, "let is only allowed at the top level")
                self.globals.append(command)
                continue
            if op == "for":
                if depth >= 32:
                    _fail(line, "loop nesting limit exceeded (32)")
                try:
                    name, arguments = loop_header(command.text, ignore_case=True)
                except ValueError as exc:
                    _fail(line, f"for: {exc}")
                items, _ = self._read(records, context, command, depth + 1, True)
                body.append(_Loop(line, name, arguments, items))
                continue
            try:
                fields = expression_arguments(command.tail)
            except ValueError as exc:
                _fail(line, str(exc))
            if context == "root" and op == "animation":
                if len(fields) == 2 and fields[0].lower() == "loop":
                    fields.insert(0, "main")
                if len(fields) != 3 or fields[1].lower() != "loop":
                    _fail(line, "expected animation [name] loop <seconds>")
                if "${" not in fields[0] and not _CLIP_NAME.fullmatch(fields[0]):
                    _fail(line, "invalid animation clip name")
                items, end = self._read(records, "animation", command, depth)
                body.append(_Block(line, [fields[0], fields[2]], items, end, in_loop))
            elif context == "animation" and op == "track" and len(fields) == 1:
                items, end = self._read(records, "track", command, depth)
                body.append(_Block(line, fields, items, end, in_loop))
            elif context == "track" and op == "key" and len(fields) == 5 and fields[1].lower() in DEFAULTS:
                fields[1] = fields[1].lower()
                body.append((line, [op, *fields]))
            elif context == "track" and not in_loop and op == "cycle" and len(fields) == 2 and fields[0].lower() in DEFAULTS:
                fields[0] = fields[0].lower()
                body.append((line, [op, *fields]))
            else:
                expected = {"root": "let, animation, or for", "animation": "track, for, or end",
                            "track": "key, for, or end" if in_loop else "key, cycle, for, or end"}
                _fail(line, f"expected {expected[context]}")
        if opener is not None:
            _fail(opener.line, f"{opener.op} has no end")
        return body

    def evaluate(self, scope, *, syntax_only=False, meshes=None):
        if not self.body:
            return None
        return _AnimationEvaluator(scope, syntax_only, _group_paths(meshes or ())).parse(self.body)


class _AnimationEvaluator:
    def __init__(self, scope, syntax_only, groups):
        self.scope, self.syntax_only, self.groups = scope, syntax_only, groups
        self.poses = {}

    def name(self, word, line, scope):
        try:
            expand = validate_interpolation if self.syntax_only else interpolate
            return expand(word, scope)
        except ValueError as exc:
            _fail(line, str(exc))

    def parse(self, body):
        clips = []
        names = set()
        for block, scope in self.expand(body, self.scope, [0]):
            raw_name, length = block.fields
            dynamic = self.syntax_only and "${" in raw_name
            name = self.name(raw_name, block.line, scope)
            if not _CLIP_NAME.fullmatch(name):
                _fail(block.line, "invalid animation clip name")
            if dynamic:
                name = raw_name
            if not (self.syntax_only and (dynamic or block.looped)):
                if len(names) >= 64 or name in names:
                    _fail(block.line, "duplicate clip name or more than 64 clips")
                names.add(name)
            duration = self.number(length, block.line, scope)
            if not self.syntax_only and not 0 < duration <= 1000:
                _fail(block.line, "duration must be greater than 0 and at most 1000 seconds")
            tracks, targets = [], set()
            self.key_count = 0
            work = [0]
            for entry, track_scope in self.expand(block.body, scope, work):
                raw_target = entry.fields[0]
                dynamic_target = self.syntax_only and "${" in raw_target
                target = self.name(raw_target, entry.line, track_scope)
                if dynamic_target:
                    target = raw_target
                if not (self.syntax_only and (dynamic_target or entry.looped)):
                    if len(targets) >= 256 or target in targets:
                        _fail(entry.line, "duplicate target or more than 256 tracks")
                    targets.add(target)
                tracks.append(self.track(target, duration, entry.body, entry.end, track_scope, work))
            if not tracks:
                _fail(block.end, "animation needs at least one track")
            clips.append({"name": name, "duration": duration, "tracks": tracks})
        if not self.syntax_only:
            total = 0
            for clip in clips:
                for track in clip["tracks"]:
                    total += len(sample_times(track, clip["duration"]))
                    if total > MAX_SAMPLES:
                        raise ValueError("Animation exceeds 120000 generated samples")
        return {"clips": clips} if clips else None

    def substitute_base(self, source, target):
        if not _BASE_COMPONENT.search(source):
            return source
        if target is None:
            raise ValueError("base is only available inside a track")
        if target not in self.poses:
            matches = _matching_paths(target, self.groups) if self.groups is not None else []
            if len(matches) == 1:
                self.poses[target] = _base_pose(self.groups[matches[0]])
            elif self.syntax_only:
                self.poses[target] = DEFAULTS
            else:
                raise ValueError("base requires an unambiguous evaluated target group")
        base = self.poses[target]

        def component(match):
            channel, axis = match.groups()
            return format(base[channel]["xyz".index(axis)], ".17g")

        return _BASE_COMPONENT.sub(component, source)

    def number(self, word, line, scope, *, target=None, angle=False):
        try:
            word = self.substitute_base(word, target)
            if self.syntax_only:
                validate_number_expression(argument_expression(word), scope)
                return 1.
            value = number_argument(word, scope)
            if not self.syntax_only and not angle and abs(value) > 1e9:
                raise ValueError("number must be finite and within ±1e9")
            return 1. if self.syntax_only else value
        except (ValueError, OverflowError) as exc:
            _fail(line, str(exc))

    def visit(self, line, work):
        work[0] += 1
        if work[0] > 20_000:
            _fail(line, "loop expansion limit exceeded (20000)")

    def expand(self, body, scope, work, target=None):
        for item in body:
            if not isinstance(item, _Loop):
                self.visit(item.line if isinstance(item, _Block) else item[0], work)
                yield item, scope
                continue
            self.visit(item.line, work)
            if item.name in scope:
                _fail(item.line, f"loop variable already defined: {item.name}")
            try:
                arguments = self.substitute_base(item.arguments, target)
                expressions = range_expressions(arguments)
                if self.syntax_only:
                    for expression in expressions:
                        validate_number_expression(expression, scope, max_nodes=512)
                    values = (1,)  # Validate the body once with a symbolic loop variable.
                else:
                    values = bounded_range(expressions, scope, 4096)
            except (ValueError, OverflowError) as exc:
                _fail(item.line, str(exc))
            for value in values:
                self.visit(item.line, work)
                nested = ExpressionScope(scope)
                nested[item.name] = value
                yield from self.expand(item.body, nested, work, target)

    def track(self, target, duration, body, end_line, inherited, work):
        track = {"target": target, "channels": {}}
        for (line, words), scope in self.expand(body, inherited, work, target):
            if words[0] == "cycle":
                channel = words[1]
                cycles = track.setdefault("cycles", {})
                if channel in cycles:
                    _fail(line, "duplicate channel cycle")
                period = self.number(words[2], line, scope, target=target)
                if not self.syntax_only and not 0 < period <= duration:
                    _fail(line, "cycle period must be greater than 0 and at most the loop duration")
                cycles[channel] = period
            else:
                channel = words[2]
                time = self.number(words[1], line, scope, target=target)
                value = [self.number(word, line, scope, target=target, angle=channel == "euler")
                         for word in words[3:]]
                keys = track["channels"].setdefault(channel, [])
                if not self.syntax_only and (not 0 <= time <= duration or (keys and time <= keys[-1][0])):
                    _fail(line, "channel key times must increase within the loop duration")
                if not self.syntax_only and channel == "scale" and min(value) <= 0:
                    _fail(line, "scale must be positive")
                keys.append([time, value])
                self.key_count += 1
                if self.key_count > 4096:
                    _fail(line, "at most 4096 keys are allowed")
        if not track["channels"]:
            _fail(end_line, "track needs keys")
        for channel in track.get("cycles", {}):
            if channel not in track["channels"]:
                _fail(end_line, f"{channel} cycle needs keys")
        if not self.syntax_only:
            for channel, keys in track["channels"].items():
                end = keys[-1][0]
                if keys[0][0] != 0 or end <= 0:
                    _fail(end_line, f"{channel} needs keys at 0 and a positive end time")
                period = track.get("cycles", {}).get(channel)
                if period is not None and end != period:
                    _fail(end_line, f"{channel} needs keys at 0 and {period} seconds")
                if period is None and end < duration:
                    track.setdefault("implicit_cycles", {})[channel] = end
        return track


def parse_animation(source="", *, scope=None, syntax_only=False):
    """Parse authored animation without a separate model source."""
    program = AnimationProgram(source)
    calculations = SharedCalculations(animation=program.globals, inherited=() if scope is None else scope)
    return program.evaluate(calculations.resolved_scope(), syntax_only=syntax_only)


def _base_pose(group):
    from transforms import _quaternion_euler
    pose = {key: list(group.get(key, value)) for key, value in DEFAULTS.items()}
    if "quaternion" in group:
        pose["quaternion"] = list(group["quaternion"])
        pose["euler"] = list(_quaternion_euler(group["quaternion"]))
    return pose


class ModelAnimationSources:
    """Shared text definitions used by model evaluation, preview, and export."""

    def __init__(self, source, mode, animation_source):
        if mode not in ("text", "python"):
            raise ValueError("mode must be text or python")
        self.animation = (animation_source if isinstance(animation_source, AnimationProgram)
                          else AnimationProgram(animation_source))
        self.model = ModelProgram(source) if mode == "text" else source
        model_globals = self.model.root_calculations() if mode == "text" else ()
        self.calculations = SharedCalculations(model_globals, self.animation.globals)

    def model_variables(self):
        return self.calculations.animation_values()

    def resolve(self, meshes=None, *, syntax_only=False):
        if not self.animation.body:
            self.calculations.animation_values()
            return None
        return self.animation.evaluate(self.calculations.resolved_scope(), syntax_only=syntax_only, meshes=meshes)


def resolve_animation(source, model_source="", mode="text", meshes=None, *, syntax_only=False):
    """Resolve shared variables and each target's immutable initial TRS."""
    if mode not in ("text", "python"):
        raise ValueError("mode must be text or python")
    program = AnimationProgram(source)
    if not program.body and not program.globals:
        return None
    return ModelAnimationSources(model_source, mode, program).resolve(meshes, syntax_only=syntax_only)


def resolve_animation_source(source, model_source="", mode="text", meshes=None, *, syntax_only=False):
    return animation_text(resolve_animation(source, model_source, mode, meshes, syntax_only=syntax_only))


def animation_text(animation):
    """Serialize evaluated keys for the browser; the result may exceed the source size."""
    if animation is None:
        return ""
    lines = []
    for clip in animation["clips"]:
        lines.append(f'animation {clip["name"]} loop {clip["duration"]:.17g}')
        for track in clip["tracks"]:
            lines.append(f'track {track["target"]}')
            for channel, period in track.get("cycles", {}).items():
                lines.append(f'cycle {channel} {period:.17g}')
            for channel, keys in track["channels"].items():
                for time, values in keys:
                    lines.append(f'key {time:.17g} {channel} ' + ' '.join(f'{v:.17g}' for v in values))
            lines.append('end')
        lines.append('end')
    return '\n'.join(lines)


def select_clip(animation, name=None):
    if not animation:
        if name:
            raise ValueError(f"Unknown animation clip: {name}")
        return None
    if name is None or name == "":
        return animation["clips"][0]
    for clip in animation["clips"]:
        if clip["name"] == name:
            return clip
    raise ValueError(f"Unknown animation clip: {name}")


def bind_animation(animation, meshes):
    return _bind_tracks(animation, _group_paths(meshes))


def _bind_tracks(animation, groups):
    if animation is None:
        return {}
    bound = {}
    for track in animation["tracks"]:
        target = track["target"]
        matches = _matching_paths(target, groups)
        if len(matches) != 1:
            raise ValueError(f"Animation target {target}: group missing, invisible, consumed by Boolean, or ambiguous; use a full group path")
        path = matches[0]
        if path in bound:
            raise ValueError(f"Animation target {target}: duplicate group track")
        bound[path] = dict(track, base=_base_pose(groups[path]))
    return bound


def prepare_animation(source, meshes, *, resolved=None):
    groups = _group_paths(meshes)
    animation = resolved
    if animation is None:
        animation = resolve_animation(source, mode="python", meshes=meshes)
    clips = animation["clips"] if animation else []
    return animation, [_bind_tracks(clip, groups) for clip in clips]


def _channel_period(track, channel):
    return track.get("cycles", {}).get(channel) or track.get("implicit_cycles", {}).get(channel)


def _cycle_ratio(time, period):
    ratio = time / period
    if math.isfinite(ratio):
        nearest = round(ratio)
        if math.isclose(ratio, nearest, rel_tol=4 * math.ulp(1.)):
            return nearest
    return ratio


def _before_seam(time):
    # Keep the pre-jump sample distinct after GLB stores timestamps as float32.
    bits, = struct.unpack("<I", struct.pack("<f", time))
    return struct.unpack("<f", struct.pack("<I", max(0, bits - 1)))[0]


def sample_track(track, time):
    result = dict(track.get("base", DEFAULTS))
    for channel, keys in track["channels"].items():
        period = _channel_period(track, channel)
        ratio = _cycle_ratio(time, period) if period else 0
        turns = math.floor(ratio)
        local = (0. if ratio == turns else time - turns * period) if period else time
        value = list(keys[-1][1])
        if local <= keys[0][0]:
            value = list(keys[0][1])
        else:
            for (a, av), (b, bv) in zip(keys, keys[1:]):
                if local <= b:
                    alpha = (local-a)/(b-a)
                    value = [x+(y-x)*alpha for x, y in zip(av, bv)]
                    break
        if channel == "euler" and channel in track.get("cycles", {}):
            value = [v + turns * (b-a) for v, a, b in zip(value, keys[0][1], keys[-1][1])]
        if channel == "euler":
            result.pop("quaternion", None)
        result[channel] = value
    return result


def sample_times(track, duration):
    # Expand cycles only for portable export; playback uses modular time.
    times = {0., duration}
    for channel, keys in track["channels"].items():
        repeat = _channel_period(track, channel)
        period = repeat or duration
        ratio = _cycle_ratio(duration, period)
        if not math.isfinite(ratio) or ratio > MAX_SAMPLES:
            raise ValueError("Animation exceeds 120000 generated samples")
        count = math.ceil(ratio)
        jumps = (repeat is not None and keys[0][1] != keys[-1][1]
                 and not (channel == "euler" and channel in track.get("cycles", {})))
        steps = []
        for (a, av), (b, bv) in zip(keys, keys[1:]):
            subdivisions = 1
            if channel == "euler":
                changes = [abs(y-x) for x, y in zip(av, bv)]
                subdivisions = max(1, math.ceil(sum(changes)/45))
                # A single Euler axis follows one rotation arc: elapsed time
                # adds no curvature. Keep 60 Hz for coupled Euler rotations.
                if sum(delta != 0 for delta in changes) > 1:
                    subdivisions = max(subdivisions, math.ceil((b-a)*60))
            steps.append(subdivisions)
        if count * sum(steps) + (math.floor(ratio) if jumps else 0) + 1 > MAX_SAMPLES:
            raise ValueError("Animation exceeds 120000 generated samples")
        for cycle in range(count):
            offset = cycle * period
            for ((a,_),(b,_)), subdivisions in zip(zip(keys,keys[1:]), steps):
                times.update(min(duration, offset + a + (b-a)*i/subdivisions) for i in range(subdivisions))
            if jumps and cycle + 1 <= ratio:
                seam = duration if cycle + 1 == ratio else (cycle + 1) * period
                times.update((_before_seam(seam), seam))
            if len(times) > MAX_SAMPLES:
                raise ValueError("Animation exceeds 120000 generated samples")
    ordered = sorted(times)
    if not (track.get("cycles") or track.get("implicit_cycles")):
        return ordered
    # Repeated channels can reach the same timestamp via different arithmetic.
    merged = []
    for time in ordered:
        if merged and math.isclose(time, merged[-1], rel_tol=4 * math.ulp(1.)):
            merged[-1] = time
        else:
            merged.append(time)
    return merged


def animation_meshes(meshes, bound):
    """Attach tracks directly to existing groups, without helper nodes."""
    output = []
    for mesh in meshes:
        prefix, path = (), []
        for entry in mesh.get("groupPath", []):
            prefix += (entry["name"],)
            path.append(dict(entry, animation=bound[prefix]) if prefix in bound else entry)
        output.append(dict(mesh, groupPath=path))
    return output
