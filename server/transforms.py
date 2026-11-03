"""Static group transform math shared by animation and mesh export."""

import math


def _group_quaternion(group):
    """Native order: scale, rotate X, rotate Y, rotate Z, translate."""
    if "quaternion" in group:
        return tuple(group["quaternion"])
    x, y, z = [math.radians(v) / 2 for v in group["euler"]]
    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
    return (sx*cy*cz - cx*sy*sz, cx*sy*cz + sx*cy*sz,
            cx*cy*sz - sx*sy*cz, cx*cy*cz + sx*sy*sz)


def _group_rotation(group):
    x, y, z, w = _group_quaternion(group)
    return ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
            (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
            (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))


def _normalize_quaternion(values):
    """Normalize XYZW without overflowing or underflowing the input norm."""
    if not all(math.isfinite(v) for v in values):
        raise ValueError("quaternion: values must be finite")
    largest = max(abs(v) for v in values)
    if largest == 0:
        raise ValueError("quaternion: rotation must be nonzero")
    scaled = tuple(v / largest for v in values)
    length = math.hypot(*scaled)
    return tuple(v / length for v in scaled)


def _quaternion_euler(values):
    """Equivalent XYZ degrees for the BRep kernel's Euler-only transform API."""
    r = _group_rotation({"quaternion": values})
    y = math.atan2(-r[2][0], math.hypot(r[0][0], r[1][0]))
    if math.hypot(r[0][0], r[1][0]) > 1e-12:
        x, z = math.atan2(r[2][1], r[2][2]), math.atan2(r[1][0], r[0][0])
    else:
        x, z = math.atan2(-r[1][2], r[1][1]), 0.0
    return tuple(math.degrees(v) for v in (x, y, z))


def _degree_quaternion(x, y, z, degrees):
    """Convert a nonzero axis and an angle in degrees to unit XYZW."""
    if not all(math.isfinite(v) for v in (x, y, z, degrees)):
        raise ValueError("dquaternion: axis and angle must be finite")
    largest = max(abs(x), abs(y), abs(z))
    if largest == 0:
        raise ValueError("dquaternion: axis must be nonzero")
    axis = tuple(v / largest for v in (x, y, z))
    length = math.hypot(*axis)
    half = math.radians(degrees / 2)
    sine = math.sin(half)
    return _normalize_quaternion((*[v / length * sine for v in axis], math.cos(half)))
