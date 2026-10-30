import hashlib
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def test_local_preview_serves_only_verified_build_bytes_with_isolation_headers(
    tmp_path: Path,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "preview_server", ROOT / "tools/narrative/serve_preview.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "web").mkdir()
    original = b"<title>Trusted playtest</title>"
    (tmp_path / "web/index.html").write_bytes(original)
    (tmp_path / "private.txt").write_text("not public")
    (tmp_path / "preview-build.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "parent_origin": "http://localhost:5173",
                "files": {"index.html": hashlib.sha256(original).hexdigest()},
            }
        )
    )
    server = module.create_server(tmp_path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        # Changed disk content cannot replace the immutable startup snapshot.
        (tmp_path / "web/index.html").write_bytes(b"changed")
        with urllib.request.urlopen(url + "/index.html", timeout=5) as response:
            assert response.read() == original
            csp = response.headers["Content-Security-Policy"]
            assert "frame-ancestors http://localhost:5173" in csp
            assert "script-src 'self' 'wasm-unsafe-eval'" in csp
            assert "'unsafe-eval'" not in csp
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["Referrer-Policy"] == "no-referrer"
            assert "Set-Cookie" not in response.headers
        for path, headers, status in [
            ("/../private.txt", {}, 404),
            ("/", {}, 404),
            ("/index.html?secret=x", {}, 404),
            ("/index.html", {"Authorization": "Bearer canary"}, 403),
            ("/index.html", {"Cookie": "app=canary"}, 403),
        ]:
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(
                    urllib.request.Request(url + path, headers=headers), timeout=5
                )
            assert error.value.code == status
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    with pytest.raises(ValueError, match="hash"):
        module.create_server(tmp_path, 0)
