"""PDF report rendering — TRD FR-27, package B11.

Two functions, split on purpose:

``render_html``
    Builds the complete document as HTML. Pure, deterministic, no native libraries, testable on
    any machine. Every content assertion in ``tests/test_reporting.py`` runs against this.

``render_pdf``
    Hands that HTML to WeasyPrint. This is the only step that needs the GTK3 native stack
    (pango, cairo, gdk-pixbuf), which is present on the Linux deploy VM and is usually absent on
    a Windows workstation.

The split means a missing GTK3 install costs you one skipped test rather than the ability to work
on reports at all. It also means the layout can be inspected in a browser during development,
which is considerably faster than rendering a PDF to look at it.

**Escaping.** Every interpolated value is escaped. The text in a report came off a photograph of
a package via OCR and possibly an LLM; it is untrusted input that ends up in a document somebody
opens.
"""

from __future__ import annotations

from html import escape

from app.services.reporting.model import ADVISORY_DISCLAIMER, ReportData, ReportFinding

_STYLESHEET = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm;
        @bottom-center { content: "Page " counter(page) " of " counter(pages);
                         font-size: 8pt; color: #666; } }
body { font-family: "DejaVu Sans", "Noto Sans", sans-serif; font-size: 9.5pt; color: #111;
       line-height: 1.45; }
h1 { font-size: 16pt; margin: 0 0 2mm 0; }
h2 { font-size: 11pt; margin: 7mm 0 2mm 0; border-bottom: 0.4pt solid #bbb;
     padding-bottom: 1mm; }
.sub { color: #555; font-size: 9pt; margin: 0 0 5mm 0; }
table { width: 100%; border-collapse: collapse; margin-top: 2mm; }
th, td { border: 0.4pt solid #bbb; padding: 1.6mm 2mm; text-align: left;
         vertical-align: top; font-size: 8.5pt; }
th { background: #f2f2f2; font-weight: 600; }
.meta td { border: none; padding: 0.8mm 0; font-size: 9pt; }
.meta td:first-child { color: #555; width: 38mm; }
.v { font-weight: 700; white-space: nowrap; }
.v-FAIL { color: #a11; }
.v-BORDERLINE { color: #a60; }
.v-NOT_ASSESSABLE { color: #555; }
.v-PASS { color: #161; }
.cite { color: #444; font-size: 7.5pt; font-style: italic; }
.hash { font-family: "DejaVu Sans Mono", monospace; font-size: 7pt; word-break: break-all; }
.summary span { display: inline-block; margin-right: 6mm; font-size: 9.5pt; }
.disclaimer { margin-top: 7mm; padding: 3mm; background: #f7f7f7;
              border-left: 1.2pt solid #999; font-size: 8pt; color: #333; }
.na { font-size: 8pt; color: #555; }
img.annotated { max-width: 100%; border: 0.4pt solid #bbb; margin-top: 2mm; }
"""


def _summary_row(data: ReportData) -> str:
    order = (
        ("fail", "Fail"),
        ("borderline", "Borderline"),
        ("na", "Not assessable"),
        ("pass", "Pass"),
        ("not_applicable", "Not applicable"),
    )
    return "".join(
        f"<span><strong>{data.summary.get(key, 0)}</strong> {escape(label)}</span>"
        for key, label in order
    )


def _finding_row(finding: ReportFinding) -> str:
    observed = escape(finding.observed) if finding.observed else "—"
    required = escape(finding.required) if finding.required else "—"
    band = (
        f'<div class="cite">measured band {escape(finding.band)}</div>' if finding.band else ""
    )
    # data-rule / data-verdict are machine-readable anchors: the drift test reads verdicts back
    # out of the rendered HTML and compares them against the DOCX table.
    return (
        f'<tr data-rule="{escape(finding.rule_id)}" data-verdict="{escape(finding.verdict)}">'
        f"<td>{escape(finding.rule_id)}</td>"
        f'<td class="v v-{escape(finding.verdict)}">{escape(finding.verdict_label)}</td>'
        f"<td>{observed}{band}</td>"
        f"<td>{required}</td>"
        f"<td>{escape(finding.message)}"
        f'<div class="cite">{escape(finding.citation)}</div></td>'
        "</tr>"
    )


def _metadata_table(data: ReportData) -> str:
    meta = data.metadata
    rows: list[tuple[str, str]] = [
        ("Scan ID", meta.scan_id),
        ("Product", meta.product_name or "—"),
        ("Organisation", meta.org_name),
        ("Mode", meta.mode),
        ("Captured", meta.captured_at.isoformat()),
        ("Report generated", meta.generated_at.isoformat()),
        ("Rule pack", meta.rulepack_version),
    ]
    if meta.inspector_name:
        rows.append(("Inspector", meta.inspector_name))
    if meta.location:
        rows.append(("Location", meta.location))

    body = "".join(
        f"<tr><td>{escape(label)}</td><td>{escape(value)}</td></tr>" for label, value in rows
    )
    body += (
        f'<tr><td>Image SHA-256</td><td class="hash">{escape(meta.image_sha256)}</td></tr>'
        f'<tr><td>Findings SHA-256</td><td class="hash">{escape(meta.findings_sha256)}</td></tr>'
    )
    return f'<table class="meta">{body}</table>'


def render_html(data: ReportData) -> str:
    """Render the report as a complete HTML document.

    Pure and deterministic: the same ``ReportData`` produces byte-identical HTML, which is what
    lets the report be hashed and the hash be meaningful.
    """
    findings_rows = "".join(_finding_row(finding) for finding in data.findings)

    not_applicable = ""
    if data.not_applicable_rule_ids:
        # Named, not omitted. Silence about a skipped rule reads as "we checked and it was fine"
        # (docs/decisions.md, 2026-09-12).
        listed = ", ".join(escape(rule_id) for rule_id in data.not_applicable_rule_ids)
        not_applicable = (
            "<h2>Rules that did not apply to this product</h2>"
            f'<p class="na">These rules were not evaluated because their conditions were not '
            f"met by this product, or because they are not yet in force at the date of this "
            f"scan. They are neither passes nor failures: {listed}.</p>"
        )

    image_block = ""
    if data.annotated_image_png is not None:
        import base64

        encoded = base64.b64encode(data.annotated_image_png).decode("ascii")
        image_block = (
            "<h2>Annotated evidence</h2>"
            f'<img class="annotated" src="data:image/png;base64,{encoded}" alt="Annotated label"/>'
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Compliance report {escape(data.metadata.scan_id)}</title>
<style>{_STYLESHEET}</style></head><body>
<h1>Packaged commodity compliance report</h1>
<p class="sub">Legal Metrology (Packaged Commodities) Rules, 2011 &middot;
rule pack {escape(data.metadata.rulepack_version)}</p>

<h2>Scan details</h2>
{_metadata_table(data)}

<h2>Summary</h2>
<p class="summary">{_summary_row(data)}</p>

<h2>Findings</h2>
<table><thead><tr>
<th style="width:26%">Rule</th><th style="width:13%">Verdict</th>
<th style="width:14%">Observed</th><th style="width:12%">Required</th><th>Detail</th>
</tr></thead><tbody>{findings_rows}</tbody></table>

{not_applicable}
{image_block}

<div class="disclaimer">{escape(ADVISORY_DISCLAIMER)}</div>
</body></html>"""


def render_pdf(data: ReportData) -> bytes:
    """Render the report as a PDF.

    Requires WeasyPrint and its GTK3 native stack. Imported lazily so that importing this module
    — and rendering the HTML — works on a machine without those libraries.

    Raises:
        ReportRenderingError: WeasyPrint or its native dependencies are unavailable.
    """
    try:
        from weasyprint import HTML
    except Exception as exc:  # OSError from the native loader, or ImportError
        raise ReportRenderingError(
            "PDF rendering needs WeasyPrint and the GTK3 native stack (pango, cairo, "
            "gdk-pixbuf). On Debian/Ubuntu: apt install libpango-1.0-0 libpangoft2-1.0-0 "
            "libcairo2 libgdk-pixbuf-2.0-0. See backend/README.md."
        ) from exc

    rendered: bytes | None = HTML(string=render_html(data)).write_pdf()
    if rendered is None:  # pragma: no cover - WeasyPrint returns bytes when no target is given
        raise ReportRenderingError("WeasyPrint returned no PDF bytes")
    return rendered


class ReportRenderingError(RuntimeError):
    """A report could not be rendered in the requested format."""


__all__ = ["ReportRenderingError", "render_html", "render_pdf"]
