"""Reading a label to prefill the product context form — the impure half of FR-03's prefill.

``extraction.prefill`` maps declarations to suggestions and is pure. This module is what gets the
declarations: decode a scan's photographs, recognise them, merge the words, extract, and hand the
result somewhere the API can read it back.

**Why this is not the scan pipeline.** The pipeline exists to produce verdicts, and a verdict
needs the marker, the homography and millimetres. Prefill produces *form values*, so it needs
none of that:

* **No marker, no rectification, no measurement.** Nothing here computes a millimetre, which is
  why it is allowed to run on a photograph that was downscaled on the phone before it was sent.
  CLAUDE.md §3.3 is not weakened by this — it is respected by not producing the quantity that
  would violate it. The scan itself still carries its marker and is still measured by the
  pipeline, off the full-resolution original.
* **No scan row, no findings, no evidence.** The images are thumbnails of photographs the user has
  not yet decided to turn into a scan. They are deleted as soon as they have been read, and nothing
  derived from them reaches a report. The evidence chain starts where it always did: at
  ``POST /v1/scans``, with the client's declared SHA-256 over the full-resolution bytes.

**It runs in the worker**, not in the API, for the same reason processing does: the API process
does not load OCR models and must not start doing so on a request path.

**Failure is silence, never an error the user must deal with.** Every way this can go wrong —
unreadable image, OCR finding nothing, the model unavailable, Redis down — ends as "no
suggestions", and the context form behaves exactly as it did before this feature existed. The
form is the fallback and it is always there, which is what keeps FR-04 intact: a capture with no
network still reaches the queue, having asked for nothing.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

import cv2
import numpy as np
import numpy.typing as npt

from app.config import settings
from app.services.extraction import extract
from app.services.extraction.plausibility import screen
from app.services.extraction.prefill import Suggestion, suggest
from app.services.extraction.product_name import read_product_name
from app.services.extraction.regex_layer import extract_with_patterns
from app.services.extraction.text import build_text
from app.services.llm.provider import LLMProvider, LLMResult, Tier
from app.services.rules.loader import RulePack
from app.services.rules.types import Profile
from app.services.vision.ocr import OCREngine, Word
from app.services.vision.orientation import read as read_oriented

logger = logging.getLogger(__name__)

PrefillStatus = Literal["reading", "ready", "failed"]
"""Where one prefill is. ``failed`` is reported, not raised: see the module docstring."""


class UnreadableImageError(ValueError):
    """The bytes are not an image this can decode.

    The only failure this module raises rather than swallows, and it is caught by the task, which
    records ``failed``. Distinguished from "read it and found nothing" because the two mean
    different things to a person: one is a broken upload, the other is a label with no words on
    it.
    """


@dataclass(frozen=True)
class LabelReading:
    """What a scan's photographs, read together, propose for the product context form."""

    suggestions: tuple[Suggestion, ...]

    word_count: int
    """How many words were recognised across every photograph. Zero with no suggestions means they
    were read and had nothing usable on them — blurred, or a hand over the label — which is a
    different thing from the read never happening, and the client says so differently."""

    reduced: bool
    """True when extraction ran without the model, so only the pattern layer contributed.

    Mirrors ``pipeline.ScanOutcome.reduced_extraction`` and means the same thing: the suggestions
    are the deterministic layer's alone. In practice this is the difference between getting a
    quantity and getting a quantity *and* a product name — no pattern extracts a common name.
    """


def _decode_image(payload: bytes) -> npt.NDArray[np.uint8]:
    """Decode image bytes to greyscale.

    Greyscale to match ``pipeline._decode``: the same photograph must reach the recognition engine
    the same way here and in the pipeline, or a label could read one way on the form and another
    way in the findings.

    Raises:
        UnreadableImageError: the bytes are not a decodable image.
    """
    buffer = np.frombuffer(payload, dtype=np.uint8)
    decoded = cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)
    if decoded is None:
        raise UnreadableImageError("could not decode the uploaded bytes as an image")
    return np.ascontiguousarray(decoded)


class _WatchedProvider:
    """A provider that remembers whether any of its calls failed.

    Exists because ``reduced`` used to be computed as ``llm is None``, and that is the wrong
    question. The extraction layer turns a failed model call into an empty list and never raises
    (``extraction.llm_layer``), so a provider that was *present* but refused — a 429 from a
    rate-limited free tier, a timeout, a malformed body — produced a record reading "full read, not
    reduced, no suggestions". That is indistinguishable from "read everything and found nothing",
    and it is exactly what an inspector saw: three photographs of a Dabur carton, 91 words read, an
    empty form, and nothing to say the model had never answered.

    Reproduced against the live provider: three extraction-sized calls in parallel returned one 200
    and two ``429 We have to rate limit you``. The same photographs read with the model answering
    produced name, net quantity and unit.

    Structural, not a subclass: it satisfies ``LLMProvider`` by shape, which is all ``extract``
    asks for, so no adapter has to know it is being watched.
    """

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.failed = False

    def complete(
        self,
        *,
        prompt: str,
        schema: dict[str, Any] | None,
        temperature: float,
        max_tokens: int,
        tier: Tier,
    ) -> LLMResult:
        result = self._inner.complete(
            prompt=prompt,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            tier=tier,
        )
        # `parsed is None` counts as a failure for the same reason `llm_layer` treats it as one: a
        # schema was asked for, and a response that does not parse contributed nothing.
        if not result.ok or (schema is not None and result.parsed is None):
            self.failed = True
        return result


def read_label(
    images: Sequence[bytes],
    *,
    ocr: OCREngine,
    pack: RulePack,
    llm: LLMProvider | None,
) -> LabelReading:
    """Read a scan's photographs and propose product-context values from them.

    **Every photograph, merged into one read.** The declarations are not all on one panel: the net
    quantity and the commodity name are usually on the front, and the importer, the country of
    origin and the consumer-care line are usually on the back. Reading only the first photograph
    means proposing nothing for the fields that are hardest to type, which is most of them — so all
    of them are read and their words are merged before extraction runs once over the lot.

    That is what the pipeline already does with a scan's images, and for the same reason: a
    declaration is a declaration wherever on the pack it is printed.

    **Merging is safe here in a way it is not in the pipeline.** Word polygons from two photographs
    are in two different coordinate spaces, which is why ``pipeline`` keeps a per-asset
    ``ocr_pages`` alongside its merged text. Prefill discards geometry entirely — a suggestion
    carries a value and the text it was read from, never a box — so there is nothing here for the
    mismatch to corrupt.

    **An unreadable photograph does not fail the read.** With several images, one that will not
    decode is skipped and the rest are read; a caller gets ``UnreadableImageError`` only when
    *nothing* could be decoded. One bad frame out of three should cost its own words, not the
    other two photographs'.

    Args:
        images: encoded image bytes, in capture order — typically downscaled JPEGs.
        ocr: the recognition engine.
        pack: the active rule pack. Supplies the unit table extraction normalises against;
            no threshold is read and no rule is evaluated here.
        llm: the provider, or ``None`` for pattern-only. A provider that fails behaves as ``None``
            — ``extract`` already absorbs that (architecture §11).

    Returns:
        The suggestions, and enough context for the client to explain an empty result.

    Raises:
        UnreadableImageError: not one of ``images`` could be decoded.
    """
    words: list[Word] = []
    decoded = 0

    for index, image in enumerate(images):
        try:
            page = _decode_image(image)
        except UnreadableImageError as exc:
            logger.warning("prefill skipping photograph %d: %s", index, exc)
            continue

        decoded += 1
        words.extend(
            read_oriented(
                page,
                ocr,
                min_words=settings.OCR_MIN_WORDS,
                min_confidence=settings.OCR_MIN_CONFIDENCE,
                sideways_share=settings.OCR_SIDEWAYS_SHARE,
            )
        )

    if decoded == 0:
        raise UnreadableImageError("none of the uploaded photographs could be decoded")

    # An empty Profile, and it is never read: `extract` deletes its profile argument on the first
    # line precisely so the model cannot be told what it is expected to find (see its docstring).
    # Prefill has no profile to give it in any case — building one is the whole point.
    #
    # Once, over the merged words, rather than once per photograph: a single pass is one LLM call
    # instead of N, and it lets a value printed on one panel be read in the context of the others.
    watched = _WatchedProvider(llm) if llm is not None else None
    extractions = extract(words, Profile(), llm=watched, pack=pack)

    # The pattern layer's readings as well as the merged ones. `extract` lets the model's answer
    # replace a pattern's, which is right for verdicts and cost prefill a real importer line: a
    # pattern-matched "Country of Origin Nepal" at 0.95 became the model's 0.70, below the bar
    # `is_imported` needs. `extraction.prefill._imported` says on what terms these are believed.
    text, spans = build_text(words)
    patterns = screen(extract_with_patterns(text, spans, pack))
    suggestions = suggest(extractions, pattern_readings=patterns)

    # No common name on the label — typical of a back panel — so ask the model for the product's
    # name directly. Not when the model already failed on this read: a provider that refused a
    # second ago will refuse again, and the wait is someone's.
    if (
        watched is not None
        and not watched.failed
        and not any(item.field == "name" for item in suggestions)
    ):
        named = read_product_name(text, llm=watched)
        if named is not None:
            suggestions = suggest(extractions, pattern_readings=patterns, product_name=named)

    return LabelReading(
        suggestions=tuple(suggestions),
        word_count=len(words),
        # Reduced when there was no model, *or* when there was one and it did not answer. The
        # docstring above has always promised "a provider that fails behaves as None"; this is
        # the line that makes the record say so.
        reduced=watched is None or watched.failed,
    )


# --------------------------------------------------------------------------- the result store


@dataclass(frozen=True)
class PrefillRecord:
    """One prefill as the API hands it back."""

    prefill_id: str
    status: PrefillStatus
    suggestions: tuple[Suggestion, ...] = ()
    word_count: int = 0
    reduced: bool = False

    @classmethod
    def reading(cls, prefill_id: str) -> PrefillRecord:
        return cls(prefill_id=prefill_id, status="reading")

    @classmethod
    def of(cls, prefill_id: str, result: LabelReading) -> PrefillRecord:
        return cls(
            prefill_id=prefill_id,
            status="ready",
            suggestions=result.suggestions,
            word_count=result.word_count,
            reduced=result.reduced,
        )

    @classmethod
    def failed(cls, prefill_id: str) -> PrefillRecord:
        return cls(prefill_id=prefill_id, status="failed")


class PrefillStore(Protocol):
    """Where a prefill waits between the worker writing it and the client asking for it."""

    def put(self, org_id: str, record: PrefillRecord) -> None: ...

    def get(self, org_id: str, prefill_id: str) -> PrefillRecord | None: ...


def _key(org_id: str, prefill_id: str) -> str:
    """The storage key, org first.

    Org scoping is in the key rather than in a check after the read, so a prefill id guessed or
    replayed from another org does not resolve at all — the API then answers 404, which is the
    same answer it gives for an id that never existed (CLAUDE.md §3.7: never leak existence).
    """
    return f"prefill:{org_id}:{prefill_id}"


def _encode(record: PrefillRecord) -> str:
    return json.dumps(
        {
            "prefill_id": record.prefill_id,
            "status": record.status,
            "word_count": record.word_count,
            "reduced": record.reduced,
            "suggestions": [asdict(item) for item in record.suggestions],
        }
    )


def _decode(raw: str | bytes) -> PrefillRecord | None:
    try:
        data = json.loads(raw)
        return PrefillRecord(
            prefill_id=str(data["prefill_id"]),
            status=data["status"],
            suggestions=tuple(Suggestion(**item) for item in data.get("suggestions", ())),
            word_count=int(data.get("word_count", 0)),
            reduced=bool(data.get("reduced", False)),
        )
    except (ValueError, KeyError, TypeError) as exc:
        # A record written by an older build. Treated as absent: the form works without it.
        logger.warning("discarding an unreadable prefill record: %s", exc)
        return None


class RedisPrefillStore:
    """Prefills in Redis, with a TTL.

    Redis rather than Postgres because a prefill is not a record of anything. It is read once,
    within a minute, by the phone that asked for it, and then it is rubbish — storing it would
    mean a table, a migration and a cleanup job for data whose whole life is shorter than the
    session that created it.

    **Fails closed.** Unlike the rate limiter, which admits a request when Redis is unreachable, a
    prefill that cannot be stored or read is simply absent, and the form is filled by hand. There
    is nothing to fail open *to*.
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._tried = client is not None

    def _connect(self) -> Any | None:
        if not self._tried:
            self._tried = True
            try:
                import redis

                self._client = redis.Redis.from_url(
                    settings.REDIS_URL, socket_timeout=1, socket_connect_timeout=1
                )
            except Exception as exc:  # noqa: BLE001 — any failure means "no prefill"
                logger.warning("prefill store has no Redis: %s", exc)
                self._client = None
        return self._client

    def put(self, org_id: str, record: PrefillRecord) -> None:
        client = self._connect()
        if client is None:
            return
        try:
            client.set(
                _key(org_id, record.prefill_id),
                _encode(record),
                ex=settings.PREFILL_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not store prefill %s: %s", record.prefill_id, exc)

    def get(self, org_id: str, prefill_id: str) -> PrefillRecord | None:
        client = self._connect()
        if client is None:
            return None
        try:
            raw = client.get(_key(org_id, prefill_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not read prefill %s: %s", prefill_id, exc)
            return None
        return None if raw is None else _decode(raw)


class MemoryPrefillStore:
    """An in-process store, for tests and for a dev run with no Redis.

    Useless across processes — the API and the worker are two — so it is never the production
    choice. It exists so the router suite can exercise the whole path without a broker.
    """

    def __init__(self) -> None:
        self._records: dict[str, PrefillRecord] = {}

    def put(self, org_id: str, record: PrefillRecord) -> None:
        self._records[_key(org_id, record.prefill_id)] = record

    def get(self, org_id: str, prefill_id: str) -> PrefillRecord | None:
        return self._records.get(_key(org_id, prefill_id))

    def reset(self) -> None:
        self._records.clear()


_STORES: dict[str, type[RedisPrefillStore] | type[MemoryPrefillStore]] = {
    "redis": RedisPrefillStore,
    "memory": MemoryPrefillStore,
}

_store: PrefillStore | None = None


def get_store() -> PrefillStore:
    """The configured store, built once.

    Cached like ``ratelimit.get_limiter``: a Redis client rebuilt per request would open a
    connection per request, and a memory store rebuilt per request would remember nothing.
    """
    global _store
    if _store is None:
        _store = _STORES[settings.PREFILL_STORE]()
    return _store


def reset_store() -> None:
    """Drop the cached store. For tests that switch the setting."""
    global _store
    _store = None


def new_prefill_id() -> str:
    """An opaque id for one prefill. Random rather than sequential — it is a capability."""
    return uuid.uuid4().hex


__all__ = [
    "LabelReading",
    "MemoryPrefillStore",
    "PrefillRecord",
    "PrefillStatus",
    "PrefillStore",
    "RedisPrefillStore",
    "UnreadableImageError",
    "get_store",
    "new_prefill_id",
    "read_label",
    "reset_store",
]
