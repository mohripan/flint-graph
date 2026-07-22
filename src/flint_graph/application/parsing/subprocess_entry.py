import base64
import json
import sys

from pydantic import ValidationError

from flint_graph.application.parsing.errors import ParserError
from flint_graph.application.parsing.models import SourceMetadata
from flint_graph.application.parsing.parsers import parse_normalized_document


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        content = base64.b64decode(request["content_b64"])
        metadata = SourceMetadata.model_validate(request["metadata"])
        artifact = parse_normalized_document(content, metadata=metadata)
    except (KeyError, ValueError, ValidationError, ParserError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(artifact.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
