# Negative anatomy regression

The creator identified a missing second leg and an unfinished trouser contour in
this synthetic Aster pose. The same seed, reference and stored prompt reproduce
the defect before cutout. `cases.json` records the immutable source hash and manual
label. This is a negative quality case, not a positive training image or automatic
anatomy detector. The corresponding owned QA asset is marked flawed through the
normal review API, which excludes its bytes from later training in that project.

See [seated pose guidance](../../../docs/reports/2026-11-02-seated-pose-guidance.md)
for the model change, all sample outcomes and limits.
