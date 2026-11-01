"""Static group transform math shared by animation and mesh export."""

import math


def _group_quaternion(group):
    """Native order: scale, rotate X, rotate Y, rotate Z, translate."""
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


