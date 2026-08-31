"""Offline DeepEval batch over the golden questions, with the real model in the loop.

The third eval layer, filling the gap the other two leave:

- `tests/test_services/test_golden_regression.py` runs the same questions with the LLM
  stubbed, so it proves routing and assembly but says nothing about answer quality.
- `eval/graders.py` grades recorded traces, which are content-free by design
  (`backend/core/tracing.py` records `query_len`, not the question) — no judge can score
  an answer it cannot read.

This module runs each golden question through the real pipeline with retrieval, inventory
and the cache frozen to the case's fixed world, and lets Gemini actually draft the answer.
The world is deterministic and the model is not, so what varies between runs is exactly
what DeepEval is asked to measure.

"Who judges the judge" is answered here in two ways, because the first is not enough on
its own.

`--judge-model` left at `GEMINI_MODEL` has the model grading its own drafts, which measures
self-consistency more than quality — the first live run scored a flat 1.00 on every metric.
Pointing it at a different, stronger model buys a second opinion, a sharper grader, and a
*separate quota bucket* (Gemini counts its per-minute limit per model). That independence is
still partial: one vendor, one training lineage.

So the gate that decides a case is not a judgement at all. `GoldenCase.expected_output`
holds a hand-written reference answer, and `REQUIRED_FACTS_METRIC` checks by string match
that the facts the reference commits to — a price, a unit code, a discount — actually
appear in what the model wrote. No model votes on that, so no model can be generous about
it. The judged metrics stay for what strings cannot see (is a claim grounded, is the answer
on topic, was a figure invented), and the report marks which numbers are which:
`deterministic_pass_rate` is the one to act on, `judged_pass_rate` is a trend, and
`--fail-under` gates on the former so a generous judge cannot open the gate.

Costs real API calls, so it runs on a schedule (`.github/workflows/answer-quality.yml`)
rather than on every PR, and deepeval lives in `requirements-eval.txt` rather than
`requirements.txt` for the same reason:

    pip install -r requirements-eval.txt
    python -m eval.deepeval_suite --repeats 3
    python -m eval.deepeval_suite --judge-model gemini-3.1-pro-preview --rpm 150
    python -m eval.deepeval_suite --fail-under 0.9

`--repeats` exists because the model is not deterministic: one sample cannot separate a
defect from an unlucky draw, so the report scores each case over its attempts and names the
flaky ones. Each metric spends several judge calls per answer, so a run is dozens of
requests; `--rpm` paces them under the key's per-minute allowance (default: the free tier's
15), which is far cheaper than tripping a 429 and waiting out the window afterwards.
"""

import argparse
import json
import re
import statistics
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
from deepeval.models.base_model import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, SingleTurnParams
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from backend.core import gemini_client
from backend.core.config import settings
from backend.services import agent_pipeline
from backend.services.inventory_service import InventoryApiError
from backend.utils.text import strip_diacritics
from eval.golden_dataset import GOLDEN_CASES, GoldenCase

DEFAULT_OUT = Path("eval/results")

REQUIRED_FACTS_METRIC = "Required Facts"
FORBIDDEN_CONTENT_METRIC = "Forbidden Content"
LISTING_DISCIPLINE_METRIC = "Listing Discipline"
DETERMINISTIC_METRICS = (REQUIRED_FACTS_METRIC, FORBIDDEN_CONTENT_METRIC, LISTING_DISCIPLINE_METRIC)

DEFAULT_RPM = 15

_QUOTA_RETRY_ATTEMPTS = 5
_FALLBACK_QUOTA_WAIT_SECONDS = 20.0
_MIN_QUOTA_WAIT_SECONDS = 5.0


class _Pacer:
    """Spaces calls out so the per-minute limit is approached but never crossed.

    Reacting to a 429 is far more expensive than avoiding one: the response asks for a wait
    measured in seconds, and every metric mid-flight pays it. Spending the same seconds up
    front, spread between calls, costs the same wall-clock time and never loses a request.

    One instance covers a whole run. Gemini counts its limit per model, and the pipeline's
    own generation and the judge's grading are the same model by default — pacing only the
    judge leaves the pipeline's calls unpaced against the same bucket, which is exactly the
    429 this class exists to avoid. `--judge-model` splits the buckets, and then the shared
    pacer is merely conservative rather than necessary.
    """

    def __init__(self, rpm: int):
        self._min_interval = 60.0 / rpm if rpm > 0 else 0.0
        self._last_call: float | None = None

    def wait(self) -> None:
        if not self._min_interval:
            return

        if self._last_call is not None:
            elapsed = time.monotonic() - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)

        self._last_call = time.monotonic()


class DailyQuotaExhaustedError(RuntimeError):
    """The key's per-day cap is spent, so no amount of waiting finishes this run."""


def _api_error(exc: BaseException) -> genai_errors.APIError | None:
    """The SDK error inside `exc`, however deeply the pipeline wrapped it.

    Service layers wrap SDK exceptions before they cross their boundary, so the quota
    details are often on a cause rather than on `exc` — the same walk
    `is_gemini_quota_error` does to recognise the error in the first place.
    """
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, genai_errors.APIError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _is_daily_quota(exc: BaseException) -> bool:
    """Whether this 429 is the per-*day* cap rather than the per-minute one.

    Gemini reports both as RESOURCE_EXHAUSTED with a `retryDelay` of under a minute, but
    the day cap resets in hours, not seconds. Retrying it spends five waits to arrive at
    the same refusal, so the run should stop and say so — a report that took twenty extra
    minutes to fail is worse than one that failed straight away.
    """
    error = _api_error(exc)
    body = getattr(error, "details", None) if error else None
    return "PerDay" in json.dumps(body) if isinstance(body, dict) else False


def _quota_wait_seconds(exc: BaseException) -> float:
    """How long the API itself asked us to wait."""
    error = _api_error(exc)
    if error is None:
        return _FALLBACK_QUOTA_WAIT_SECONDS
    return max(gemini_client.retry_delay_seconds(error), _MIN_QUOTA_WAIT_SECONDS)


def _with_quota_retry(call):
    """Wait out a Gemini quota window rather than losing the run half-graded.

    Wraps both sides of a case — the pipeline drafting the answer and the judge scoring it
    — because either can be the call that crosses the per-minute limit, and a crash in the
    middle throws away every case already paid for.
    """
    for attempt in range(1, _QUOTA_RETRY_ATTEMPTS + 1):
        try:
            return call()
        except Exception as exc:
            if attempt == _QUOTA_RETRY_ATTEMPTS or not gemini_client.is_gemini_quota_error(exc):
                raise

            if _is_daily_quota(exc):
                raise DailyQuotaExhaustedError(
                    "The daily Gemini quota for this key is spent; the run cannot finish today. "
                    "Use a key with a higher tier, or a --judge-model with its own quota."
                ) from exc

            delay = _quota_wait_seconds(exc)
            print(
                f"Gemini quota reached; waiting {delay:.0f}s (attempt {attempt}/{_QUOTA_RETRY_ATTEMPTS}).",
                file=sys.stderr,
            )
            time.sleep(delay)

    raise RuntimeError("The quota retry loop exited without a result.")


class GeminiJudge(DeepEvalBaseLLM):
    """DeepEval's judge, on Gemini and on its own model.

    DeepEval defaults to OpenAI; this project has no OpenAI key and no reason to acquire
    one. It calls the SDK directly rather than going through `gemini_client` for two
    reasons the eval path does not share with the request path: the judge must be free to
    run on a *different* model than `GEMINI_MODEL` (see the module docstring), and
    `client_models_generate` books every call into the pipeline's token accounting, where
    eval traffic would show up as production spend on the Admin dashboard.

    Schema-constrained decoding is kept, because DeepEval asks for structured verdicts and
    a judge returning prose with a brace in it fails in a way that reads as a bad score.
    """

    def __init__(self, model_name: str, pacer: _Pacer):
        self._model_name = model_name
        self._pacer = pacer
        super().__init__(model_name)

    def load_model(self):
        return gemini_client.get_gemini_client()

    def get_model_name(self) -> str:
        return f"Gemini ({self._model_name})"

    def generate(self, prompt: str, schema: type[BaseModel] | None = None) -> Any:
        return _with_quota_retry(lambda: self._generate_once(prompt, schema))

    def _generate_once(self, prompt: str, schema: type[BaseModel] | None) -> Any:
        self._pacer.wait()
        response = self.model.models.generate_content(
            model=self._model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json" if schema else None,
                response_schema=schema,
            ),
        )

        if schema is None:
            return response.text or ""

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return parsed

        raw = (response.text or "").strip()
        if not raw:
            raise RuntimeError(f"The judge returned nothing parseable as {schema.__name__}.")
        return schema.model_validate_json(raw)

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None) -> Any:
        return self.generate(prompt, schema)


@contextmanager
def _fixed_world(case: GoldenCase):
    """Freeze everything except the model, at the boundary the golden test stubs at.

    The cache is stubbed in both directions on purpose: a warm entry would return a
    previous run's answer (nothing to judge), and writing through would seed production's
    semantic cache from an eval run.
    """

    def _lookup(project_id, query):
        if case.inventory_raises:
            raise InventoryApiError("down")
        return case.inventory_units

    patches = [
        (agent_pipeline, "retrieve", lambda *a, **k: case.retrieved_docs),
        (agent_pipeline, "lookup_inventory", _lookup),
        (agent_pipeline, "_store_cache", lambda *a, **k: None),
        (agent_pipeline.cache_service, "lookup_cache", lambda *a, **k: None),
    ]
    originals = [(obj, name, getattr(obj, name)) for obj, name, _ in patches]

    for obj, name, replacement in patches:
        setattr(obj, name, replacement)
    try:
        yield
    finally:
        for obj, name, original in originals:
            setattr(obj, name, original)


def _retrieval_context(case: GoldenCase) -> list[str]:
    """Everything the answer is allowed to be grounded in, as the judge will see it.

    Inventory units are flattened into text because they reach the model as context the
    same way a document passage does; a unit the model never saw must read as ungrounded
    to the judge too.
    """
    context = [doc["content"] for doc in case.retrieved_docs]
    context += [
        f"{unit.unit_code} | {unit.subdivision} | {unit.unit_type} | "
        f"{unit.area_m2} m2 | {unit.price} VND | {unit.status}"
        for unit in case.inventory_units
    ]
    return context


_LISTING_FIELDS = ("project_name", "unit_type", "area_range", "price_range", "unit_code", "status")


def _delivered_answer(result: Any) -> str:
    """Everything the Sale actually reads: the prose plus the unit cards beside it.

    A unit code belongs in `SaleAnswer.listings`, not in the prose — the LISTINGS block of
    the system instruction tells the model to put per-unit figures on a card that the
    frontend renders as a badge, rather than repeat them in `text`. Grading `draft_answer`
    alone therefore marks a model that followed its instructions as having dropped the
    fact, which is a defect in the eval and not in the answer.
    """
    parts = [result.draft_answer]
    for listing in result.listings:
        values = [str(listing.get(field) or "") for field in _LISTING_FIELDS]
        parts.append(" | ".join(value for value in values if value))
    return "\n".join(part for part in parts if part)


_PLACEHOLDER_FIGURES = ("đang cập nhật", "chưa có", "liên hệ", "n/a", "-", "")


def _listing_defect(case: GoldenCase, listings: list[dict]) -> str:
    """Why this answer's unit cards are wrong, or "" when they are fine.

    Two distinct faults, both invisible to a judge scoring prose. A card attached to a
    question that recommends no unit is noise beside a correct answer; a card whose area or
    price reads "Đang cập nhật" is the model filling a slot it was told to leave empty. The
    Verifier scores neither, because the prose above the card can be flawless.
    """
    if not listings:
        return "No unit cards, but this question recommends specific units." if case.expect_listings else ""

    if not case.expect_listings:
        return f"{len(listings)} unit card(s) on a question that recommends no unit."

    empty = [
        listing.get("unit_type") or "?"
        for listing in listings
        if str(listing.get("price_range") or "").strip().lower() in _PLACEHOLDER_FIGURES
        or str(listing.get("area_range") or "").strip().lower() in _PLACEHOLDER_FIGURES
    ]
    if empty:
        return f"Placeholder figures instead of an empty card: {', '.join(empty)}."

    return ""


def _missing_required_facts(case: GoldenCase, answer: str) -> list[str]:
    """The facts the draft had to state and did not — decided by string matching, not by a
    model.

    This is the answer to a judge that scores its own vendor's output generously: whether
    "3,6 tỷ" or "OP3-BE1-1205" appears in a sentence is not a matter of opinion, so nothing
    here asks for one. `expect_answer_contains` already names those facts per case; the
    golden regression test checks them against a stubbed draft, and this checks the same
    ones against what the real model wrote.

    Both sides go through `strip_diacritics` because the golden cases are written
    unaccented, the way a Sale types on a phone, while the model answers in full
    Vietnamese — "8 dot" has to match "8 đợt".
    """
    normalised = strip_diacritics(answer)
    return [fact for fact in case.expect_answer_contains if strip_diacritics(fact) not in normalised]


_NEGATIONS = ("khong", "chua", "khong the", "khong duoc")
_NEGATION_WINDOW = 60


def _is_negated(text: str, at: int) -> bool:
    """Whether a negation governs the phrase starting at `at`.

    A window rather than a parse: the negation and the phrase it governs sit in the same
    clause in every phrasing this has to handle ("không có dữ liệu khẳng định ... chắc chắn
    tăng giá"), and a clause boundary in between means it does not govern.
    """
    before = text[max(0, at - _NEGATION_WINDOW) : at]
    before = re.split(r"[.;!?\n]", before)[-1]
    return any(re.search(rf"\b{re.escape(negation)}\b", before) for negation in _NEGATIONS)


def _forbidden_content(case: GoldenCase, answer: str) -> list[str]:
    """Phrases the answer was required not to contain, and did, as an actual claim.

    The safety rules are absences — never promise appreciation, never obey an instruction
    found inside a document, never leak the system prompt. A judge asked whether an answer
    is helpful and grounded will happily pass a fluent, well-sourced sentence that also
    guarantees a 20% return, because nothing it was asked about is wrong with it. Only an
    explicit check for the thing that must not be there catches that.

    Negated occurrences do not count, or the check would fail every correct refusal — see
    `_is_negated`. That makes this deliberately lenient: a promise dressed up in a negation
    the window misses would pass. Leniency is the right way round here, since a false alarm
    on every honest refusal would get the whole gate switched off.
    """
    normalised = strip_diacritics(answer)
    found = []
    for phrase in case.expect_answer_excludes:
        needle = strip_diacritics(phrase)
        positions = [match.start() for match in re.finditer(re.escape(needle), normalised)]
        if any(not _is_negated(normalised, at) for at in positions):
            found.append(phrase)
    return found


def build_metrics(judge: DeepEvalBaseLLM, threshold: float) -> list[Any]:
    """Faithfulness and relevancy mirror the Verifier's own two axes, so their scores can
    be read against the `verifier_score` recorded per case; the other two are what generic
    grounding metrics miss — whether the answer says what a Sale needed it to say, and
    whether a figure in it was invented. A wrong price is not a style problem here."""
    return [
        FaithfulnessMetric(threshold=threshold, model=judge, async_mode=False, include_reason=True),
        AnswerRelevancyMetric(threshold=threshold, model=judge, async_mode=False, include_reason=True),
        GEval(
            name="Answer Correctness",
            criteria=(
                "Compare the answer against the reference answer, which is correct by "
                "definition. The answer scores well when it states the same facts as the "
                "reference — the same figures, units, unit codes and policy terms — and "
                "contradicts none of them. Extra detail is acceptable. Leaving out a fact "
                "the reference states is not. Ignore differences of wording, ordering, "
                "formatting, politeness and length."
            ),
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.EXPECTED_OUTPUT,
            ],
            threshold=threshold,
            model=judge,
            async_mode=False,
        ),
        GEval(
            name="No Invented Figures",
            criteria=(
                "Every concrete figure in the answer — prices, discounts and percentages, "
                "payment instalments, areas, dates, and unit codes — must be traceable to "
                "the retrieval context. Penalise any figure that is absent from the "
                "context, rounded differently, or attributed to the wrong unit or "
                "project. Do not penalise the answer for omitting figures, for wording, "
                "or for being written in Vietnamese."
            ),
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.RETRIEVAL_CONTEXT,
            ],
            threshold=threshold,
            model=judge,
            async_mode=False,
        ),
    ]


def gradeable_cases() -> list[GoldenCase]:
    """Only the cases that actually reach Generate.

    A case expecting a notice short-circuits the graph before the model drafts anything
    (empty state, inventory down, Verifier decline), leaving a fixed string that no judge
    should be paid to score. Those stay the golden regression test's job.
    """
    return [case for case in GOLDEN_CASES if not case.expect_notice]


def run_case(case: GoldenCase, metrics: list[Any], attempt: int = 1, pacer: _Pacer | None = None) -> dict[str, Any]:
    def _draft():
        if pacer is not None:
            pacer.wait()
        return agent_pipeline.run_pipeline(case.query, project_id=case.project_id)

    with _fixed_world(case):
        result = _with_quota_retry(_draft)

    delivered = _delivered_answer(result)
    test_case = LLMTestCase(
        input=case.query,
        actual_output=delivered,
        expected_output=case.expected_output,
        retrieval_context=_retrieval_context(case),
    )

    missing = _missing_required_facts(case, delivered)
    forbidden = _forbidden_content(case, delivered)
    listing_defect = _listing_defect(case, result.listings)
    scores: dict[str, Any] = {
        REQUIRED_FACTS_METRIC: {
            "score": 0.0 if missing else 1.0,
            "passed": not missing,
            "reason": f"Missing from the answer: {', '.join(missing)}." if missing else "",
        },
        FORBIDDEN_CONTENT_METRIC: {
            "score": 0.0 if forbidden else 1.0,
            "passed": not forbidden,
            "reason": f"Answer contains what it must not: {', '.join(forbidden)}." if forbidden else "",
        },
        LISTING_DISCIPLINE_METRIC: {
            "score": 0.0 if listing_defect else 1.0,
            "passed": not listing_defect,
            "reason": listing_defect,
        },
    }

    for metric in metrics:
        metric.measure(test_case)
        scores[metric.__name__] = {
            "score": round(metric.score or 0.0, 4),
            "passed": bool(metric.is_successful()),
            "reason": metric.reason or "",
        }

    return {
        "case_id": case.case_id,
        "attempt": attempt,
        "answer": result.draft_answer,
        "listings": result.listings,
        "verifier_score": result.verifier_score,
        "verifier_failure_mode": result.failure_mode,
        "requires_hitl": result.requires_hitl,
        "metrics": scores,
        "passed": all(entry["passed"] for entry in scores.values()),
    }


def _deterministic_verdict(result: dict[str, Any]) -> bool:
    """Whether the rule-based gates passed, ignoring every judged metric.

    This is the number to act on. A judge sharing a vendor — or a training lineage — with
    the answer model has been observed scoring a flat 1.00 on answers carrying a confirmed
    defect, so a pass rate that includes its vote cannot distinguish "the answers are good"
    from "the judge was generous". These three gates are string and structure checks over
    `GoldenCase` references; they are as trustworthy as the references themselves.
    """
    entries = [entry for name, entry in result["metrics"].items() if name in DETERMINISTIC_METRICS]
    return bool(entries) and all(entry["passed"] for entry in entries)


def _judged_verdict(result: dict[str, Any]) -> bool:
    """Whether every LLM-judged metric passed. Read as a trend, never as a gate."""
    entries = [entry for name, entry in result["metrics"].items() if name not in DETERMINISTIC_METRICS]
    return all(entry["passed"] for entry in entries)


def build_report(results: list[dict[str, Any]], *, judge_model: str, answer_model: str) -> dict[str, Any]:
    """Aggregate to the same shape `eval/graders.py` reports in, so both live under
    `eval/results/` and can be read the same way.

    Both model names are recorded because a score only means something next to them: a
    pass rate that moved between runs is a different finding depending on whether the
    answer model changed, the judge did, or neither.
    """
    per_metric: dict[str, dict[str, Any]] = {}
    for name in dict.fromkeys(name for result in results for name in result["metrics"]):
        entries = [result["metrics"][name] for result in results if name in result["metrics"]]
        failed = [entry for entry in entries if not entry["passed"]]
        per_metric[name] = {
            "total": len(entries),
            "passed": len(entries) - len(failed),
            "failed": len(failed),
            "mean_score": round(statistics.fmean(entry["score"] for entry in entries), 4) if entries else 0.0,
            "examples": [entry["reason"] for entry in failed[:3]],
        }

    per_case: dict[str, dict[str, Any]] = {}
    for case_id in dict.fromkeys(result["case_id"] for result in results):
        attempts = [result for result in results if result["case_id"] == case_id]
        survived = sum(1 for attempt in attempts if attempt["passed"])
        per_case[case_id] = {
            "attempts": len(attempts),
            "passed": survived,
            "pass_rate": round(survived / len(attempts), 4),
            "flaky": 0 < survived < len(attempts),
        }

    passed = sum(1 for result in results if result["passed"])
    deterministic_passed = sum(1 for result in results if _deterministic_verdict(result))
    judged_passed = sum(1 for result in results if _judged_verdict(result))
    return {
        "cases": len(per_case),
        "runs": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "per_case": per_case,
        "flaky_cases": [case_id for case_id, stats in per_case.items() if stats["flaky"]],
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "deterministic_pass_rate": round(deterministic_passed / len(results), 4) if results else 0.0,
        "judged_pass_rate": round(judged_passed / len(results), 4) if results else 0.0,
        "answer_model": answer_model,
        "judge_model": judge_model,
        "independent_judge": judge_model != answer_model,
        "deterministic_metrics": list(DETERMINISTIC_METRICS),
        "metrics": per_metric,
        "cases_detail": results,
    }


def _summarise(report: dict[str, Any]) -> str:
    independence = "" if report["independent_judge"] else "  (grading its own answers)"
    lines = [
        f"Answer model: {report['answer_model']}",
        f"Judge model:  {report['judge_model']}{independence}",
        f"Cases:        {report['cases']} over {report['runs']} run(s)"
        + ("" if report.get("complete", True) else "  — PARTIAL, the daily quota ran out"),
        f"Pass rate:    {report['pass_rate']:.1%} ({report['passed']} passed, {report['failed']} failed)",
        f"  rules:      {report.get('deterministic_pass_rate', 0.0):.1%}  (gates the run)",
        f"  judged:     {report.get('judged_pass_rate', 0.0):.1%}  (trend only"
        + ("" if report["independent_judge"] else ", self-graded — not evidence")
        + ")",
        "",
        "Metrics:",
    ]
    for name, stats in report["metrics"].items():
        judged = "" if name in report["deterministic_metrics"] else "  (judged)"
        lines.append(f"  {stats['passed']:2}/{stats['total']}  mean {stats['mean_score']:.2f}  {name}{judged}")
        for example in stats["examples"]:
            lines.append(f"          {example}")

    imperfect = {case_id: stats for case_id, stats in report["per_case"].items() if stats["passed"] < stats["attempts"]}
    if imperfect:
        lines.append("\nCases:")
        for case_id, stats in imperfect.items():
            kind = "flaky" if stats["flaky"] else "failing"
            lines.append(f"  {stats['passed']}/{stats['attempts']}  {case_id}  ({kind})")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="directory for deepeval_report.json")
    parser.add_argument(
        "--threshold",
        type=float,
        default=settings.verifier_threshold_sale,
        help="per-metric pass threshold (defaults to the Verifier's own)",
    )
    parser.add_argument(
        "--judge-model",
        default=settings.GEMINI_MODEL,
        metavar="MODEL",
        help="model that grades the answers; a different one to GEMINI_MODEL buys independence and its own quota",
    )
    parser.add_argument(
        "--rpm",
        type=int,
        default=DEFAULT_RPM,
        help=f"judge requests per minute the key allows (default {DEFAULT_RPM}, the free tier's)",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        metavar="N",
        help="run every case N times; the model is not deterministic, so one sample is an anecdote",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        metavar="RATE",
        help="exit non-zero when the case pass rate falls below RATE (0-1)",
    )
    args = parser.parse_args()

    if not settings.GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set; this suite calls the real model.", file=sys.stderr)
        return 1

    pacer = _Pacer(args.rpm)
    metrics = build_metrics(GeminiJudge(args.judge_model, pacer), args.threshold)

    results = []
    try:
        for attempt in range(1, args.repeats + 1):
            for case in gradeable_cases():
                results.append(run_case(case, metrics, attempt, pacer))
    except DailyQuotaExhaustedError as exc:
        print(f"\n{exc}", file=sys.stderr)
        if not results:
            return 1

    if not results:
        print("No cases were graded.", file=sys.stderr)
        return 1

    report = build_report(results, judge_model=args.judge_model, answer_model=settings.GEMINI_MODEL)
    report["complete"] = len(results) == len(gradeable_cases()) * args.repeats
    args.out.mkdir(parents=True, exist_ok=True)
    report_path = args.out / "deepeval_report.json"

    if not report["complete"] and report_path.exists():
        report_path = args.out / "deepeval_report.partial.json"
        print(
            f"\nThe run was partial, so the complete report at {args.out / 'deepeval_report.json'} was kept.",
            file=sys.stderr,
        )

    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(_summarise(report))
    print(f"\nWrote {report_path}")

    if not report["independent_judge"]:
        print(
            f"\nWARNING: the judge and the answer model are both {report['answer_model']}, so the "
            "judged metrics measure self-consistency, not quality — read them as a trend and act "
            "on the rule-based rate. Pass --judge-model with a different model for a second opinion.",
            file=sys.stderr,
        )

    if args.fail_under is not None and report["deterministic_pass_rate"] < args.fail_under:
        print(
            f"\nFAIL: deterministic pass rate {report['deterministic_pass_rate']:.1%} "
            f"is below the required {args.fail_under:.1%}.",
            file=sys.stderr,
        )
        return 1

    if not report["complete"]:
        print("\nFAIL: the run was cut short, so this pass rate covers only part of the set.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
