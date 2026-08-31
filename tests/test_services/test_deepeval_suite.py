"""Wiring tests for the offline DeepEval suite, with no model and no judge involved.

`eval/deepeval_suite.py` exists to spend real API calls, so the thing that rots silently is
everything around them: the world-freezing patches, the retrieval context handed to the
judge, the report the run is read from. Those are checked here deterministically. What is
deliberately *not* checked is whether Gemini writes a good answer — that is the suite's own
job, on a developer's machine, against a real key.

Skipped when deepeval is absent: it ships in `requirements-eval.txt`, not `requirements.txt`,
so CI installs neither it nor its dependencies.
"""

import json
import sys

import pytest

pytest.importorskip("deepeval", reason="deepeval is in requirements-eval.txt, not requirements.txt")

from backend.services import agent_pipeline  # noqa: E402
from backend.services.verifier_service import FailureMode, NextAction, VerifierResult  # noqa: E402
from eval import deepeval_suite  # noqa: E402
from eval.golden_dataset import GOLDEN_CASES  # noqa: E402


class _StubMetric:
    """Stands in for a DeepEval metric: measured once per case, then read for its verdict."""

    def __init__(self, name: str, score: float, passed: bool):
        self.__name__ = name
        self.score = score
        self.reason = f"{name} said so."
        self._passed = passed
        self.measured: list = []

    def measure(self, test_case) -> float:
        self.measured.append(test_case)
        return self.score

    def is_successful(self) -> bool:
        return self._passed


def _case(case_id: str):
    return next(case for case in GOLDEN_CASES if case.case_id == case_id)


def _stub_model(monkeypatch, case) -> None:
    """Stub only what `_fixed_world` deliberately leaves live: the model and the Verifier.

    The stub answers with a card whenever the case calls for one, because otherwise it
    trips `Listing Discipline` and every test using it would fail for a reason that has
    nothing to do with what it is checking.
    """
    listings = (
        [
            {
                "project_name": "The Beverly",
                "unit_type": "2PN",
                "area_range": "68,2 m²",
                "price_range": "3,6 tỷ đồng",
                "unit_code": "OP3-BE1-1205",
                "status": "còn trống",
            }
        ]
        if case.expect_listings
        else []
    )

    def _generate_json(prompt, schema, **_kwargs):
        return schema(text=case.answer_text, quick_replies=[], suggested_questions=[], listings=listings)

    monkeypatch.setattr(agent_pipeline, "generate_json", _generate_json)
    monkeypatch.setattr(
        agent_pipeline.verifier_service,
        "score_answer",
        lambda *a, **k: VerifierResult(
            faithfulness=0.9,
            relevancy=0.9,
            completeness=0.9,
            failure_mode=FailureMode("none"),
            feedback="",
            next_action=NextAction("accept"),
        ),
    )


def test_gradeable_cases_skip_the_ones_that_never_reach_generate():
    """A notice case has no model-written answer, so paying a judge to score it is waste."""
    gradeable = deepeval_suite.gradeable_cases()

    assert gradeable, "every golden case was filtered out"
    assert all(not case.expect_notice for case in gradeable)


def test_fixed_world_restores_every_patch():
    """A leaked patch would silently disable retrieval for the rest of the process."""
    case = _case("policy-payment-schedule")
    before = (
        agent_pipeline.retrieve,
        agent_pipeline.lookup_inventory,
        agent_pipeline._store_cache,
        agent_pipeline.cache_service.lookup_cache,
    )

    with deepeval_suite._fixed_world(case):
        assert agent_pipeline.retrieve(case.query) == case.retrieved_docs

    assert (
        agent_pipeline.retrieve,
        agent_pipeline.lookup_inventory,
        agent_pipeline._store_cache,
        agent_pipeline.cache_service.lookup_cache,
    ) == before


def test_retrieval_context_carries_documents_and_inventory():
    """Both sources ground the answer, so both must reach the judge — a unit code judged
    against documents alone would read as invented."""
    case = _case("mixed-inventory-and-policy")

    context = deepeval_suite._retrieval_context(case)

    assert case.retrieved_docs[0]["content"] in context
    assert any(case.inventory_units[0].unit_code in entry for entry in context)


def test_run_case_scores_the_pipelines_own_answer(monkeypatch):
    case = _case("inventory-available-units")
    _stub_model(monkeypatch, case)
    metric = _StubMetric("Faithfulness", 0.82, True)

    result = deepeval_suite.run_case(case, [metric])

    assert result["case_id"] == case.case_id
    assert result["passed"] is True
    assert result["metrics"]["Faithfulness"]["score"] == 0.82
    assert result["answer"] in metric.measured[0].actual_output
    assert "OP3-BE1-1205" in metric.measured[0].actual_output
    assert case.answer_text in result["answer"]


def test_delivered_answer_includes_the_listing_cards():
    """A unit code belongs on a card, not in the prose. Grading the prose alone would fail
    a model for following the LISTINGS instruction."""

    class _Result:
        draft_answer = "Hiện có 1 căn 2PN còn trống."
        listings = [
            {
                "project_name": "The Beverly",
                "unit_type": "2PN",
                "area_range": "68,2 m²",
                "price_range": "3,6 tỷ",
                "unit_code": "OP3-BE1-1205",
                "status": "còn trống",
                "image_urls": ["https://cdn/photo.jpg"],
            }
        ]

    delivered = deepeval_suite._delivered_answer(_Result())

    assert "OP3-BE1-1205" in delivered
    assert _Result.draft_answer in delivered
    assert "cdn/photo.jpg" not in delivered


def test_delivered_answer_is_just_the_prose_when_there_are_no_cards():
    class _Result:
        draft_answer = "Chính sách thanh toán chia theo 8 đợt."
        listings: list = []

    assert deepeval_suite._delivered_answer(_Result()) == _Result.draft_answer


def test_required_facts_match_across_vietnamese_diacritics():
    """The golden cases are written unaccented; the model answers in full Vietnamese. A
    literal match would report every correct answer as missing its facts."""
    case = _case("policy-payment-schedule")

    assert case.expect_answer_contains == ("8 dot",)
    assert deepeval_suite._missing_required_facts(case, "Thanh toán theo tiến độ 8 đợt.") == []


def test_required_facts_reports_what_the_answer_left_out():
    case = _case("mixed-inventory-and-policy")

    missing = deepeval_suite._missing_required_facts(case, "Còn căn OP3-BE1-1205, giá 3,6 tỷ.")

    assert missing == ["5%"]


def test_required_facts_gate_fails_a_case_no_judge_would(monkeypatch):
    """The whole point of the deterministic gate: every judged metric can pass an answer
    that dropped a fact the reference commits to, and the case must still fail."""
    case = _case("inventory-available-units")
    monkeypatch.setattr(deepeval_suite, "_missing_required_facts", lambda *a: ["OP3-BE1-1205"])
    _stub_model(monkeypatch, case)

    result = deepeval_suite.run_case(case, [_StubMetric("Faithfulness", 1.0, True)])

    assert result["passed"] is False
    assert result["metrics"][deepeval_suite.REQUIRED_FACTS_METRIC]["passed"] is False
    assert "OP3-BE1-1205" in result["metrics"][deepeval_suite.REQUIRED_FACTS_METRIC]["reason"]


def test_run_case_hands_the_reference_answer_to_the_judge(monkeypatch):
    """`Answer Correctness` grades against the reference, so it has to reach the test case."""
    case = _case("inventory-available-units")
    _stub_model(monkeypatch, case)
    metric = _StubMetric("Answer Correctness [GEval]", 0.9, True)

    deepeval_suite.run_case(case, [metric])

    assert metric.measured[0].expected_output == case.expected_output
    assert case.expected_output, "the case lost its reference answer"


def test_forbidden_content_catches_a_broken_safety_rule():
    """The safety rules are absences, and a judge scoring helpfulness will not miss what is
    not there. Diacritics are stripped on both sides, as for required facts."""
    case = _case("no-investment-guarantee")

    assert case.expect_answer_excludes
    assert deepeval_suite._forbidden_content(case, "Căn này CHẮC CHẮN TĂNG giá sau 2 năm.") == ["chắc chắn tăng"]
    assert deepeval_suite._forbidden_content(case, "Tài liệu không cam kết về việc tăng giá.") == []


def test_forbidden_content_does_not_fail_a_correct_refusal():
    """Verbatim from the suite's first live run, where a substring test failed the model
    for refusing correctly: the forbidden promise appears inside its own negation."""
    case = _case("no-investment-guarantee")
    refusals = [
        "Không có dữ liệu khẳng định căn hộ chắc chắn tăng giá.",
        "Không có dữ liệu khẳng định căn hộ chắc chắn tăng giá, nhà tư vấn không được cam kết lợi nhuận cho khách.",
        "Chưa có cơ sở nào đảm bảo sinh lời từ căn này.",
    ]

    for refusal in refusals:
        assert deepeval_suite._forbidden_content(case, refusal) == [], refusal


def test_forbidden_content_still_catches_a_promise_after_a_negation():
    """A negation only reaches to the end of its clause: a refusal followed by a promise is
    still a promise, and the lenient reading must not swallow it."""
    case = _case("no-investment-guarantee")

    answer = "Tài liệu không có số liệu. Nhưng căn này chắc chắn tăng giá sau 2 năm."

    assert deepeval_suite._forbidden_content(case, answer) == ["chắc chắn tăng"]


def test_listing_discipline_rejects_a_card_invented_to_fill_the_slot():
    """The defect this suite found on a live run: a policy question answered with a card
    whose figures read "Đang cập nhật", which the LISTINGS block forbids in as many words."""
    policy = _case("policy-payment-schedule")
    placeholder = [{"unit_type": "Nhiều loại căn", "area_range": "Đang cập nhật", "price_range": "Đang cập nhật"}]

    assert not policy.expect_listings
    assert "recommends no unit" in deepeval_suite._listing_defect(policy, placeholder)
    assert deepeval_suite._listing_defect(policy, []) == ""


def test_listing_discipline_rejects_placeholder_figures_on_a_real_recommendation():
    inventory = _case("inventory-available-units")
    assert inventory.expect_listings

    real = [{"unit_type": "2PN", "area_range": "68,2 m²", "price_range": "3,6 tỷ đồng"}]
    placeholder = [{"unit_type": "2PN", "area_range": "68,2 m²", "price_range": "Liên hệ"}]

    assert deepeval_suite._listing_defect(inventory, real) == ""
    assert "Placeholder figures" in deepeval_suite._listing_defect(inventory, placeholder)
    assert "No unit cards" in deepeval_suite._listing_defect(inventory, [])


def test_report_separates_a_flaky_case_from_a_failing_one():
    """A case that passes 2 of 3 attempts is not passing and not broken; conflating the two
    either hides a real defect or sends someone chasing a single unlucky sample."""
    results = [
        {"case_id": "flaky", "passed": True, "metrics": {}},
        {"case_id": "flaky", "passed": False, "metrics": {}},
        {"case_id": "broken", "passed": False, "metrics": {}},
        {"case_id": "broken", "passed": False, "metrics": {}},
    ]

    report = deepeval_suite.build_report(results, judge_model="j", answer_model="a")

    assert report["cases"] == 2
    assert report["runs"] == 4
    assert report["flaky_cases"] == ["flaky"]
    assert report["per_case"]["broken"] == {"attempts": 2, "passed": 0, "pass_rate": 0.0, "flaky": False}


def test_run_case_fails_when_any_metric_fails(monkeypatch):
    """One failed metric fails the case: an answer with an invented price is not two-thirds
    acceptable."""
    case = _case("inventory-available-units")
    _stub_model(monkeypatch, case)

    result = deepeval_suite.run_case(
        case,
        [_StubMetric("Faithfulness", 0.9, True), _StubMetric("No Invented Figures [GEval]", 0.2, False)],
    )

    assert result["passed"] is False


def test_build_report_aggregates_per_metric():
    results = [
        {"case_id": "a", "passed": True, "metrics": {"Faithfulness": {"score": 1.0, "passed": True, "reason": ""}}},
        {
            "case_id": "b",
            "passed": False,
            "metrics": {"Faithfulness": {"score": 0.0, "passed": False, "reason": "unsupported claim"}},
        },
    ]

    report = deepeval_suite.build_report(results, judge_model="judge", answer_model="answerer")

    assert report["cases"] == 2
    assert report["pass_rate"] == 0.5
    assert report["metrics"]["Faithfulness"] == {
        "total": 2,
        "passed": 1,
        "failed": 1,
        "mean_score": 0.5,
        "examples": ["unsupported claim"],
    }


def _metrics(*, required: bool, faithfulness: bool) -> dict:
    """One deterministic gate and one judged metric, so a report can be built with the two
    halves disagreeing."""
    return {
        deepeval_suite.REQUIRED_FACTS_METRIC: {"score": 1.0 if required else 0.0, "passed": required, "reason": ""},
        "Faithfulness": {"score": 1.0 if faithfulness else 0.0, "passed": faithfulness, "reason": ""},
    }


def test_report_splits_the_rule_based_rate_from_the_judged_one():
    """The headline blends a gate no model votes on with an opinion, so both halves are
    reported separately — a generous judge must not be able to move the trustworthy number."""
    results = [
        {"case_id": "a", "passed": False, "metrics": _metrics(required=False, faithfulness=True)},
        {"case_id": "b", "passed": True, "metrics": _metrics(required=True, faithfulness=True)},
    ]

    report = deepeval_suite.build_report(results, judge_model="j", answer_model="a")

    assert report["deterministic_pass_rate"] == 0.5
    assert report["judged_pass_rate"] == 1.0


def test_a_generous_judge_cannot_lift_the_deterministic_rate():
    """The defect this whole split exists for: the judge passes everything while a
    hand-written reference fact is missing from every answer."""
    results = [
        {"case_id": "a", "passed": False, "metrics": _metrics(required=False, faithfulness=True)},
        {"case_id": "b", "passed": False, "metrics": _metrics(required=False, faithfulness=True)},
    ]

    report = deepeval_suite.build_report(results, judge_model="same", answer_model="same")

    assert report["judged_pass_rate"] == 1.0
    assert report["deterministic_pass_rate"] == 0.0
    assert report["independent_judge"] is False


def test_fail_under_gates_on_the_rule_based_rate(monkeypatch, tmp_path):
    """A run whose judged metrics all pass still fails when the gates do not: `--fail-under`
    reads the number no model got a vote on."""
    case = deepeval_suite.gradeable_cases()[0]
    monkeypatch.setattr(deepeval_suite, "gradeable_cases", lambda: [case])
    monkeypatch.setattr(
        deepeval_suite,
        "run_case",
        lambda case, metrics, attempt=1, pacer=None: {
            "case_id": case.case_id,
            "attempt": attempt,
            "passed": False,
            "metrics": _metrics(required=False, faithfulness=True),
        },
    )
    monkeypatch.setattr(deepeval_suite, "build_metrics", lambda judge, threshold: [])
    monkeypatch.setattr(deepeval_suite.settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        sys, "argv", ["prog", "--out", str(tmp_path), "--fail-under", "0.9", "--judge-model", "other-model"]
    )

    assert deepeval_suite.main() == 1

    report = json.loads((tmp_path / "deepeval_report.json").read_text(encoding="utf-8"))
    assert report["judged_pass_rate"] == 1.0
    assert report["deterministic_pass_rate"] == 0.0


def test_a_partial_run_does_not_overwrite_a_complete_report(monkeypatch, tmp_path):
    """Two graded cases standing in for five is a worse artifact than the complete run it
    would replace, and the Admin page reads whatever is on disk."""
    cases = deepeval_suite.gradeable_cases()[:2]
    monkeypatch.setattr(deepeval_suite, "gradeable_cases", lambda: cases)

    def _run_case(case, metrics, attempt=1, pacer=None):
        if case.case_id != cases[0].case_id:
            raise deepeval_suite.DailyQuotaExhaustedError("spent")
        return {"case_id": case.case_id, "attempt": attempt, "passed": True, "metrics": {}}

    monkeypatch.setattr(deepeval_suite, "run_case", _run_case)
    monkeypatch.setattr(deepeval_suite, "build_metrics", lambda judge, threshold: [])
    monkeypatch.setattr(deepeval_suite.settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(sys, "argv", ["prog", "--out", str(tmp_path)])

    complete = tmp_path / "deepeval_report.json"
    complete.write_text(json.dumps({"runs": 99, "complete": True}), encoding="utf-8")

    deepeval_suite.main()

    assert json.loads(complete.read_text(encoding="utf-8"))["runs"] == 99
    assert json.loads((tmp_path / "deepeval_report.partial.json").read_text(encoding="utf-8"))["complete"] is False


def test_a_partial_run_is_not_reported_as_green(monkeypatch, tmp_path):
    """A pass rate over the cases that fitted inside the quota says nothing about the rest.
    Exiting 0 would tell the nightly job all is well on a run that mostly did not happen."""
    graded: list = []

    def _run_case(case, metrics, attempt=1, pacer=None):
        if len(graded) >= 2:
            raise deepeval_suite.DailyQuotaExhaustedError("spent")
        graded.append(case.case_id)
        return {"case_id": case.case_id, "attempt": attempt, "passed": True, "metrics": {}}

    monkeypatch.setattr(deepeval_suite, "GeminiJudge", lambda *a, **k: None)
    monkeypatch.setattr(deepeval_suite, "build_metrics", lambda *a, **k: [])
    monkeypatch.setattr(deepeval_suite, "run_case", _run_case)
    monkeypatch.setattr(sys, "argv", ["prog", "--out", str(tmp_path)])

    code = deepeval_suite.main()

    report = json.loads((tmp_path / "deepeval_report.json").read_text(encoding="utf-8"))
    assert code == 1, "a truncated run exited green"
    assert report["complete"] is False
    assert report["runs"] == 2
    assert report["pass_rate"] == 1.0


def test_build_report_handles_an_empty_run():
    """`--fail-under` reads `pass_rate`; a ZeroDivisionError here would look like a failing
    eval rather than an empty one."""
    report = deepeval_suite.build_report([], judge_model="judge", answer_model="answerer")

    assert report["cases"] == 0
    assert report["pass_rate"] == 0.0


def test_build_report_flags_a_judge_grading_its_own_answers():
    """The scores are worth less when both models are the same one, so the run says so
    rather than leaving a reader to compare two strings."""
    same = deepeval_suite.build_report([], judge_model="gemini-x", answer_model="gemini-x")
    different = deepeval_suite.build_report([], judge_model="gemini-pro", answer_model="gemini-x")

    assert same["independent_judge"] is False
    assert different["independent_judge"] is True


def test_pacer_spaces_calls_out_to_the_allowed_rate(monkeypatch):
    """Waiting before a call is the whole point: a 429 costs more than the pause avoiding
    it, and the first call must not pay for a window nothing has used yet."""
    slept: list[float] = []
    clock = iter([0.0, 0.1, 0.1])
    monkeypatch.setattr(deepeval_suite.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(deepeval_suite.time, "sleep", slept.append)

    pacer = deepeval_suite._Pacer(rpm=60)
    pacer.wait()
    pacer.wait()

    assert slept == [pytest.approx(0.9)]


def test_the_pipelines_own_call_is_paced_too(monkeypatch):
    """Gemini counts its limit per model, and by default the pipeline drafts and the judge
    grades on the same one. Pacing only the judge leaves the drafting calls unpaced against
    the same bucket, which is the 429 the pacer exists to avoid."""
    case = _case("policy-payment-schedule")
    _stub_model(monkeypatch, case)
    waits: list[int] = []

    class _CountingPacer(deepeval_suite._Pacer):
        def wait(self) -> None:
            waits.append(1)

    deepeval_suite.run_case(case, [], pacer=_CountingPacer(rpm=15))

    assert waits, "the pipeline's own generation call was not paced"


def test_pacer_does_nothing_when_pacing_is_switched_off(monkeypatch):
    monkeypatch.setattr(deepeval_suite.time, "sleep", lambda _seconds: pytest.fail("should not sleep"))

    deepeval_suite._Pacer(rpm=0).wait()


def _quota_error(quota_id: str, retry_delay: str = "55s"):
    """A 429 shaped like the ones Gemini actually returned during this suite's live runs."""
    from google.genai import errors as genai_errors

    return genai_errors.APIError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota_id}]},
                    {"retryDelay": retry_delay},
                ],
            }
        },
    )


def test_a_daily_quota_is_not_retried():
    """Both caps arrive as RESOURCE_EXHAUSTED with a sub-minute retryDelay, but the day cap
    resets in hours. Retrying it spends five waits to reach the same refusal."""
    per_day = _quota_error("GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    per_minute = _quota_error("GenerateRequestsPerMinutePerProjectPerModel-FreeTier")

    assert deepeval_suite._is_daily_quota(per_day) is True
    assert deepeval_suite._is_daily_quota(per_minute) is False
    assert deepeval_suite._is_daily_quota(RuntimeError("not an API error")) is False


def test_the_run_stops_immediately_on_a_daily_quota(monkeypatch):
    calls: list[int] = []

    def _explode():
        calls.append(1)
        raise _quota_error("GenerateRequestsPerDayPerProjectPerModel-FreeTier")

    monkeypatch.setattr(deepeval_suite.time, "sleep", lambda _s: pytest.fail("should not wait out a daily cap"))

    with pytest.raises(deepeval_suite.DailyQuotaExhaustedError):
        deepeval_suite._with_quota_retry(_explode)

    assert calls == [1], "the daily cap was retried"


def test_quota_wait_uses_the_delay_the_api_asked_for():
    """The 429 names its own retry delay; guessing a fixed 20s either wastes time or wakes
    up into the same closed window."""
    from google.genai import errors as genai_errors

    error = genai_errors.APIError(
        429,
        {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [{"retryDelay": "9s"}]}},
    )

    assert deepeval_suite._quota_wait_seconds(error) == 9.0
    assert deepeval_suite._quota_wait_seconds(RuntimeError("wrapped")) == deepeval_suite._FALLBACK_QUOTA_WAIT_SECONDS
