"""Checks that need Maya: names kept across import and export, CUBICSPLINE
import, skinned Draco import, key reduction on export.

Run with mayapy from the repository folder:
    mayapy _dev/check_maya.py

The Draco check is skipped when the DracoPy decoder is not installed
(`maya_glb_io.commands.install_draco()` installs it).

Prints SUCCESS at the end; raises on the first mismatch.
"""
import base64
import json
import math
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "scripts")))
os.environ["MAYA_GLB_IO_OFFLINE"] = "1"

import maya.standalone  # noqa: E402

maya.standalone.initialize()

from maya import cmds  # noqa: E402

from maya_glb_io import _draco, _gltf, _keys, _names, exporter, importer  # noqa: E402

OUT = tempfile.mkdtemp(prefix="glb_io_check_")
IMPORT_OPTIONS = {"skipMaterials": False, "target": "phong", "dropToFloor": False,
                  "bakeTransforms": False, "flatten": False}
FLOAT, USHORT, UINT = 5126, 5123, 5125


class Buffer(object):
    """One glTF buffer built accessor by accessor."""

    def __init__(self):
        self.data = b""
        self.views = []
        self.accessors = []

    def view(self, blob):
        while len(self.data) % 4:
            self.data += b"\x00"
        self.views.append({"buffer": 0, "byteOffset": len(self.data),
                           "byteLength": len(blob)})
        self.data += blob
        return len(self.views) - 1

    def add(self, rows, kind, component=FLOAT, minmax=False):
        flat = []
        for row in rows:
            if isinstance(row, (list, tuple)):
                flat.extend(row)
            else:
                flat.append(row)
        code = {FLOAT: "f", USHORT: "H", UINT: "I"}[component]
        accessor = {"bufferView": self.view(struct.pack("<%d%s" % (len(flat), code), *flat)),
                    "componentType": component, "count": len(rows), "type": kind}
        if minmax:
            width = len(flat) // len(rows)
            accessor["min"] = [min(flat[i::width]) for i in range(width)]
            accessor["max"] = [max(flat[i::width]) for i in range(width)]
        self.accessors.append(accessor)
        return len(self.accessors) - 1

    def bare(self, count, kind, component=FLOAT, minmax=None):
        """An accessor with no data of its own, as a Draco primitive has."""
        accessor = {"componentType": component, "count": count, "type": kind}
        if minmax:
            accessor["min"], accessor["max"] = minmax
        self.accessors.append(accessor)
        return len(self.accessors) - 1

    def finish(self, doc):
        doc["asset"] = {"version": "2.0"}
        doc["accessors"] = self.accessors
        doc["bufferViews"] = self.views
        doc["buffers"] = [{
            "byteLength": len(self.data),
            "uri": "data:application/octet-stream;base64,"
                   + base64.b64encode(self.data).decode("ascii"),
        }]
        return doc


def write(name, doc):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False)
    return path


def read(path):
    with open(path, "rb") as handle:
        return _gltf.loads(handle.read(), base_dir=os.path.dirname(path))


def close(a, b, tolerance=1e-4):
    return abs(a - b) <= tolerance


def triangle(buffer):
    positions = buffer.add([(0, 0, 0), (1, 0, 0), (0, 1, 0)], "VEC3", minmax=True)
    indices = buffer.add([0, 1, 2], "SCALAR", UINT)
    return {"attributes": {"POSITION": positions}, "indices": indices}


# ---------------------------------------------------------------------------

def check_names():
    cmds.file(new=True, force=True)
    buffer = Buffer()
    prim = triangle(buffer)
    prim["material"] = 0
    wanted = ["Root.001", "ルート", "mixamorig:Hips", "plain", "Left Arm"]
    doc = buffer.finish({
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": wanted[0], "mesh": 0, "children": [1, 2, 3, 4]},
            {"name": wanted[1], "translation": [1, 0, 0]},
            {"name": wanted[2], "translation": [2, 0, 0]},
            {"name": wanted[3], "translation": [3, 0, 0]},
            {"name": wanted[4], "translation": [4, 0, 0]},
        ],
        "meshes": [{"name": "Mesh.001", "primitives": [prim]}],
        "materials": [{"name": "Mat 1", "pbrMetallicRoughness": {}}],
    })
    tops = importer.import_file(write("names.gltf", doc), dict(IMPORT_OPTIONS))
    assert tops, "nothing imported"
    root = tops[0]
    assert _names.short_name(root) == "Root_001", root
    assert _names.original(root) == "Root.001"
    plain = [n for n in cmds.listRelatives(root, children=True, fullPath=True, type="transform")
             if _names.short_name(n) == "plain"]
    assert plain and not cmds.attributeQuery("gltfName", node=plain[0], exists=True), \
        "a name Maya kept needs no attribute"

    out = os.path.join(OUT, "names_out.gltf")
    exporter.export_nodes([root], out, {"format": "gltf", "exportAnimation": False})
    back = read(out).doc
    names = [n.get("name") for n in back["nodes"]]
    assert sorted(names) == sorted(wanted), names
    assert [m.get("name") for m in back["materials"]] == ["Mat 1"], back["materials"]

    # A renamed node and a duplicate export under their Maya names.
    arm = [n for n in cmds.listRelatives(root, children=True, fullPath=True)
           if _names.short_name(n) == "Left_Arm"][0]
    copy = cmds.duplicate(arm)[0]
    cmds.rename(arm, "upperArm")
    exporter.export_nodes([root], out, {"format": "gltf", "exportAnimation": False})
    names = [n.get("name") for n in read(out).doc["nodes"]]
    assert "Left Arm" not in names and "upperArm" in names, names
    assert _names.short_name(copy) in names, names

    # The default import collapses a pass-through parent: its name must not
    # land on the child that takes its place.
    cmds.file(new=True, force=True)
    buffer = Buffer()
    doc = buffer.finish({
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Wrapper Node", "children": [1]},
                  {"name": "Child.A", "mesh": 0}],
        "meshes": [{"primitives": [triangle(buffer)]}],
    })
    options = dict(IMPORT_OPTIONS)
    del options["flatten"]
    tops = importer.import_file(write("collapse.gltf", doc), options)
    assert [_names.short_name(top) for top in tops] == ["Child_A"], tops
    assert _names.original(tops[0]) == "Child.A", _names.original(tops[0])
    assert exporter.written_name(tops[0]) == "Child.A"
    print("names ok")


def check_target_names():
    cmds.file(new=True, force=True)
    buffer = Buffer()
    prim = triangle(buffer)
    prim["targets"] = [
        {"POSITION": buffer.add([(0, 0, 1), (0, 0, 0), (0, 0, 0)], "VEC3", minmax=True)},
        {"POSITION": buffer.add([(0, 0, 0), (0, 0, 1), (0, 0, 0)], "VEC3", minmax=True)},
    ]
    wanted = ["Smile Wide", "blink"]
    doc = buffer.finish({
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "face", "mesh": 0}],
        "meshes": [{"primitives": [prim], "weights": [0, 0],
                    "extras": {"targetNames": wanted}}],
    })
    tops = importer.import_file(write("targets.gltf", doc), dict(IMPORT_OPTIONS))
    shapes = cmds.ls(type="blendShape")
    assert len(shapes) == 1, shapes
    assert _names.target_names(shapes[0]) == {"Smile_Wide": "Smile Wide"}, \
        _names.target_names(shapes[0])
    out = os.path.join(OUT, "targets_out.gltf")
    exporter.export_nodes(tops, out, {"format": "gltf", "exportAnimation": False})
    mesh = read(out).doc["meshes"][0]
    assert mesh.get("extras", {}).get("targetNames") == wanted, mesh.get("extras")
    print("target names ok")


def hermite(s, d, p0, m0, p1, m1):
    return ((2 * s**3 - 3 * s**2 + 1) * p0 + (s**3 - 2 * s**2 + s) * d * m0
            + (-2 * s**3 + 3 * s**2) * p1 + (s**3 - s**2) * d * m1)


def check_cubic():
    cmds.file(new=True, force=True)
    cmds.currentUnit(time="ntsc")
    fps = 30.0
    buffer = Buffer()
    prim = triangle(buffer)
    times = buffer.add([0.0, 2.0], "SCALAR", minmax=True)
    # in-tangent, value, out-tangent per key
    move = [(0, 0, 0), (1, 0, 0), (3, 1, 0), (-2, 0, 0), (4, 2, 0), (0, 0, 0)]
    grow = [(0, 0, 0), (1, 1, 1), (0, 2, 0), (0, -1, 0), (1, 3, 1), (0, 0, 0)]
    half = math.sqrt(0.5)
    turn = [(0, 0, 0, 0), (0, 0, 0, 1), (0, 0.6, 0, 0),
            (0, 0.2, 0, 0), (0, half, 0, half), (0, 0, 0, 0)]
    doc = buffer.finish({
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "mover", "mesh": 0}],
        "meshes": [{"primitives": [prim]}],
        "animations": [{"name": "curve", "samplers": [
            {"input": times, "output": buffer.add(move, "VEC3"),
             "interpolation": "CUBICSPLINE"},
            {"input": times, "output": buffer.add(grow, "VEC3"),
             "interpolation": "CUBICSPLINE"},
            {"input": times, "output": buffer.add(turn, "VEC4"),
             "interpolation": "CUBICSPLINE"},
        ], "channels": [
            {"sampler": 0, "target": {"node": 0, "path": "translation"}},
            {"sampler": 1, "target": {"node": 0, "path": "scale"}},
            {"sampler": 2, "target": {"node": 0, "path": "rotation"}},
        ]}],
    })
    tops = importer.import_file(write("cubic.gltf", doc), dict(IMPORT_OPTIONS))
    node = tops[0]
    unit = 100.0  # the scene is in centimetres, the file in metres
    for s in (0.25, 0.5, 0.75):
        frame = s * 2.0 * fps
        want_x = hermite(s, 2.0, 1, 3, 4, -2) * unit
        want_y = hermite(s, 2.0, 0, 1, 2, 0) * unit
        got_x = cmds.getAttr(node + ".translateX", time=frame)
        got_y = cmds.getAttr(node + ".translateY", time=frame)
        assert close(got_x, want_x, 1e-3) and close(got_y, want_y, 1e-3), \
            (s, got_x, want_x, got_y, want_y)
        want_s = hermite(s, 2.0, 1, 2, 3, -1)
        got_s = cmds.getAttr(node + ".scaleY", time=frame)
        assert close(got_s, want_s), (s, got_s, want_s)
        assert close(cmds.getAttr(node + ".scaleX", time=frame), 1.0)

    # Rotation: one key per frame, each on the spline.
    keys = cmds.keyframe(node, attribute="rotateY", query=True, timeChange=True)
    assert len(keys) == 61, len(keys)
    for s in (0.25, 0.5, 0.75):
        y = hermite(s, 2.0, 0, 0.6, half, 0.2)
        w = hermite(s, 2.0, 1, 0, half, 0)
        want = math.degrees(2.0 * math.atan2(y, w))
        got = cmds.getAttr(node + ".rotateY", time=s * 2.0 * fps)
        assert close(got, want, 1e-3), (s, got, want)
    print("cubic ok")


def check_cubic_weights():
    """A CUBICSPLINE `weights` output is, per key, the in-tangents of every
    target, then the values, then the out-tangents."""
    cmds.file(new=True, force=True)
    cmds.currentUnit(time="ntsc")
    fps = 30.0
    buffer = Buffer()
    prim = triangle(buffer)
    prim["targets"] = [
        {"POSITION": buffer.add([(0, 0, 1), (0, 0, 0), (0, 0, 0)], "VEC3", minmax=True)},
        {"POSITION": buffer.add([(0, 0, 0), (0, 0, 1), (0, 0, 0)], "VEC3", minmax=True)},
    ]
    times = buffer.add([0.0, 2.0], "SCALAR", minmax=True)
    output = [0, 0, 0, 1, 1.5, -0.5,
              0.5, 0, 1, 0.25, 0, 0]
    doc = buffer.finish({
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "face", "mesh": 0}],
        "meshes": [{"primitives": [prim], "weights": [0, 0]}],
        "animations": [{"name": "talk", "samplers": [
            {"input": times, "output": buffer.add(output, "SCALAR"),
             "interpolation": "CUBICSPLINE"},
        ], "channels": [{"sampler": 0, "target": {"node": 0, "path": "weights"}}]}],
    })
    importer.import_file(write("cubic_weights.gltf", doc), dict(IMPORT_OPTIONS))
    shapes = cmds.ls(type="blendShape")
    assert len(shapes) == 1, shapes
    for s in (0.0, 0.25, 0.5, 0.75, 1.0):
        frame = s * 2.0 * fps
        first = cmds.getAttr(shapes[0] + ".weight[0]", time=frame)
        second = cmds.getAttr(shapes[0] + ".weight[1]", time=frame)
        want_first = hermite(s, 2.0, 0, 1.5, 1, 0.5)
        want_second = hermite(s, 2.0, 1, -0.5, 0.25, 0)
        assert close(first, want_first, 1e-3) and close(second, want_second, 1e-3), \
            (s, first, want_first, second, want_second)
    print("cubic weights ok")


def check_skin_names():
    """Joints and a skinned mesh keep their glTF names through import and export."""
    cmds.file(new=True, force=True)
    buffer = Buffer()
    points = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (0, 2, 0), (1, 2, 0)]
    faces = [0, 1, 2, 2, 1, 3, 2, 3, 4, 4, 3, 5]
    joints = [(0, 1, 0, 0)] * 6
    weights = [(1, 0, 0, 0), (0.9, 0.1, 0, 0), (0.5, 0.5, 0, 0),
               (0.4, 0.6, 0, 0), (0.2, 0.8, 0, 0), (0, 1, 0, 0)]
    identity = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    up = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -1, 0, 1)
    prim = {
        "attributes": {
            "POSITION": buffer.add(points, "VEC3", minmax=True),
            "JOINTS_0": buffer.add(joints, "VEC4", USHORT),
            "WEIGHTS_0": buffer.add(weights, "VEC4"),
        },
        "indices": buffer.add(faces, "SCALAR", UINT),
    }
    wanted = ["Body Mesh", "mixamorig:Hips", "Bone.001"]
    doc = buffer.finish({
        "scene": 0,
        "scenes": [{"nodes": [0, 1]}],
        "nodes": [
            {"name": wanted[0], "mesh": 0, "skin": 0},
            {"name": wanted[1], "children": [2]},
            {"name": wanted[2], "translation": [0, 1, 0]},
        ],
        "meshes": [{"primitives": [prim]}],
        "skins": [{"joints": [1, 2], "inverseBindMatrices": buffer.add([identity, up], "MAT4")}],
    })
    for name, options in (("skin_names", dict(IMPORT_OPTIONS)),
                          ("skin_names_default", {"skipMaterials": True})):
        cmds.file(new=True, force=True)
        importer.import_file(write(name + ".gltf", doc), dict(options))
        found = {}
        for node in cmds.ls(type="transform", long=True):
            if cmds.attributeQuery("gltfName", node=node, exists=True):
                found[_names.short_name(node)] = exporter.written_name(node)
        assert found == {"Body_Mesh": "Body Mesh", "mixamorig_Hips": "mixamorig:Hips",
                         "Bone_001": "Bone.001"}, (name, found)
        assert cmds.nodeType("Bone_001") == "joint" and cmds.ls(type="skinCluster"), name
        out = os.path.join(OUT, name + "_out.gltf")
        tops = cmds.ls("Body_Mesh", "mixamorig_Hips", long=True)
        exporter.export_nodes(tops, out, {"format": "gltf", "exportAnimation": False})
        back = read(out).doc
        names = [n.get("name") for n in back["nodes"]]
        assert sorted(names) == sorted(wanted), (name, names)
        skin_joints = [back["nodes"][i]["name"] for i in back["skins"][0]["joints"]]
        assert sorted(skin_joints) == sorted(wanted[1:]), (name, skin_joints)
    print("skin names ok")


def check_draco():
    if not _draco.dracopy_available():
        print("draco SKIPPED: DracoPy is not installed")
        return
    import DracoPy
    import numpy

    cmds.file(new=True, force=True)
    points = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (0, 2, 0), (1, 2, 0)]
    faces = [(0, 1, 2), (2, 1, 3), (2, 3, 4), (4, 3, 5)]
    joints = [(0, 1, 0, 0)] * 6
    weights = [(1, 0, 0, 0), (0.9, 0.1, 0, 0), (0.5, 0.5, 0, 0),
               (0.4, 0.6, 0, 0), (0.2, 0.8, 0, 0), (0, 1, 0, 0)]
    stream = DracoPy.encode(
        numpy.array(points, dtype=numpy.float32),
        numpy.array(faces, dtype=numpy.uint32),
        quantization_bits=14,
        generic_attributes={
            3: numpy.array(joints, dtype=numpy.uint16),
            4: numpy.array(weights, dtype=numpy.float32),
        },
    )
    position_id = None
    decoded = DracoPy.decode(stream)
    for attribute in decoded.attributes:
        if attribute["attribute_type"] == 0:
            position_id = attribute["unique_id"]
    assert position_id is not None

    buffer = Buffer()
    stream_view = buffer.view(stream)
    identity = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    up = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -1, 0, 1)
    bind = buffer.add([identity, up], "MAT4")
    prim = {
        "attributes": {
            "POSITION": buffer.bare(6, "VEC3", minmax=([0, 0, 0], [1, 2, 0])),
            "JOINTS_0": buffer.bare(6, "VEC4", USHORT),
            "WEIGHTS_0": buffer.bare(6, "VEC4"),
        },
        "indices": buffer.bare(12, "SCALAR", UINT),
        "extensions": {"KHR_draco_mesh_compression": {
            "bufferView": stream_view,
            "attributes": {"POSITION": position_id, "JOINTS_0": 3, "WEIGHTS_0": 4},
        }},
    }
    doc = buffer.finish({
        "scene": 0,
        "scenes": [{"nodes": [0, 1]}],
        "nodes": [
            {"name": "body", "mesh": 0, "skin": 0},
            {"name": "hip", "children": [2]},
            {"name": "spine", "translation": [0, 1, 0]},
        ],
        "meshes": [{"primitives": [prim]}],
        "skins": [{"joints": [1, 2], "inverseBindMatrices": bind}],
        "extensionsUsed": ["KHR_draco_mesh_compression"],
        "extensionsRequired": ["KHR_draco_mesh_compression"],
    })
    importer.import_file(write("draco_skin.gltf", doc), dict(IMPORT_OPTIONS))
    clusters = cmds.ls(type="skinCluster")
    assert len(clusters) == 1, "the Draco mesh was not skinned: %s" % clusters
    shape = cmds.skinCluster(clusters[0], query=True, geometry=True)[0]
    assert cmds.polyEvaluate(shape, vertex=True) == 6
    hip = cmds.ls("hip", type="joint")[0]
    by_place = {}
    for point, row in zip(points, weights):
        by_place[(point[0], point[1])] = row[0]
    for index in range(6):
        place = cmds.pointPosition("%s.vtx[%d]" % (shape, index), world=True)
        want = by_place[(round(place[0] / 100.0), round(place[1] / 100.0))]
        got = cmds.skinPercent(clusters[0], "%s.vtx[%d]" % (shape, index),
                               query=True, transform=hip)
        assert close(got, want, 1e-3), (index, place, got, want)
    print("draco ok")


def check_reduce_keys():
    cmds.file(new=True, force=True)
    cmds.currentUnit(time="ntsc")
    cmds.playbackOptions(minTime=0, maxTime=60, animationStartTime=0, animationEndTime=60)
    cube = cmds.polyCube(name="box")[0]
    # A straight move, then a hold, and an eased turn.
    cmds.setKeyframe(cube, attribute="translateX", time=0, value=0)
    cmds.setKeyframe(cube, attribute="translateX", time=30, value=300)
    cmds.setKeyframe(cube, attribute="translateX", time=60, value=300)
    cmds.keyTangent(cube, attribute="translateX", itt="linear", ott="linear")
    cmds.setKeyframe(cube, attribute="rotateY", time=0, value=0)
    cmds.setKeyframe(cube, attribute="rotateY", time=60, value=170)
    cmds.keyTangent(cube, attribute="rotateY", itt="flat", ott="flat")

    def channels(path):
        gltf = read(path)
        found = {}
        for channel in gltf.read_animations()[0].channels:
            found[channel.path] = (channel.times, channel.values)
        return found

    full_path = os.path.join(OUT, "keys_full.glb")
    thin_path = os.path.join(OUT, "keys_thin.glb")
    base = {"format": "glb", "frameRange": (0, 60)}
    exporter.export_nodes([cube], full_path, dict(base, reduceKeys=False))
    exporter.export_nodes([cube], thin_path, dict(base, reduceKeys=True))
    full = channels(full_path)
    thin = channels(thin_path)
    assert len(full["translation"][0]) == 61 and len(full["rotation"][0]) == 61
    assert len(thin["translation"][0]) == 3, thin["translation"][0]
    assert 3 < len(thin["rotation"][0]) < 61, len(thin["rotation"][0])
    assert os.path.getsize(thin_path) < os.path.getsize(full_path)

    # What a player computes from the kept keys is what every frame held.
    for path, quaternions in (("translation", False), ("rotation", True)):
        times, rows = thin[path]
        for time, row in zip(*full[path]):
            after = next(i for i, t in enumerate(times) if t >= time - 1e-6)
            before = max(after - 1, 0)
            span = times[after] - times[before]
            s = (time - times[before]) / span if span > 0 else 0.0
            if quaternions:
                guess = _keys.slerp(tuple(rows[before]), tuple(rows[after]), s)
                assert _keys.angle_between(guess, tuple(row)) < 2e-4, (path, time)
            else:
                guess = _keys.lerp(tuple(rows[before]), tuple(rows[after]), s)
                assert max(abs(a - b) for a, b in zip(guess, row)) < 2e-5, (path, time)
    print("reduce keys ok: %d -> %d rotation keys, %d -> %d bytes" % (
        len(full["rotation"][0]), len(thin["rotation"][0]),
        os.path.getsize(full_path), os.path.getsize(thin_path)))


def check_missing_texture():
    cmds.file(new=True, force=True)
    cube = cmds.polyCube(name="box")[0]
    shader = cmds.shadingNode("lambert", asShader=True, name="paint")
    group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="paintSG")
    cmds.connectAttr(shader + ".outColor", group + ".surfaceShader")
    texture = cmds.shadingNode("file", asTexture=True, name="gone")
    lost = os.path.join(OUT, "not_there.png").replace("\\", "/")
    cmds.setAttr(texture + ".fileTextureName", lost, type="string")
    cmds.connectAttr(texture + ".outColor", shader + ".color")
    cmds.sets(cube, edit=True, forceElement=group)
    for name, options in (("lost.glb", {"format": "glb", "embedTextures": True}),
                          ("lost.gltf", {"format": "gltf", "embedTextures": False})):
        out = os.path.join(OUT, name)
        result = exporter.export_nodes([cube], out, dict(options, exportAnimation=False))
        assert [os.path.basename(p) for p in result["missing_textures"]] == ["not_there.png"], result
        doc = read(out).doc
        assert not doc.get("images") and len(doc["meshes"]) == 1, doc.get("images")
    print("missing texture ok")


def check_uv_sets():
    cmds.file(new=True, force=True)
    cube = cmds.polyCube(name="box")[0]
    cmds.polyUVSet(cube, create=True, uvSet="lightmap")
    cmds.polyProjection(cube + ".f[*]", type="Planar", md="x", uvSetName="lightmap")
    out = os.path.join(OUT, "uv_sets.glb")
    exporter.export_nodes([cube], out, {"format": "glb", "exportAnimation": False})
    gltf = read(out)
    attrs = gltf.doc["meshes"][0]["primitives"][0]["attributes"]
    assert "TEXCOORD_1" in attrs, attrs
    first = gltf.read_accessor(attrs["TEXCOORD_0"])
    second = gltf.read_accessor(attrs["TEXCOORD_1"])
    assert len(first) == len(second) and first != second, (first[:3], second[:3])
    print("uv sets ok")


def main():
    check_names()
    check_target_names()
    check_cubic()
    check_cubic_weights()
    check_skin_names()
    check_draco()
    check_reduce_keys()
    check_missing_texture()
    check_uv_sets()
    print("SUCCESS")


if __name__ == "__main__":
    main()
