# Milestone 22: production hardening

Status: in progress. Tracking: [issue #8](https://github.com/mohripan/flint-graph/issues/8).
Full acceptance criteria are in the [roadmap](../ROADMAP.md).

## Frontend dependency audit

[Issue #22](https://github.com/mohripan/flint-graph/issues/22) applies compatible
lockfile updates without forcing a Tailwind major migration. The installed
development-toolchain audit decreased from 12 advisories (8 high, 4 moderate) to
7 (5 high, 2 moderate). Locked installation, outcome tests, TypeScript and the
production build pass; `npm audit --omit=dev` reports zero vulnerabilities.

The remaining advisories involve Tailwind 3's glob/selector dependencies. A clean
runtime-dependency audit does not remove CI/build-tool exposure to hostile
patterns or CSS. A tested toolchain migration is tracked separately; this
milestone is not complete and the full dependency audit is not clean.
