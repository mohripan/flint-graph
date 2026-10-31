"""Create private local-only Langfuse fixture settings. Never prints credentials."""

import argparse
import secrets
from pathlib import Path
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("notes/langfuse-local.env"))
    args = parser.parse_args()
    values = {
        "LF_" + key: secrets.token_hex(32)
        for key in (
            "POSTGRES_PASSWORD",
            "CLICKHOUSE_PASSWORD",
            "MINIO_PASSWORD",
            "REDIS_PASSWORD",
            "SALT",
            "ENCRYPTION_KEY",
            "NEXTAUTH_SECRET",
        )
    }
    values.update(
        {
            "LF_INIT_ORG_ID": "flint-local-authoring",
            "LF_INIT_ORG_NAME": "FlintGraph local",
            "LF_INIT_PROJECT_ID": "flint-prompt-catalog",
            "LF_INIT_PROJECT_NAME": "Reviewed generic prompts",
            "LF_INIT_PROJECT_PUBLIC_KEY": "pk-lf-" + str(uuid4()),
            "LF_INIT_PROJECT_SECRET_KEY": "sk-lf-" + secrets.token_hex(32),
            "LF_INIT_USER_EMAIL": "author@flint.local",
            "LF_INIT_USER_NAME": "Local prompt author",
            "LF_INIT_USER_PASSWORD": secrets.token_urlsafe(32),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write("".join(key + "=" + value + "\n" for key, value in values.items()))
    print(
        "Private local settings created for the isolated Langfuse compose stack."
    )


if __name__ == "__main__":
    main()
