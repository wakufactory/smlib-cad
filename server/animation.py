"""Bounded TRS loop language and sampling shared by mesh export entry points.

Named clips overwrite a group's local transform channels. Euler values are
unwrapped degrees, interpolated component by component.
No native geometry is evaluated here.
"""

import math
import re
import struct

DEFAULTS = {"position": [0., 0., 0.], "euler": [0., 0., 0.], "scale": [1., 1., 1.]}
MAX_SAMPLES = 120_000
_DECIMAL = r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"


def _angle_expression(source):
    """Small decimal arithmetic grammar, shared with the browser (no eval)."""
    if source.startswith("${") and source.endswith("}"):
        source = source[2:-1]
    tokens = re.findall(_DECIMAL + r"|\S", source)
    if not tokens or len(tokens) > 512:
        raise ValueError("angle expression must contain 1 to 512 tokens")
    index = 0

    def finite(value):
        if not math.isfinite(value):
            raise ValueError("angle expression result must be finite")
        return value

    def expression(depth=0, product=False):
        nonlocal index
        if depth > 32:
            raise ValueError("angle expression is too deeply nested")
        if product:
            value = atom(depth)
        else:
            value = expression(depth, True)
        operators = ("*", "/") if product else ("+", "-")
        while index < len(tokens) and tokens[index] in operators:
            op = tokens[index]
            index += 1
            right = atom(depth) if product else expression(depth, True)
            if op == "/" and right == 0:
                raise ValueError("angle expression: division by zero")
            value = finite({"+": lambda: value + right, "-": lambda: value - right,
                            "*": lambda: value * right, "/": lambda: value / right}[op]())
        return value

    def atom(depth):
        nonlocal index
        if depth > 32:
            raise ValueError("angle expression is too deeply nested")
        token = tokens[index] if index < len(tokens) else ""
        index += 1
        if token in ("+", "-"):
            value = atom(depth + 1)
            return -value if token == "-" else value
        if token == "(":
            value = expression(depth + 1)
            if index >= len(tokens) or tokens[index] != ")":
                raise ValueError("angle expression: expected closing parenthesis")
            index += 1
            return value
        if not re.fullmatch(_DECIMAL, token):
            raise ValueError("angle expression: expected a finite number or parenthesized expression")
        return finite(float(token))

    value = expression()
    if index != len(tokens):
        raise ValueError("angle expression: unexpected token")
    return value


def _animation_words(line, n):
    """Keep whitespace inside parenthesized or ${...} key expressions."""
    words = line.split()
    if not words or words[0] not in ("key", "animation", "cycle"):
        return words
    words, word, stack = [], "", []
    for char in line:
        if char.isspace() and not stack:
            if word:
                words.append(word)
                word = ""
            continue
        word += char
        if char in "({":
            stack.append(char)
        elif char in ")}":
            if not stack or stack.pop() != {")": "(", "}": "{"}[char]:
                raise ValueError(f"Animation line {n}: unmatched expression delimiter")
    if stack:
        raise ValueError(f"Animation line {n}: unmatched expression delimiter")
    if word:
        words.append(word)
    return words


def _expand_animation_loops(lines, scope):
    """Expand bounded key-generating loops, retaining original line numbers."""
    from modeler import _ExpressionScope, _number_expression, _range_expressions
    budget = 0

    def fail(n, message):
        raise ValueError(f"Animation line {n}: {message}")

    def expand(records, inherited, depth=0, origin=1):
        nonlocal budget
        if depth > 32:
            fail(origin, "loop nesting limit exceeded (32)")
        output, index = [], 0
        while index < len(records):
            n, words = records[index]
            budget += 1
            if budget > 20000:
                fail(n, "loop expansion limit exceeded (20000)")
            if words[0] == "for":
                match = re.fullmatch(r"for\s+([A-Za-z_][A-Za-z_0-9]*)\s+in\s+range\((.*)\)", " ".join(words))
                if not match:
                    fail(n, "expected for <name> in range(count) or range(start, stop[, step])")
                name = match[1]
                if name in inherited:
                    fail(n, f"loop variable already defined: {name}")
                try:
                    values = [_number_expression(arg, inherited) for arg in _range_expressions(match[2])]
                    if not 1 <= len(values) <= 3 or any(not float(v).is_integer() for v in values):
                        fail(n, "range arguments must be one to three integers")
                    iteration = range(*map(int, values))
                    if len(iteration) > 4096:
                        fail(n, "loop iteration limit exceeded (4096)")
                except (ValueError, OverflowError) as exc:
                    fail(n, str(exc))
                end, nesting = index + 1, 1
                while end < len(records):
                    op = records[end][1][0]
                    if op == "for":
                        nesting += 1
                    elif records[end][1] == ["end"]:
                        nesting -= 1
                        if nesting == 0:
                            break
                    elif op != "key":
                        fail(records[end][0], "for body allows only key and nested for blocks")
                    end += 1
                if nesting:
                    fail(n, "for has no end")
                body = records[index+1:end]
                for value in iteration:
                    budget += 1
                    if budget > 20000:
                        fail(n, "loop expansion limit exceeded (20000)")
                    nested = _ExpressionScope(inherited)
                    nested[name] = value
                    output.extend(expand(body, nested, depth+1, n))
                index = end
            elif depth:
                if len(words) != 6 or words[0] != "key" or words[2] not in DEFAULTS:
                    fail(n, "for body allows only key and nested for blocks")
                try:
                    def numeric(word):
                        expression = word[2:-1] if word.startswith("${") and word.endswith("}") else word
                        return format(float(_number_expression(expression, inherited)), ".17g")
                    output.append((n, ["key", numeric(words[1]), words[2], *map(numeric, words[3:])]))
                except (ValueError, OverflowError) as exc:
                    fail(n, str(exc))
            else:
                output.append((n, words))
            index += 1
        return output

    # Only track bodies may contain control blocks.
    output, index = [], 0
    while index < len(lines):
        n, words = lines[index]
        if words[0] == "for":
            fail(n, "for is only allowed inside a track")
        output.append((n, words))
        if words[0] == "track":
            end, nesting = index+1, 0
            while end < len(lines):
                op = lines[end][1][0]
                if op == "for":
                    nesting += 1
                elif lines[end][1] == ["end"]:
                    if nesting == 0:
                        break
                    nesting -= 1
                end += 1
            output.extend(expand(lines[index+1:end], _ExpressionScope(scope or ())))
            index = end-1
        index += 1
    return output


def _validate_expression(word, scope):
    """Check expressions without substituting/evaluating an unknown initial pose."""
    import ast
    from modeler import _expression_tree, _EXPRESSION_CONSTANTS, _EXPRESSION_FUNCTIONS
    expression = word[2:-1] if word.startswith("${") and word.endswith("}") else word
    tree = _expression_tree(expression)
    budget = 512
    def visit(node, depth=0):
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > 32:
            raise ValueError("expression limit exceeded")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if not math.isfinite(node.value):
                raise ValueError("number must be finite")
        elif isinstance(node, ast.Name):
            if node.id not in (scope or {}) and node.id not in _EXPRESSION_CONSTANTS:
                raise ValueError(f"unknown variable: {node.id}")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            visit(node.operand, depth+1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            visit(node.left, depth+1); visit(node.right, depth+1)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            functions = getattr(scope, "functions", {})
            if name not in functions and name not in _EXPRESSION_FUNCTIONS:
                raise ValueError(f"unknown function: {name}")
            arity = len(functions[name][0]) if name in functions else _EXPRESSION_FUNCTIONS[name][1]
            if node.keywords or len(node.args) != arity:
                raise ValueError(f"{name}: expected {arity} positional argument(s)")
            for arg in node.args:
                visit(arg, depth+1)
        else:
            raise ValueError("only numeric expressions and approved math functions are allowed")
    visit(tree)


def _syntax_loop_lines(lines, scope):
    """Validate loop bodies without evaluating ranges or initial-pose expressions."""
    from modeler import _ExpressionScope, _range_expressions
    output, stack = [], []
    variables = _ExpressionScope(scope or {})
    for n, words in lines:
        inside = any(kind == "for" for kind, _ in stack)
        if words[0] == "for":
            if not any(kind == "track" for kind, _ in stack):
                raise ValueError(f"Animation line {n}: for is only allowed inside a track")
            match = re.fullmatch(r"for\s+([A-Za-z_][A-Za-z_0-9]*)\s+in\s+range\((.*)\)", " ".join(words))
            if not match:
                raise ValueError(f"Animation line {n}: expected for <name> in range(...)")
            name = match[1]
            if name in variables:
                raise ValueError(f"Animation line {n}: loop variable already defined: {name}")
            args = _range_expressions(match[2])
            if not 1 <= len(args) <= 3:
                raise ValueError(f"Animation line {n}: range needs one to three arguments")
            for arg in args:
                _validate_expression(arg, variables)
            variables[name] = 1
            stack.append(("for", name))
            if sum(kind == "for" for kind, _ in stack) > 32:
                raise ValueError(f"Animation line {n}: loop nesting limit exceeded (32)")
        elif words == ["end"]:
            kind, name = stack.pop() if stack else (None, None)
            if kind == "for":
                del variables[name]
            else:
                output.append((n, words))
        else:
            if inside and words[0] != "key":
                raise ValueError(f"Animation line {n}: for body allows only key and nested for blocks")
            if words[0] in ("animation", "track"):
                stack.append((words[0], None))
            if inside:
                # Retain one symbolic iteration; actual expansion is done with real meshes.
                loop_names = {name for kind, name in stack if kind == "for"}
                words = [re.sub(r"\b[A-Za-z_][A-Za-z_0-9]*\b", lambda m: "1" if m[0] in loop_names else m[0], w) if i not in (0, 2) else w for i, w in enumerate(words)]
            output.append((n, words))
    if stack:
        raise ValueError("close all blocks with end")
    return output


def _parse_clip(source="", *, scope=None, syntax_only=False):
    if not isinstance(source, str) or len(source) > 100_000:
        raise ValueError("animationSource must be text (at most 100000 characters)")
    lines = [(n, _animation_words(line.split("#", 1)[0], n)) for n, line in enumerate(source.splitlines(), 1)]
    lines = [(n, words) for n, words in lines if words]
    if not lines:
        return None
    if any(words[0] == "for" for _, words in lines):
        lines = _syntax_loop_lines(lines, scope) if syntax_only else _expand_animation_loops(lines, scope)

    def fail(n, message):
        raise ValueError(f"Animation line {n}: {message}")

    def number(word, n, *, angle=False):
        if syntax_only:
            try:
                _validate_expression(word, scope)
            except (ValueError, OverflowError) as exc:
                fail(n, str(exc))
            return 1.
        if scope is not None:
            from modeler import _number_expression
            expression = word[2:-1] if word.startswith("${") and word.endswith("}") else word
            try:
                value = float(_number_expression(expression, scope))
            except (ValueError, OverflowError) as exc:
                fail(n, str(exc))
            if not math.isfinite(value):
                fail(n, "number must be finite")
            if not angle and abs(value) > 1e9:
                fail(n, "number must be finite and within ±1e9")
            return value
        if angle:
            try:
                return _angle_expression(word)
            except ValueError as exc:
                fail(n, str(exc))
        if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", word, flags=re.ASCII):
            fail(n, "expected a finite number")
        try:
            value = float(word)
        except ValueError:
            fail(n, "expected a finite number")
        if not math.isfinite(value):
            fail(n, "number must be finite")
        if not angle and abs(value) > 1e9:
            fail(n, "number must be finite and within ±1e9")
        return value

    n, words = lines[0]
    if len(words) == 3 and words[:2] == ["animation", "loop"]:
        words.insert(1, "main")
    if len(words) != 4 or words[0] != "animation" or words[2] != "loop" or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9-]*", words[1]):
        fail(n, "expected animation [name] loop <seconds>")
    duration = number(words[3], n)
    if not syntax_only and not 0 < duration <= 1000:
        fail(n, "duration must be greater than 0 and at most 1000 seconds")
    tracks, track, closed, key_count = [], None, False, 0
    for n, words in lines[1:]:
        if closed:
            fail(n, "only one animation block is allowed")
        if words == ["end"]:
            if track is None:
                closed = True
            else:
                if not track["channels"]:
                    fail(n, "track needs keys")
                for channel in track.get("cycles", {}):
                    if channel not in track["channels"]:
                        fail(n, f"{channel} cycle needs keys")
                for channel, keys in track["channels"].items():
                    if syntax_only:
                        continue
                    end = keys[-1][0]
                    if keys[0][0] != 0 or end <= 0:
                        fail(n, f"{channel} needs keys at 0 and a positive end time")
                    period = track.get("cycles", {}).get(channel)
                    if period is not None and end != period:
                        fail(n, f"{channel} needs keys at 0 and {period} seconds")
                    if period is None and end < duration:
                        track.setdefault("implicit_cycles", {})[channel] = end
                tracks.append(track)
                track = None
        elif len(words) == 2 and words[0] == "track" and track is None:
            if len(tracks) >= 256 or any(t["target"] == words[1] for t in tracks):
                fail(n, "duplicate target or more than 256 tracks")
            track = {"target": words[1], "channels": {}}
        elif len(words) == 3 and words[0] == "cycle" and track is not None and words[1] in DEFAULTS:
            channel = words[1]
            cycles = track.setdefault("cycles", {})
            if channel in cycles:
                fail(n, "duplicate channel cycle")
            period = number(words[2], n)
            if not syntax_only and not 0 < period <= duration:
                fail(n, "cycle period must be greater than 0 and at most the loop duration")
            cycles[channel] = period
        elif len(words) == 6 and words[0] == "key" and track is not None and words[2] in DEFAULTS:
            time = number(words[1], n)
            value = [number(word, n, angle=words[2] == "euler") for word in words[3:]]
            keys = track["channels"].setdefault(words[2], [])
            if not syntax_only and (not 0 <= time <= duration or (keys and time <= keys[-1][0])):
                fail(n, "channel key times must increase within the loop duration")
            if not syntax_only and words[2] == "scale" and min(value) <= 0:
                fail(n, "scale must be positive")
            keys.append([time, value])
            key_count += 1
            if key_count > 4096:
                fail(n, "at most 4096 keys are allowed")
        else:
            fail(n, "expected track <group>, cycle position|euler|scale <seconds>, key <seconds> position|euler|scale x y z, or end")
    if not closed or track is not None or not tracks:
        fail(lines[-1][0], "close all blocks with end; at least one track is required")
    animation = {"name": lines[0][1][1], "duration": duration, "tracks": tracks}
    # Bound generated data before starting expensive work.
    if not syntax_only and sum(len(sample_times(t, duration)) for t in tracks) > MAX_SAMPLES:
        raise ValueError("Animation exceeds 120000 generated samples")
    return animation


def parse_animation(source="", *, scope=None, syntax_only=False):
    """Parse up to 64 named clips; keep original line numbers in errors."""
    if not isinstance(source, str) or len(source) > 100_000:
        raise ValueError("animationSource must be text (at most 100000 characters)")
    clips, start, depth = [], 0, 0
    lines = source.splitlines()
    for index, line in enumerate(lines):
        words = line.split("#", 1)[0].split()
        if not words:
            continue
        if words[0] in ("animation", "track", "for"):
            depth += 1
        elif words == ["end"]:
            depth -= 1
        if depth <= 0:
            clip = _parse_clip("\n" * start + "\n".join(lines[start:index+1]), scope=scope, syntax_only=syntax_only)
            if clip:
                if len(clips) >= 64 or any(c["name"] == clip["name"] for c in clips):
                    raise ValueError("Animation: duplicate clip name or more than 64 clips")
                clips.append(clip)
            start = index+1
    if depth or any(line.split("#", 1)[0].strip() for line in lines[start:]):
        _parse_clip("\n" * start + "\n".join(lines[start:]), scope=scope, syntax_only=syntax_only)
    if not syntax_only and sum(len(sample_times(t, c["duration"])) for c in clips for t in c["tracks"]) > MAX_SAMPLES:
        raise ValueError("Animation exceeds 120000 generated samples")
    return {"clips": clips} if clips else None


def _base_pose(group):
    from transforms import _quaternion_euler
    pose = {key: list(group.get(key, value)) for key, value in DEFAULTS.items()}
    if "quaternion" in group:
        pose["quaternion"] = list(group["quaternion"])
        pose["euler"] = list(_quaternion_euler(group["quaternion"]))
    return pose


def resolve_animation_source(source, model_source="", mode="text", meshes=None, *, syntax_only=False):
    """Resolve root model expressions and each target's immutable initial TRS.

    syntax_only validates saved text before geometry exists. Its numeric result
    must never be used for playback/export; those callers supply evaluated meshes.
    """
    from modeler import _ExpressionScope, text_calculation_scope
    if mode not in ("text", "python"):
        raise ValueError("mode must be text or python")
    if not isinstance(source, str) or len(source) > 100_000:
        raise ValueError("animationSource must be text (at most 100000 characters)")
    scope = text_calculation_scope(model_source) if mode == "text" else _ExpressionScope()
    groups = {}
    for mesh in meshes or []:
        path = ()
        for entry in mesh.get("groupPath", []):
            path += (entry["name"],)
            groups[path] = entry
    base, expanded, track_depth = None, [], 0
    for n, line in enumerate(source.splitlines(), 1):
        line = line.split("#", 1)[0]
        words = line.split()
        if words == ["end"] and track_depth:
            track_depth -= 1
            if not track_depth:
                base = None
        if words and words[0] == "for" and track_depth:
            track_depth += 1
        if words and words[0] == "track" and len(words) == 2:
            track_depth = 1
            target = words[1]
            matches = [entry for path, entry in groups.items()
                       if ("/".join(path) == target.removeprefix("/") if "/" in target else path[-1] == target)]
            base = _base_pose(matches[0]) if len(matches) == 1 else None
        def reference(match):
            if not track_depth:
                raise ValueError(f"Animation line {n}: base is only available inside a track")
            if base is None and not syntax_only:
                raise ValueError(f"Animation line {n}: base requires an unambiguous evaluated target group")
            channel, axis = match.groups()
            return format((base or DEFAULTS)[channel]["xyz".index(axis)], ".17g")
        line = re.sub(r"\bbase\.(position|euler|scale)\.([xyz])\b", reference, line)
        expanded.append(line)
    animation = parse_animation("\n".join(expanded), scope=scope, syntax_only=syntax_only)
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
    if animation is None:
        return {}
    paths = set()
    for mesh in meshes:
        prefix = ()
        for entry in mesh.get("groupPath", []):
            prefix += (entry["name"],)
            paths.add(prefix)
    bound = {}
    for track in animation["tracks"]:
        target = track["target"]
        matches = [p for p in paths if ("/".join(p) == target.removeprefix("/") if "/" in target else p[-1] == target)]
        if len(matches) != 1:
            raise ValueError(f"Animation target {target}: group missing, invisible, consumed by Boolean, or ambiguous; use a full group path")
        path = matches[0]
        if path in bound:
            raise ValueError(f"Animation target {target}: duplicate group track")
        entries = next(mesh["groupPath"] for mesh in meshes if tuple(e["name"] for e in mesh.get("groupPath", [])[:len(path)]) == path)
        bound[path] = dict(track, base=_base_pose(entries[len(path)-1]))
    return bound


def prepare_animation(source, meshes):
    if isinstance(source, str) and re.search(r"\bbase\.", source):
        source = resolve_animation_source(source, mode="python", meshes=meshes)
    animation = parse_animation(source)
    clips = animation["clips"] if animation else []
    return animation, [bind_animation(clip, meshes) for clip in clips]


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
