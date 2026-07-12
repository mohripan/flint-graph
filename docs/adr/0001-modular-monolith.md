# ADR 0001: Begin as a modular monolith

## Status

Accepted.

## Decision

AtlasRAG begins as one Python distribution with explicit domain, application, API, and infrastructure boundaries. It is deployed as independently scalable processes when needed, rather than split into separate repositories or network services immediately.

## Why

Distributed ingestion already introduces queues, databases, workers, retries, and failure modes. Premature service decomposition would add network contracts and deployment overhead before workload boundaries are measured.

## Consequences

- Modules must not bypass their intended boundaries.
- Workers can later be extracted without rewriting domain contracts.
- Architecture tests will eventually enforce import rules.
