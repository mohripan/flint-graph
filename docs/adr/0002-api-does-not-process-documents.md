# ADR 0002: API processes never perform document ingestion

## Status

Accepted.

## Decision

The API records intent and durable state, then emits work for ingestion workers. Parsing, extraction, embedding, graph mutation, and indexing never execute inside an HTTP request process.

## Why

Ingestion is slow, failure-prone, retryable, and resource intensive. Keeping it outside FastAPI prevents request timeouts, duplicate side effects, and capacity coupling.

## Consequences

The current foundation stops at a queued ingestion job. The next stage introduces workflow orchestration and an outbox-backed dispatch path.
