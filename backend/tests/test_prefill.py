"""Context prefill — FR-03's "pre-filled from OCR, confirmed by the user".

The feature's whole value is that a user stops typing eight fields after every photograph. Its
whole risk is that a machine quietly fills the three fields that decide *which rules run*. So the
tests are mostly about what prefill refuses to say.

**The three safety properties, each with a test that fails loudly if it is ever relaxed:**

* ``is_imported`` is proposed in one direction only. A label with an importer line suggests
  imported; a label with no importer line suggests **nothing**, because ``is_imported=false``
  switches the importer rules off and "the pack did not mention it" is not evidence for switching
  a rule off — it is the description of the pack most likely to be in breach.
* ``surface`` is never proposed. It selects a Rule 9 threshold column and cannot be read from
  words.
* No verdict, no profile and no scan is produced anywhere on this path.

Plus the ordinary ones: org scoping on the collect endpoint (404, never 403), a read that finds
nothing is not a read that failed, and every failure degrades to a form the user fills by hand.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services.extraction.prefill import NEVER_SUGGESTED, SUGGESTED_FIELDS, suggest
from app.services.llm.adapters.stub import StubLLMProvider
from app.services.prefill import (
    LabelReading,
    MemoryPrefillStore,
    PrefillRecord,
    UnreadableImageError,
    read_label,
)
from app.services.rules.loader import active_pack
from app.services.rules.types import Extraction
from app.services.storage import StorageError, build_prefill_key
from app.services.vision.adapters.stub import StubOCREngine
from tests.conftest import make_org, make_user

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture


def extraction(code: str, value: str, *, confidence: float = 0.95) -> Extraction:
    return Extraction(field_code=code, value_raw=value, value_norm=value, confidence=confidence)


# --------------------------------------------------------------------------- the pure mapper


def test_a_net_quantity_becomes_a_value_and_a_unit() -> None:
    """The two halves that stop a user typing the field the Rule 9 table is keyed on."""
    proposed = {item.field: item.value for item in suggest([extraction("net_quantity", "250 g")])}

    assert proposed == {"net_qty_value": "250", "net_qty_unit": "g"}


def test_a_quantity_with_no_usable_unit_proposes_nothing() -> None:
    """Both halves or neither: a value with no unit leaves the form holding a number whose table
    nobody has chosen, which is worse than an empty field the user must fill."""
    assert suggest([extraction("net_quantity", "250")]) == []


def test_the_common_name_becomes_the_product_name() -> None:
    read = suggest([extraction("common_name", "Roasted Chana")])
    proposed = {item.field: item.value for item in read}

    assert proposed["name"] == "Roasted Chana"


def test_a_manufacturer_name_is_not_a_product_name() -> None:
    """A company is not a commodity. Using it would fill the field *and* make the client's
    category search match nothing, which is worse than leaving it empty."""
    assert suggest([extraction("manufacturer_name", "Hindustan Foods Pvt Ltd")]) == []


def test_an_importer_declaration_suggests_imported() -> None:
    read = suggest([extraction("importer_name", "Acme Imports")])
    proposed = {item.field: item.value for item in read}

    assert proposed["is_imported"] == "true"


def test_a_country_of_origin_that_is_not_india_suggests_imported() -> None:
    read = suggest([extraction("country_of_origin", "Made in Vietnam")])
    proposed = {item.field: item.value for item in read}

    assert proposed["is_imported"] == "true"


def test_country_of_origin_india_suggests_nothing() -> None:
    """Rule 6(10A) puts a country of origin on e-commerce listings of domestic goods too, so
    "India" is not evidence of import — and it is not evidence of *not* importing either."""
    assert suggest([extraction("country_of_origin", "India")]) == []


def test_a_label_with_no_importer_line_never_suggests_domestic() -> None:
    """**The safety property.** ``is_imported=false`` turns the importer rules off. A pack whose
    importer declaration is missing is exactly the pack that is in breach of Rule 6, and prefill
    must not launder that omission into a profile field that hides it.
    """
    proposed = suggest(
        [
            extraction("common_name", "Roasted Chana"),
            extraction("net_quantity", "250 g"),
            extraction("mrp", "45.00"),
        ]
    )

    assert [item.field for item in proposed if item.field == "is_imported"] == []
    assert "false" not in {item.value for item in proposed}


def test_surface_and_the_other_rule_relevant_fields_are_never_proposed() -> None:
    """Rule 9 gives embossed text a higher threshold than printed text, and which one a pack is
    cannot be read from its words. Same for pack type, panel area, channel and category."""
    every_code = [
        extraction(code, "something")
        for code in (
            "common_name",
            "net_quantity",
            "importer_name",
            "country_of_origin",
            "manufacturer_name",
            "mrp",
            "mfg_month_year",
        )
    ]

    proposed = {item.field for item in suggest(every_code)}

    assert proposed & set(NEVER_SUGGESTED) == set()
    assert proposed <= set(SUGGESTED_FIELDS)


def test_a_blank_declaration_is_absent_not_a_value() -> None:
    """An empty string extracted at high confidence is an absent declaration (FR-24)."""
    assert suggest([Extraction(field_code="common_name", value_raw="  ", confidence=0.95)]) == []


def test_confidence_is_inherited_not_invented() -> None:
    """A model-proposed value carries 0.70, below FR-06's threshold on purpose. Passing through
    here must not raise it."""
    [proposed] = suggest([extraction("common_name", "Roasted Chana", confidence=0.70)])

    assert proposed.confidence == 0.70
    assert proposed.needs_confirmation


def test_every_suggestion_carries_the_reading_it_came_from() -> None:
    """"Why is my form saying 250 g" must have an answer that points at the pack."""
    for item in suggest([extraction("net_quantity", "250 g"), extraction("common_name", "Chana")]):
        assert item.from_field_code
        assert item.source_text


def test_the_order_is_stable() -> None:
    one = suggest([extraction("net_quantity", "250 g"), extraction("common_name", "Chana")])
    two = suggest([extraction("common_name", "Chana"), extraction("net_quantity", "250 g")])

    assert [item.field for item in one] == [item.field for item in two]


# --------------------------------------------------------------------------- reading a label


@pytest.fixture(scope="module")
def pack():  # type: ignore[no-untyped-def]
    return active_pack()


@pytest.fixture
def ocr() -> StubOCREngine:
    return StubOCREngine.from_fixture("roasted_chana_250g")


def encoded_image() -> bytes:
    """A real PNG, small. ``read_label`` decodes before it recognises, so the bytes must decode."""
    import cv2

    canvas = np.full((64, 64, 3), 255, dtype=np.uint8)
    ok, buffer = cv2.imencode(".png", canvas)
    assert ok
    return bytes(buffer.tobytes())


def test_reading_a_label_proposes_the_quantity_without_a_model(ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """The pattern layer alone carries net quantity (FR-24), so the most tedious field on the
    form fills itself even with the LLM unreachable."""
    reading = read_label(encoded_image(), ocr=ocr, pack=pack, llm=None)

    proposed = {item.field: item.value for item in reading.suggestions}
    assert proposed["net_qty_value"] == "250"
    assert proposed["net_qty_unit"] == "g"
    assert reading.reduced is True
    assert reading.word_count > 0


def test_reading_never_produces_a_measurement(ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """CLAUDE.md §3.3: millimetres come from the marker homography and nowhere else. Prefill runs
    on a downscaled photograph with no marker, so it must propose no physical dimension at all."""
    reading = read_label(encoded_image(), ocr=ocr, pack=pack, llm=None)

    assert all(item.field != "pdp_area_cm2" for item in reading.suggestions)


def test_bytes_that_are_not_an_image_are_refused(ocr, pack) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(UnreadableImageError):
        read_label(b"not an image", ocr=ocr, pack=pack, llm=None)


def test_a_photograph_with_no_text_reads_empty_rather_than_failing(pack) -> None:  # type: ignore[no-untyped-def]
    """A back panel or a thumb over the label. Nothing to propose is a normal outcome, and the
    client distinguishes it from a failure by the word count."""
    reading = read_label(
        encoded_image(), ocr=StubOCREngine.from_words([]), pack=pack, llm=None
    )

    assert reading.suggestions == ()
    assert reading.word_count == 0


# --------------------------------------------------------------------------- the store


def test_a_prefill_is_not_readable_by_another_org() -> None:
    """Org scoping lives in the key, so another org's id does not resolve at all."""
    store = MemoryPrefillStore()
    reading = LabelReading(suggestions=(), word_count=3, reduced=False)
    store.put("org-a", PrefillRecord.of("pf1", reading))

    assert store.get("org-a", "pf1") is not None
    assert store.get("org-b", "pf1") is None


def test_a_scratch_key_is_org_prefixed_and_cannot_be_escaped() -> None:
    key = build_prefill_key(org_id="org1", prefill_id="pf1", extension="jpg")
    assert key == "prefill/org1/pf1.jpg"

    with pytest.raises(StorageError):
        build_prefill_key(org_id="../other", prefill_id="pf1", extension="jpg")


# --------------------------------------------------------------------------- the endpoints


class FakeObjectStore:
    """Holds the scratch bytes in memory and records the deletes."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def put_bytes(self, key: str, data: bytes, content_type: str) -> object:
        self.objects[key] = data
        return object()

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "OTP_ECHO_IN_RESPONSE", True)
    monkeypatch.setattr(settings, "ENV", "local")
    monkeypatch.setattr(settings, "PREFILL_ENABLED", True)


@pytest.fixture
def prefill_store() -> MemoryPrefillStore:
    return MemoryPrefillStore()


@pytest.fixture
def object_store() -> FakeObjectStore:
    return FakeObjectStore()


@pytest.fixture
def queued() -> list[tuple[str, str, str]]:
    return []


@pytest.fixture
def api(db_session, prefill_store, object_store, queued, monkeypatch) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """The real app with the stores and the broker substituted — the handlers are untouched."""
    from app.main import app
    from app.routers import prefill as prefill_router
    from app.routers.deps import db, prefill_enqueuer

    monkeypatch.setattr(prefill_router, "get_store", lambda: prefill_store)
    monkeypatch.setattr(prefill_router, "get_object_store", lambda: object_store)

    app.dependency_overrides[db] = lambda: db_session
    app.dependency_overrides[prefill_enqueuer] = lambda: (
        lambda prefill_id, org_id, key: queued.append((prefill_id, org_id, key)) or "task-1"
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def sign_in(api: TestClient, phone: str) -> str:
    requested = api.post("/v1/auth/otp/request", json={"phone": phone})
    body = requested.json()
    verified = api.post(
        "/v1/auth/otp/verify", json={"request_id": body["request_id"], "code": body["code"]}
    )
    assert verified.status_code == 200, verified.text
    return str(verified.json()["access"])


@pytest.fixture
def inspector(db_session, api):  # type: ignore[no-untyped-def]
    org = make_org(db_session, name="Legal Metrology, Nadia", mode="enforcement")
    make_user(db_session, org=org, phone="+919812345678", role="inspector")
    db_session.commit()
    token = sign_in(api, "+919812345678")
    return {"org": org, "auth": {"Authorization": f"Bearer {token}"}}


def body(**overrides: object) -> dict:  # type: ignore[type-arg]
    payload = {
        "image_base64": base64.b64encode(encoded_image()).decode("ascii"),
        "content_type": "image/png",
    }
    payload.update(overrides)
    return payload


def test_posting_a_photograph_queues_a_read(api, inspector, queued, object_store) -> None:  # type: ignore[no-untyped-def]
    created = api.post("/v1/prefill", json=body(), headers=inspector["auth"])

    assert created.status_code == 202, created.text
    assert created.json()["status"] == "reading"

    prefill_id = created.json()["prefill_id"]
    assert len(queued) == 1
    assert queued[0][0] == prefill_id
    # The bytes went to object storage under the org's prefix, not into a scan.
    [key] = list(object_store.objects)
    assert key.startswith(f"prefill/{inspector['org'].id}/")


def test_polling_before_the_worker_answers_reports_reading(api, inspector) -> None:  # type: ignore[no-untyped-def]
    """Recorded as `reading` before the enqueue, so the gap between the two is not a 404 the
    client would read as "gone"."""
    created = api.post("/v1/prefill", json=body(), headers=inspector["auth"])
    prefill_id = created.json()["prefill_id"]

    polled = api.get(f"/v1/prefill/{prefill_id}", headers=inspector["auth"])

    assert polled.status_code == 200
    assert polled.json()["status"] == "reading"


def test_a_finished_read_returns_its_suggestions(api, inspector, prefill_store) -> None:  # type: ignore[no-untyped-def]
    created = api.post("/v1/prefill", json=body(), headers=inspector["auth"])
    prefill_id = created.json()["prefill_id"]

    prefill_store.put(
        str(inspector["org"].id),
        PrefillRecord.of(
            prefill_id,
            LabelReading(
                suggestions=tuple(suggest([extraction("net_quantity", "250 g")])),
                word_count=42,
                reduced=False,
            ),
        ),
    )

    polled = api.get(f"/v1/prefill/{prefill_id}", headers=inspector["auth"])
    payload = polled.json()

    assert payload["status"] == "ready"
    assert {item["field"] for item in payload["suggestions"]} == {"net_qty_value", "net_qty_unit"}
    assert all(item["from_field_code"] == "net_quantity" for item in payload["suggestions"])


def test_another_orgs_prefill_is_404_not_403(api, db_session, inspector, prefill_store) -> None:  # type: ignore[no-untyped-def]
    """CLAUDE.md §3.7: cross-org access must not leak existence."""
    other = make_org(db_session, name="Another Org", mode="industry")
    db_session.commit()
    prefill_store.put(str(other.id), PrefillRecord.reading("pf-elsewhere"))

    polled = api.get("/v1/prefill/pf-elsewhere", headers=inspector["auth"])

    assert polled.status_code == 404


def test_an_expired_prefill_is_404(api, inspector) -> None:  # type: ignore[no-untyped-def]
    polled = api.get("/v1/prefill/never-existed", headers=inspector["auth"])

    assert polled.status_code == 404


def test_an_oversized_image_is_refused_before_it_is_stored(  # type: ignore[no-untyped-def]
    api, inspector, object_store, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "PREFILL_MAX_BYTES", 16)

    refused = api.post("/v1/prefill", json=body(), headers=inspector["auth"])

    assert refused.status_code == 413
    assert object_store.objects == {}


def test_bytes_that_are_not_base64_are_refused(api, inspector) -> None:  # type: ignore[no-untyped-def]
    refused = api.post(
        "/v1/prefill", json=body(image_base64="not base64!!"), headers=inspector["auth"]
    )

    assert refused.status_code == 422


def test_prefill_can_be_switched_off_without_breaking_the_form(api, inspector, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """503 is the honest answer and the client's cue to stop asking. The context form is
    unaffected — it is what the app falls back to with no network anyway."""
    monkeypatch.setattr(settings, "PREFILL_ENABLED", False)

    refused = api.post("/v1/prefill", json=body(), headers=inspector["auth"])

    assert refused.status_code == 503


def test_an_unauthenticated_request_is_refused(api) -> None:  # type: ignore[no-untyped-def]
    assert api.post("/v1/prefill", json=body()).status_code == 401


# --------------------------------------------------------------------------- the task


def test_the_task_deletes_the_photograph_whatever_happened(
    prefill_store, object_store, pack, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    """It is a throwaway thumbnail, not evidence. Nothing keeps it, including a failed read."""
    from app.tasks import prefill as task_module

    key = "prefill/org-a/pf1.png"
    object_store.objects[key] = b"not an image"

    monkeypatch.setattr(task_module, "get_store", lambda: prefill_store)
    monkeypatch.setattr(task_module, "get_object_store", lambda: object_store)
    monkeypatch.setattr(task_module, "active_pack", lambda: pack)
    monkeypatch.setattr(task_module, "get_engine", lambda: StubOCREngine.from_words([]))
    monkeypatch.setattr(task_module, "get_provider", lambda: None)

    result = task_module.read_label_task.run("pf1", "org-a", key)

    assert result["status"] == "failed"
    assert key in object_store.deleted
    assert prefill_store.get("org-a", "pf1") is not None


def test_the_task_records_what_it_read(prefill_store, object_store, pack, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.tasks import prefill as task_module

    key = "prefill/org-a/pf2.png"
    object_store.objects[key] = encoded_image()

    monkeypatch.setattr(task_module, "get_store", lambda: prefill_store)
    monkeypatch.setattr(task_module, "get_object_store", lambda: object_store)
    monkeypatch.setattr(task_module, "active_pack", lambda: pack)
    monkeypatch.setattr(
        task_module, "get_engine", lambda: StubOCREngine.from_fixture("roasted_chana_250g")
    )
    monkeypatch.setattr(task_module, "get_provider", lambda: None)

    result = task_module.read_label_task.run("pf2", "org-a", key)

    assert result["status"] == "ready"
    record = prefill_store.get("org-a", "pf2")
    assert record is not None
    assert {item.field for item in record.suggestions} >= {"net_qty_value", "net_qty_unit"}
    assert key in object_store.deleted


def test_the_llm_path_proposes_a_name_the_patterns_cannot(ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """No pattern extracts a common name, so the product name is the field the model earns its
    place for. It arrives at 0.70 — below FR-06's threshold, so the client asks."""
    reading = read_label(encoded_image(), ocr=ocr, pack=pack, llm=StubLLMProvider())

    assert reading.reduced is False
