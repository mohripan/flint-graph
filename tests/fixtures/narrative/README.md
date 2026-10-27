# Original narrative runtime fixtures

`lantern_archive/` is an original short mystery created for M30. Its text and
simple procedural placeholder artwork are released under CC0-1.0; see the
package's `NOTICES.txt`. It contains no downloaded novel, anime character, private
document, model output transcript or external artwork.

The three independently authored action sequences and expected final state are
in `lantern_routes.json`, outside the runtime package. Package inventory is strict:
documentation, expected answers, scripts and route labels are not game inputs.
The fixture is a runtime proof, not the M34 15–30 minute production game.

Rebuild the two original placeholder PNGs with
`python tools/narrative/build_fixture_art.py`; the script prints SHA-256s to compare
with `story.json`. It does not automatically change the story's declared hashes.
