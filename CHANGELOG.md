# Changelog

All notable changes to Maya GLB I/O are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [1.1.1] - 2026-11-24

### Fixed
- Dragging a .glb into Maya (or File > Import with Maya namespaces) no longer wraps the whole
  scene, default cameras and the UI namespace included, into the file's namespace. Merging
  it back destroyed the viewport panels and left Maya unable to show windows.

## [1.1.0] - 2026-11-21

### Added
- Names survive an import and export. Maya node names are ASCII letters, digits and
  underscores, so `Bone.001`, `mixamorig:Hips`, `Left Arm` or a non-ASCII name is changed on
  import. The glTF name is now kept on the node (string attributes `gltfName` and
  `gltfNameOf`) and written back on export, for nodes, materials and morph targets. A node
  that was renamed or duplicated in Maya exports under its Maya name.
- Import: a Draco-compressed mesh keeps its skin. `JOINTS_n` / `WEIGHTS_n` (and any other
  attribute of the extension's table) are read from the Draco stream; such a mesh used to
  come in as static geometry.
- Import: CUBICSPLINE animation keeps the file's tangents for translation, scale and morph
  weights (the Maya curve is the same Hermite curve). CUBICSPLINE rotation is evaluated on
  every frame, because quaternion tangents have no euler counterpart.
- Export: option `reduceKeys` (on by default) leaves out the keys that linear interpolation
  between their neighbours reproduces, within 0.01 mm and 0.01 degrees. A hold or a
  constant-speed move becomes two keys instead of one per frame.
- `commands.install_draco()` installs the Draco decoder from a script, without dialogs;
  `importer.uses_draco(path)` and `importer.draco_ready()` tell whether a file needs it and
  whether it is there; `exporter.written_name(node)` is the name a node gets in the file.

### Changed
- The DracoPy decoder is installed into the plug-in's own folder (`draco/py<XY>`, one per
  Python version) instead of Maya's site-packages, which is the fallback when that folder
  cannot be written. A DracoPy that is already importable is still used.

- Installing the decoder runs pip with the `mayapy` next to `maya` when it is started from a
  Maya with a window, where `sys.executable` is Maya itself.

### Fixed
- Export: a material whose texture file is not on disk stopped the export with an error. The
  material is now written without that map, with a warning, and the result of
  `export_nodes` lists the files as `missing_textures`.
- Import: a `.gltf` whose texture file is missing stopped with an error before anything was
  built. The mesh, skin and animation now come in, with a warning per missing image.
- Import: a channel's interpolation (step, linear) is set on that channel's keys only, not on
  the keys another animation of the file put on the same attribute.

## [1.0.4] - 2026-11-20

### Fixed
- Import: a file whose animations overlap in time (most files: every animation starts at 0)
  had them keyed on top of each other. They are now laid out one after another, in file
  order, 10 frames apart. Animations that do not overlap keep their own frames.
- Import: keys land on whole frames; 32-bit glTF times put them at 19.9999995 and the like.

### Added
- Import: a time slider bookmark per animation with its name and frames (option
  `animationBookmarks`, on by default), and the animation range grows to hold them.

## [1.0.3] - 2026-11-20

### Fixed
- Import: undoing the import of a mesh with morph targets left a stray `polySurface` mesh
  behind. The temporary target meshes now sit under transforms made by `cmds`, so undo
  removes them.

## [1.0.2] - 2026-11-20

Fork of annomodtutorials/maya-glb-io, used by bmaya-cli.

### Fixed
- Export: inverse bind matrices were transposed, which put the translation in the wrong
  cells; Maya's flat bindPreMatrix already has glTF's layout. Engines now bind skins at
  the right joint positions.
- Export: lengths from the Maya API are centimetres in every scene, so scenes in metres,
  millimetres or inches export at their real size.
- Export: animation is sampled from each node's matrix, so constraints, IK, expressions
  and driven keys are written, and animated translation keeps pivots and parent space.
  Only channels that move, or hold away from the rest pose, are written.
- Export: constraints, IK handles and effectors are no longer written as empty nodes.

### Added
- Export options `clips` (one glTF animation per name and frame range), `frameRange` and
  `animationName`.
- `MAYA_GLB_IO_OFFLINE=1` turns off the update check and the DracoPy pip install.
- Update checks follow this fork's releases.

## [1.0.1] - 2026-06-22

### Added
- **In-plugin update check** — tells you inside Maya when a newer release is available
  (automatic once per day on load, fail-silent offline), plus a
  *GLB I/O → Check for Updates...* menu item.

### Changed
- Renamed the top menu to **GLB I/O**.
- Plug-in now reports its correct version in the Plug-in Manager.
- The landing page offers a direct one-click download of the release zip; install docs
  point at the release installer.

## [1.0.0] - 2026-06-03

First public release — a complete, free, MIT-licensed glTF 2.0 importer **and** exporter for
Autodesk Maya 2022+.

### Added — Import
- `.glb` (binary) and `.gltf` (+ external `.bin`) import, auto-detected.
- Full node hierarchy; multi-mesh and multi-primitive (per-material) meshes.
- UVs (correct V-flip), vertex colors, and UV-derived tangents.
- Drop-to-floor toggle and a clean-import bake that removes leftover root scale / junk nodes.
- Namespace-safe import (auto-flattens Maya's File > Import namespace wrapping).
- Automatic unit conversion (glTF metres → Maya scene units).
- Per-import shader target: openPBR / StingrayPBS / Arnold / Maya Phong.
- PBR materials: base color, metallic-roughness, normal, ambient occlusion, emissive.
- Emissive with `KHR_materials_emissive_strength` and tunable emission luminance (nits).
- Transparency (alpha BLEND / MASK).
- `KHR_materials_transmission` + `_ior` + `_volume` → refractive glass.
- `KHR_materials_clearcoat`, `_sheen`, `_anisotropy`, `_iridescence`, `_specular`.
- Full legacy `KHR_materials_pbrSpecularGlossiness` (diffuse + spec/gloss).
- `KHR_materials_variants` → live "Material Variant" dropdown in the Channel Box / Attribute Editor
  (scriptJob-driven, pre-warmed for instant switching).
- Skinning (joints + skinCluster, bulk weights) and skeletal animation (with euler unrolling, fps
  mapping).
- Morph targets / blendshapes with animated weights.
- Cameras (perspective + orthographic) and `KHR_lights_punctual` (directional / point / spot).
- `KHR_draco_mesh_compression` decode (auto-installs the DracoPy decoder once).
- `KHR_mesh_quantization` dequantization.

### Added — Export
- `.glb` and `.gltf` (+ external `.bin`); selection or whole scene.
- Materials → glTF metallic-roughness (from openPBR / StingrayPBS / aiStandardSurface / lambert /
  blinn / phong); embedded or referenced textures.
- Node hierarchy + transforms (pivots baked; roots carry world transform).
- Skinning export (joints + inverse-bind matrices + JOINTS_0 / WEIGHTS_0).
- Animation export (animCurves → samplers) and morph-target export (blendShapes → glTF morph
  targets + weights).
- Faithful round-trip with the importer.

### Added — UX / install
- Top-level **GLB I/O** menu and File > Import file translator with an options panel.
- Import and Export Preferences windows; one-time Draco-decoder installer.
- Drag-and-drop `install.py`, a Maya module `.mod`, and Plug-in Manager loading.

[1.0.1]: https://github.com/annomodtutorials/maya-glb-io/releases/tag/v1.0.1
[1.0.0]: https://github.com/annomodtutorials/maya-glb-io/releases/tag/v1.0.0
