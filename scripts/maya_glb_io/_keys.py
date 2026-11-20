"""Drop animation keys a player would compute anyway (Maya-free).

The exporter samples every moving node on every frame. Most of those samples
lie on the straight line between their neighbours: a hold, a constant-speed
move, a joint that turns evenly. glTF LINEAR interpolation (lerp for vectors,
slerp for rotations) gives the same value there, so the key only costs bytes.

thin() keeps the first and last key and every key the interpolation between
the kept keys around it would miss by more than a tolerance. The tolerances
are far below what is visible: 0.01 mm, 0.01 degrees.
"""
from __future__ import annotations

import math


VECTOR_TOLERANCE = 1e-5      # metres, scale factors, morph weights
ANGLE_TOLERANCE = 1.75e-4    # radians, about 0.01 degrees


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def lerp(a, b, s):
    return tuple(x + (y - x) * s for x, y in zip(a, b))


def slerp(a, b, s):
    """Spherical interpolation of two unit quaternions, the short way round."""
    cosine = _dot(a, b)
    if cosine < 0.0:
        b = tuple(-c for c in b)
        cosine = -cosine
    if cosine > 0.9995:
        mixed = lerp(a, b, s)
        length = math.sqrt(_dot(mixed, mixed)) or 1.0
        return tuple(c / length for c in mixed)
    angle = math.acos(min(1.0, cosine))
    sine = math.sin(angle)
    wa = math.sin((1.0 - s) * angle) / sine
    wb = math.sin(s * angle) / sine
    return tuple(x * wa + y * wb for x, y in zip(a, b))


def angle_between(a, b):
    """The angle, in radians, of the rotation that takes quaternion a to b.

    Measured from the distance between the two (normalized) quaternions, not
    from acos of their dot product: near zero the dot is 1 minus the angle
    squared, and 32-bit components would turn 1e-7 of noise into 1e-3 radians.
    """
    length_a = math.sqrt(_dot(a, a)) or 1.0
    length_b = math.sqrt(_dot(b, b)) or 1.0
    sign = -1.0 if _dot(a, b) < 0.0 else 1.0
    squared = 0.0
    for x, y in zip(a, b):
        difference = x / length_a - sign * y / length_b
        squared += difference * difference
    return 4.0 * math.asin(min(1.0, math.sqrt(squared) / 2.0))


def _fits(times, rows, first, last, quaternions):
    """True when every key strictly between `first` and `last` is what the
    interpolation from `first` to `last` gives at its time."""
    t0 = times[first]
    span = times[last] - t0
    if span <= 0.0:
        return False
    a = rows[first]
    b = rows[last]
    for index in range(first + 1, last):
        s = (times[index] - t0) / span
        if quaternions:
            if angle_between(slerp(a, b, s), rows[index]) > ANGLE_TOLERANCE:
                return False
            continue
        guess = lerp(a, b, s)
        for x, y in zip(guess, rows[index]):
            if abs(x - y) > VECTOR_TOLERANCE:
                return False
    return True


def _reach(times, rows, anchor, last, quaternions):
    """The farthest key after `anchor` that can be the next kept key.

    Tried in doubling steps, then narrowed between the last step that fitted
    and the first that did not, so a long hold costs a few passes over it and
    not one pass per key. Every answer is a stretch that was checked whole.
    """
    good = anchor + 1
    step = 1
    bad = None
    while good < last:
        probe = min(good + step, last)
        if _fits(times, rows, anchor, probe, quaternions):
            good = probe
            step *= 2
        else:
            bad = probe
            break
    while bad is not None and bad - good > 1:
        middle = (good + bad) // 2
        if _fits(times, rows, anchor, middle, quaternions):
            good = middle
        else:
            bad = middle
    return good


def kept_indices(times, rows, quaternions=False):
    """Indices of the keys to keep, in order. `rows` is one tuple per key."""
    count = min(len(times), len(rows))
    if count <= 2:
        return list(range(count))
    kept = [0]
    anchor = 0
    while anchor < count - 1:
        anchor = _reach(times, rows, anchor, count - 1, quaternions)
        kept.append(anchor)
    return kept


def thin(times, rows, quaternions=False):
    """(times, rows) without the keys linear interpolation reproduces."""
    kept = kept_indices(times, rows, quaternions)
    return [times[i] for i in kept], [rows[i] for i in kept]
