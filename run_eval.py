"""
Run offline Weave evaluations against the relatability engine.

Usage:
  python run_eval.py                  # structured Evaluation with scorers
  python run_eval.py --logger         # EvaluationLogger (incremental) path
  python run_eval.py --seed-traces    # generate sample traces for UI monitors

After seeding traces, set up online monitors in the Weave UI:
  1. Open https://wandb.ai → your project → Weave → Monitors → + New Monitor
  2. Select ops: orchestrator_spine, council_vote
  3. Add an LLM judge scorer (see MONITOR_PROMPTS below)
"""

import argparse
import asyncio
import json
from pathlib import Path

import weave
from weave import Evaluation, EvaluationLogger

from app import AnalysisRequest, orchestrator_spine
from scorers import ActionabilityScorer, DossierCompletenessScorer, EvidenceGroundingScorer
from weave_setup import WEAVE_PROJECT, init_weave

MONITOR_PROMPTS = {
    "grounding-monitor": {
        "scorer_name": "grounding-scorer",
        "system_prompt": "You are an impartial AI judge evaluating interview prep dossiers.",
        "scoring_prompt": """Evaluate whether the dossier output is grounded in professional facts
and avoids speculative or overly personal claims.

Input request: {request}
Output dossier: {output}

Return JSON with:
- score: float 0.0-1.0
- reasoning: brief explanation""",
        "ops": ["orchestrator_spine"],
    },
    "actionability-monitor": {
        "scorer_name": "actionability-scorer",
        "system_prompt": "You are an impartial AI judge evaluating interview prep quality.",
        "scoring_prompt": """Rate how actionable and interview-ready the icebreakers,
smart_questions, and trapdoor_project are.

Output dossier: {output}

Return JSON with:
- score: float 0.0-1.0
- reasoning: brief explanation""",
        "ops": ["council_vote"],
    },
}


@weave.op()
def evaluate_orchestrator(
    recruiter_name: str,
    company: str,
    role: str,
    resume_text: str,
    linkedin_url: str = "",
):
    """Wrapper so Evaluation can pass dataset columns as kwargs."""
    request = AnalysisRequest(
        recruiter_name=recruiter_name,
        company=company,
        role=role,
        linkedin_url=linkedin_url,
        resume_text=resume_text,
    )
    return orchestrator_spine(request)


def load_eval_samples() -> list[dict]:
    path = Path(__file__).parent / "eval_data" / "samples.json"
    return json.loads(path.read_text())


async def run_structured_eval() -> dict:
    """Standard Evaluation framework with predefined dataset + scorers."""
    samples = load_eval_samples()
    evaluation = Evaluation(
        dataset=samples,
        scorers=[
            DossierCompletenessScorer(),
            EvidenceGroundingScorer(),
            ActionabilityScorer(),
        ],
        evaluation_name="relatability-engine-offline-eval",
    )
    return await evaluation.evaluate(evaluate_orchestrator)


def run_logger_eval() -> None:
    """EvaluationLogger path — logs predictions and scores incrementally."""
    samples = load_eval_samples()
    eval_logger = EvaluationLogger(
        model="relatability-engine",
        dataset="eval_data/samples.json",
    )

    for sample in samples:
        with eval_logger.log_prediction(inputs=sample) as pred:
            output = evaluate_orchestrator(**sample)
            pred.output = output

            completeness = DossierCompletenessScorer().score(output=output)
            pred.log_score("completeness", completeness["score"])

            grounding = EvidenceGroundingScorer().score(output=output)
            pred.log_score("grounding", grounding["score"])

            actionability = ActionabilityScorer().score(output=output)
            pred.log_score("actionability", actionability["score"])

    eval_logger.log_summary({"eval_type": "evaluation_logger", "samples": len(samples)})
    print("EvaluationLogger run complete. View results in the Weave UI.")


def seed_traces() -> None:
    """Run sample requests so ops appear in Weave for monitor setup."""
    for sample in load_eval_samples():
        evaluate_orchestrator(**sample)
    print(f"Seeded traces for project '{WEAVE_PROJECT}'.")
    print("Configure online monitors in Weave UI → Monitors → + New Monitor")
    print("Suggested monitor configs:")
    print(json.dumps(MONITOR_PROMPTS, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Weave evaluations")
    parser.add_argument(
        "--logger",
        action="store_true",
        help="Use EvaluationLogger instead of structured Evaluation",
    )
    parser.add_argument(
        "--seed-traces",
        action="store_true",
        help="Generate sample traces for online monitor setup in Weave UI",
    )
    args = parser.parse_args()

    init_weave()

    if args.seed_traces:
        seed_traces()
    elif args.logger:
        run_logger_eval()
    else:
        summary = asyncio.run(run_structured_eval())
        print("Structured evaluation complete.")
        print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
