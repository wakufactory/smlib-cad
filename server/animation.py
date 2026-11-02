"""Bounded TRS loop language and sampling shared by mesh export entry points.

Transforms are relative to a group's static local frame (static TRS * animated
TRS). Euler values are unwrapped degrees, interpolated component by component.
No native geometry is evaluated here.
"""

import math
import re

from transforms import _group_quaternion

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


def parse_animation(source="", *, scope=None):
    if not isinstance(source, str) or len(source) > 100_000:
        raise ValueError("animationSource must be text (at most 100000 characters)")
    lines = [(n, _animation_words(line.split("#", 1)[0], n)) for n, line in enumerate(source.splitlines(), 1)]
    lines = [(n, words) for n, words in lines if words]
    if not lines:
        return None
    if any(words[0] == "for" for _, words in lines):
        lines = _expand_animation_loops(lines, scope)

    def fail(n, message):
        raise ValueError(f"Animation line {n}: {message}")

    def number(word, n, *, angle=False):
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
    if len(words) != 3 or words[:2] != ["animation", "loop"]:
        fail(n, "expected animation loop <seconds>")
    duration = number(words[2], n)
    if not 0 < duration <= 1000:
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
                    period = track.get("cycles", {}).get(channel, duration)
                    if keys[0][0] != 0 or keys[-1][0] != period:
                        fail(n, f"{channel} needs keys at 0 and {period} seconds")
                    first, last = keys[0][1], keys[-1][1]
                    if channel == "euler":
                        # Rotation equivalence, including coupled Euler representations.
                        a, b = (_group_quaternion({"euler": v}) for v in (first, last))
                        equal = abs(sum(x*y for x, y in zip(a, b))) >= 1 - 1e-9
                    else:
                        equal = all(abs(a-b) <= 1e-9 for a, b in zip(first, last))
                    if channel == "euler" and channel in track.get("cycles", {}):
                        whole_turns = all(abs((b-a)/360 - round((b-a)/360)) <= 1e-9
                                          for a, b in zip(first, last))
                        if not whole_turns:
                            fail(n, "euler cycle endpoints must differ by whole turns on each axis")
                    if not equal:
                        fail(n, f"{channel} loop endpoints must have the same pose")
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
            if not 0 < period <= duration:
                fail(n, "cycle period must be greater than 0 and at most the loop duration")
            count = duration / period
            if not math.isfinite(count) or count > MAX_SAMPLES or abs(count-round(count)) > 1e-9:
                fail(n, "loop duration must be a whole number of cycles (at most 120000)")
            cycles[channel] = period
        elif len(words) == 6 and words[0] == "key" and track is not None and words[2] in DEFAULTS:
            time = number(words[1], n)
            value = [number(word, n, angle=words[2] == "euler") for word in words[3:]]
            keys = track["channels"].setdefault(words[2], [])
            if not 0 <= time <= duration or (keys and time <= keys[-1][0]):
                fail(n, "channel key times must increase within the loop duration")
            if words[2] == "scale" and min(value) <= 0:
                fail(n, "scale must be positive")
            keys.append([time, value])
            key_count += 1
            if key_count > 4096:
                fail(n, "at most 4096 keys are allowed")
        else:
            fail(n, "expected track <group>, cycle position|euler|scale <seconds>, key <seconds> position|euler|scale x y z, or end")
    if not closed or track is not None or not tracks:
        fail(lines[-1][0], "close all blocks with end; at least one track is required")
    animation = {"duration": duration, "tracks": tracks}
    # Bound generated data before starting expensive work.
    if sum(len(sample_times(t, duration)) for t in tracks) > MAX_SAMPLES:
        raise ValueError("Animation exceeds 120000 generated samples")
    return animation


def resolve_animation_source(source, model_source="", mode="text"):
    """Compile expressions to portable numeric keys; never evaluate Python models."""
    from modeler import _ExpressionScope, text_calculation_scope
    if mode not in ("text", "python"):
        raise ValueError("mode must be text or python")
    if not isinstance(source, str) or len(source) > 100_000:
        raise ValueError("animationSource must be text (at most 100000 characters)")
    if not source.strip():
        return ""
    scope = text_calculation_scope(model_source) if mode == "text" else _ExpressionScope()
    animation = parse_animation(source, scope=scope)
    if animation is None:
        return ""
    lines = [f'animation loop {animation["duration"]:.17g}']
    for track in animation["tracks"]:
        lines.append(f'track {track["target"]}')
        for channel, period in track.get("cycles", {}).items():
            lines.append(f'cycle {channel} {period:.17g}')
        for channel, keys in track["channels"].items():
            for time, values in keys:
                lines.append(f'key {time:.17g} {channel} ' + ' '.join(f'{v:.17g}' for v in values))
        lines.append('end')
    lines.append('end')
    return '\n'.join(lines)


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
        bound[path] = track
    return bound


def prepare_animation(source, meshes):
    animation = parse_animation(source)
    return animation, bind_animation(animation, meshes)


def sample_track(track, time):
    result = {key: list(value) for key, value in DEFAULTS.items()}
    for channel, keys in track["channels"].items():
        period = track.get("cycles", {}).get(channel)
        turns = math.floor(time / period) if period else 0
        # Derive phase from the same quotient: modulo can disagree at decimal seams.
        local = max(0., min(period, time - turns * period)) if period else time
        value = list(keys[-1][1])
        if local <= keys[0][0]:
            value = list(keys[0][1])
        else:
            for (a, av), (b, bv) in zip(keys, keys[1:]):
                if local <= b:
                    alpha = (local-a)/(b-a)
                    value = [x+(y-x)*alpha for x, y in zip(av, bv)]
                    break
        if channel == "euler" and period:
            value = [v + turns * (b-a) for v, a, b in zip(value, keys[0][1], keys[-1][1])]
        result[channel] = value
    return result


def sample_times(track, duration):
    # Expand cycles only for portable export; playback uses modular time.
    times = {0., duration}
    for channel, keys in track["channels"].items():
        period = track.get("cycles", {}).get(channel, duration)
        count = round(duration / period)
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
        if count * sum(steps) + 1 > MAX_SAMPLES:
            raise ValueError("Animation exceeds 120000 generated samples")
        for cycle in range(count):
            offset = cycle * period
            for ((a,_),(b,_)), subdivisions in zip(zip(keys,keys[1:]), steps):
                times.update(min(duration, offset + a + (b-a)*i/subdivisions) for i in range(subdivisions))
            if len(times) > MAX_SAMPLES:
                raise ValueError("Animation exceeds 120000 generated samples")
    return sorted(times)


def animation_meshes(meshes, bound):
    """Insert animation frames with scene-wide unique names for Apple importers.

    Reuse the same frame name for every solid under the same animated group.
    Different paths must not produce same-named animation nodes, even when
    their leaf group names are identical or path components contain '__'.
    """
    reserved = {mesh["name"] for mesh in meshes}
    reserved.update(entry["name"] for mesh in meshes for entry in mesh.get("groupPath", []))
    reserved.update(("Model", "Geometry", "ModelContent", "Materials"))
    frame_names = {}
    for prefix in sorted(bound):
        name = "Animation_" + "__".join(prefix)
        while name in reserved:
            name += "_"
        reserved.add(name)
        frame_names[prefix] = name
    output = []
    for mesh in meshes:
        prefix, path = (), []
        original = mesh.get("groupPath", [])
        for entry in original:
            prefix += (entry["name"],)
            path.append(entry)
            if prefix in bound:
                path.append(dict(name=frame_names[prefix], **DEFAULTS, animation=bound[prefix]))
        output.append(dict(mesh, groupPath=path))
    return output
