"""glTF names Maya cannot hold, kept on the node and written back on export.

Maya node names are ASCII letters, digits and underscores. A glTF name such as
"Bone.001", "mixamorig:Hips", "Left Arm" or "ルート" is changed on import, so an
import followed by an export would rename the node in the file.

The importer stores the glTF name in the string attribute `gltfName`, next to
`gltfNameOf`, the Maya name the node had at that moment. The exporter writes
`gltfName` only while the node still has that Maya name: a node the user
renamed, or a duplicate of an imported node, exports under its Maya name.

Morph target names live on the blendShape node as `gltfTargetNames`, a JSON
object {weight alias: glTF name}; an alias the user changed is not in it.
"""
from __future__ import annotations

import json

from maya import cmds


NAME_ATTR = "gltfName"
OWNER_ATTR = "gltfNameOf"
TARGETS_ATTR = "gltfTargetNames"


def short_name(node):
    """The node's own name: no DAG path, no namespace."""
    return node.split("|")[-1].split(":")[-1]


def _set_string(node, attr, value):
    if not cmds.attributeQuery(attr, node=node, exists=True):
        cmds.addAttr(node, longName=attr, dataType="string")
    cmds.setAttr(node + "." + attr, value, type="string")


def _get_string(node, attr):
    try:
        if not cmds.attributeQuery(attr, node=node, exists=True):
            return ""
        return cmds.getAttr(node + "." + attr) or ""
    except Exception:
        return ""


def remember(node, gltf_name, maya_name=None):
    """Store `gltf_name` on `node` when it differs from the Maya name.

    `maya_name` is the name the exporter would otherwise write (the node's
    short name by default; a material passes its name without the _SHD suffix).
    Returns True when something was stored. Never raises: a node that refuses
    an attribute (locked, referenced) simply exports under its Maya name.
    """
    if not gltf_name or not node:
        return False
    try:
        if not cmds.objExists(node):
            return False
        current = short_name(node)
        if gltf_name == (maya_name if maya_name is not None else current):
            return False
        _set_string(node, NAME_ATTR, gltf_name)
        _set_string(node, OWNER_ATTR, current)
        return True
    except Exception:
        return False


def original(node):
    """The glTF name stored on `node`, or "" when there is none or the node has
    been renamed or duplicated since the import."""
    name = _get_string(node, NAME_ATTR)
    if not name:
        return ""
    if _get_string(node, OWNER_ATTR) != short_name(node):
        return ""
    return name


def remember_targets(blendshape, names_by_alias):
    """Store {weight alias: glTF target name} for the aliases that differ."""
    changed = {}
    for alias, name in names_by_alias.items():
        if name and name != alias:
            changed[alias] = name
    if not changed:
        return False
    try:
        _set_string(blendshape, TARGETS_ATTR, json.dumps(changed, sort_keys=True))
        return True
    except Exception:
        return False


def target_names(blendshape):
    """{weight alias: glTF target name} stored on a blendShape, {} when none."""
    raw = _get_string(blendshape, TARGETS_ATTR)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}
