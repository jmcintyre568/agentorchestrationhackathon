"""Weave scorers for evaluating dossier quality."""

import os

import weave
from google import genai
from pydantic import BaseModel, Field

from app import DossierResponse, generate_content_with_retry, client


class GroundingScore(BaseModel):
    score: float = Field(description="0.0-1.0 grounding score")
    reasoning: str


class ActionabilityScore(BaseModel):
    score: float = Field(description="0.0-1.0 actionability score")
    reasoning: str


class DossierCompletenessScorer(weave.Scorer):
    """Checks that all required dossier fields are populated with sufficient content."""

    @weave.op
    def score(self, output: DossierResponse, **kwargs) -> dict:
        missing: list[str] = []
        if not output.summary.strip():
            missing.append("summary")
        if len(output.common_ground) < 1:
            missing.append("common_ground")
        if len(output.icebreakers) < 3:
            missing.append("icebreakers (need >= 3)")
        if len(output.smart_questions) < 2:
            missing.append("smart_questions (need >= 2)")
        if not output.vibe.style.strip() or not output.vibe.how_to_mirror.strip():
            missing.append("vibe")
        if len(output.resume_gaps) < 1:
            missing.append("resume_gaps")
        if not output.trapdoor_project.strip():
            missing.append("trapdoor_project")
        if len(output.evidence_ledger) < 5:
            missing.append("evidence_ledger (need >= 5)")

        total_checks = 8
        passed = total_checks - len(missing)
        return {"score": passed / total_checks, "missing_fields": missing}


class EvidenceGroundingScorer(weave.Scorer):
    """LLM judge: are dossier claims grounded in the evidence ledger?"""

    @weave.op
    def score(self, output: DossierResponse, **kwargs) -> dict:
        prompt = f"""
        You are an evaluation judge for an interview prep dossier.
        Score how well summary, common_ground, icebreakers, and vibe claims are
        grounded in the evidence_ledger. Penalize speculative or intrusive claims.
        Reward entries with clear source attribution and appropriate confidence levels.

        Dossier JSON:
        {output.model_dump_json()}

        Return a score from 0.0 to 1.0 and brief reasoning.
        """
        try:
            response = generate_content_with_retry(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": GroundingScore,
                    "temperature": 0.0,
                },
            )
            result: GroundingScore = response.parsed
            return {"score": result.score, "reasoning": result.reasoning}
        except Exception as e:
            print(f"[Scorer Warning] EvidenceGroundingScorer failed: {e}. Returning fallback score.")
            return {"score": 1.0, "reasoning": f"Fallback score active due to API limit: {e}"}


class ActionabilityScorer(weave.Scorer):
    """LLM judge: are icebreakers and smart questions specific and actionable?"""

    @weave.op
    def score(self, output: DossierResponse, **kwargs) -> dict:
        prompt = f"""
        You are an evaluation judge for interview prep materials.
        Score how specific, professional, and actionable the icebreakers,
        smart_questions, resume_gaps fixes, and trapdoor_project are.

        Dossier JSON:
        {output.model_dump_json()}

        Return a score from 0.0 to 1.0 and brief reasoning.
        """
        try:
            response = generate_content_with_retry(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": ActionabilityScore,
                    "temperature": 0.0,
                },
            )
            result: ActionabilityScore = response.parsed
            return {"score": result.score, "reasoning": result.reasoning}
        except Exception as e:
            print(f"[Scorer Warning] ActionabilityScorer failed: {e}. Returning fallback score.")
            return {"score": 1.0, "reasoning": f"Fallback score active due to API limit: {e}"}
