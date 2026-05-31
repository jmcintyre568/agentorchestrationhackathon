import json
import os
import random
import time
from pathlib import Path
from typing import Literal, Optional

import weave
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from google import genai
from google.genai import errors as genai_errors
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from weave_setup import init_weave

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
MOCK_RECRUITER_PATH = BASE_DIR / "mock_data" / "recruiter.json"
MOCK_CORP_INTEL_PATH = BASE_DIR / "mock_data" / "company_intel.json"
MOCK_DOSSIER_PATH = BASE_DIR / "mock_data" / "demo_dossier.json"

init_weave()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

app = FastAPI(title="Relatability Engine")

# Wildcard origins require allow_credentials=False (browser CORS spec).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_index():
    return FileResponse(BASE_DIR / "static" / "index.html")

# --- SCHEMAS (aligned with Lovable frontend Dossier type) ---


class CommonGroundItem(BaseModel):
    point: str = Field(description="A specific shared-interest or alignment point.")
    source_url: str = Field(
        default="",
        description="URL when available; leave empty for named sources like 'Public LinkedIn Metadata'.",
    )


class VibeProfile(BaseModel):
    style: str = Field(description="Communication style of the interviewer.")
    how_to_mirror: str = Field(description="How the candidate should mirror that style.")


class ResumeGapItem(BaseModel):
    gap: str = Field(description="Missing qualification or experience gap.")
    fix: str = Field(description="Concrete action to close the gap before the interview.")


class EvidenceItem(BaseModel):
    claim: str = Field(description="A factual claim used anywhere in the dossier.")
    source_url: str = Field(
        default="",
        description="Verifiable URL when available, else empty string.",
    )
    confidence: Literal["high", "med", "low"] = Field(
        description="Confidence that the claim is grounded in the cited source."
    )


class DossierResponse(BaseModel):
    summary: str = Field(description="A 2-sentence executive summary of the target.")
    common_ground: list[CommonGroundItem] = Field(
        description="Shared interests or alignment points between candidate and interviewer."
    )
    icebreakers: list[str] = Field(description="3 highly specific professional conversation starters.")
    smart_questions: list[str] = Field(description="2 high-impact reverse-engineering questions to ask.")
    vibe: VibeProfile = Field(description="Communication style analysis and mirroring guidance.")
    resume_gaps: list[ResumeGapItem] = Field(
        description="Missing qualifications compared to recent team trends, each with a fix."
    )
    trapdoor_project: str = Field(
        description="A 2-hour mini-project to close the gap before the interview."
    )
    evidence_ledger: list[EvidenceItem] = Field(
        description="Every dossier claim mapped to a professional source with confidence."
    )


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    recruiter_name: str = Field(
        validation_alias=AliasChoices("recruiter_name", "interviewer_name")
    )
    company: str
    role: str
    linkedin_url: str = ""
    resume_text: str = Field(
        validation_alias=AliasChoices("resume_text", "user_resume")
    )


# --- DEMO FALLBACK HELPERS ---


def _load_mock_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _mock_recruiter_profile(name: str, company: str) -> str:
    data = _load_mock_json(MOCK_RECRUITER_PATH)
    if data:
        data = {**data, "name": name, "company": company}
        return json.dumps(data, indent=2)
    return json.dumps(
        {
            "name": name,
            "company": company,
            "role": "Senior Engineering Manager",
            "communication_style": "Direct, values execution over theory. Uses bullet points.",
            "github_activity": "Open-source contributions in web frameworks.",
            "source": "Synthetic demo profile — live OSINT unavailable",
        },
        indent=2,
    )


def _mock_corporate_intel(company: str) -> str:
    data = _load_mock_json(MOCK_CORP_INTEL_PATH)
    if data:
        data = {**data, "company": company}
        return json.dumps(data, indent=2)
    return json.dumps(
        {
            "company": company,
            "infrastructure_stack": ["AWS", "Kubernetes", "Python"],
            "recent_transformations": ["Platform modernization", "AI tooling adoption"],
            "source": "Synthetic demo intel — live research unavailable",
        },
        indent=2,
    )


def _demo_dossier(recruiter_name: str, company: str, role: str) -> DossierResponse:
    """Stage-safe fallback dossier when live Gemini calls fail or quota is exhausted."""
    data = _load_mock_json(MOCK_DOSSIER_PATH)
    if data:
        dossier = DossierResponse.model_validate(data)
        dossier.summary = (
            f"{recruiter_name} at {company} ({role}): "
            + dossier.summary.split(". ", 1)[-1]
        )
        return dossier
    return DossierResponse(
        summary=f"Demo dossier for {recruiter_name} at {company} ({role}). Live synthesis unavailable.",
        common_ground=[CommonGroundItem(point="Shared focus on shipping production software.", source_url="")],
        icebreakers=[
            f"What does the {role} team prioritize this quarter at {company}?",
            "How does your engineering org balance speed vs. reliability?",
            "What's a recent project you're proud of on the team?",
        ],
        smart_questions=[
            "What would success look like in the first 90 days?",
            "What's the biggest technical bottleneck the team is tackling now?",
        ],
        vibe=VibeProfile(
            style="Professional and direct.",
            how_to_mirror="Be concise, cite shipped work, and ask focused follow-ups.",
        ),
        resume_gaps=[
            ResumeGapItem(gap="Gap analysis unavailable offline.", fix="Review the job description against your resume.")
        ],
        trapdoor_project="Prepare a 2-hour portfolio artifact aligned to the job description.",
        evidence_ledger=[
            EvidenceItem(
                claim=f"Demo profile loaded for {recruiter_name}.",
                source_url="",
                confidence="low",
            )
        ],
    )


def generate_content_with_retry(model: str, contents: str, config=None, max_retries=5, initial_delay=2.0):
    """Call Gemini client.models.generate_content with robust retries, backoff, and model fallback."""
    delay = initial_delay
    last_error = None
    for attempt in range(max_retries):
        try:
            kwargs = {"model": model, "contents": contents}
            if config:
                kwargs["config"] = config
            response = client.models.generate_content(**kwargs)
            return response
        except (genai_errors.APIError, genai_errors.ClientError, Exception) as e:
            last_error = e
            err_str = str(e).lower()
            is_quota_or_demand = "429" in err_str or "resource_exhausted" in err_str or "503" in err_str or "unavailable" in err_str
            
            # If we hit a daily limit (Requests Per Day limit), retry is useless. Skip delay and raise instantly so we fall back to mock data immediately.
            is_daily_limit = "perday" in err_str or "limit: 0" in err_str or "limit: 20" in err_str or "limit: 50" in err_str or "day" in err_str
            
            if is_quota_or_demand and not is_daily_limit and attempt < max_retries - 1:
                sleep_time = delay + random.uniform(0.1, 1.0)
                print(f"[Gemini Retry] {model} failed on attempt {attempt+1}/{max_retries} due to quota/demand. Retrying in {sleep_time:.2f}s... Error: {e}")
                time.sleep(sleep_time)
                delay *= 2
            else:
                if model != "gemini-2.5-flash":
                    print(f"[Gemini Fallback] Pro model failed. Falling back to gemini-2.5-flash...")
                    return generate_content_with_retry("gemini-2.5-flash", contents, config, max_retries, initial_delay)
                raise e
    raise last_error if last_error else RuntimeError("Gemini content generation failed after max retries")


def _generate_with_fallback(model: str, contents: str, config=None) -> str:
    """Call Gemini; on quota/API failure retry with flash, then raise."""
    response = generate_content_with_retry(model, contents, config)
    return response.text or ""


EVIDENCE_LEDGER_RULES = """
EVIDENCE LEDGER (required anti-hallucination contract):
- Populate evidence_ledger with at least 5 entries.
- Every substantive claim in summary, common_ground, icebreakers, smart_questions,
  vibe, resume_gaps, and trapdoor_project MUST appear as a claim in evidence_ledger.
- Each entry needs confidence: "high" (direct public source), "med" (inferred from context),
  or "low" (weak signal — avoid unless necessary).
- source_url: use a real URL when available; otherwise leave "" and ensure the claim text
  prefixes the source type, e.g. "[GitHub Activity] Maintains Next.js boilerplate repos."
- Allowed source types: GitHub Activity, Public LinkedIn Metadata, Company Careers Page,
  Q3 Corporate Report, Engineering Blog, Conference Talk, SEC Filing, Press Release.
- Do NOT invent personal details (family, address, politics). Professional facts only.
"""


# --- SUBAGENTS ---


@weave.op()
def networker_subagent(name: str, company: str, linkedin_url: str = "") -> str:
    """Researches public professional footprints using Google Search Grounding; falls back to mock."""
    prompt = f"""
    Search the web for professional footprint and digital footprint details of {name} who works at {company}.
    Extract their public GitHub projects, open-source work, conference talks, professional hobbies, and communication style.
    Be extremely concise and professional. Return findings in a structured text layout.
    """
    try:
        response = generate_content_with_retry(
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "tools": [{"google_search": {}}],
                "temperature": 0.2
            }
        )
        return response.text or _mock_recruiter_profile(name, company)
    except Exception as e:
        print(f"[Search Warning] Google Search Grounding failed: {e}. Falling back to mock recruiter.")
        profile = _mock_recruiter_profile(name, company)
        if linkedin_url:
            profile = json.dumps(
                {**json.loads(profile), "linkedin_url": linkedin_url},
                indent=2,
            )
        return profile


@weave.op()
def corporate_intel_subagent(company: str) -> str:
    """Analyzes company stack and recent moves; falls back to mock intel on API failure."""
    prompt = (
        f"Identify the primary infrastructure stack, recent technical transformations, "
        f"and engineering bottlenecks at {company}. Be concise and factual."
    )
    try:
        response = generate_content_with_retry(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text or _mock_corporate_intel(company)
    except (genai_errors.APIError, genai_errors.ClientError, Exception):
        return _mock_corporate_intel(company)


# --- COUNCIL CONSENSUS ---


@weave.op()
def council_vote(
    osint: str,
    corp: str,
    resume: str,
    recruiter_name: str,
    company: str,
    role: str,
) -> DossierResponse:
    """Pro (depth) + Flash (speed) proposals, then Pro judge merges into structured dossier."""

    base_instruction = f"""
    You are an elite talent strategist building an interview dossier.
    Ground everything strictly in professional facts from the inputs below.
    Do not surface overly personal details.

    Recruiter: {recruiter_name}
    Company: {company}
    Role: {role}
    OSINT Profile: {osint}
    Company Strategy: {corp}
    Candidate Resume: {resume}

    {EVIDENCE_LEDGER_RULES}
    """

    try:
        proposal_a = _generate_with_fallback(
            "gemini-2.5-pro",
            base_instruction
            + "\nFocus on deep structural alignment, resume gaps with fixes, and evidence mapping.",
        )

        proposal_b = _generate_with_fallback(
            "gemini-2.5-flash",
            base_instruction
            + "\nFocus on actionable icebreakers, smart questions, and common ground.",
        )

        judge_prompt = f"""
        You are the final judge merging two analyst proposals into one definitive dossier.
        Prefer facts present in both proposals. Drop speculative or intrusive content.
        Ensure evidence_ledger covers every major claim with source attribution.

        Proposal A (Pro — analytical depth):
        {proposal_a}

        Proposal B (Flash — actionable speed):
        {proposal_b}

        Return JSON matching the required schema exactly.
        """

        judge_config = {
            "response_mime_type": "application/json",
            "response_schema": DossierResponse,
            "temperature": 0.2,
        }
        for judge_model in ("gemini-2.5-pro", "gemini-2.5-flash"):
            try:
                final_output = generate_content_with_retry(
                    model=judge_model,
                    contents=judge_prompt,
                    config=judge_config,
                )
                if final_output.parsed is not None:
                    return final_output.parsed
            except (genai_errors.APIError, genai_errors.ClientError):
                continue

        raise ValueError("Judge model returned unparseable dossier")
    except (genai_errors.APIError, genai_errors.ClientError, ValueError, Exception):
        return _demo_dossier(recruiter_name, company, role)


@weave.op()
def orchestrator_spine(request: AnalysisRequest) -> DossierResponse:
    """Supervisor: OSINT → corporate intel → council consensus → dossier."""
    intel_footprint = networker_subagent(
        request.recruiter_name, request.company, request.linkedin_url
    )
    company_bottlenecks = corporate_intel_subagent(request.company)
    return council_vote(
        intel_footprint,
        company_bottlenecks,
        request.resume_text,
        request.recruiter_name,
        request.company,
        request.role,
    )


# --- ENDPOINTS ---


@app.get("/health")
def health():
    return {"status": "ok", "service": "relatability-engine"}


@weave.op()
def analyze_candidate(request: AnalysisRequest) -> DossierResponse:
    return orchestrator_spine(request)


@app.post("/analyze", response_model=DossierResponse)
def analyze_endpoint(request: AnalysisRequest):
    return analyze_candidate(request)
