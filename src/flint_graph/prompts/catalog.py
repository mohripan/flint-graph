"""Immutable, typed prompt entries with exact UTF-8 identity."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

_VARIABLE = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
_NAME = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")
MAX_TEMPLATE_BYTES = 256 * 1024


class PromptError(ValueError):
    """Only a stable code, never values or remote response bodies."""


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _local_references(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(item, str) or not item.startswith("#")
            ):
                raise PromptError("external_schema_reference")
            _local_references(item)
    elif isinstance(value, list):
        for item in value:
            _local_references(item)


@dataclass(frozen=True)
class PromptEntry:
    # Encoded data prevents a caller mutating a shared schema/config/template.
    _encoded: bytes

    @classmethod
    def create(
        cls,
        *,
        name: str,
        template: str | list[dict[str, str]],
        catalog_version: int,
        variables_schema: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        langfuse_version: int = 1,
        kind: str = "prompt",
        legacy_version: str | None = None,
    ) -> "PromptEntry":
        if (
            not isinstance(name, str)
            or not _NAME.fullmatch(name)
            or type(catalog_version) is not int
            or catalog_version < 1
        ):
            raise PromptError("invalid_entry")
        if (
            type(langfuse_version) is not int
            or langfuse_version < 1
            or not isinstance(kind, str)
            or kind not in {"prompt", "policy"}
        ):
            raise PromptError("invalid_entry")
        if len(canonical(template)) > MAX_TEMPLATE_BYTES:
            raise PromptError("template_too_large")
        if isinstance(template, list):
            if not template or any(
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message["role"] not in {"system", "user", "assistant"}
                or not isinstance(message["content"], str)
                for message in template
            ):
                raise PromptError("invalid_chat_template")
            texts = [message["content"] for message in template]
        elif isinstance(template, str):
            texts = [template]
        else:
            raise PromptError("invalid_template")
        schema = variables_schema or {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
        if not isinstance(schema, dict) or (
            output_schema is not None and not isinstance(output_schema, dict)
        ):
            raise PromptError("invalid_schema")
        _local_references(schema)
        _local_references(output_schema)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError:
            raise PromptError("invalid_variable_schema") from None
        names = {name for text in texts for name in _VARIABLE.findall(text)}
        if (
            schema.get("type") != "object"
            or schema.get("additionalProperties") is not False
            or names != set(schema.get("properties", {}))
            or names != set(schema.get("required", []))
        ):
            raise PromptError("variable_schema_mismatch")
        if output_schema is not None:
            try:
                Draft202012Validator.check_schema(output_schema)
            except SchemaError:
                raise PromptError("invalid_output_schema") from None
        if config is not None and not isinstance(config, dict):
            raise PromptError("invalid_config")
        if name == "narrative.image.content_policy":
            policy_schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["version", "negative", "blocked"],
                "properties": {
                    "version": {"const": 1, "type": "integer"},
                    **{
                        key: {
                            "type": "array",
                            "maxItems": 256,
                            "items": {"type": "string", "minLength": 1, "maxLength": 240},
                        }
                        for key in ("negative", "blocked")
                    },
                },
            }
            try:
                Draft202012Validator(policy_schema).validate(config)
            except ValidationError:
                raise PromptError("invalid_policy_config") from None
        if name == "narrative.image.conditioning":
            maps = {"CHARACTER_TYPES", "TYPE_NEGATIVES", "EXPRESSION_TAGS", "FRAMING_TAGS"}
            lists = {"SHORT_LENGTHS", "LONG_LENGTHS"}
            strings = {
                "BACKGROUND_PEOPLE_NEGATIVE",
                "BACKGROUND_QUALITY",
                "CUTOUT_NEGATIVE",
                "CUTOUT_TAGS",
                "EXPRESSION_QUALITY",
                "LONG_HAIR_NEGATIVE",
                "QUALITY",
                "QUALITY_NEGATIVE",
            }
            if not isinstance(config, dict) or set(config) != maps | lists | strings:
                raise PromptError("invalid_conditioning_config")
            text_schema = {"type": "string", "maxLength": 4096}
            try:
                for key in strings:
                    Draft202012Validator(text_schema).validate(config[key])
                for key in lists:
                    Draft202012Validator(
                        {"type": "array", "maxItems": 256, "items": text_schema}
                    ).validate(config[key])
                for key in maps:
                    Draft202012Validator(
                        {"type": "object", "maxProperties": 64, "additionalProperties": text_schema}
                    ).validate(config[key])
                if set(config["EXPRESSION_TAGS"]) != {
                    "angry",
                    "crying",
                    "determined",
                    "embarrassed",
                    "happy",
                    "laughing",
                    "sad",
                    "sleepy",
                    "smug",
                    "surprised",
                    "thinking",
                    "worried",
                }:
                    raise PromptError("invalid_conditioning_config")
                characters = {"boy", "girl", "man", "woman", "other"}
                if (
                    set(config["CHARACTER_TYPES"]) != characters
                    or set(config["TYPE_NEGATIVES"]) != characters
                    or set(config["FRAMING_TAGS"]) != {"portrait", "full_body"}
                ):
                    raise PromptError("invalid_conditioning_config")
            except ValidationError:
                raise PromptError("invalid_conditioning_config") from None
        if name == "narrative.image.scene_conditioning":

            def string_map_schema(keys: set[str]) -> dict[str, Any]:
                return {
                    "type": "object",
                    "additionalProperties": False,
                    "required": sorted(keys),
                    "properties": {key: {"type": "string", "maxLength": 4096} for key in keys},
                }

            properties = {
                "quality": {"type": "string", "minLength": 1, "maxLength": 4096},
                "solo_negatives": string_map_schema({"boy", "girl", "man", "woman", "other"}),
                **{
                    key: string_map_schema({"boy", "girl"})
                    for key in ("pair_absent", "pair_single", "pair_double")
                },
            }
            try:
                Draft202012Validator(
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": sorted(properties),
                        "properties": properties,
                    }
                ).validate(config)
            except ValidationError:
                raise PromptError("invalid_scene_conditioning_config") from None
        data = {
            "name": name,
            "kind": kind,
            "type": "text" if isinstance(template, str) else "chat",
            "catalog_version": catalog_version,
            "langfuse_version": langfuse_version,
            "template": template,
            "variables_schema": schema,
            "output_schema": output_schema,
            "config": config or {},
            "legacy_version": legacy_version,
        }
        return cls(canonical(data))

    @property
    def data(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self._encoded)
        return value

    @property
    def name(self) -> str:
        return str(self.data["name"])

    @property
    def config(self) -> dict[str, Any]:
        value: dict[str, Any] = self.data["config"]
        return value

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self._encoded).hexdigest()

    def identity(self, effective_config: dict[str, Any] | None = None) -> dict[str, Any]:
        data = self.data
        template = data["template"]
        return {
            "name": self.name,
            "catalog_version": data["catalog_version"],
            "langfuse_version": data["langfuse_version"],
            "entry_sha256": self.sha256,
            "template_sha256": hashlib.sha256(template.encode("utf-8")).hexdigest()
            if isinstance(template, str)
            else digest(template),
            "schema_sha256": digest([data["variables_schema"], data["output_schema"]]),
            "config_sha256": digest(data["config"]),
            "effective_config_sha256": digest(effective_config or data["config"]),
        }

    def render(self, **variables: Any) -> str | list[dict[str, str]]:
        data = self.data
        try:
            Draft202012Validator(data["variables_schema"]).validate(variables)
        except (ValidationError, ValueError, TypeError):
            raise PromptError("invalid_variables") from None

        def substitute(text: str) -> str:
            return _VARIABLE.sub(lambda match: str(variables[match[1]]), text)

        template = data["template"]
        if isinstance(template, str):
            return substitute(template)
        return [
            {"role": message["role"], "content": substitute(message["content"])}
            for message in template
        ]
