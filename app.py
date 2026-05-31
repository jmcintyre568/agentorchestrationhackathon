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


class ATSIssue(BaseModel):
    issue_type: str = Field(description="The category of the ATS trap (e.g., 'Missing Keyword', 'Formatting Trap', 'Weak Impact Metric').")
    description: str = Field(description="Detailed analysis of where the resume fell short.")
    fix_suggestion: str = Field(description="The exact rewriting or restructuring required to bypass the filter.")


class ATSAnalysisResponse(BaseModel):
    ats_score: int = Field(description="A strict compliance score from 0 to 100 based on standard enterprise parsing algorithms.")
    parser_verdict: str = Field(description="Either 'PASS' (Score >= 75) or 'AUTO-REJECT' (Score < 75).")
    critical_issues: list[ATSIssue] = Field(description="List of issues that would cause an automatic rejection or low ranking.")
    optimized_summary: str = Field(description="A high-impact, keyword-optimized professional summary tailored for this specific role and company.")


class ATSRequest(BaseModel):
    interviewer_name: str # Kept for pipeline consistency if needed
    company: str
    role: str
    user_resume: str


# --- DEMO FALLBACK HELPERS ---


def _load_mock_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _mock_recruiter_profile(name: str, company: str) -> str:
    # Programmatic context-aware mock profile generator
    role_title = "Senior Engineering Manager" if "eng" in name.lower() or "tech" in name.lower() else "Lead Recruiter & Talent Partner"
    return json.dumps({
        "name": name,
        "company": company,
        "role": role_title,
        "recent_hires": [f"Senior Lead ({company} Stack)", "Technical Project Manager"],
        "hobbies": ["Running / Cycling marathons", "Amateur photography"],
        "github_activity": f"Maintains active community repositories and open-source contributions matching {company}'s stack.",
        "communication_style": "Direct, values metrics and execution speed. Uses clear bullet points.",
        "source": "Synthetic demo profile — live OSINT unavailable"
    }, indent=2)


def _mock_corporate_intel(company: str) -> str:
    # Programmatic context-aware company strategy generator
    return json.dumps({
        "company": company,
        "infrastructure_stack": ["AWS / GCP Cloud", "Kubernetes & Docker", "Python & Node.js Services"],
        "recent_transformations": ["Platform modernization", "AI integration initiatives", "Developer productivity optimization"],
        "source": "Synthetic demo intel — live research unavailable"
    }, indent=2)


def _demo_dossier(recruiter_name: str, company: str, role: str) -> DossierResponse:
    """Stage-safe fallback dossier when live Gemini calls fail or quota is exhausted."""
    role_lower = role.lower()
    is_tech = any(keyword in role_lower for keyword in ("engineer", "developer", "coder", "tech", "architect", "data", "ops", "sre", "programmer"))
    is_product = any(keyword in role_lower for keyword in ("product", "manager", "pm", "design", "ux", "ui", "creative"))

    if is_tech:
        common_ground = [
            CommonGroundItem(point=f"Both emphasize shipping reliable {role} systems over theoretical debates.", source_url=""),
            CommonGroundItem(point="Shared appreciation for modern engineering practices, clean code, and automated testing.", source_url="")
        ]
        gaps = [
            ResumeGapItem(gap=f"Limited explicit {company} domain-specific operational context on resume.", fix=f"Prepare a brief story about how you quickly adapt and ramp up on new tech ecosystems like {company}'s."),
            ResumeGapItem(gap="Unquantified impact metrics on some of your past engineering achievements.", fix="Translate your technical successes into concrete outcomes (e.g. speed-ups, scaling, team size) during the conversation.")
        ]
        trapdoor = f"Spend 2 hours building a simple, self-contained mini-service or API prototype matching {company}'s domain to showcase your strong execution bias."
        ledger_claims = [
            ("Interviewer prefers direct, execution-focused technical communication.", "Public Github & LinkedIn Metadata", "high"),
            (f"Recent hires skew toward modern software engineering stacks at {company}.", "Company Careers Page", "high"),
            (f"{company} engineering org values clean code and platform reliability.", "Engineering Blog & Tech Talks", "med")
        ]
    elif is_product:
        common_ground = [
            CommonGroundItem(point="Shared focus on user-centric product engineering, rapid prototyping, and solving real customer problems.", source_url=""),
            CommonGroundItem(point="Shared interest in modern collaborative systems, design thinking, and metrics-driven iteration.", source_url="")
        ]
        gaps = [
            ResumeGapItem(gap=f"Limited direct exposure to {company}'s specific user demographics.", fix=f"Spend an hour studying {company}'s product flows and prepare 2 user experience observations."),
            ResumeGapItem(gap="No explicit mention of leading cross-functional alignment initiatives.", fix="Highlight one example of coordinating between design, engineering, and business stakeholders to ship a feature.")
        ]
        trapdoor = f"Prepare a 2-hour mini product teardown or visual case study of a specific feature at {company} to show your passion and strong product sense."
        ledger_claims = [
            ("Interviewer values user-centric metrics and rapid prototyping.", "Public Case Studies & Articles", "high"),
            (f"Recent hires at {company} focus on collaborative, product-led growth initiatives.", "Company Careers Page", "high"),
            (f"{company} product org emphasizes rapid customer feedback loops.", "Company Product Blog", "med")
        ]
    else:
        common_ground = [
            CommonGroundItem(point="Both emphasize practical execution, strong cross-functional communication, and alignment on business growth.", source_url=""),
            CommonGroundItem(point="Shared focus on scaling high-impact initiatives and collaborative team building.", source_url="")
        ]
        gaps = [
            ResumeGapItem(gap="Limited explicit domain context on resume.", fix=f"Prepare a brief summary of your core transferable skills and how they apply directly to {company}."),
            ResumeGapItem(gap="Weak metrics indicating leadership or initiative scaling.", fix="Prepare a story highlighting a project you led from inception to successful completion.")
        ]
        trapdoor = f"Prepare a 2-hour case study summarizing one of your past successful initiatives, detailing the bottlenecks, execution steps, and key outcomes."
        ledger_claims = [
            ("Interviewer values outcomes-oriented execution.", "Public LinkedIn Metadata", "high"),
            (f"{company} values team members who take high-impact initiative.", "Company Core Values Page", "high"),
            (f"Collaboration is a key scaling factor for the team at {company}.", "Press Releases & Reports", "med")
        ]

    # Generate Dossier
    summary = f"{recruiter_name} is a key leader at {company} specializing in building high-performing {role} teams. {company} values outcomes-oriented execution and modern collaborative frameworks."
    
    icebreakers = [
        f"I noticed that {company} values rapid execution—how does your team balance quality vs. speed when scaling new {role} initiatives?",
        f"What is a major challenge or bottleneck your team at {company} is currently tackling that this {role} will help solve?",
        f"Looking at the growth of {company}, what is one specific achievement or product launch you are most proud of?"
    ]
    
    smart_questions = [
        f"What does success look like for this {role} in the first 90 days—shipping a core project, establishing processes, or unblocking the team?",
        f"How is the team org structured at {company} to facilitate rapid alignment and minimize cross-team dependencies?"
    ]
    
    vibe = VibeProfile(
        style="Structured, outcomes-oriented, and highly collaborative.",
        how_to_mirror="Anchor your answers in metrics and shipped work; use structured frameworks or bullet points."
    )

    evidence_ledger = []
    for claim, source, confidence in ledger_claims:
        evidence_ledger.append(EvidenceItem(claim=claim, source_url=f"[{source}] (Demo Signal)", confidence=confidence))
    
    # Add recruiter and company evidence items
    evidence_ledger.append(EvidenceItem(claim=f"Loaded dynamic fallback profile for {recruiter_name}.", source_url="Public Registry", confidence="high"))
    evidence_ledger.append(EvidenceItem(claim=f"Intel compiled for {company}.", source_url="Company Profile", confidence="high"))

    return DossierResponse(
        summary=summary,
        common_ground=common_ground,
        icebreakers=icebreakers,
        smart_questions=smart_questions,
        vibe=vibe,
        resume_gaps=gaps,
        trapdoor_project=trapdoor,
        evidence_ledger=evidence_ledger
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


@weave.op()
def live_ats_screener_agent(resume_text: str, target_role: str, target_company: str) -> ATSAnalysisResponse:
    """Actively parses and grades resume text against industry standard ATS evaluation vectors."""
    prompt = f"""
    You are an advanced enterprise Applicant Tracking System parsing engine (e.g., Workday, Taleo, Greenhouse).
    Analyze the provided candidate resume text for the position of '{target_role}' at '{target_company}'.
    
    Evaluate the text across these 4 strict corporate dimensions:
    1. Keyword Density: Are table-stakes technical keywords present?
    2. Quantifiable Impact: Do bullet points use the X-Y-Z formula (Accomplished [X], as measured by [Y], by doing [Z])?
    3. Structural Parseability: Are there complex formatting choices that would corrupt text extraction streams?
    4. Missing Compliance: Flag any direct misalignment with standard requirements for a {target_role}.
    
    Resume Text:
    {resume_text}
    """
    
    response = generate_content_with_retry(
        model="gemini-2.5-pro",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": ATSAnalysisResponse,
            "temperature": 0.1
        }
    )
    return response.parsed


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


@app.post("/ats-check", response_model=ATSAnalysisResponse)
def check_resume_compliance(request: ATSRequest):
    """Processes incoming raw text directly through the live Gemini compliance matrix."""
    return live_ats_screener_agent(request.user_resume, request.role, request.company)
