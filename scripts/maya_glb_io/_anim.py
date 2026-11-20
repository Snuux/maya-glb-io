"""Apply decoded glTF animations to Maya nodes as animCurves.

This module turns the parser's Maya-free Animation/AnimChannel objects (see
_gltf.read_animations()) into keyframes on the transforms that _build created.
Imported separately from the parser so _gltf.py stays Maya-free for the smoke
tests; this module DOES import maya and is only ever called from inside Maya.

Conventions mirrored from _build.py:
  * translation samples are run through the same `coord_convert` the mesh used,
    so animated translations land at the unit scale of the geometry.
  * rotation samples are glTF quaternions (x, y, z, w) converted to euler
    degrees via om.MQuaternion(...).asEulerRotation(), exactly like _apply_trs.
  * scale samples are keyed verbatim (scale is unitless).

Rotation:
  Each key's quaternion becomes the euler solution closest to the key before
  it (MEulerRotation.setToClosestSolution), so curves stay continuous instead
  of jumping between equivalent angles. Maya interpolates the three euler
  curves, glTF the quaternion: between two keys far apart the paths differ,
  on per-frame samples (what exporters write) they do not.

CUBICSPLINE:
  * translation, scale and morph weights keep the file's tangents: every key
    gets fixed in and out tangents with the glTF slopes (units per second,
    turned into Maya's per-frame angles), which gives the same Hermite curve.
  * rotation tangents are quaternion derivatives, which an euler curve cannot
    hold. The spline is evaluated at every whole frame between its keys and
    keyed there with linear tangents.

Several animations:
  Maya has one timeline, so every animation is keyed on it. When the file's
  animations do not overlap in time (a file exported from one Maya timeline,
  clips sharing at most their end frames) they keep their own frames. When they
  overlap (most files: every animation starts at 0) they are laid out one after
  another, in file order, ANIMATION_GAP frames apart. Each animation gets a time
  slider bookmark with its name and range (option "animationBookmarks", default
  on), and the scene's animation range grows to hold them all.

Morph-target `weights` channels:
  A glTF `weights` channel animates ALL of a mesh's morph weights at once. Its
  output is a flat SCALAR array laid out keyframe-major: for keyframe k and
  target t (of N targets), weight = output[k*N + t]. We resolve the target
  node's blendShape (via the node_to_blendshape map built by _build, falling
  back to walking the mesh shape's history) and key each blendShape weight[t].
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional

import maya.api.OpenMaya as om
from maya import cmds


# glTF samples are in seconds; Maya keys are in frames. Map the scene's time
# unit name to its frames-per-second. Fallback is 24 (film) for anything we
# don't recognise.
_TIME_UNIT_FPS = {
    "game": 15.0,
    "film": 24.0,
    "pal": 25.0,
    "ntsc": 30.0,
    "show": 48.0,
    "palf": 50.0,
    "ntscf": 60.0,
    "2fps": 2.0,
    "3fps": 3.0,
    "4fps": 4.0,
    "5fps": 5.0,
    "6fps": 6.0,
    "8fps": 8.0,
    "10fps": 10.0,
    "12fps": 12.0,
    "16fps": 16.0,
    "20fps": 20.0,
    "40fps": 40.0,
    "75fps": 75.0,
    "80fps": 80.0,
    "100fps": 100.0,
    "120fps": 120.0,
}


def scene_fps():
    # type: () -> float
    """Frames-per-second of the current scene's time unit.

    Prefers the OpenMaya conversion (robust against exotic "<n>fps" unit names
    Maya supports), falling back to the name table, then to 24.
    """
    try:
        # MTime(1 second) expressed in the UI time unit == frames per second.
        fps = om.MTime(1.0, om.MTime.kSeconds).asUnits(om.MTime.uiUnit())
        if fps and fps > 0:
            return float(fps)
    except Exception:
        pass
    try:
        unit = cmds.currentUnit(query=True, time=True) or "film"
    except Exception:
        unit = "film"
    return _TIME_UNIT_FPS.get(unit, 24.0)


ANIMATION_GAP = 10  # frames between animations laid out one after another


def animation_span(anim, fps):
    """(first, last) frame of an animation's keys, or None when it has none."""
    times = [t for channel in anim.channels for t in channel.times]
    if not times:
        return None
    return (_frame(min(times), fps), _frame(max(times), fps))


def layout_offsets(spans, gap=ANIMATION_GAP):
    """Frame offset per animation so that no two share frames.

    spans: (first, last) frames or None, in file order. When no span starts
    before another one ends (touching ends are fine) every offset is 0.
    Otherwise the first animation stays where it is and each next one starts on
    a whole frame `gap` frames after the previous one ends.
    """
    real = sorted(span for span in spans if span)
    overlap = False
    reach = None
    for first, last in real:
        if reach is not None and first < reach - 1e-6:
            overlap = True
            break
        reach = last if reach is None else max(reach, last)
    if not overlap:
        return [0.0] * len(spans)
    offsets = []
    cursor = None
    for span in spans:
        if span is None:
            offsets.append(0.0)
            continue
        offset = 0.0 if cursor is None else math.ceil(cursor + gap) - span[0]
        offsets.append(offset)
        cursor = span[1] + offset
    return offsets


_WHOLE_FRAME = 1e-3


def _frame(seconds, fps, offset=0.0):
    """The frame of a key. glTF stores times as 32-bit floats, so 20/24 s reads
    back as frame 19.9999995: a frame that close to a whole one is that one."""
    frame = seconds * fps + offset
    whole = round(frame)
    return float(whole) if abs(frame - whole) < _WHOLE_FRAME else frame


def _bookmark(name, first, last):
    """A time slider bookmark over first..last frames named `name`, or None."""
    try:
        if not cmds.pluginInfo("timeSliderBookmark", query=True, loaded=True):
            cmds.loadPlugin("timeSliderBookmark", quiet=True)
        node_name = "bookmark_" + (re.sub(r"[^A-Za-z0-9_]", "_", name) or "anim")
        node = cmds.createNode("timeSliderBookmark", name=node_name)
        cmds.setAttr(node + ".name", name, type="string")
        cmds.setAttr(node + ".timeRangeStart", first)
        cmds.setAttr(node + ".timeRangeStop", last)
        return node
    except Exception as exc:
        om.MGlobal.displayWarning(
            "[glb_io] could not make a bookmark for animation '%s': %s" % (name, exc)
        )
        return None


def _grow_animation_range(first, last):
    try:
        start = cmds.playbackOptions(query=True, animationStartTime=True)
        end = cmds.playbackOptions(query=True, animationEndTime=True)
        cmds.playbackOptions(animationStartTime=min(start, first),
                             animationEndTime=max(end, last))
    except Exception:
        pass


def apply_animations(gltf, node_to_maya, coord_convert, unit_scale, options=None,
                     node_to_blendshape=None):
    # type: (object, Dict[int, str], object, float, Optional[dict], Optional[Dict[int, list]]) -> int
    """Key every glTF animation channel onto its target Maya node.

    Args:
      gltf          : parsed Gltf — provides read_animations().
      node_to_maya  : dict glTF node index -> Maya node full path (built by
                      _build.build_scene). Targets missing from this map are
                      warned + skipped (e.g. collapsed pass-through nodes).
      coord_convert : callable(triplet) -> triplet, the SAME one the mesh used,
                      so animated translation matches geometry units.
      unit_scale    : numeric scale factor (kept for signature symmetry /
                      potential future use; translation already goes through
                      coord_convert which folds the scale in).
      options       : import options dict (currently unused but threaded in).
      node_to_blendshape : dict glTF mesh-node index -> [blendShape node names]
                      built by _build for morphed meshes. Used to resolve a
                      `weights` channel to its blendShape(s). May be None/empty
                      (then we fall back to the mesh shape's history); morph
                      meshes are the only case where this is populated.

    Returns the number of channels successfully keyed. A no-op (returns 0) when
    the document has no animations — safe for the Anno building pipeline.
    """
    try:
        animations = gltf.read_animations()
    except Exception as exc:
        om.MGlobal.displayWarning("[glb_io] failed to read animations: %s" % exc)
        return 0

    if not animations:
        return 0

    fps = scene_fps()
    keyed_channels = 0
    node_to_blendshape = node_to_blendshape or {}
    options = options or {}
    spans = [animation_span(anim, fps) for anim in animations]
    offsets = layout_offsets(spans)
    if any(offsets):
        om.MGlobal.displayInfo(
            "[glb_io] the file's animations overlap in time; laid out one after "
            "another, %d frames apart" % ANIMATION_GAP
        )

    for anim, span, offset in zip(animations, spans, offsets):
        if span is not None:
            first = round(span[0] + offset, 3)
            last = round(span[1] + offset, 3)
            if options.get("animationBookmarks", True):
                _bookmark(anim.name, first, last)
            _grow_animation_range(first, last)
        for channel in anim.channels:
            try:
                if _apply_channel(channel, node_to_maya, coord_convert, fps,
                                  node_to_blendshape, offset):
                    keyed_channels += 1
            except Exception as exc:
                # One bad channel must never abort the whole import.
                om.MGlobal.displayWarning(
                    "[glb_io] animation channel (node %s, %s) failed: %s"
                    % (channel.target_node, channel.path, exc)
                )

    if keyed_channels:
        om.MGlobal.displayInfo(
            "[glb_io] applied %d animation channel(s) at %g fps"
            % (keyed_channels, fps)
        )
    return keyed_channels


# Maya attribute names per glTF path + axis.
_AXIS_ATTRS = {
    "translation": ("translateX", "translateY", "translateZ"),
    "scale": ("scaleX", "scaleY", "scaleZ"),
    "rotation": ("rotateX", "rotateY", "rotateZ"),
}


def _apply_channel(channel, node_to_maya, coord_convert, fps,
                   node_to_blendshape=None, offset=0.0):
    """Key a single channel. Returns True if at least one key was set."""
    node = node_to_maya.get(channel.target_node)
    if not node:
        om.MGlobal.displayWarning(
            "[glb_io] animation targets node %d which has no live Maya node "
            "(collapsed/removed?); skipping channel '%s'"
            % (channel.target_node, channel.path)
        )
        return False
    if not cmds.objExists(node):
        om.MGlobal.displayWarning(
            "[glb_io] animation target '%s' no longer exists; skipping" % node
        )
        return False

    path = channel.path

    if path == "weights":
        return _apply_weights_channel(
            channel, node, fps, node_to_blendshape or {}, offset
        )

    times = channel.times
    values = channel.values
    interp = (channel.interpolation or "LINEAR").upper()
    cubic = interp == "CUBICSPLINE"

    # CUBICSPLINE stores 3 outputs per key (in-tangent, value, out-tangent).
    # For v1 we lift just the value (middle) element of each triple. LINEAR /
    # STEP store one output per key.
    n_keys = len(times)

    attrs = _AXIS_ATTRS.get(path)
    if attrs is None:
        return False

    if cubic:
        n_keys = min(n_keys, len(values) // 3)
        if path == "rotation":
            # Quaternion tangents have no euler counterpart: sample the spline.
            times, values = _sample_cubic_rotation(times, values, n_keys, fps)
            n_keys = len(times)
            cubic = False
            interp = "LINEAR"

    set_any = False
    prev_euler = None  # rotation continuity (euler unrolling) — see below
    frames = []
    slopes_in = ([], [], [])   # per axis, value units per second (CUBICSPLINE)
    slopes_out = ([], [], [])
    for ki in range(n_keys):
        frame = _frame(times[ki], fps, offset)

        if cubic:
            value = values[ki * 3 + 1]
            tan_in = values[ki * 3]
            tan_out = values[ki * 3 + 2]
            if path == "translation":
                tan_in = _convert_delta(coord_convert, tan_in)
                tan_out = _convert_delta(coord_convert, tan_out)
            frames.append(frame)
            for axis in range(3):
                slopes_in[axis].append(tan_in[axis])
                slopes_out[axis].append(tan_out[axis])
        else:
            if ki >= len(values):
                break
            value = values[ki]

        if path == "translation":
            x, y, z = coord_convert((value[0], value[1], value[2]))
            axis_vals = (x, y, z)
        elif path == "scale":
            axis_vals = (value[0], value[1], value[2])
        else:  # rotation: quaternion (x, y, z, w) -> euler degrees
            q = om.MQuaternion(value[0], value[1], value[2], value[3])
            e = q.asEulerRotation()
            # Euler unrolling: a quaternion maps to many equivalent euler triples
            # (and ±360 wraps). Converting each key independently lets adjacent
            # frames land on different branches -> the joint flips / spins the
            # long way (the "junky limbs" on fast rigs like BrainStem). Snapping
            # each euler to the solution closest to the previous frame keeps the
            # animation curves continuous.
            if prev_euler is not None:
                try:
                    e.setToClosestSolution(prev_euler)
                except Exception:
                    pass
            prev_euler = om.MEulerRotation(e.x, e.y, e.z, e.order)
            axis_vals = (
                _deg(e.x),
                _deg(e.y),
                _deg(e.z),
            )

        for attr, val in zip(attrs, axis_vals):
            cmds.setKeyframe(node, attribute=attr, time=frame, value=float(val))
            set_any = True

    if not set_any:
        return False

    # Tangent handling per interpolation.
    if interp == "STEP":
        itt, ott = "linear", "step"
    elif cubic:
        for axis, attr in enumerate(attrs):
            _set_cubic_tangents(
                node, attr, frames, slopes_in[axis], slopes_out[axis], fps
            )
        return True
    else:  # LINEAR (and unknown -> default linear)
        itt, ott = "linear", "linear"

    # Only this channel's keys: another animation of the file may have keyed
    # the same attribute with another interpolation.
    span = frames_of(times, fps, offset)
    for attr in attrs:
        try:
            cmds.keyTangent(node, edit=True, attribute=attr, time=span,
                            itt=itt, ott=ott)
        except Exception:
            # Tangent setting is cosmetic; never let it fail the channel.
            pass

    return True


def frames_of(times, fps, offset=0.0):
    """(first, last) frame of a channel's keys, as a keyTangent time range."""
    return (_frame(times[0], fps, offset), _frame(times[-1], fps, offset))


def _convert_delta(coord_convert, vector):
    """A direction (a tangent) through coord_convert. The convert is linear
    (unit scale, axis swap), so the difference of two converted points is the
    converted direction, whatever offset a convert might add."""
    zero = coord_convert((0.0, 0.0, 0.0))
    moved = coord_convert((vector[0], vector[1], vector[2]))
    return (moved[0] - zero[0], moved[1] - zero[1], moved[2] - zero[2])


def _set_cubic_tangents(node, attr, frames, slopes_in, slopes_out, fps):
    """Give each key of a CUBICSPLINE channel the file's tangents.

    glTF's cubic Hermite spline and a Maya curve with non-weighted fixed
    tangents are the same curve when the slopes match. glTF slopes are value
    units per second; Maya's tangent angle is atan(value units per frame).
    """
    try:
        cmds.keyTangent(node, attribute=attr, edit=True, weightedTangents=False)
    except Exception:
        pass
    for frame, slope_in, slope_out in zip(frames, slopes_in, slopes_out):
        try:
            cmds.keyTangent(node, attribute=attr, edit=True, time=(frame,),
                            lock=False, itt="fixed", ott="fixed")
            cmds.keyTangent(
                node, attribute=attr, edit=True, time=(frame,),
                inAngle=math.degrees(math.atan(slope_in / fps)),
                outAngle=math.degrees(math.atan(slope_out / fps)),
            )
        except Exception:
            # Tangent setting is cosmetic; never let it fail the channel.
            pass


def _sample_cubic_rotation(times, values, n_keys, fps):
    """A CUBICSPLINE rotation channel as plain keys: the file's keys plus the
    spline's value at every whole frame between them, each a unit quaternion.

    Follows the glTF spec: with d = t1 - t0 and s = (t - t0) / d,
      q = (2s^3 - 3s^2 + 1) v0 + (s^3 - 2s^2 + s) d b0
        + (-2s^3 + 3s^2) v1 + (s^3 - s^2) d a1
    where b0 is key 0's out-tangent and a1 key 1's in-tangent, then normalized.
    """
    out_times = []
    out_values = []
    for ki in range(n_keys):
        v0 = values[ki * 3 + 1]
        out_times.append(times[ki])
        out_values.append(_unit(v0))
        if ki + 1 >= n_keys:
            break
        t0 = times[ki]
        t1 = times[ki + 1]
        d = t1 - t0
        if d <= 0.0:
            continue
        b0 = values[ki * 3 + 2]
        v1 = values[(ki + 1) * 3 + 1]
        a1 = values[(ki + 1) * 3]
        frame = math.floor(t0 * fps + _WHOLE_FRAME) + 1
        while frame < t1 * fps - _WHOLE_FRAME:
            t = frame / fps
            s = (t - t0) / d
            s2 = s * s
            s3 = s2 * s
            h00 = 2 * s3 - 3 * s2 + 1
            h10 = (s3 - 2 * s2 + s) * d
            h01 = -2 * s3 + 3 * s2
            h11 = (s3 - s2) * d
            out_times.append(t)
            out_values.append(_unit([
                h00 * v0[c] + h10 * b0[c] + h01 * v1[c] + h11 * a1[c]
                for c in range(4)
            ]))
            frame += 1
    return out_times, out_values


def _unit(quaternion):
    length = math.sqrt(sum(c * c for c in quaternion))
    if length < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    return tuple(c / length for c in quaternion)


def _apply_weights_channel(channel, node, fps, node_to_blendshape, offset=0.0):
    """Key a glTF morph-target `weights` channel onto its blendShape weights.

    A `weights` channel animates ALL of the mesh's morph weights together. Its
    output is a flat SCALAR array laid out keyframe-major: for keyframe k and
    target t (of N targets), weight = output[k*N + t]. (CUBICSPLINE stores 3
    values per target per key — in/value/out — so the stride is 3*N and we take
    the middle value, consistent with the transform paths.)

    Returns True if at least one key was set.
    """
    blendshapes = _resolve_blendshapes(channel.target_node, node, node_to_blendshape)
    if not blendshapes:
        om.MGlobal.displayWarning(
            "[glb_io] weights animation targets node %d but no blendShape was "
            "found for it; skipping channel" % channel.target_node
        )
        return False

    times = channel.times
    values = channel.values
    n_keys = len(times)
    if n_keys == 0 or not values:
        return False

    interp = (channel.interpolation or "LINEAR").upper()
    cubic = interp == "CUBICSPLINE"
    stride_factor = 3 if cubic else 1

    set_any = False
    for bs in blendshapes:
        if not cmds.objExists(bs):
            continue
        # N = number of blendShape weight targets. weightCount is the multi
        # plug length; query the existing indices to be robust.
        try:
            n_targets = cmds.blendShape(bs, query=True, weightCount=True)
        except Exception:
            n_targets = 0
        if not n_targets:
            # Fall back to the output layout: total / keys / stride.
            if cubic:
                n_targets = len(values) // (n_keys * 3) if n_keys else 0
            else:
                n_targets = len(values) // n_keys if n_keys else 0
        if not n_targets:
            continue

        expected = n_keys * n_targets * stride_factor
        if len(values) < expected:
            om.MGlobal.displayWarning(
                "[glb_io] weights channel for '%s' has %d output values but "
                "%d keys x %d targets (x%d) expects %d; skipping"
                % (bs, len(values), n_keys, n_targets, stride_factor, expected)
            )
            continue

        # CUBICSPLINE output is keyframe-major, then in / value / out blocks
        # of N weights each: [in x N, value x N, out x N] per key.
        frames = []
        slopes_in = [[] for _ in range(n_targets)]
        slopes_out = [[] for _ in range(n_targets)]
        for ki in range(n_keys):
            frame = _frame(times[ki], fps, offset)
            frames.append(frame)
            for t in range(n_targets):
                if cubic:
                    base = ki * n_targets * 3
                    w = values[base + n_targets + t]
                    slopes_in[t].append(values[base + t])
                    slopes_out[t].append(values[base + 2 * n_targets + t])
                else:
                    w = values[ki * n_targets + t]
                try:
                    cmds.setKeyframe(
                        bs, attribute="weight[%d]" % t,
                        time=frame, value=float(w),
                    )
                    set_any = True
                except Exception:
                    pass

        # Tangent style mirrors the transform channels.
        if interp == "STEP":
            itt, ott = "linear", "step"
        elif cubic:
            for t in range(n_targets):
                _set_cubic_tangents(
                    bs, "weight[%d]" % t, frames, slopes_in[t], slopes_out[t], fps
                )
            continue
        else:
            itt, ott = "linear", "linear"
        for t in range(n_targets):
            try:
                cmds.keyTangent(
                    bs, edit=True, attribute="weight[%d]" % t,
                    time=(frames[0], frames[-1]), itt=itt, ott=ott
                )
            except Exception:
                pass

    return set_any


def _resolve_blendshapes(node_index, node_path, node_to_blendshape):
    """Resolve the blendShape node(s) for a glTF mesh node.

    Preference order:
      1. The node_to_blendshape map built by _build (authoritative — survives
         flatten since blendShape is a DG node, not path-based).
      2. Fall back to walking the mesh shape(s) under node_path and collecting
         any blendShape in their history (handles callers that don't thread the
         map, and shapes whose owning transform got remapped).

    Returns a de-duplicated list of blendShape node names (may be empty).
    """
    found = []

    mapped = node_to_blendshape.get(node_index) if node_to_blendshape else None
    if mapped:
        for bs in mapped:
            if bs and bs not in found and cmds.objExists(bs):
                found.append(bs)
    if found:
        return found

    # History fallback: the node's mesh shapes -> blendShapes upstream.
    try:
        shapes = cmds.listRelatives(
            node_path, shapes=True, fullPath=True, type="mesh",
            noIntermediate=True,
        ) or []
        # Also consider intermediate shapes (a blendShape's input is often an
        # intermediate orig shape), so don't filter them out for history.
        all_shapes = cmds.listRelatives(
            node_path, shapes=True, fullPath=True, type="mesh"
        ) or []
        for s in (shapes + all_shapes):
            hist = cmds.listHistory(s) or []
            for bs in cmds.ls(hist, type="blendShape") or []:
                if bs not in found:
                    found.append(bs)
    except Exception:
        pass

    return found


def _deg(radians):
    import math
    return math.degrees(radians)
