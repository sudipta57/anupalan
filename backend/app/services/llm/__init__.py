"""LLM provider interface and adapters.

Three call sites in the whole codebase, all behind ``provider.py`` (CLAUDE.md §9):

| Call site                 | Purpose                                            | Tier   |
|---------------------------|----------------------------------------------------|--------|
| ``extraction.llm_layer``  | Map OCR text to field codes, strict JSON, temp 0   | Budget |
| ``reporting.explain``     | Turn a finding into plain-language guidance        | Budget |
| ``bis.answer``            | Write a cited answer from retrieved chunks         | Mid    |

Rules:

* **No vendor name appears anywhere outside config and the adapter files.** Calling code talks
  to ``LLMProvider`` and nothing else.
* **An open-weight adapter must stay working.** A government deployment may need to run
  entirely on-premise, and that capability is part of the pitch. Never write code that assumes
  a specific provider's features.
* The LLM never decides compliance (CLAUDE.md §3.1). It proposes field values and writes prose.
* Pick a model per call site on measured schema-failure rate and citation accuracy against E2
  and E4 — not on leaderboards (docs/01-architecture.md §9).

When the LLM is unavailable the pipeline degrades rather than failing: presence, format and
metric rules still run, extraction falls back to regex-only, and the report is flagged
"reduced extraction" (docs/01-architecture.md §11).

Modules planned: ``provider.py`` (the interface), plus one adapter per backend.
Not implemented yet — P2.5 brings the first call site online. No LLM SDK is a dependency yet;
adding one needs approval (CLAUDE.md §7).
"""
