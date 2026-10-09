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

## Tailwind build-tool migration

[Issue #23](https://github.com/mohripan/flint-graph/issues/23) replaces Tailwind 3's
PostCSS/glob dependency chain with Tailwind 4.3's Vite integration. The existing
brand theme is explicitly loaded; neutral colors, form placeholders, border
defaults, pointer behavior, shadows and keyboard focus appearance are preserved.
A duplicate logo-size class was removed to retain the original desktop header
height after utility-order changes. Locked installation, six frontend tests,
TypeScript, build and the **full** `npm audit` now pass with zero advisories.

The supported browser floor is now Safari 16.4+, Chrome 111+, Firefox 128+, as
required by Tailwind 4. Older browser support is not promised. See the official
[upgrade guide](https://tailwindcss.com/docs/upgrade-guide) and
[Vite integration](https://tailwindcss.com/docs/installation/using-vite).

Desktop/narrow-screen screenshot and computed-layout comparisons are part of
the migration verification. The baseline already had a fixed-width sidebar that
crowds/overflows mobile; responsive shell repair is separate follow-up work, not
a security migration acceptance claim.
