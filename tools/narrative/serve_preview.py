"""Serve one immutable trusted preview build on 127.0.0.1 only; never serve a repository root."""

import argparse
import hashlib
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def create_server(build: Path, port: int) -> ThreadingHTTPServer:
    build = build.resolve(strict=True)
    manifest = build / "preview-build.json"
    if manifest.stat().st_size > 1048576:
        raise ValueError("Invalid build manifest size")
    report = json.loads(manifest.read_bytes())
    parent = report["parent_origin"]
    parsed = urlsplit(parent)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "localhost"
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not parsed.port
    ):
        raise ValueError("Local parent must be an exact localhost origin")
    if (
        report["schema_version"] != "1"
        or not isinstance(report["files"], dict)
        or not 1 <= len(report["files"]) <= 20
    ):
        raise ValueError("Invalid file allowlist")
    public = (build / "web").resolve(strict=True)
    payloads: dict[str, tuple[bytes, str]] = {}
    total = 0
    for name, expected in report["files"].items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name) or name in {".", ".."}:
            raise ValueError("Invalid public name")
        path = public / name
        if (
            path.is_symlink()
            or path.resolve(strict=True).parent != public
            or not path.is_file()
            or path.stat().st_size > 50 * 1024 * 1024
        ):
            raise ValueError("Invalid public file")
        data = path.read_bytes()
        total += len(data)
        if total > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Invalid build file hash or total size")
        content_type = (
            "application/wasm"
            if name.endswith(".wasm")
            else mimetypes.guess_type(name)[0] or "application/octet-stream"
        )
        if name.endswith(".js"):
            content_type = "text/javascript"
        payloads["/" + name] = data, content_type

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass  # No source, credentials, nonce or query strings in server logs.

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            if self.headers.get("Authorization") or self.headers.get("Cookie"):
                self.send_error(403, "Credentials are not accepted")
                return
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":  # type: ignore[attr-defined]
                self.send_error(400, "Invalid host")
                return
            path = (
                self.path.removesuffix("?qa=1")
                if self.path.startswith("/index.html?")
                else self.path
            )
            if path not in payloads:
                self.send_error(404)
                return
            data, content_type = payloads[path]
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
            )
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; "
                "img-src 'self' data:; font-src 'self'; connect-src 'self'; worker-src 'none'; "
                "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors "
                + parent,
            )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    with create_server(args.build, args.port) as server:
        print(
            f"Trusted preview listening at http://127.0.0.1:{server.server_port}/index.html",
            flush=True,
        )
        server.serve_forever()


if __name__ == "__main__":
    main()
