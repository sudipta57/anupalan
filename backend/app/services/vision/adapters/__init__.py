"""OCR engine adapters.

Each module here implements ``services.vision.ocr.OCREngine`` for one backend. Adapters are the
replaceable half of TRD FR-22: the interface is stable, the engine behind it is not. Nothing
outside this package imports an adapter directly — callers go through
``services.vision.ocr.get_engine``, which resolves the name in ``settings.OCR_ENGINE``.
"""
