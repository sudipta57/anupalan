"""Report generation — PDF, DOCX and JSON from one shared data structure.

Implements **TRD FR-27 Report generation**: PDF (annotated image, findings table, metadata,
both hashes, advisory disclaimer) via WeasyPrint, DOCX (same content, editable) via
python-docx, and JSON. Built from one shared structure so the formats cannot drift.

Accept: the DOCX opens in Word and LibreOffice with the findings table editable as a real
``w:tbl``, not an image.

Also hosts ``explain`` — the LLM call site that turns a finding into plain-language guidance
(CLAUDE.md §9, budget tier). It explains a verdict; it never produces one.

Requirements that bind every report (CLAUDE.md §3.6, §3.8):

* Every finding carries ``rulepack_version``, so a report regenerated next year reproduces the
  verdict issued under the rules in force at scan time.
* Every report carries the advisory disclaimer: this is a pre-audit tool, not a certification.

Modules planned: ``pdf.py``, ``docx.py``, ``json_report.py``, ``explain.py``.
Not implemented yet — P2.6. Note that WeasyPrint and python-docx are not yet dependencies;
adding them needs approval (CLAUDE.md §7).
"""
