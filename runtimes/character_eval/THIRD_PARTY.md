# Character evaluation research dependencies

`score.py` adapts CCIP preprocessing, feature/learned-metric invocation and WD14
preprocessing from [deepghs/imgutils](https://github.com/deepghs/imgutils/tree/46df848dc4d20ac93f4919a40e2636d5f7c19766),
copyright 2023 DeepGHS, MIT. Its notice is retained in `LICENSE.imgutils.txt`.
Changes: local files and hashes only, CPU-only ONNX sessions with four threads,
two explicit CCIP checkpoints, original SmilingWolf WD checkpoint, no automatic
downloads, no character-name output, rating tags kept outside general tags.
This adapter does **not** call the full imgutils package or its mirrored WD model.

Model licenses are separate from this code license. CCIP repositories declare
`openrail` without an exact license text/variant; this remains unresolved for
production adoption. The experimental download manifest explicitly records
`openrail-unspecified`. SmilingWolf WD SwinV2 v3 declares Apache-2.0. See the
research report's pinned source/license table. The weights are downloaded
separately under ignored `notes/models`, never committed or exported into games.

ONNX Runtime: MIT; NumPy: BSD-3-Clause; Pillow: MIT-CMU; psutil: BSD-3-Clause.
Their exact versions and transitive dependency pins are in this runtime's own
`uv.lock`. No dependencies are added to the API, Studio, or Godot runtime.
