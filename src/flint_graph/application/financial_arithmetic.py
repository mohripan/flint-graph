"""Bounded, source-cited payments-table division; never evaluates source instructions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, Inexact, localcontext
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from flint_graph.application.query_orchestration import (
    AnswerClaim,
    PackedContextRecord,
    QueryContextPack,
)

ARITHMETIC_METHOD: Literal["cited-payments-ratio-v1"] = "cited-payments-ratio-v1"
_SCALES = {
    "thousand": Decimal(1000),
    "million": Decimal(1000000),
    "billion": Decimal(1000000000),
    "trillion": Decimal(1000000000000),
}
_NUMBER = r"(?:\d{1,3}(?:,\d{3}){1,5}|\d{1,18})(?:\.\d{1,12})?"
_CELL_NUMBER = re.compile(rf"\$?\s*(?P<number>{_NUMBER})")
_MONEY = re.compile(
    rf"\$\s*(?P<dollar>{_NUMBER})(?!\w|,\d|\.\d)"
    r"(?:\s+(?P<dollar_scale>thousand|million|billion|trillion)s?\b)?|"
    rf"(?<![\w.,])(?P<word>{_NUMBER})"
    r"(?:\s+(?P<word_scale>thousand|million|billion|trillion)s?)?\s+dollars?\b",
    re.IGNORECASE,
)
_REQUIRED = re.compile(r"\baverage\s+payments\s+volume\s+per\s+transaction\b", re.IGNORECASE)
_DERIVED = re.compile(r"\b(?:average|ratio|divid\w*)\b|\bper\s+transaction\b", re.IGNORECASE)
_NEGATED_RESULT = re.compile(r"\b(?:not|isn't|wasn't|aren't|weren't)\b", re.IGNORECASE)
_RESULT_END = re.compile(
    r"\s*(?:dollars?\b|USD\b)?\s*(?:per\s+transaction\b)?\s*[.!?]?\s*",
    re.IGNORECASE,
)


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=4000)


class CitedOperand(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: Decimal
    scale: Literal["thousand", "million", "billion", "trillion"]
    dimension: Literal["money", "transactions"]
    citation_id: str
    context_id: str
    source_ids: dict[str, str]
    chunk_hash: str
    value_span: EvidenceSpan
    unit_span: EvidenceSpan
    entity_span: EvidenceSpan


class CalculationCheck(BaseModel):
    model_config = ConfigDict(frozen=True)
    claim_index: int
    operation: Literal["divide"] = "divide"
    output_dimension: Literal["money_per_transaction"] = "money_per_transaction"
    operands: list[CitedOperand] = Field(default_factory=list, max_length=2)
    computed_value: str | None = None
    verified: bool = False
    reason: str = "financial_arithmetic_unverified"


class VerifiedCalculationHint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: Literal["cited-payments-ratio-v1"] = ARITHMETIC_METHOD
    operation: Literal["divide"] = "divide"
    output_dimension: Literal["money_per_transaction"] = "money_per_transaction"
    computed_value: str = Field(max_length=80, pattern=r"^\d+(?:\.\d+)?$")
    citation_id: str = Field(min_length=1, max_length=100)
    company: str = Field(min_length=1, max_length=120)


def prepare_verified_calculation(
    query: str, context_pack: QueryContextPack
) -> dict[str, Any] | None:
    if not _REQUIRED.search(query):
        return None
    operands = _unique_operands(query, context_pack.records)
    if operands is None or len(operands[0].entity_span.quote) > 120:
        return None
    computed = _compute_ratio(operands)
    if computed is None:
        return None
    with localcontext() as context:
        context.prec = 50
        return VerifiedCalculationHint(
            computed_value=format(computed.normalize(), "f"),
            citation_id=operands[0].citation_id,
            company=operands[0].entity_span.quote,
        ).model_dump(mode="json")


@dataclass(frozen=True)
class ArithmeticReview:
    claims: list[AnswerClaim]
    required: bool
    satisfied: bool
    metadata: dict[str, Any]


def review_financial_arithmetic(
    query: str,
    claims: list[AnswerClaim],
    context_pack: QueryContextPack,
    *,
    provider_claims: list[AnswerClaim] | None = None,
) -> ArithmeticReview:
    required = bool(_REQUIRED.search(query))
    if not required:
        return ArithmeticReview(claims, False, True, {})
    records = {record.citation_id: record for record in context_pack.records}
    checks: list[CalculationCheck] = []
    reviewed: list[AnswerClaim] = []
    derived_count = 0
    for claim in claims:
        if not _DERIVED.search(claim.text):
            reviewed.append(claim)
            continue
        derived_count += 1
        check = (
            _check_claim(query, claim, records)
            if derived_count <= 8
            else CalculationCheck(
                claim_index=claim.claim_index, reason="financial_arithmetic_limit"
            )
        )
        if derived_count <= 8:
            checks.append(check)
        reviewed.append(
            claim
            if check.verified
            else claim.model_copy(
                update={
                    "support_status": "unsupported",
                    "support_score": 0.0,
                    "support_reason": check.reason,
                    "method": ARITHMETIC_METHOD,
                }
            )
        )
    satisfied = (
        bool(checks)
        and derived_count <= 8
        and all(check.verified for check in checks)
        and all(
            claim.support_status == "supported" for claim in reviewed if _DERIVED.search(claim.text)
        )
    )
    return ArithmeticReview(
        reviewed,
        True,
        satisfied,
        {
            "method": ARITHMETIC_METHOD,
            "required": True,
            "satisfied": satisfied,
            "calculations": [check.model_dump(mode="json") for check in checks],
            "provider_judgments": [
                {
                    key: value
                    for key, value in claim.model_dump(mode="json").items()
                    if key not in {"text", "citation_ids"}
                }
                for claim in (provider_claims if provider_claims is not None else claims)
            ],
        },
    )


def _check_claim(
    query: str,
    claim: AnswerClaim,
    records: dict[str, PackedContextRecord],
) -> CalculationCheck:
    check = CalculationCheck(claim_index=claim.claim_index)
    operands = _unique_operands(
        query, [records[key] for key in claim.citation_ids if key in records]
    )
    if operands is None:
        return check
    computed = _compute_ratio(operands)
    if computed is None:
        return check.model_copy(update={"operands": operands})
    with localcontext() as context:
        context.prec = 50
        rendered = list(_MONEY.finditer(claim.text))
        # Atomic result claims only; no guessing which of several dollar amounts is the result.
        matched = False
        if len(rendered) == 1:
            amount = rendered[0]
            claimed = Decimal((amount["dollar"] or amount["word"]).replace(",", ""))
            scale = amount["dollar_scale"] or amount["word_scale"]
            if scale:
                claimed *= _SCALES[scale.casefold()]
            entity = r"\s+".join(re.escape(word) for word in operands[0].entity_span.quote.split())
            matched = (
                claimed == computed
                and bool(re.search(rf"(?<!\w){entity}(?!\w)", claim.text, re.IGNORECASE))
                and not _NEGATED_RESULT.search(claim.text)
                and bool(_RESULT_END.fullmatch(claim.text[amount.end() :]))
            )
        return check.model_copy(
            update={
                "operands": operands,
                "computed_value": format(computed.normalize(), "f"),
                "verified": matched,
                "reason": "financial_arithmetic_verified"
                if matched
                else "financial_arithmetic_result_mismatch",
            }
        )


def _unique_operands(query: str, records: list[PackedContextRecord]) -> list[CitedOperand] | None:
    pairs: dict[tuple[str, ...], list[CitedOperand]] = {}
    for record in records:
        if not _authoritative(record):
            continue
        for operands in _table_operands(record, query):
            key = (
                *(
                    record.source_ids[key]
                    for key in ("document_id", "document_version_id", "chunk_id")
                ),
                record.metadata["chunk_hash"],
                *(str(operand.value_span.start) for operand in operands),
            )
            pairs[key] = operands
    if len(pairs) != 1:
        return None
    return next(iter(pairs.values()))


def _compute_ratio(operands: list[CitedOperand]) -> Decimal | None:
    with localcontext() as context:
        context.prec = 50
        numerator = operands[0].value * _SCALES[operands[0].scale]
        denominator = operands[1].value * _SCALES[operands[1].scale]
        if numerator < 0 or denominator <= 0:
            return None
        computed = numerator / denominator
        return None if context.flags[Inexact] else computed


def _authoritative(record: PackedContextRecord) -> bool:
    return (
        record.metadata.get("evidence_origin") == "postgresql_chunk"
        and all(
            record.source_ids.get(key) for key in ("document_id", "document_version_id", "chunk_id")
        )
        and record.metadata.get("chunk_hash")
        == "sha256:" + hashlib.sha256(record.text.encode()).hexdigest()
    )


def _table_rows(text: str) -> list[list[EvidenceSpan]]:
    rows: list[list[EvidenceSpan]] = []
    cells: list[EvidenceSpan] = []
    for match in re.finditer(r"[^|]+", text):
        raw = match[0]
        if not raw.strip():
            if cells:
                rows.append(cells)
                cells = []
            continue
        start = match.start() + len(raw) - len(raw.lstrip())
        cells.append(EvidenceSpan(start=start, end=start + len(raw.strip()), quote=raw.strip()))
    if cells:
        rows.append(cells)
    return rows


def _table_operands(record: PackedContextRecord, query: str) -> list[list[CitedOperand]]:
    if not re.search(r"\bdollars?\b", query, re.IGNORECASE):
        return []
    header: list[EvidenceSpan] | None = None
    selections: list[tuple[int, str, Literal["money", "transactions"]]] = []
    pairs: list[list[CitedOperand]] = []
    for row in _table_rows(record.text):
        if row[0].quote.casefold() == "company":
            header = row
            selections = []
            for index, cell in enumerate(row):
                match = re.fullmatch(
                    r"(payments volume|total transactions)\s*\(\s*"
                    r"(thousand|million|billion|trillion)s?\s*\)",
                    cell.quote.casefold(),
                )
                if match:
                    selections.append(
                        (
                            index,
                            match[2],
                            "money" if match[1] == "payments volume" else "transactions",
                        )
                    )
            continue
        if (
            header is None
            or len(row) != len(header)
            or len(selections) != 2
            or {item[2] for item in selections} != {"money", "transactions"}
        ):
            continue
        entity = r"\s+".join(re.escape(word) for word in row[0].quote.split())
        # Source row identity must be the explicit subject, not merely the report owner.
        if not re.search(
            rf"(?<!\w){entity}['\u2019]s\s+average\s+payments\s+volume\s+"
            r"per\s+transaction\b",
            query,
            re.IGNORECASE,
        ):
            continue
        operands: list[CitedOperand] = []
        for index, scale, dimension in sorted(selections, key=lambda item: item[2]):
            match = _CELL_NUMBER.fullmatch(row[index].quote)
            if match is None:
                break
            operands.append(
                CitedOperand(
                    value=Decimal(match["number"].replace(",", "")),
                    scale=scale,
                    dimension=dimension,
                    citation_id=record.citation_id,
                    context_id=record.context_id,
                    source_ids=dict(record.source_ids),
                    chunk_hash=record.metadata["chunk_hash"],
                    value_span=row[index],
                    unit_span=header[index],
                    entity_span=row[0],
                )
            )
        if len(operands) == 2:
            pairs.append(operands)
    return pairs
