"""JSON report rendering — TRD FR-27, package B11.

The machine-readable third format. Two callers matter: the mobile app, which renders the findings
screen, and whatever hashes the report — which is why ``render_json`` is canonical and
byte-stable. A serialisation that reorders keys between runs makes the SHA-256 in the report
header meaningless.

Renders from the same ``ReportData`` as the PDF and the DOCX.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.reporting.model import ADVISORY_DISCLAIMER, ReportData


def render_dict(data: ReportData) -> dict[str, Any]:
    """Build the report as a plain dictionary."""
    meta = data.metadata
    return {
        "metadata": {
            "scan_id": meta.scan_id,
            "product_name": meta.product_name,
            "org_name": meta.org_name,
            "mode": meta.mode,
            "captured_at": meta.captured_at.isoformat(),
            "generated_at": meta.generated_at.isoformat(),
            "rulepack_version": meta.rulepack_version,
            "image_sha256": meta.image_sha256,
            "findings_sha256": meta.findings_sha256,
            "inspector_name": meta.inspector_name,
            "location": meta.location,
        },
        "summary": dict(data.summary),
        "findings": [
            {
                "rule_id": finding.rule_id,
                "verdict": finding.verdict,
                "severity": finding.severity,
                "citation": finding.citation,
                "message": finding.message,
                "observed": finding.observed,
                "required": finding.required,
                "band": finding.band,
            }
            for finding in data.findings
        ],
        "not_applicable_rule_ids": list(data.not_applicable_rule_ids),
        "disclaimer": ADVISORY_DISCLAIMER,
    }


def render_json(data: ReportData) -> str:
    """Render the report as canonical JSON.

    Sorted keys, fixed separators, UTF-8 preserved. Byte-stable across runs and across Python
    versions, so a hash taken over this output means something a year later.
    """
    return json.dumps(
        render_dict(data),
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        separators=(",", ": "),
    )


__all__ = ["render_dict", "render_json"]
