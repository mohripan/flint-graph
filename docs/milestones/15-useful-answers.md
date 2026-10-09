# Milestone 15: useful answers and explainable failures

Status: in progress. Tracking: [issue #1](https://github.com/mohripan/flint-graph/issues/1).
See the [roadmap](../ROADMAP.md) for the complete acceptance criteria.

## Verified claim policy

[Issue #10](https://github.com/mohripan/flint-graph/issues/10) fixes publication of
partially supported draft statements. Final verified output retains only claims
with a `supported` decision; partially supported and unsupported decisions remain
inspectable in the faithfulness report and persisted claim records. Their
citations are omitted from final output when no retained claim uses them.

An answer with zero supported claims abstains even if the configured minimum
supported-claim ratio is zero. Mixed drafts may retain fully supported facts if
the existing ratio policy passes. This is claim filtering, not yet the planned
question-coverage model for partial answers in Milestone 20.

Regression tests cover a correct headquarters claim alongside an office claim
with an unevidenced date/profitability, and zero-threshold abstention. Provider
support decisions are still the verification boundary; a deterministic lexical
checker is an offline fixture, not proof of production semantic accuracy.

## Offline OIDC integration harness

[Issue #11](https://github.com/mohripan/flint-graph/issues/11) makes the shared
OIDC fixture explicitly select deterministic extraction, embeddings, answers,
and support checking. It retains local OIDC behavior without requiring hosted
credentials or a developer `.env`. Production provider defaults are unchanged.
The original complete suite had 17 credential-validation failures in this
fixture; explicitly selecting offline providers resolves those failures.
