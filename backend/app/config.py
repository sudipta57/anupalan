"""Application settings, loaded from the environment via pydantic-settings.

Every tunable lives here. Two values in particular must never be written at a call site:

``PX_PER_MM``
    The rectified-image scale, 20 px/mm (docs/01-architecture.md §5 S3). CLAUDE.md §8 names
    hardcoding ``20`` as a gotcha that has already cost time: a literal at a call site is
    invisible when the scale changes, and every millimetre downstream is then silently wrong.

``RULEPACK_PATH``
    Rule packs are data in ``rulepacks/``, never inside ``app/`` (CLAUDE.md §2). Thresholds,
    table rows and effective dates are read from the loaded pack, never from Python
    (CLAUDE.md §3.2).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root, i.e. the directory above backend/. Used only to resolve default paths.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration. Override any field with an environment variable."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    APP_NAME: str = "anupalan"
    ENV: str = Field(default="local", description="local | ci | staging | production")
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    API_V1_PREFIX: str = "/v1"

    # CORS origins for the mobile dev client and any local tooling.
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:8081"])

    # ------------------------------------------------------------------ datastores
    # Managed services — Neon for Postgres, Redis Cloud for the broker. There are deliberately
    # NO localhost defaults: a fallback would silently connect to whatever unrelated Postgres or
    # Redis happens to be running on a developer's machine, and writing scans into someone
    # else's database is a failure you discover late. Unset means /health reports "error".
    DATABASE_URL: str = ""
    """Neon **pooled** connection string. Host contains `-pooler`. Required.

    Scheme must be ``postgresql+psycopg://`` and the URL must carry ``?sslmode=require``.
    """

    DATABASE_URL_DIRECT: str = ""
    """Neon **direct** (non-pooled) connection string, used only for Alembic DDL.

    Falls back to ``DATABASE_URL`` when unset, which works but is not recommended: the pooled
    endpoint is pgbouncer in transaction mode and cannot run migrations reliably.
    """

    DB_POOL_RECYCLE: int = 280
    """Recycle connections below Neon's idle timeout, so a suspended branch never hands back a
    dead connection."""

    DB_CONNECT_TIMEOUT: int = 10
    """Seconds. Covers a Neon cold start after scale-to-zero."""

    REDIS_URL: str = ""
    """Redis Cloud URL. Use ``rediss://`` — the scheme switches Celery's TLS on (see worker.py)."""

    # Celery reuses Redis for both broker and results; see docs/01-architecture.md §9.
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None

    # ------------------------------------------------------------------ object storage
    # Cloudflare R2, addressed through the S3 API.
    #
    # Named S3_* rather than R2_* on purpose: the client speaks S3, and any S3-compatible store
    # — MinIO on-premise, AWS S3 — works by changing the endpoint and the keys. A government
    # deployment may have to run wholly on-premise, and object storage is the easiest piece to
    # move (docs/01-architecture.md §9).
    S3_ENDPOINT_URL: str = ""
    """``https://<account_id>.r2.cloudflarestorage.com`` for R2."""

    S3_REGION: str = "auto"
    """R2 has no regions and requires the literal string ``auto``."""

    S3_BUCKET: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_USE_PATH_STYLE: bool = True
    S3_PRESIGN_EXPIRY_SECONDS: int = 900

    S3_PUBLIC_BASE_URL: str = ""
    """Optional custom domain for public reads. Buckets stay private; access is by presigned URL
    (docs/01-architecture.md §10). R2 rejects per-object ACLs, so there is no public-read flag."""

    UPLOAD_MAX_BYTES: int = 15 * 1024 * 1024
    """Largest asset accepted, enforced when the presigned URL is issued rather than after the
    bytes arrive — a limit checked post-upload has already cost the bandwidth it was meant to
    save."""

    UPLOAD_ALLOWED_CONTENT_TYPES: list[str] = Field(
        default_factory=lambda: ["image/jpeg", "image/png", "image/webp", "image/heic"]
    )
    """MIME allow-list for scan assets (docs/01-architecture.md §10). An allow-list, never a
    deny-list: the set of things a camera legitimately produces is small and known."""

    # ------------------------------------------------------------------ metrology
    PX_PER_MM: int = 20
    """Pixels per millimetre in the rectified plane. Never write this number at a call site."""

    # ------------------------------------------------------------------ metrology tuning
    GLYPH_MIN_AREA_PX: int = 12
    """Connected components smaller than this are noise, not glyphs (P0 spike §2)."""

    GLYPH_MIN_HEIGHT_PX: int = 4
    """Components shorter than this are speckle. At 20 px/mm this is 0.2 mm."""

    BASELINE_TOLERANCE_PX: int = 3
    """How far apart two component bottoms can be and still share a text baseline."""

    CAP_HEIGHT_RATIO: float = 0.75
    """Fraction of a text line's tallest glyph at which a component counts as cap height.

    Rule 9's tables are about the height of the *numerals* in a declaration. Where connected
    components cannot be matched to individual characters, this separates cap-height glyphs from
    punctuation and x-height lowercase — without it, the two dots of a colon are measured as
    numerals and a compliant label fails on a 0.75 mm "numeral".
    """

    MARK_HEIGHT_RATIO: float = 0.4
    """Below this fraction of the line's cap height, a component is punctuation, not a letter.

    x-height lowercase sits around 0.5-0.7 of cap height; a comma or a colon dot is far below
    that. Rule 9(3) sets a minimum letter height, and a full stop measured as a letter would fail
    a label that is entirely compliant.
    """

    CURVATURE_MAX_RESIDUAL_MM: float = 0.45
    """Above this baseline bow, the surface is not planar enough to measure on.

    An **engineering tuning parameter, not a legal threshold** — it decides whether a measurement
    can be taken at all, never what the measurement must be. Legal thresholds live in the rule
    pack (CLAUDE.md §3.2). A planar homography under-measures on a curved pack
    (docs/01-architecture.md §12.2), so past this the metric rules go NOT_ASSESSABLE rather than
    reporting a confident wrong number.
    """

    BLUR_REFERENCE: float = 120.0
    """Variance-of-Laplacian at which capture is considered sharp (TRD FR-01 gate)."""

    TILT_REFERENCE_DEG: float = 25.0
    """Viewing angle at which capture is considered maximally tilted (TRD FR-01 gate)."""

    # ------------------------------------------------------------------ auth
    SECRET_KEY: str = ""
    """The one server secret. Signs access tokens, and peppers the OTP and refresh-token hashes.

    Deliberately **one** value rather than three: three secrets is three things to rotate and
    three chances for one of them to be left at a default. It is never used directly —
    ``services/auth/tokens.derive_key`` HMACs it with a purpose label, so the key that signs a JWT
    and the key that peppers an OTP are different keys that happen to share an origin. Reusing a
    single key across purposes is how a signature oracle turns into a hash oracle.

    Unset means no token can be issued: ``services/auth`` raises rather than falling back to a
    development default, because a development default that reaches production is an authentication
    system with a published key.
    """

    ACCESS_TOKEN_TTL_SECONDS: int = 900
    """15 minutes. Short because an access token is stateless and therefore cannot be revoked —
    revocation acts on the refresh family instead, and this is how long a stolen access token
    outlives it."""

    REFRESH_TOKEN_TTL_SECONDS: int = 60 * 60 * 24 * 30
    """30 days. An inspector in the field should not be logged out mid-inspection because they
    were offline for a fortnight (FR-04)."""

    OTP_LENGTH: int = 6
    OTP_TTL_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5
    """Wrong guesses before a code is dead. Six digits is 10^6 of entropy, so the guard against
    brute force is this number and the rate limits below — not the cost of the hash."""

    OTP_RATE_WINDOW_SECONDS: int = 3600
    OTP_MAX_PER_PHONE: int = 5
    """Codes per number per window. Also the cap on using this endpoint to send someone SMS."""

    OTP_MAX_PER_IP: int = 20
    """Codes per source address per window. Both axes are needed: per-phone alone lets one caller
    sweep many numbers, per-IP alone lets many callers sweep one number."""

    OTP_ECHO_IN_RESPONSE: bool = False
    """Return the code in the API response instead of sending it.

    For local development and the demo, where there is no SMS gateway wired up. Refused outright
    when ``ENV`` is ``production`` — see ``services/auth/otp.py``, which checks rather than
    trusting whoever set the variable.
    """

    # ------------------------------------------------------------------ llm
    # No vendor name appears here or anywhere outside the adapter files (CLAUDE.md §9). The
    # provider is a base URL and a model name; a hosted vendor and a local vLLM/Ollama server are
    # the same adapter pointed somewhere different, which is what keeps the open-weight path
    # working without a second code path to rot.
    LLM_PROVIDER: str = "chat_completions"
    """Which LLMProvider implementation to use: ``chat_completions`` or ``stub``."""

    LLM_BASE_URL: str = ""
    """Chat-completions endpoint base, e.g. a hosted API or ``http://localhost:11434/v1``."""

    LLM_API_KEY: str = ""
    LLM_MODEL_BUDGET: str = ""
    """Model for extraction and explanations — the two high-volume, low-difficulty call sites."""

    LLM_MODEL_MID: str = ""
    """Model for Sahayak answers, where citation accuracy matters more than cost."""

    LLM_TIMEOUT_SECONDS: float = 30.0
    LLM_MAX_RETRIES: int = 2

    LLM_EXTRA_BODY: str = ""
    """Extra JSON merged into every chat-completions request body. Empty by default.

    An escape hatch for server-specific knobs, so the adapter stays provider-agnostic (§9). The
    case it exists for: a hybrid reasoning model such as Qwen3 arrives with thinking *on* at one
    host and *off* at another, and with it on, a 150-token extraction turns into thousands of
    tokens of deliberation and a timeout. Turning it off is one field in the request body — but
    which field, and whether it is honoured at all, is a property of the server, not of this code.

    So the knob lives in configuration, where a vendor detail is allowed to appear, rather than as
    a branch in the adapter that would have to grow a case per host. Example::

        LLM_EXTRA_BODY={"chat_template_kwargs": {"enable_thinking": false}}

    Keys the adapter computes itself — model, messages, temperature, max_tokens, response_format —
    always win, so this can add to a request but never quietly rewrite the prompt contract.
    """

    # ------------------------------------------------------------------ ocr
    OCR_SIDEWAYS_SHARE: float = 0.6
    """Share of taller-than-wide word boxes that means the page was photographed on its side.

    Measured on a real scan: 100% of boxes taller than wide as shot, 0% once rotated upright — so
    this is a wide margin rather than a tuned one. Above it, the page is read again at other
    orientations and the readings merged (``services/vision/orientation.py``).
    """

    OCR_MIN_WORDS: int = 12
    """Below this many words, an upright pass is not trusted as the whole label on its own."""

    OCR_MIN_CONFIDENCE: float = 0.70
    """Below this mean confidence, likewise — the engine found text it could not read."""

    OCR_ENGINE: str = "paddle"
    """Which OCREngine implementation to use: ``paddle`` in production, ``stub`` in tests.

    TRD FR-22 requires that swapping the engine changes no calling code, so this name is the
    only thing that selects one. The engine itself is resolved by
    ``services.vision.ocr.get_engine``.
    """

    # ------------------------------------------------------------------ rate limiting
    # Two axes, both required (B23, NFR-01). Per-IP alone lets one org flood from many addresses;
    # per-org alone lets one address sweep many orgs. See services/ratelimit.py.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_BACKEND: str = "memory"
    """``redis`` in any deployment with more than one worker, ``memory`` for local development,
    ``off`` to disable. ``memory`` counts per process, so N workers admit N times the ceiling —
    ``get_limiter`` refuses it when ``ENV`` is production rather than letting a deployment find
    that out under load."""

    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_PER_IP: int = 120
    """Requests per minute from one address. An inspector's phone retrying an upload is nowhere
    near this; a script is."""

    RATE_LIMIT_PER_ORG: int = 600
    """Requests per minute from one organisation, across every user and device it has."""

    RATE_LIMIT_EXEMPT_PATHS: list[str] = Field(
        default_factory=lambda: ["/health", "/docs", "/openapi.json", "/redoc"]
    )
    """Never limited. ``/health`` in particular: a load balancer polling it must not be throttled
    into declaring the service dead, which would turn a rate limit into an outage."""

    # ------------------------------------------------------------------ sahayak (bis)
    # No model name from a vendor appears here either: an embedder and a reranker are names in a
    # registry, resolved exactly the way OCR_ENGINE and LLM_PROVIDER are, so an on-premise
    # deployment swaps a string rather than a code path.
    BIS_EMBEDDER: str = "bge_m3"
    """Which Embedder implementation to use: ``bge_m3`` in production, ``hashing`` in tests.

    ``hashing`` is a deterministic stand-in that needs no model weights and refuses to be selected
    in production — see ``services/bis/embedding.py``. CI must never download a 2 GB model.
    """

    BIS_RERANKER: str = "cross_encoder"
    """Which Reranker implementation to use: ``cross_encoder`` in production, ``overlap`` in
    tests."""

    BIS_RETRIEVAL_CANDIDATES: int = 30
    """How many fused candidates go to the reranker (architecture §7: rerank the top 30)."""

    BIS_RETRIEVAL_TOP_K: int = 6
    """How many chunks reach the generator (architecture §7: top 30 -> top 6)."""

    BIS_RRF_K: int = 60
    """Reciprocal-rank-fusion constant. 60 is the value the RRF paper uses and every
    implementation since has kept; it is here so it is visible, not so it is tuned."""

    BIS_LISTS_PATH: Path = _REPO_ROOT / "bis" / "qco-crs-v1.yaml"
    """The QCO/CRS applicability lists (B20). Data in ``bis/``, versioned independently of code,
    for the same reason rule packs are: "does this product need the ISI mark" is a lookup against
    a published list, and a published list belongs in a file somebody can review and diff."""

    # ------------------------------------------------------------------ rule packs
    RULEPACK_PATH: Path = _REPO_ROOT / "rulepacks" / "lm-2011-v1.yaml"
    """Active rule pack. Data, versioned independently of code (CLAUDE.md §2)."""

    RULEPACK_DIR: Path = _REPO_ROOT / "rulepacks"

    @property
    def alembic_url(self) -> str:
        """Connection string for migrations: the direct endpoint when available."""
        return self.DATABASE_URL_DIRECT or self.DATABASE_URL

    @property
    def redis_is_tls(self) -> bool:
        """True when the Redis URL is TLS, which Celery must be told about explicitly."""
        return self.celery_broker.startswith("rediss://")

    @property
    def celery_broker(self) -> str:
        """Broker URL, defaulting to ``REDIS_URL`` when not set explicitly."""
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def celery_backend(self) -> str:
        """Result backend URL, defaulting to ``REDIS_URL`` when not set explicitly."""
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


settings = get_settings()
