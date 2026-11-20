"""KHR_draco_mesh_compression decode wrapper (Maya-free, optional dependency).

Draco is Google's mesh-compression codec. glTFs exported by Sketchfab,
Blender (with "Compression" on), the glTF-Pipeline, etc. ship their vertex
data as a Draco bitstream referenced by `KHR_draco_mesh_compression` instead of
plain accessors, so without a Draco decoder those meshes import EMPTY.

We decode via the `DracoPy` pip package, a self-contained C++/Cython wheel
(NOT a Maya module), so this whole layer runs in the same Maya-free space as
_gltf.py once DracoPy is there. Nothing here raises on a missing decoder:
callers check the bool and warn+skip.

The decoder is installed into the plug-in's own folder, `draco/py<XY>` next
to `scripts` (one folder per Python version, since the wheel is built per
version), not into Maya's site-packages: no admin rights, nothing left behind
when the plug-in is removed, and several Maya versions can share one copy of
the plug-in. A DracoPy already importable from elsewhere is used as it is.

API:
  dracopy_available() -> bool   : is DracoPy importable right now?
  ensure_dracopy()    -> bool   : importable, or installed-then-importable
                                  (never installs with MAYA_GLB_IO_OFFLINE=1)
  install(python=None) -> (bool, str) : run pip now, whatever the environment
                                  says; what `Install Draco Decoder` and
                                  scripted installs call
  vendor_dir()        -> str    : where the decoder goes for this Python
  decode(buffer_bytes, attributes=None) -> dict : POSITION, NORMAL,
                                  TEXCOORD_0, indices, plus every semantic of
                                  the extension's `attributes` table
                                  (JOINTS_0, WEIGHTS_0, COLOR_0, ...). Raises
                                  DracoError if DracoPy is unavailable or the
                                  buffer is bad.

This module deliberately has NO top-level `import DracoPy` and NO `import maya`
: both are imported lazily inside the functions so _gltf can import _draco
(and the smoke tests can import both) without either dependency present.
"""
from __future__ import annotations

import importlib
import os
import sys


class DracoError(Exception):
    """Raised when a Draco primitive can't be decoded (no DracoPy / bad data).

    Always catchable by the caller, which warns + skips the primitive rather
    than aborting the whole import.
    """
    pass


def _warn(msg):
    """Print a warning via Maya's console if available, else stdout.

    Keeps the module Maya-free: we only touch maya.api if it's already
    importable (i.e. we're running inside Maya), otherwise fall back to print
    so the smoke tests stay silent-friendly.
    """
    try:
        import maya.api.OpenMaya as om  # noqa: F401
        om.MGlobal.displayWarning("[glb_io] " + msg)
    except Exception:
        print("[glb_io] " + msg)


PACKAGE = "DracoPy"
PIP_SECONDS = 300


def vendor_dir():
    # type: () -> str
    """The folder this Python's decoder is installed into: `draco/py<XY>` in
    the plug-in folder (the parent of `scripts`)."""
    scripts = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tag = "py%d%d" % (sys.version_info[0], sys.version_info[1])
    return os.path.join(os.path.dirname(scripts), "draco", tag)


def _use_vendor_dir():
    path = vendor_dir()
    if os.path.isdir(path) and path not in sys.path:
        sys.path.append(path)
        importlib.invalidate_caches()


def dracopy_available():
    # type: () -> bool
    """True if `import DracoPy` succeeds in the current interpreter."""
    _use_vendor_dir()
    try:
        import DracoPy  # noqa: F401
        return True
    except Exception:
        return False


def python_executable():
    # type: () -> str
    """The Python that can run pip for this interpreter.

    In mayapy that is sys.executable. In a Maya with a window sys.executable
    is maya itself, and `maya -m pip` would start a second Maya: use the
    mayapy that sits next to it.
    """
    exe = sys.executable or ""
    folder, name = os.path.split(exe)
    stem = os.path.splitext(name)[0].lower()
    if stem.startswith("mayapy") or stem.startswith("python"):
        return exe
    for candidate in ("mayapy.exe", "mayapy"):
        path = os.path.join(folder, candidate)
        if os.path.isfile(path):
            return path
    return exe


def install(python=None):
    # type: (str) -> tuple
    """Install the decoder into vendor_dir() with pip. Needs internet.

    Returns (ok, text): `text` is pip's output on failure, the place it went
    to on success. Never raises. Runs whatever MAYA_GLB_IO_OFFLINE says: this
    is the explicit request, ensure_dracopy() is the automatic one.

    When the plug-in folder cannot be written (a studio-wide install), pip is
    run again with --user, into the user's site-packages.
    """
    import subprocess

    target = vendor_dir()
    base = [
        python or python_executable(), "-m", "pip", "install",
        "--disable-pip-version-check", "--upgrade",
    ]
    attempts = (
        (base + ["--target", target, PACKAGE], target),
        (base + ["--user", PACKAGE], "the user's site-packages"),
    )
    creationflags = 0
    if sys.platform == "win32":
        # Don't pop a console window when launched from Maya's GUI.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    output = ""
    for command, place in attempts:
        try:
            res = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,   # text mode, 3.6-compatible spelling
                creationflags=creationflags,
                timeout=PIP_SECONDS,
            )
        except Exception as exc:
            output = "could not launch pip (%s): %s" % (" ".join(command), exc)
            continue
        if res.returncode != 0:
            output = (res.stdout or "")[-1500:]
            continue
        importlib.invalidate_caches()
        if dracopy_available():
            return True, place
        output = (
            "pip reported success but `import DracoPy` still fails from %s"
            % place
        )
    return False, output


def ensure_dracopy():
    # type: () -> bool
    """Make DracoPy importable, installing it into vendor_dir() if needed.

    Returns True at once when DracoPy already imports (callers only reach
    here on a Draco primitive, so other imports never pay for it). Returns
    False without trying when MAYA_GLB_IO_OFFLINE is set, and on any failure
    (offline, pip blocked, no wheel for this Python). NEVER raises: the caller
    warns + skips.
    """
    if dracopy_available():
        return True
    if os.environ.get("MAYA_GLB_IO_OFFLINE"):
        return False

    _warn(
        "Draco-compressed mesh found; installing the DracoPy decoder into %s "
        "(one-time, needs internet)..." % vendor_dir()
    )
    ok, text = install()
    if not ok:
        _warn(
            "DracoPy install failed (offline or pip blocked?). "
            "Draco-compressed meshes will be skipped. Install it manually with:"
            "  %s -m pip install --target \"%s\" DracoPy\npip output:\n%s"
            % (python_executable(), vendor_dir(), text)
        )
        return False
    _warn("DracoPy installed and importable; decoding Draco meshes.")
    return True


def _rows(arr, integers=False):
    """A decoded generic attribute (an N x K array) as a list of tuples."""
    try:
        rows = arr.tolist()
    except AttributeError:
        rows = list(arr)
    cast = int if integers else float
    out = []
    for row in rows:
        if isinstance(row, (list, tuple)):
            out.append(tuple(cast(v) for v in row))
        else:
            out.append((cast(row),))
    return out


def _by_unique_id(mesh, unique_id):
    """The array of the Draco attribute with this unique id, or None (older
    DracoPy has no such lookup, and an id may simply be absent)."""
    getter = getattr(mesh, "get_attribute_by_unique_id", None)
    if getter is None:
        return None
    try:
        found = getter(int(unique_id))
    except Exception:
        return None
    if not isinstance(found, dict):
        return None
    return found.get("data")


def _to_xyz_list(arr):
    """Reshape a points/normals array (flat or Nx3 / ndarray or list) into a
    list of (x, y, z) float tuples."""
    # numpy ndarray (the DracoPy 2.x path) — Nx3 or flat.
    try:
        import numpy as _np  # noqa
        if isinstance(arr, _np.ndarray):
            a = arr
            if a.ndim == 2 and a.shape[1] == 3:
                return [(float(r[0]), float(r[1]), float(r[2])) for r in a]
            flat = a.reshape(-1)
            return [
                (float(flat[i]), float(flat[i + 1]), float(flat[i + 2]))
                for i in range(0, len(flat) - 2, 3)
            ]
    except Exception:
        pass

    # Plain Python sequence fallback (older DracoPy returned flat lists or
    # lists of 3-tuples).
    if not arr:
        return []
    first = arr[0]
    if isinstance(first, (list, tuple)) and len(first) >= 3:
        return [(float(p[0]), float(p[1]), float(p[2])) for p in arr]
    return [
        (float(arr[i]), float(arr[i + 1]), float(arr[i + 2]))
        for i in range(0, len(arr) - 2, 3)
    ]


def _to_uv_list(arr):
    """Reshape a tex_coord array (flat or Nx2) into a list of (u, v) tuples."""
    try:
        import numpy as _np  # noqa
        if isinstance(arr, _np.ndarray):
            a = arr
            if a.ndim == 2 and a.shape[1] >= 2:
                return [(float(r[0]), float(r[1])) for r in a]
            flat = a.reshape(-1)
            return [
                (float(flat[i]), float(flat[i + 1]))
                for i in range(0, len(flat) - 1, 2)
            ]
    except Exception:
        pass

    if not arr:
        return []
    first = arr[0]
    if isinstance(first, (list, tuple)) and len(first) >= 2:
        return [(float(p[0]), float(p[1])) for p in arr]
    return [
        (float(arr[i]), float(arr[i + 1]))
        for i in range(0, len(arr) - 1, 2)
    ]


def _to_index_list(faces):
    """Flatten a faces array (Mx3 or already-flat) into a flat triangle index
    list [i, i, i, ...]."""
    try:
        import numpy as _np  # noqa
        if isinstance(faces, _np.ndarray):
            return [int(v) for v in faces.reshape(-1)]
    except Exception:
        pass

    if not faces:
        return []
    first = faces[0]
    if isinstance(first, (list, tuple)):
        out = []
        for tri in faces:
            out.extend(int(v) for v in tri)
        return out
    return [int(v) for v in faces]


def decode(buffer_bytes, attributes=None):
    # type: (bytes, dict) -> dict
    """Decode a Draco bitstream into normalized glTF-semantic arrays.

    `attributes` is the extension's table {glTF semantic: Draco unique id}.
    Returns a dict:
      {
        "POSITION":   [(x, y, z), ...],     # always present on a valid mesh
        "NORMAL":     [(x, y, z), ...] | None,
        "TEXCOORD_0": [(u, v), ...]   | None,
        "indices":    [i, i, i, ...],       # flat triangle list
        "JOINTS_0":   [(j, j, j, j), ...],  # every other semantic of the table
        "WEIGHTS_0":  [(w, w, w, w), ...],  # the stream really carries
        ...
      }

    Every attribute of one stream is in the same decoded vertex order, so rows
    of JOINTS_0 / WEIGHTS_0 line up with POSITION. Integer components come back
    as they are stored: scaling a normalized accessor is the caller's job
    (_gltf.decode_draco_primitive knows the accessor).

    With no table, or a DracoPy too old to look attributes up by id,
    POSITION / NORMAL / TEXCOORD_0 are resolved by type and nothing else is
    returned.

    Raises DracoError if DracoPy isn't importable or the buffer fails to decode.
    """
    _use_vendor_dir()
    try:
        import DracoPy
    except Exception as exc:
        raise DracoError(
            "DracoPy is not installed; cannot decode KHR_draco_mesh_compression "
            "(%s)" % exc
        )

    try:
        mesh = DracoPy.decode(bytes(buffer_bytes))
    except Exception as exc:
        raise DracoError("DracoPy failed to decode Draco buffer: %s" % exc)

    attributes = attributes or {}
    typed = {
        "POSITION": getattr(mesh, "points", None),
        "NORMAL": getattr(mesh, "normals", None),
        "TEXCOORD_0": getattr(mesh, "tex_coord", None),
    }
    for semantic in typed:
        if semantic in attributes:
            data = _by_unique_id(mesh, attributes[semantic])
            if data is not None:
                typed[semantic] = data
    faces = getattr(mesh, "faces", None)

    if typed["POSITION"] is None:
        raise DracoError("decoded Draco stream has no POSITION data")

    normals = typed["NORMAL"]
    tex = typed["TEXCOORD_0"]
    result = {
        "POSITION": _to_xyz_list(typed["POSITION"]),
        "NORMAL": _to_xyz_list(normals) if normals is not None else None,
        "TEXCOORD_0": _to_uv_list(tex) if tex is not None else None,
        "indices": _to_index_list(faces) if faces is not None else [],
    }
    for semantic, unique_id in attributes.items():
        if semantic in result:
            continue
        data = _by_unique_id(mesh, unique_id)
        if data is None:
            continue
        try:
            integers = data.dtype.kind in "iu"
        except AttributeError:
            integers = semantic.startswith("JOINTS_")
        result[semantic] = _rows(data, integers=integers)
    return result
