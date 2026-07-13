# ADR 0003: Transactional outbox dispatches ingestion work to Temporal

## Status

Accepted.

## Context

The API must create document versions and ingestion jobs without doing document processing inside an HTTP request. A queued job also must not depend on an in-memory publish step after commit, because process crashes, deploys, and network failures can lose work between database commit and workflow start.

The system needs a durable boundary between request-time control-plane writes and asynchronous ingestion execution.

## Decision

The API writes an `outbox_messages` row in the same database transaction that creates the document version, ingestion job, and initial job event.

An outbox relay process polls pending outbox messages, starts or cancels Temporal workflows, and marks the message `published` only after Temporal accepts the operation.

Temporal owns ingestion workflow execution. The worker executes activities that call application services for job-state transitions. Workflow code stays deterministic and does not import database infrastructure.

## Consequences

- A committed queued job has a durable dispatch record.
- Relay crashes are recoverable because pending messages remain in the database.
- Workflow starts and cancellations use deterministic workflow ID `ingestion-job-{job_id}`.
- Relay retries are safe because Temporal workflow identity is stable.
- Job state changes remain inspectable through `ingestion_job_events`.
- The API remains responsible for intent, not ingestion execution.
- The relay and worker become required local and production processes.

## Current Limitations

- The worker performs stub ingestion only.
- Object storage is a documented contract but not yet implemented.
- Trace context is preserved in outbox headers and Temporal workflow memo; automatic span continuation inside Temporal activities is not implemented yet.
