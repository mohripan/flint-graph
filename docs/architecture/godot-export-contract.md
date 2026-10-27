# Editable Godot source export

M30 / #119. `export_godot(validated_package, new_path)` and the registered
`flint-graph-narrative export-godot SOURCE --output NEW_PATH` produce source from
an immutable package snapshot. There is no model, engine subprocess, template
download, global installation or data-service dependency in ordinary export.

## Source contents and ownership

The exporter copies an explicit trusted template allowlist, canonical story,
captured asset bytes, original notices and package/build manifests. It does not
scan arbitrary source directories, reopen assets after validation, generate
scripts from story text, or include workspace credentials/drafts/provider prompts.

```text
new-project/
  project.godot, main.tscn, export_presets.cfg
  runtime/bootstrap.gd
  content/story.json, package-manifest.json, NOTICES.txt
  content/assets/<id>.png, <id>.png.import
  toolchain.json, build-manifest.json
  README.txt, LICENSE.runtime.txt, GODOT-NOTICE.txt
```

The current bootstrap verifies source/notices/PNG hashes and displays an explicit
verification placeholder. Actual narrative gameplay is #120; this source-proof
milestone does not claim to deliver its player or browser route acceptance.

Every output target must be a new directory, even if an existing directory is
empty. Its parent must already exist and resolve without symlink/junction aliases.
The CLI also rejects output inside the source package. Files are created
exclusively. Re-export uses a different directory; existing customized projects
are not overwritten or reverse-synchronized.

The readiness build manifest is written last. If host I/O fails after target
creation, return `incomplete_export` and retain the new partial directory for
inspection. There is no automatic deletion, recursive cleanup, retry into an
existing path or claim of atomic publication. This preserves host-modified files
even if a failure occurs after the directory was created. Before target creation,
failures return safe `output_exists`, `unsafe_output_path`, `runtime_unavailable`
or `export_io` errors. A local export is not a sandbox against a hostile host.

## Reproducibility and packaging

The build manifest records schema/compiler/runtime/qualified Godot versions,
package hash and a sorted relative-path → SHA-256 map of every other output file.
It contains no wall-clock timestamp or host source directory. Its own SHA-256 is
returned by `ExportResult`/CLI, not recursively included in itself. The package
hash is unchanged by export. Repeated content exports have equal manifest hashes;
archive/native-binary reproducibility is not asserted.

Templates ship in wheels under `flint_graph/narrative/export/template` through
an explicit Hatch file allowlist. Editable checkouts use the same repository
`runtimes/godot/` files. Arbitrary caches, plugins or other runtime-directory
contents are not wheel inputs. `.gitattributes` fixes template text to LF.
An actually built/installed wheel exported outside the source checkout and its
manifest matched the source export; no editable fallback or project dependencies
were available in that isolated environment.

## Qualified toolchain and integrity

The initial qualified platform is Windows x86-64, Godot **4.7.2 stable**, observed
version `4.7.2.stable.official.ed1daf0bf`, GDScript. Source projects target the
Compatibility renderer and single-threaded Web preset. Exact official archive,
template and extracted member hashes are committed in
[`runtimes/godot/toolchain.json`](../../runtimes/godot/toolchain.json).

The actual archives were downloaded explicitly into ignored task-local notes,
checked against the official release's `SHA512-SUMS.txt`, then SHA-256 recorded.
Only exact engine and single-threaded web template members were extracted.
No binary/template is embedded in source exports or installed globally.
Another platform/engine version requires its own pinned native qualification.

The Godot bootstrap verifies the canonical package manifest against the declared
package hash, then exact source/notices/assets against that manifest. `.png.import`
uses Godot's keep-file mode so original bytes stay available to `FileAccess` in
the exported PCK; assets are rendered later from those verified bytes. A native
run of the actual generated Web PCK, with no loose source files, reproduced the
same successful content-hash check.

This is integrity, not an authenticity signature. Creators can modify their own
exported source. The bootstrap does not replace the strict Python package loader;
it consumes the compiler's already validated snapshot. Hosted compilation of
untrusted code remains excluded and needs a separate isolated-worker boundary.

## Licensing and actual checks

The original runtime/template source has an explicit MIT license so developers
can modify and distribute their exported copies. That license does not change
the license of the backend/repository, creator story/art or Godot. Original sample
assets/text retain their separate CC0 notice. Godot notices link the engine's
license and guidance; preserve notices for the exact engine/third-party components
used in a distribution. This is not an ownership or compliance certification.

Native qualification checks a pinned executable hash, real engine import,
successful package/asset verification and rejection of a tampered exported PNG.
Normal offline tests do not download or execute an engine. An explicitly
configured `FLINT_GRAPH_NARRATIVE_GODOT_BIN` runs the opt-in integration test.
The actual native source import, web export and Web PCK integrity proof passed;
browser input, UI layout, save/runtime route parity and complete gameplay remain
#120–#121 acceptance.

Official references reviewed 2026-10-27:

- [Pinned Godot release](https://github.com/godotengine/godot-builds/releases/tag/4.7.2-stable).
- [FileAccess and keep-file import mode](https://github.com/godotengine/godot/blob/master/doc/classes/FileAccess.xml).
- [Export filtering](https://docs.godotengine.org/en/stable/tutorials/export/exporting_projects.html).
- [Godot notice guidance](https://docs.godotengine.org/en/stable/about/complying_with_licenses.html).
