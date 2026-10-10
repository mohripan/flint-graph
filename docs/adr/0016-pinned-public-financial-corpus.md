# ADR 0016: pinned financial excerpts with a separate answer boundary

Status: accepted for public corpus collection. Date: 2026-10-10.
Tracking: [#54](https://github.com/mohripan/flint-graph/issues/54),
[#53](https://github.com/mohripan/flint-graph/issues/53).

The user selected business and financial reports for realistic corpus growth.
Choose the official [FinQA release](https://github.com/czyssrs/FinQA), pinned to
`0f16e2867befa6840783e58be38c9efb9229d742`. Download only `LICENSE`,
`dataset/dev.json`, and `dataset/test.json`. Their sizes and Git blob IDs are
independently pinned in code. Do not fetch training/private-test data, run
downloaded code, or download inference models.

Render evidence from `pre_text`, `table`, and `post_text` only. Company, report
year and page identify each excerpt. Preserve questions, programs, answers and
retriever annotations in separate raw/annotation artifacts, never uploadable
evidence. Deduplicate identical rendered evidence by SHA-256, without collapsing
different text from the same report page. Re-verification checks pinned raw bytes
and re-renders evidence, not merely hashes from an editable local manifest.

Collection is bounded, HTTPS-only to a fixed host/path set, redirect-free and
non-overwriting. Downloaded artifacts stay outside Git; completed manifests
record source/file hashes, counts and original example identities. An explicit
evidence-only export produces at most 100 files for existing public-API corpus
preparation in a dedicated evaluation workspace. Collection/export never uploads
or runs inference. Failures leave inspectable partial artifacts; no implicit
cleanup deletes user data.

The [release license](https://github.com/czyssrs/FinQA/blob/0f16e2867befa6840783e58be38c9efb9229d742/LICENSE)
is MIT, Copyright (c) 2021 Zhiyu Chen. Preserve the notice and license. Original
issuer report rights are not relabeled; these are historical benchmark excerpts,
not complete annual reports or current financial advice. Public benchmark/model
training contamination limits quality claims. Production redistribution rights,
fresh issuer filings, reviewed gold suites, and 10k/100k/1M-chunk scale tests
remain separate work.
