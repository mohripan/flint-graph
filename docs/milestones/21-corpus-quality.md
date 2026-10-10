# Milestone 21: corpus and graph quality

Status: in progress. Tracking: [#7](https://github.com/mohripan/flint-graph/issues/7).

[#54](https://github.com/mohripan/flint-graph/issues/54) implements bounded pinned
public financial-report collection, evidence-only rendering/deduplication,
source integrity and provenance, separate annotations, offline verification,
and explicit <=100-document ingestion-dataset export. No downloaded data is
committed. See [ADR 0016](../adr/0016-pinned-public-financial-corpus.md) and the
[runbook](../runbooks/financial-corpus.md).

The real download yielded 679 distinct excerpts / 2,030 examples / 409 company-year
reports. Initial 100-file live preparation revealed tenant-unique evidence ID
collisions between different document versions; [#55](https://github.com/mohripan/flint-graph/issues/55)
tracks that ingestion blocker. Download/export success is not completed ingestion
or answer-quality proof. Reviewed financial black-box cases are tracked in #53.

#55 implements immutable-version evidence identity and savepoint-protected
failure/retry recording. The real retry completed all 100 document versions and
coverage rows. Per-document projection probes then exposed a separate narrow
vector-filter recall issue, tracked in [#56](https://github.com/mohripan/flint-graph/issues/56).
The bounded preparation helper was stopped after those checks; indexed data and
the original failed workspace were preserved. Neither issue is closed until its
required live verification is complete.
Extraction-quality audits, independent fresh issuer datasets, large-corpus scale,
and the milestone's remaining graph-quality criteria are not completed here.
