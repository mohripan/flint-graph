FlintGraph editable Godot source export, runtime 0.5.0.

Use the qualified Godot 4.7.2 stable GDScript engine. No AI service or platform
account is required by this project. Install matching engine export templates
explicitly if you build a browser executable; this export never installs them.

The bootstrap verifies package and asset hashes, then starts the authored player.
Stories in format 2 play on a full-screen stage with a styled text box; their
images and fonts are under content/assets/ and are credited in content/NOTICES.txt.
Use Continue/Enter/Space, listed choices (or digits 1-9), and Save/Load/Restart.
Saves are local to the device/browser and package version; no cloud sync is used.
Gameplay conformance and actual browser qualification are documented separately
in the repository. This export is not an authoring studio or AI server.

Edit your downloaded copy as needed. Re-export always creates a separate project;
custom engine edits are not reverse-synchronized into the studio. Creator source
is under content/, with immutable revision hashes in build-manifest.json. The
manifest is integrity metadata, not a signature or authentication credential.

Keep runtime and engine notices when distributing; creator content has separate
rights declarations. No credentials, provider prompts or model endpoints are
needed or embedded. Browser privacy/publishing and hosted build isolation require
their own qualification; a local source export is not a production sandbox.
