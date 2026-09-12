"""LLM provider adapters.

Each module implements ``services.llm.provider.LLMProvider`` for one transport. The vendor lives
here and in config, nowhere else (CLAUDE.md §9). Callers go through
``services.llm.provider.get_provider``, which resolves ``settings.LLM_PROVIDER``.
"""
