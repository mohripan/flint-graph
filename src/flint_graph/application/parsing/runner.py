from __future__ import annotations

import base64
import json
import subprocess
import sys

from pydantic import ValidationError

from flint_graph.application.parsing.errors import (
    ParserExecutionError,
    ParserLimitError,
)
from flint_graph.application.parsing.models import (
    NormalizedDocument,
    ParserLimits,
    SourceMetadata,
)


class BoundedParserRunner:
    def __init__(self, *, limits: ParserLimits) -> None:
        self._limits = limits

    def parse(self, content: bytes, *, metadata: SourceMetadata) -> NormalizedDocument:
        if len(content) > self._limits.max_raw_bytes:
            raise ParserLimitError("Raw source exceeds parser byte limit.")

        request = {
            "content_b64": base64.b64encode(content).decode("ascii"),
            "metadata": metadata.model_dump(mode="json"),
        }
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "flint_graph.application.parsing.subprocess_entry",
                ],
                input=json.dumps(request),
                capture_output=True,
                text=True,
                timeout=self._limits.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ParserLimitError("Parser subprocess timed out.") from exc

        if completed.returncode != 0:
            raise ParserExecutionError(completed.stderr.strip() or "Parser subprocess failed.")

        output = completed.stdout.encode("utf-8")
        if len(output) > self._limits.max_normalized_bytes:
            raise ParserLimitError("Normalized parser output exceeds byte limit.")

        try:
            artifact = NormalizedDocument.model_validate_json(completed.stdout)
        except ValidationError as exc:
            raise ParserExecutionError("Parser subprocess returned invalid artifact JSON.") from exc

        if len(artifact.elements) > self._limits.max_elements:
            raise ParserLimitError("Normalized artifact exceeds element limit.")
        return artifact
