"""Field extraction — regex layer, LLM layer, normalisation.

Implements **TRD FR-24 Field extraction** for the 15 field codes: ``manufacturer_name``,
``manufacturer_address``, ``packer_name``, ``importer_name``, ``importer_address``,
``country_of_origin``, ``common_name``, ``net_quantity``, ``mrp``, ``mfg_month_year``,
``consumer_care_name``, ``consumer_care_phone``, ``consumer_care_email``, ``unit_sale_price``,
``best_before``.

Order is fixed (docs/01-architecture.md §5 S6): deterministic regex first, LLM structuring
second for what regex missed, human confirmation third for anything below the confidence
threshold. Every value stores its ``source`` (``regex|llm|human``) and the character span it
came from.

Accept: field-level F1 ≥ 0.85 for ``net_quantity``, ``mrp``, ``mfg_month_year``; ≥ 0.75 for
address fields, on the E2 ground-truth set.

Constraints (CLAUDE.md §3.1, §8):

* The LLM proposes field **values** only. It never decides compliance.
* Every LLM-extracted field must carry a ``source_span`` that actually exists in the input OCR
  text. Validate it; do not trust it.
* Unit normalisation (``gms|Gms|gm → g``, ``ltr|Ltr → l``) reads its table from the rule pack,
  not from a dict in code.

Modules planned: ``regex_layer.py``, ``llm_layer.py``, ``normalise.py``.
Not implemented yet — P2.5.
"""
