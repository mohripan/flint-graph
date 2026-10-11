"""Governance asset checks, not an assertion that attack defenses are implemented."""

import json
import re
from pathlib import Path


def test_redacted_attack_catalog_covers_documented_risks_without_claiming_runtime_acceptance():
    catalog = json.loads(Path("tests/fixtures/security/agent-threat-cases.json").read_text("utf-8"))
    design = Path("docs/architecture/agent-threat-model.md").read_text("utf-8")
    assert catalog["schema_version"] == 1
    assert catalog["classification"] == "synthetic-public-no-secrets"
    assert catalog["runtime_qualification"] == "not-attested"
    cases = catalog["cases"]
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["risk_id"] for case in cases} == set(re.findall(r"^\| (FG-\d\d) \|", design, re.M))
    for case in cases:
        assert case["expected_outcome"] in {
            "deny",
            "abstain",
            "clarify",
            "display_as_text",
            "bound_and_stop",
        }
        assert case["payload"] and case["boundary"] and case["observable_assertion"]
        assert case["acceptance_status"] == "required-not-attested"
        assert "@" not in case["payload"]
        assert "https://" not in case["payload"] or "https://sink.invalid/" in case["payload"]
        assert case["remediation_issue"] > 0
