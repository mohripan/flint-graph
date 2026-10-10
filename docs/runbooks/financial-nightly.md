# Fresh financial black-box gate

Tracking: [#53](https://github.com/mohripan/flint-graph/issues/53).
See [ADR 0018](../adr/0018-fresh-public-financial-nightly-gate.md).

Use a dedicated workspace containing exactly the first 100 pinned FinQA evidence
excerpts, prepared/verified as described in [the corpus runbook](financial-corpus.md).
Use a separate workspace in which the same caller has membership for genuine
tenant 404 checks. Never upload customer documents into the evaluation workspace.

```powershell
uv run flint-graph-eval nightly --dataset evals/datasets/financial-nightly --corpus notes/finqa-public-0f16e286 --manifest notes/finqa-batch-0-verified-manifest.json --base-url http://localhost:8000 --isolation-workspace-id <UUID> --inspect --output notes/nightly-inspection.json
```

Inspection performs GET requests only and reports `inspected_not_evaluated`.
Review its model fingerprint; pass it as `--model-fingerprint <SHA256>` in place
of `--inspect` to execute fresh queries, using a new output file. The API must
advertise `query_usage_rollups` and expose actual per-run provider tokens.
`FLINT_GRAPH_EVAL_TOKEN` supplies a bearer token where OIDC is configured.
HTTP is allowed only for credential-free loopback URLs; remote access needs HTTPS.

The checked-in 12-case suite covers factual figures, arithmetic, two-source
synthesis, forecasts, ambiguous wording and absent future data. Rubrics were
checked against pinned DVN/2007/page_58, PM/2017/page_38 and V/2008/page_17
evidence, not generated answers. The American Express average is 637/5 = 127.4
dollars, matching FinQA's separate expert annotation. External human review is
pending. Numeric normalization accepts formatted/equivalent literals without
converting units automatically; these assertions cannot detect every contradiction.

Rubric review #71 adds only the explicit source-used plural `rrps` to the two
RRP concept groups; it does not add general stemming or change numeric groups.
Reports emitted by the updated client use `format_version: 2` and include
`dataset_name`, `dataset_version`, `rubric_fingerprint` and `policy_fingerprint`.
Fingerprints hash canonical, sorted-key JSON of the validated rubric mapping and
policy. Compare them before comparing scores: a new rubric is a scoring revision,
not an answer-model improvement. Corpus dataset/version and existing recordings
are unchanged. Older format-1 reports have no rubric/policy attestation; do not
backfill those fields or overwrite recordings. External human review remains pending.

`policy.json` specifies useful-answer rate >=0.8, abstention accuracy 1.0 and
p95 latency <=90 seconds. Every non-abstained answer needs supported claims,
no partial/unsupported claims and valid citations. Do not silently update this
policy or accepted baselines from a new recording. Incomplete reports remain
failed and any available aggregate describes only captured cases.

## GitHub activation

`.github/workflows/live-eval.yml` runs nightly at 02:17 Asia/Jakarta and manually,
with serialized concurrency and a 30-minute job ceiling. It downloads and verifies
pinned public sources, then queries an existing authorized HTTPS deployment.
It does not upload or backfill documents. GitHub-hosted runners cannot reach this
machine's localhost services.

Configure secrets `FLINT_GRAPH_EVAL_BASE_URL`, `FLINT_GRAPH_EVAL_TOKEN` and
`FLINT_GRAPH_EVAL_MANIFEST` (prepared JSON). Configure variables
`FLINT_GRAPH_EVAL_ISOLATION_WORKSPACE`, `FLINT_GRAPH_EVAL_MODEL_FINGERPRINT`, then
explicitly enable `FLINT_GRAPH_RUN_LIVE_EVAL=true`. Disabled configuration is
reported as `UNCONFIGURED`; the evaluation job is skipped, not a quality pass.
Only `notes/nightly-report.json` is uploaded, retained seven days, including
failed quality reports. Configuration failures before capture may have no artifact.

No reachable remote evaluation deployment or secrets are currently configured.
Do not configure public tunnels, runners, paid providers or notification recipients
without the necessary operator choices. Local manual verification is available.
