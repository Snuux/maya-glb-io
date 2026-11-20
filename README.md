# maya-glb-io (bmaya fork)

A fork of [annomodtutorials/maya-glb-io](https://github.com/annomodtutorials/maya-glb-io), the free glTF / GLB importer and exporter for Autodesk Maya (pure Python, MIT). The original has the full feature list, screenshots and usage guide; this page says only what is different here.

## Why this fork exists

[bmaya-cli](https://github.com/Snuux/bmaya-cli) lets AI agents drive Maya and needs glTF both ways from one Python library. The original 1.0.1 wrote skinned characters that game engines bound in the wrong place, and exported scenes that are not in centimetres at the wrong size. The fixes live here so that bmaya can pin one known release.

## What was changed

Export:

- Skins bind at the right joint positions (inverse bind matrices were written transposed).
- Scenes in metres, millimetres or inches export at their real size.
- Animation is sampled from each node's matrix, so constraints, IK, expressions and driven keys are written.
- Constraints, IK handles and effectors are no longer written as empty nodes.
- Several named clips in one file: options `clips`, `frameRange` and `animationName`.
- Keys that linear interpolation reproduces are left out (option `reduceKeys`, on by default): a hold or an even move is two keys, not one per frame.

Import:

- Animations that overlap in time are laid out one after another instead of on top of each other, each with a time slider bookmark.
- Keys land on whole frames.
- Undo removes everything an import made, morph target meshes included.
- A Draco-compressed mesh keeps its skin weights.
- CUBICSPLINE animation keeps its tangents (translation, scale, morph weights); CUBICSPLINE rotation is evaluated on every frame.

Both ways:

- Names Maya cannot hold (`Bone.001`, `mixamorig:Hips`, `Left Arm`, non-ASCII) are kept on the node and written back on export, for nodes, materials and morph targets.

Other:

- `MAYA_GLB_IO_OFFLINE=1` turns off the update check and the automatic DracoPy `pip install`.
- The Draco decoder goes into the plug-in's own `draco` folder, not into Maya's site-packages; `maya_glb_io.commands.install_draco()` installs it from a script.
- The update check follows this fork's releases.

[CHANGELOG.md](CHANGELOG.md) has the details, from 1.0.2 on.

## What is still limited

- Clearcoat, sheen, anisotropy and iridescence render fully in Arnold; Viewport 2.0 shows them partly. That is Maya's viewport.
- The Draco decoder is a compiled wheel (DracoPy), downloaded once with pip. There is no pure-Python decoder.
- Rotation is keyed as euler angles. Each key takes the solution closest to the key before it, so curves do not jump, but between keys far apart Maya's euler interpolation and glTF's quaternion interpolation take different paths.
- Export writes LINEAR samples of the evaluated motion, not Maya's curve tangents.
- Imported light intensity is a rough conversion from glTF's physical units.

## Install

With bmaya:

```bash
bmaya install --gltf
```

It downloads the release bmaya pins, checks its SHA-256 and installs it as a Maya module.

On its own: download the zip from [Releases](https://github.com/Snuux/maya-glb-io/releases), unpack it and drag `install.py` into a Maya viewport, as with the original.

## License

MIT, see [LICENSE](LICENSE). All credit for the plug-in goes to its author, [annomodtutorials](https://github.com/annomodtutorials/maya-glb-io).
