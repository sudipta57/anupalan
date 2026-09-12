"""Sahayak — the BIS / Indian Standards assistant (SIH26107).

Implements:

* **TRD FR-28 Sahayak retrieval** — hybrid BM25 + dense retrieval, RRF fusion, cross-encoder
  rerank on the top 30, generation with mandatory citation of retrieved chunk ids
  (``retrieval.py``, ``answer.py``). Accept: ≥ 90% of answers carry a correct citation and 0
  answers cite a chunk that does not contain the claim, on the 60-question E4 set.
* **TRD FR-29 BIS applicability from a scan** — given a product profile, return
  ``{qco_applicable, scheme, candidate_is_numbers, next_steps, sources}``
  (``applicability.py``). Applicability is a **deterministic table lookup**, not retrieval;
  retrieval supplies only the explanation and next steps. Accept: correct for ≥ 17 of 20 known
  products.

**The non-negotiable that shapes this whole package (CLAUDE.md §3.5):**

Never ingest priced Indian Standards texts into the corpus. Full IS documents are copyrighted
and sold by BIS. The corpus is public material only — Quality Control Orders, the
mandatory-certification and CRS product lists, BIS scheme guides and FAQs, hallmarking pages,
the lab directory, catalogue metadata (IS number, title, scope abstract, ICS code, year,
amendment status).

``ingest.py`` must carry an explicit blocklist with the comment explaining why, so nobody adds
priced content later by accident. Sahayak **refuses** to state technical clause content — test
limits, clause text, tolerance tables — and points to the BIS purchase route instead. That
refusal is a design feature, not a gap (docs/01-architecture.md §7).

Modules planned: ``ingest.py``, ``chunk.py``, ``retrieval.py``, ``answer.py``,
``applicability.py``.
Not implemented yet — P4.
"""
