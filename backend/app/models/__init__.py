"""SQLAlchemy models — one per table in docs/01-architecture.md §8, plus three §8 does not have.

Importing this package registers every model on ``Base.metadata``. ``alembic/env.py`` imports it
for exactly that side effect, so a table added to a module below and re-exported here is picked up
by ``--autogenerate`` without anyone having to remember it. A model not re-exported here is a
table that silently never migrates.

**Three shapes carry the requirements that would otherwise be honour-system:**

* ``findings`` is append-only and every row is stamped with ``rulepack_version`` (CLAUDE.md §3.6),
  so a report regenerated a year later reproduces the verdict issued under the rules in force at
  scan time. ``scan_evaluations`` groups those rows into revisions and remembers which pack, which
  checksum and which ``as_of`` each revision used.
* ``audit_log`` is hash-chained — ``hash = H(prev_hash || row)`` — so a report can be shown to be
  unaltered after issue (architecture §10). Its integer primary key gives the chain its order.
* **Every org-owned table carries ``org_id``**, including the ones that hang off a scan and could
  have reached it by a join. Enforcement lives in ``app/repositories/`` (CLAUDE.md §3.7); the
  composite foreign keys back to ``scans (id, org_id)`` are what stop the denormalised copy ever
  disagreeing with the original.

Three tables are not in architecture §8 and were approved as deviations: ``scan_evaluations``
(above), and ``otp_requests`` / ``refresh_tokens``, which hold auth state §8 never described. §8
has been updated to match.
"""

from __future__ import annotations

from app.models.audit import GENESIS_HASH, AuditLogEntry
from app.models.auth import OtpRequest, RefreshToken
from app.models.base import EMBEDDING_DIMENSIONS, Base
from app.models.bis import BIS_SOURCE_TYPES, BisChunk, BisDocument, BisQuery
from app.models.catalog import PACK_TYPES, SURFACES, Product, RulePackRow
from app.models.evidence import EXTRACTION_SOURCES, FIELD_CODES, Extraction, Measurement
from app.models.finding import EVALUATION_SOURCES, VERDICTS, Finding, ScanEvaluation
from app.models.org import ORG_MODES, USER_ROLES, Org, User
from app.models.report import Report
from app.models.scan import ASSET_KINDS, MARKER_TYPES, SCAN_STATUSES, OCRResult, Scan, ScanAsset

__all__ = [
    "ASSET_KINDS",
    "BIS_SOURCE_TYPES",
    "EMBEDDING_DIMENSIONS",
    "EVALUATION_SOURCES",
    "EXTRACTION_SOURCES",
    "FIELD_CODES",
    "GENESIS_HASH",
    "MARKER_TYPES",
    "ORG_MODES",
    "PACK_TYPES",
    "SCAN_STATUSES",
    "SURFACES",
    "USER_ROLES",
    "VERDICTS",
    "AuditLogEntry",
    "Base",
    "BisChunk",
    "BisDocument",
    "BisQuery",
    "Extraction",
    "Finding",
    "Measurement",
    "OCRResult",
    "Org",
    "OtpRequest",
    "Product",
    "RefreshToken",
    "Report",
    "RulePackRow",
    "Scan",
    "ScanAsset",
    "ScanEvaluation",
    "User",
]
