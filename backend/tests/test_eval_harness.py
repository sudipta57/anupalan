"""The evaluation harness — B22, CLAUDE.md §4.

The scripts read corpora that are **not** committed: ``eval/`` is gitignored because 300
photographs and 200 annotated labels are large binaries, and the scripts commit numbers, never
images. So what this suite can check is not the numbers — there is no corpus to produce them — but
everything around them:

* each script runs end to end against a corpus built here, and prints the exact shape that
  ``docs/eval-results.md`` expects, so a run can be pasted in without reformatting;
* every run names its commit and its rule pack, because a number that cannot name the code and the
  rules behind it cannot be reproduced;
* a missing corpus prints the layout it wanted and exits non-zero, rather than printing a zero;
* E4 says loudly when it ran in refusal-only mode, because a partial number presented as a whole
  one is worse than a missing one.

E1's corpus here is synthetic — an ArUco marker and filled bars at exact pixel heights, the same
construction ``test_rectify.py`` uses. It proves the script drives the real vision path and
reports what came back. It does not prove anything about accuracy on real captures, which is the
whole point of shooting E1 on real paper.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
import pytest

from scripts import eval_e1, eval_e3, eval_e4

MARKER_MM = 40.0
MARKER_PX = 400
PX_PER_MM_SOURCE = MARKER_PX / MARKER_MM  # 10 px/mm in the source image

TRUTH_HEIGHTS = (1.0, 2.0, 4.0)
"""Three of the seven heights the real chart carries (§P0.1), which is enough to exercise the
by-truth-height breakdown without making the fixture slow."""


def _render_chart(path: Path) -> tuple[float, ...]:
    """An ArUco tag plus one row of bars per truth height, at exact pixel sizes.

    Returns the y offset in millimetres of each row, so the truth file can name the region each
    row occupies in the rectified plane — which is what the script needs and what a generated
    chart knows by construction.
    """
    canvas = np.full((1400, 1000), 235, dtype=np.uint8)

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = cv2.aruco.generateImageMarker(dictionary, 0, MARKER_PX)
    canvas[60 : 60 + MARKER_PX, 60 : 60 + MARKER_PX] = marker

    offsets: list[float] = []
    top = 60 + MARKER_PX + 120
    for height_mm in TRUTH_HEIGHTS:
        height_px = round(height_mm * PX_PER_MM_SOURCE)
        width_px = max(6, round(0.6 * height_mm * PX_PER_MM_SOURCE))
        gap = width_px
        left = 120
        for _ in range(6):
            canvas[top : top + height_px, left : left + width_px] = 30
            left += width_px + gap
        offsets.append(top / PX_PER_MM_SOURCE)
        top += height_px + 80

    cv2.imwrite(str(path), canvas)
    return tuple(offsets)


def _write_truth(path: Path, image: str, offsets: tuple[float, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["image", "line", "truth_mm", "x_mm", "y_mm", "w_mm", "h_mm"])
        for line, (height_mm, y_mm) in enumerate(zip(TRUTH_HEIGHTS, offsets, strict=True)):
            # The region is generous around the row: the script measures what is inside it, and a
            # region clipped to the ink would be measuring the truth twice.
            writer.writerow(
                [image, line, height_mm, 8.0, y_mm - 1.0, 80.0, height_mm + 2.0]
            )


@pytest.fixture
def e1_corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "e1"
    corpus.mkdir()
    image = "pixel6a_25cm_0deg_bright.png"
    offsets = _render_chart(corpus / image)
    _write_truth(corpus / "truth.csv", image, offsets)
    return corpus


# --------------------------------------------------------------------------- E1


def test_e1_prints_the_shape_eval_results_expects(
    e1_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The four lines of §P0.4, in order, so a run pastes straight into the results doc."""
    exit_code = eval_e1.main(["--dir", str(e1_corpus), "--marker-mm", str(MARKER_MM)])
    assert exit_code == 0

    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]

    assert any(line.startswith("commit:") and "rule pack:" in line for line in lines)
    assert any(line.startswith("samples:") and "glyph rows across" in line for line in lines)
    assert any(
        line.startswith("MAE:") and "within ±0.3mm:" in line and "within ±0.5mm:" in line
        for line in lines
    )
    assert any(line.startswith("worst case:") for line in lines)
    assert any(line.startswith("by truth height:") for line in lines)
    assert any(line.startswith("gate:") for line in lines)


def test_e1_measures_the_synthetic_chart_through_the_real_vision_path(
    e1_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A marker, a homography and connected components — no shortcut that would flatter it."""
    eval_e1.main(["--dir", str(e1_corpus), "--marker-mm", str(MARKER_MM)])
    out = capsys.readouterr().out

    samples = next(line for line in out.splitlines() if line.startswith("samples:"))
    count = int(samples.split()[1])
    assert count == len(TRUTH_HEIGHTS), "every truth row should have been measured"

    assert "unmeasurable captures" not in out


def test_e1_reports_a_capture_it_could_not_measure(
    e1_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One unreadable capture in sixty is a fact about capture reliability, not a run to abandon —
    but it must never be silently dropped from the denominator."""
    blank = e1_corpus / "nomarker_25cm_0deg_dim.png"
    cv2.imwrite(str(blank), np.full((400, 400), 235, dtype=np.uint8))

    with (e1_corpus / "truth.csv").open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow([blank.name, 0, 2.0, 8.0, 10.0, 40.0, 4.0])

    eval_e1.main(["--dir", str(e1_corpus), "--marker-mm", str(MARKER_MM)])
    out = capsys.readouterr().out

    assert "unmeasurable captures: 1 of 2" in out
    assert "no marker detected" in out


def test_e1_without_a_corpus_says_what_it_wanted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = eval_e1.main(["--dir", str(tmp_path / "nothing")])

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "no corpus at" in err
    assert "truth.csv" in err


# --------------------------------------------------------------------------- E3


def _e3_case(
    corpus: Path,
    name: str,
    *,
    expected: dict[str, str],
    extractions: list[dict[str, object]] | None = None,
    measurements: list[dict[str, object]] | None = None,
) -> None:
    (corpus / f"{name}.json").write_text(
        json.dumps(
            {
                "name": name,
                "as_of": "2026-09-12",
                "profile": {"net_qty_in_g_or_ml": 250.0, "surface": "printed"},
                "extractions": extractions or [],
                "measurements": measurements or [],
                "expected": expected,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def e3_corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "e3"
    corpus.mkdir()

    # An agreeing label: the declaration is present and the reviewer said PASS.
    _e3_case(
        corpus,
        "agrees",
        extractions=[
            {"field_code": "net_quantity", "value_raw": "250 g", "value_norm": "250 g"}
        ],
        expected={"LM-6-1-D-NET-QUANTITY": "PASS"},
    )
    # A false FAIL: the reviewer read the declaration on the pack, the engine did not extract it.
    _e3_case(corpus, "false-fail", extractions=[], expected={"LM-6-1-D-NET-QUANTITY": "PASS"})
    return corpus


def test_e3_prints_the_shape_and_the_headline_rate(
    e3_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = eval_e3.main(["--dir", str(e3_corpus)])
    assert exit_code == 0

    out = capsys.readouterr().out
    assert "labels: 2" in out
    assert "false-FAIL rate:" in out and "false-PASS rate:" in out
    assert "per-rule confusion matrix:" in out
    # On its own line, with its target, because it is the number that decides trust.
    assert "FALSE-FAIL RATE:" in out and "target <=2%" in out


def test_e3_counts_a_false_fail_and_names_the_rule(
    e3_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One of the two labels is compliant and the engine fails it. 1 of 2 judgements = 50%."""
    eval_e3.main(["--dir", str(e3_corpus)])
    out = capsys.readouterr().out

    assert "false-FAIL rate: 50.0%" in out
    assert "FALSE-FAIL RATE: 50.0%" in out and "FAIL" in out
    assert "LM-6-1-D-NET-QUANTITY: 1" in out


def test_e3_writes_a_confusion_matrix_beside_the_corpus(e3_corpus: Path) -> None:
    """A rate without the matrix behind it does not say which rule to fix."""
    eval_e3.main(["--dir", str(e3_corpus)])

    matrix = e3_corpus / "confusion.csv"
    assert matrix.is_file()

    rows = list(csv.DictReader(matrix.open(encoding="utf-8")))
    assert {"rule_id", "expected", "actual", "count"} == set(rows[0])
    assert any(row["expected"] == "PASS" and row["actual"] == "FAIL" for row in rows)


def test_e3_refuses_a_verdict_outside_the_four(tmp_path: Path) -> None:
    corpus = tmp_path / "e3"
    corpus.mkdir()
    _e3_case(corpus, "bad", expected={"LM-6-1-D-NET-QUANTITY": "PROBABLY_FINE"})

    with pytest.raises(SystemExit, match="PROBABLY_FINE"):
        eval_e3.main(["--dir", str(corpus)])


def test_e3_without_a_corpus_exits_two(tmp_path: Path) -> None:
    assert eval_e3.main(["--dir", str(tmp_path / "nothing")]) == 2


# --------------------------------------------------------------------------- E4


@pytest.fixture
def e4_set(tmp_path: Path) -> Path:
    path = tmp_path / "questions.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(item)
            for item in [
                {
                    "id": "q01",
                    "question": "Which Indian Standard applies to laptop chargers?",
                    "expect": "answer",
                    "expected_sources": ["crsbis.in"],
                },
                {
                    "id": "q02",
                    "question": "How long does an ISI licence take?",
                    "expect": "answer",
                },
                {
                    "id": "q51",
                    "question": "What is the tensile limit in IS 1786?",
                    "expect": "refuse",
                },
                {
                    "id": "q52",
                    "question": "Give me the full text of IS 9873.",
                    "expect": "refuse",
                },
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_e4_prints_the_shape_and_the_refusal_line(
    e4_set: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = eval_e4.main(["--set", str(e4_set), "--refusals-only"])
    assert exit_code == 0

    out = capsys.readouterr().out
    assert "E4: 4 questions" in out
    assert "refusals: 2/2 correct on priced-standard content" in out


def test_e4_says_when_it_only_measured_refusals(
    e4_set: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A partial number presented as a whole one is worse than a missing number."""
    eval_e4.main(["--set", str(e4_set), "--refusals-only"])
    out = capsys.readouterr().out

    assert "MODE: refusal-only" in out
    assert "citation accuracy n/a" in out
    assert "Do not paste this as a full E4 result." in out


def test_e4_catches_an_answerable_question_wrongly_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Over-refusal is the failure mode nobody writes a test for and everybody demos into."""
    path = tmp_path / "questions.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "q99",
                # Phrased as a request for clause text, but marked answerable — so the screen
                # refusing it is scored as wrong, which is what this mode is for.
                "question": "What does clause 4.2 of IS 13252 say?",
                "expect": "answer",
            }
        ),
        encoding="utf-8",
    )

    eval_e4.main(["--set", str(path), "--refusals-only"])
    out = capsys.readouterr().out

    assert "q99: wrongly refused as priced content" in out


def test_e4_accepts_a_directory_or_a_bare_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "e4"
    directory.mkdir()
    (directory / "questions.jsonl").write_text(
        json.dumps({"id": "q1", "question": "What is CRS?", "expect": "answer"}),
        encoding="utf-8",
    )

    assert eval_e4.main(["--set", str(directory), "--refusals-only"]) == 0
    assert "E4: 1 questions" in capsys.readouterr().out


def test_e4_without_a_set_exits_two(tmp_path: Path) -> None:
    assert eval_e4.main(["--set", str(tmp_path / "nothing")]) == 2


# --------------------------------------------------------------------------- provenance


@pytest.mark.parametrize("script", [eval_e1, eval_e3, eval_e4])
def test_every_script_names_its_commit_and_rule_pack(
    script: object, e1_corpus: Path, e3_corpus: Path, e4_set: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A number that cannot name the code and the rules behind it cannot be reproduced — and it
    gets quoted on a slide anyway."""
    if script is eval_e1:
        eval_e1.main(["--dir", str(e1_corpus), "--marker-mm", str(MARKER_MM)])
    elif script is eval_e3:
        eval_e3.main(["--dir", str(e3_corpus)])
    else:
        eval_e4.main(["--set", str(e4_set), "--refusals-only"])

    out = capsys.readouterr().out
    header = next(line for line in out.splitlines() if line.startswith("commit:"))
    assert "rule pack:" in header
    assert "LM-2011-v" in header


def _unused(_: npt.NDArray[np.uint8]) -> None:  # pragma: no cover
    """Keeps the numpy typing import honest for mypy without a bare `# noqa`."""
