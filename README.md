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

Import:

- Animations that overlap in time are laid out one after another instead of on top of each other, each with a time slider bookmark.
- Keys land on whole frames.
- Undo removes everything an import made, morph target meshes included.

Other:

- `MAYA_GLB_IO_OFFLINE=1` turns off the update check and the DracoPy `pip install`.
- The update check follows this fork's releases.

[CHANGELOG.md](CHANGELOG.md) has the details, from 1.0.2 on.

## Install

With bmaya:

```bash
bmaya install --gltf
```

It downloads the release bmaya pins, checks its SHA-256 and installs it as a Maya module.

On its own: download the zip from [Releases](https://github.com/Snuux/maya-glb-io/releases), unpack it and drag `install.py` into a Maya viewport, as with the original.

## License

MIT, see [LICENSE](LICENSE). All credit for the plug-in goes to its author, [annomodtutorials](https://github.com/annomodtutorials/maya-glb-io).
