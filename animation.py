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
    if not words or words[0] != "key":
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


def parse_animation(source=""):
    if not isinstance(source, str) or len(source) > 100_000:
        raise ValueError("animationSource must be text (at most 100000 characters)")
    lines = [(n, _animation_words(line.split("#", 1)[0], n)) for n, line in enumerate(source.splitlines(), 1)]
    lines = [(n, words) for n, words in lines if words]
    if not lines:
        return None

    def fail(n, message):
        raise ValueError(f"Animation line {n}: {message}")

    def number(word, n, *, angle=False):
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
                for channel, keys in track["channels"].items():
                    if keys[0][0] != 0 or keys[-1][0] != duration:
                        fail(n, f"{channel} needs keys at 0 and {duration} seconds")
                    first, last = keys[0][1], keys[-1][1]
                    if channel == "euler":
                        # Rotation equivalence, including coupled Euler representations.
                        a, b = (_group_quaternion({"euler": v}) for v in (first, last))
                        equal = abs(sum(x*y for x, y in zip(a, b))) >= 1 - 1e-9
                    else:
                        equal = all(abs(a-b) <= 1e-9 for a, b in zip(first, last))
                    if not equal:
                        fail(n, f"{channel} loop endpoints must have the same pose")
                tracks.append(track)
                track = None
        elif len(words) == 2 and words[0] == "track" and track is None:
            if len(tracks) >= 256 or any(t["target"] == words[1] for t in tracks):
                fail(n, "duplicate target or more than 256 tracks")
            track = {"target": words[1], "channels": {}}
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
            fail(n, "expected track <group>, key <seconds> position|euler|scale x y z, or end")
    if not closed or track is not None or not tracks:
        fail(lines[-1][0], "close all blocks with end; at least one track is required")
    animation = {"duration": duration, "tracks": tracks}
    # Bound generated data before starting expensive work.
    if sum(len(sample_times(t, duration)) for t in tracks) > MAX_SAMPLES:
        raise ValueError("Animation exceeds 120000 generated samples")
    return animation


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
        if time <= keys[0][0]:
            result[channel] = list(keys[0][1])
            continue
        result[channel] = list(keys[-1][1])
        for (a, av), (b, bv) in zip(keys, keys[1:]):
            if time <= b:
                alpha = (time-a)/(b-a)
                result[channel] = [x+(y-x)*alpha for x, y in zip(av, bv)]
                break
    return result


def sample_times(track, duration):
    # 60 Hz plus subdivision of large rotations keeps quaternion steps small.
    times = {0., duration}
    for keys in track["channels"].values():
        times.update(time for time, _ in keys)
    keys = track["channels"].get("euler", [])
    for (a, av), (b, bv) in zip(keys, keys[1:]):
        steps = max(1, math.ceil((b-a)*60), math.ceil(sum(abs(y-x) for x, y in zip(av, bv))/45))
        if steps > MAX_SAMPLES:
            raise ValueError("Animation exceeds 120000 generated samples")
        times.update(a+(b-a)*i/steps for i in range(1, steps))
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
