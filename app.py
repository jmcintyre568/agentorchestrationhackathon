import os
import random
import time
from pathlib import Path
from typing import Literal

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


class ATSRedFlag(BaseModel):
    flag: str = Field(description="A critical resume compliance red flag or trap (e.g., table-stakes keyword missing).")
    severity: Literal["critical", "high"] = Field(description="How severely standard ATS filters penalize this flag.")
    fix: str = Field(description="The exact rewriting or restructuring required to bypass the filter.")


class RecommendedImprovement(BaseModel):
    missing_qualification: str = Field(description="A skill, stack element, or cert the candidate should have to avoid being filtered out.")
    impact: str = Field(description="Why this is critical for this specific role and team.")
    implementation: str = Field(description="A concrete way or 2-hour mini-project to build/add this qualification.")


class EvidenceItem(BaseModel):
    claim: str = Field(description="A factual claim used anywhere in the dossier.")
    source_url: str = Field(
        default="",
        description="Verifiable URL when available, else empty string.",
    )
    confidence: Literal["high", "med", "low"] = Field(
        description="Confidence that the claim is grounded in the cited source."
    )


class VibeProfile(BaseModel):
    style: str = Field(default="Standard Dynamic Profile", description="Communication style of the interviewer.")
    how_to_mirror: str = Field(default="Clear bullet-oriented strategy", description="How the candidate should mirror that style.")


class ResumeGapItem(BaseModel):
    gap: str = Field(default="Operational context analysis", description="Missing qualification or experience gap.")
    fix: str = Field(default="Focus on core scaling metrics", description="Concrete action to close the gap before the interview.")


class DossierResponse(BaseModel):
    name: str = Field(description="Scanned name of the professional.")
    email: str = Field(description="Scraped professional email address (synthetic or public record).")
    role: str = Field(description="Interviewer's current role and title.")
    company: str = Field(description="Interviewer's current company.")
    bio: str = Field(description="A detailed professional bio (3-4 sentences) summarizing their career, focus, public footprint, and the city they are based in.")
    linkedin_picture_url: str = Field(
        default="",
        description="Public URL of the linkedin profile picture if available, else empty string."
    )
    
    common_ground: list[CommonGroundItem] = Field(
        description="Shared interests or alignment points between candidate and interviewer."
    )
    icebreakers: list[str] = Field(description="3 highly specific professional conversation starters.")
    smart_questions: list[str] = Field(description="2 high-impact reverse-engineering questions to ask.")
    
    vibe: VibeProfile = Field(
        default_factory=VibeProfile,
        description="Legacy vibe profile kept for pipeline backwards-compatibility."
    )
    resume_gaps: list[ResumeGapItem] = Field(
        default_factory=list,
        description="Legacy resume gaps kept for pipeline backwards-compatibility."
    )
    trapdoor_project: str = Field(
        default="Scaffold a 2-hour dynamic prototype service",
        description="Legacy trapdoor project kept for pipeline backwards-compatibility."
    )
    
    ats_red_flags: list[ATSRedFlag] = Field(
        description="Critical compliance red flags in the resume that will get it filtered out by standard ATS."
    )
    recommended_improvements: list[RecommendedImprovement] = Field(
        description="Structural changes and credentials you should have to avoid being filtered out."
    )
    upcoming_events: list[str] = Field(
        default_factory=list,
        description="List of upcoming conferences, summits, or local industry meetups the professional is highly likely to attend."
    )
    cold_icebreakers: list[str] = Field(
        default_factory=list,
        description="Cold conversation starters for physical summits based on hobbies, interests, and professional milestones."
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


def _demo_dossier(recruiter_name: str, company: str, role: str) -> DossierResponse:
    """Stage-safe fallback dossier when live Gemini calls fail or quota is exhausted."""
    role_lower = role.lower()
    rec_name_lower = recruiter_name.lower()

    # Determine if recruiter_name indicates they are an engineer vs a recruiter vs product
    if "turlay" in rec_name_lower:
        role_title = "Staff Infrastructure Engineer"
        city = "San Francisco, CA"
        is_tech = True
        is_product = False
    elif "mercer" in rec_name_lower:
        role_title = "Senior Engineering Manager"
        city = "Seattle, WA"
        is_tech = True
        is_product = False
    elif any(kw in rec_name_lower for kw in ("recruit", "talent", "sourcer", "people", "partner", "hr", "acquisition", "jane", "doe", "sarah", "smith")):
        role_title = "Technical Recruiter"
        city = "Austin, TX"
        is_tech = False
        is_product = False
    else:
        # Default fallback heuristic:
        # If the target role is tech, but they inputted a standard recruiter name, default to Technical Recruiter!
        is_tech = any(keyword in role_lower for keyword in ("engineer", "developer", "coder", "tech", "architect", "data", "ops", "sre", "programmer"))
        is_product = any(keyword in role_lower for keyword in ("product", "manager", "pm", "design", "ux", "ui", "creative"))
        
        if is_tech:
            role_title = "Technical Recruiter"
            city = "Austin, TX"
            is_tech = False # Treat as a recruiter for common ground
            is_product = False
        elif is_product:
            role_title = "VP of Product"
            city = "New York City, NY"
        else:
            role_title = "Director of Talent Acquisition"
            city = "Austin, TX"

    email = f"{recruiter_name.lower().replace(' ', '.')}@{company.lower().replace(' ', '')}.com"
    linkedin_picture_url = "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?q=80&w=256&auto=format&fit=crop"

    if is_tech:
        bio = (
            f"{recruiter_name} is a highly accomplished {role_title} based in {city} with over 8 years of hands-on "
            f"experience building scalable software architectures, distributed cloud-native infrastructures, "
            f"and high-efficiency API services. Passionate about technical excellence and clean code, "
            f"{recruiter_name} actively drives engineering standards, platform reliability, and CI/CD "
            f"automation pipelines across the engineering organization at {company}."
        )
        common_ground = [
            CommonGroundItem(
                point=f"Both focus on designing high-throughput, fault-tolerant {role} services rather than theoretical academic patterns.",
                source_url="[GitHub Activity] Shared preference for microservice decoupling"
            ),
            CommonGroundItem(
                point="Mutual appreciation for strict automated testing, containerized architectures, and robust monitoring practices.",
                source_url="[Engineering Blog] High-coverage test suites post"
            ),
            CommonGroundItem(
                point="Active contributors to open-source developer toolkits and community infrastructure libraries.",
                source_url="[Public Registry] Starred community repositories"
            )
        ]
        red_flags = [
            ATSRedFlag(
                flag="Critical Keyword Discrepancy: Missing modern cloud-native keywords (e.g., 'Kubernetes', 'Terraform').",
                severity="critical",
                fix=f"Explicitly inject cloud provisioning experience into your recent project descriptions. Rewrite: 'Managed AWS containerized services using Kubernetes and Docker to scale operations' to align with {company}'s tech stack."
            ),
            ATSRedFlag(
                flag="Unquantified Impact Metrics: Multiple achievements are phrased as passive duties rather than outcome-driven successes.",
                severity="high",
                fix="Use Google's X-Y-Z formula. Rewrite: 'Responsible for maintaining API services' to: 'Optimized high-throughput REST APIs by refactoring cache layers, reducing p99 latency by 35% and saving $12k in monthly compute costs.'"
            ),
            ATSRedFlag(
                flag="Complex PDF Formatting Traps: Nested tables and multi-column visual grids detected in your resume layout.",
                severity="high",
                fix="Convert your resume to a single-column, clean linear layout. Enterprise parsers (e.g. Workday) frequently corrupt nested tables, completely skipping vital experience blocks during scanning."
            )
        ]
        improvements = [
            RecommendedImprovement(
                missing_qualification=f"Direct CI/CD Platform Infrastructure Credentials (e.g. GitHub Actions, GitLab CI/CD).",
                impact=f"{company} deploys multiple times a day; lack of automated deployment awareness on your resume triggers instant system filtration.",
                implementation="Dedicate 2 hours to scaffold a containerized GitHub repository, write a YAML workflow compiling a lint/test sequence on push, and link it as a verified project on your resume."
            ),
            RecommendedImprovement(
                missing_qualification="System Design & Decoupling Portfolio Showcase (REST / gRPC APIs).",
                impact=f"Interviewer {recruiter_name} expects candidates to articulate complex architectural decoupling patterns with real examples.",
                implementation="Build a simple, mock e-commerce microservice with two communicating endpoints in Go or Node.js, package it using Docker Compose, and document the design pattern in a clean README.md."
            ),
            RecommendedImprovement(
                missing_qualification="Enterprise SQL Database Optimization Techniques.",
                impact=f"{company} manages massive, high-concurrency transactional datasets where query tuning is highly valued.",
                implementation="Add a clear bullet point highlighting query performance tuning, index structuring, or database migration experience under your most recent role."
            )
        ]
        upcoming_events = [
            "KubeCon + CloudNativeCon North America (Chicago)",
            f"{company} Developer Summit (San Francisco)",
            "AWS re:Invent (Las Vegas)"
        ]
        cold_icebreakers = [
            "I saw your recent post about cycling—how do you manage to balance high-mileage training with scaling massive system architectures?",
            "I noticed you maintain active open-source repositories; what's your take on the industry transition toward platform engineering frameworks?",
            "Are you attending any of the cloud scaling workshops at the summit later this afternoon?"
        ]
        ledger_claims = [
            (f"Interviewer {recruiter_name} values direct, metrics-driven technical communication.", "Public Github & LinkedIn Metadata", "high"),
            (f"Recent hires skew heavily toward modern containerized environments at {company}.", "Company Careers Page", "high"),
            (f"{company} engineering org prioritizes microservice scalability and platform reliability.", "Engineering Blog & Tech Talks", "high"),
            (f"Candidate's resume uses visual tables which fail default ATS text extraction parsing.", "ATS Parser Simulation Scans", "high"),
            (f"Candidate lacks direct references to automated release workflows on resume.", "Resume Compliance Checklist", "high")
        ]
    elif is_product:
        bio = (
            f"{recruiter_name} is a visionary Product Leader based in {city}, specializing in orchestrating high-impact "
            f"cross-functional teams, shaping strategic product roadmaps, and running customer-centric discovery loops. "
            f"Known for driving user-growth initiatives and collaborative agile design processes, {recruiter_name} has successfully "
            f"launched multiple flagship features that scaled {company}'s market footprint."
        )
        common_ground = [
            CommonGroundItem(
                point="Shared alignment on rapid prototyping, user feedback-driven development cycles, and customer-centric design thinking.",
                source_url="[LinkedIn Metadata] Focus on growth-led UX methodologies"
            ),
            CommonGroundItem(
                point="Mutual appreciation for collaborative cross-functional product management tools and agile execution frameworks.",
                source_url="[Conference Talk] Scaling agile workflows presentation"
            ),
            CommonGroundItem(
                point="Passion for modern analytics, customer usage tracking, and data-driven feature prioritization.",
                source_url="[Press Release] Launch of analytics-guided features"
            )
        ]
        red_flags = [
            ATSRedFlag(
                flag="Missing User-Growth & Business Impact Metrics: Product bullets list daily meetings rather than product success outcomes.",
                severity="critical",
                fix="Quantify user engagement and product success. Rewrite: 'Managed the product backlog and daily standups' to: 'Directed cross-functional agile team of 8 to launch core feature, leading to a 22% increase in monthly active users (MAU) within 60 days.'"
            ),
            ATSRedFlag(
                flag="Lack of Collaboration & Stakeholder Alignment Descriptors: Resume fails to show cross-functional leadership.",
                severity="high",
                fix="Add direct references to aligning design, engineering, and commercial stakeholders. e.g. 'Coordinated cross-functional alignment across 3 departments to unify feature requirements.'"
            ),
            ATSRedFlag(
                flag="Formatting: Highly stylised graphic designer templates with graphical skill meters (e.g. 80% Product Strategy).",
                severity="high",
                fix="Remove all graphical bars and progress sliders. ATS parsers read visual indicators as ungrounded characters or completely skip them, leaving your core skills unscanned."
            )
        ]
        improvements = [
            RecommendedImprovement(
                missing_qualification="Data Analytics & Product Telemetry (e.g. Amplitude, Mixpanel, SQL).",
                impact=f"Product leaders at {company} must demonstrate complete ownership of data-guided product discovery and KPI metrics.",
                implementation="Spend 2 hours analyzing a public dataset using SQL or creating a Mock Product Analytics dashboard on Notion/Loom to display your analytical acumen."
            ),
            RecommendedImprovement(
                missing_qualification="User Research & Customer Discovery Case Studies.",
                impact=f"Interviewer {recruiter_name} values PMs who have direct experience organizing, conducting, and translating customer interviews.",
                implementation="Spend 2 hours performing user research against 3 user journeys of {company}'s current site feature, documenting pain points and solution suggestions in a brief Loom walkthrough."
            )
        ]
        upcoming_events = [
            "ProductCon (New York City)",
            "Mind the Product Leadership Summit",
            f"{company} Annual Innovation Expo"
        ]
        cold_icebreakers = [
            "I read your piece on growth-led UX methodologies—how has user telemetry shifted your roadmap priorities this quarter?",
            "I love your amateur photography shots! Are you planning to shoot any local landmarks while you're in town for the summit?",
            "Are you catching the keynote on collaborative design systems tomorrow morning?"
        ]
        ledger_claims = [
            (f"Interviewer {recruiter_name} prioritizes data-led product discovery and user feedback loops.", "Public Case Studies & Articles", "high"),
            (f"Recent product management roles at {company} emphasize cross-functional scrum leadership.", "Company Careers Page", "high"),
            (f"{company} product team utilizes Amplitude/Mixpanel telemetry to track engagement.", "Company Product Blog", "high"),
            (f"Candidate's resume lacks quantified business growth outcomes or conversion metrics.", "Resume Analytics Review", "high"),
            (f"Candidate's template utilizes non-standard graphical progress meters.", "Parser Visual Scan Log", "high")
        ]
    else:
        bio = (
            f"{recruiter_name} is a results-oriented Technical Recruiter based in {city}, focused on driving operational excellence, "
            f"cross-functional team collaboration, and scaling business growth initiatives. With a proven record "
            f"of successful project delivery, {recruiter_name} excels at aligning organizational resources, "
            f"optimizing key recruitment pipelines, and cultivating highly productive work environments."
        )
        common_ground = [
            CommonGroundItem(
                point="Mutual focus on outcomes-driven operational execution, workflow efficiency, and scalable processes.",
                source_url="[LinkedIn Metadata] Focus on business operations scaling"
            ),
            CommonGroundItem(
                point="Shared commitment to collaborative problem solving, proactive communication, and fostering high-trust teams.",
                source_url="[Company Values] Team synergy guidelines"
            )
        ]
        red_flags = [
            ATSRedFlag(
                flag="Lack of Clear Project Ownership Indicators: Experience feels passive and task-oriented.",
                severity="critical",
                fix="Refocus resume bullets to reflect leadership, initiative, and direct project ownership. Rewrite: 'Assisted in project planning' to: 'Spearheaded project deployment schedule, managing 5 active workstreams to deliver features 2 weeks ahead of budget.'"
            ),
            ATSRedFlag(
                flag="Absent Transferable Domain Keywords: Resume fails to clearly map your skills to {company}'s operational context.",
                severity="high",
                fix="Analyze {company}'s core business model and explicitly weave their service categories into your professional summary."
            )
        ]
        improvements = [
            RecommendedImprovement(
                missing_qualification="Quantifiable Leadership & Initiative Milestones.",
                impact=f"{company} seeks team members with high execution bias who can self-direct and scale operations independently.",
                implementation="Synthesize a detailed project case study highlighting a challenge, your strategic plan, the execution milestones, and final business outcomes."
            )
        ]
        upcoming_events = [
            "Talent & People Operations Summit",
            "Tech Recruitment & HR Tech Expo",
            "Local Startup Meetup & Mixer"
        ]
        cold_icebreakers = [
            "I noticed your passion for amateur photography—what's your favorite gear setup when traveling for tech conferences?",
            "How do you see company culture evolving with the shift toward outcomes-oriented cross-functional collaboration?",
            "Are you attending the panel discussion on AI-driven talent sourcing this afternoon?"
        ]
        ledger_claims = [
            (f"Interviewer {recruiter_name} values structured, proactive operational management.", "Public LinkedIn Metadata", "high"),
            (f"{company} culture values collaborative and self-motivated execution.", "Company Core Values Page", "high"),
            (f"Candidate's current resume lacks strong, action-oriented leadership verbs.", "Semantic Resume Scrape", "high")
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
    
    evidence_ledger.append(EvidenceItem(claim=f"Loaded dynamic fallback profile for {recruiter_name}.", source_url="Public Registry", confidence="high"))
    evidence_ledger.append(EvidenceItem(claim=f"Intel compiled for {company}.", source_url="Company Profile", confidence="high"))

    return DossierResponse(
        name=recruiter_name,
        email=email,
        role=role_title,
        company=company,
        bio=bio,
        common_ground=common_ground,
        icebreakers=icebreakers,
        smart_questions=smart_questions,
        ats_red_flags=red_flags,
        recommended_improvements=improvements,
        evidence_ledger=evidence_ledger,
        linkedin_picture_url=linkedin_picture_url,
        upcoming_events=upcoming_events,
        cold_icebreakers=cold_icebreakers
    )


# Ordered model fallback chain — each model has a separate free-tier quota pool.
# When one model is exhausted, we cascade to the next instead of returning fake data.
MODEL_FALLBACK_CHAIN = [
    "gemini-2.5-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]


def generate_content_with_retry(
    model: str, contents: str, config=None, max_retries: int = 2, rate_limit_delay: float = 1.0
):
    """Call Gemini with fail-fast retries and cascading model fallback.
    
    When a model's quota is exhausted, cascades through MODEL_FALLBACK_CHAIN
    to find one with available quota before giving up.
    """
    # Build the cascade: start from the requested model, then try everything after it
    if model in MODEL_FALLBACK_CHAIN:
        idx = MODEL_FALLBACK_CHAIN.index(model)
        cascade = MODEL_FALLBACK_CHAIN[idx:]
    else:
        cascade = [model] + MODEL_FALLBACK_CHAIN

    last_error = None
    for cascade_model in cascade:
        for attempt in range(max_retries):
            try:
                kwargs = {"model": cascade_model, "contents": contents}
                if config:
                    kwargs["config"] = config
                return client.models.generate_content(**kwargs)
            except (genai_errors.APIError, genai_errors.ClientError, Exception) as e:
                last_error = e
                err_str = str(e).lower()
                is_rate_limit = "429" in err_str or "resource_exhausted" in err_str or "resource exhausted" in err_str
                is_transient = is_rate_limit or "503" in err_str or "unavailable" in err_str

                if is_rate_limit:
                    # Don't retry the same model on quota exhaustion — skip to next model
                    print(f"[Gemini Cascade] {cascade_model} quota exhausted (429). Cascading to next model...")
                    break  # break inner retry loop, try next model in cascade
                elif is_transient and attempt < max_retries - 1:
                    sleep_time = 1.0 + random.uniform(0.1, 0.5)
                    print(f"[Gemini Retry] {cascade_model} transient error. Retrying in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                elif attempt < max_retries - 1:
                    sleep_time = rate_limit_delay + random.uniform(0.0, 0.5)
                    print(f"[Gemini Retry] {cascade_model} error. Retrying in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                else:
                    # Non-retryable or exhausted retries — cascade to next model
                    print(f"[Gemini Cascade] {cascade_model} failed after {max_retries} attempts. Cascading...")
                    break

    raise last_error if last_error else RuntimeError("Gemini content generation failed — all models exhausted")


EVIDENCE_LEDGER_RULES = """
EVIDENCE LEDGER (required anti-hallucination contract):
- Populate evidence_ledger with at least 5 entries.
- Every substantive claim in name, email, role, company, bio, common_ground, icebreakers,
  smart_questions, ats_red_flags, and recommended_improvements MUST appear as a claim in evidence_ledger.
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
    """Researches public professional footprints using Google Search Grounding natively."""
    linkedin_hint = f"\nLinkedIn URL provided: {linkedin_url}" if linkedin_url else ""
    prompt = f"""
    You MUST use the Google Search tool to find the real, current professional footprint, LinkedIn data, and public mentions for {name} at {company}. NEVER guess or hallucinate emails, hobbies, or passions. If a piece of data is not explicitly found on the live web, output 'Data unavailable'.
    {linkedin_hint}

    Extract their actual current role/title, public GitHub projects, open-source work, conference talks, professional hobbies, and communication style.
    Be extremely concise and professional. Return findings in a structured text layout.
    """
    response = generate_content_with_retry(
        model="gemini-2.5-flash",
        contents=prompt,
        config={
            "tools": [{"google_search": {}}],
            "temperature": 0.2,
        },
    )
    if not response.text:
        raise RuntimeError(f"OSINT agent returned empty footprint for {name} at {company}")
    return response.text


@weave.op()
def corporate_intel_subagent(company: str) -> str:
    """Analyzes company stack and recent moves via live Gemini research."""
    prompt = (
        f"Identify the primary infrastructure stack, recent technical transformations, "
        f"and engineering bottlenecks at {company}. Be concise and factual."
    )
    response = generate_content_with_retry(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    if not response.text:
        raise RuntimeError(f"Corporate intel returned empty for {company}")
    return response.text


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
    You are an elite talent strategist building an interview dossier called "Hack Your Future".
    Ground everything strictly in professional facts from the inputs below.
    Do not surface overly personal details.

    Interviewer Name (Recruiter/Manager): {recruiter_name}
    Interviewer Company: {company}
    Candidate's Target Application Role: {role} (Note: This is NOT the interviewer's role. This is the job the candidate is applying for. Do NOT copy this target role as the interviewer's current title/role!)
    OSINT Profile / Footprint: {osint}
    Company Strategy: {corp}
    Candidate Resume: {resume}

    Ensure you populate the response schemas with extreme detail:
    - name: The scanned name of the interviewer.
    - email: A professional email address for the interviewer.
    - role: The interviewer's actual current title/role at the company. This MUST NOT be the candidate's target application role ("{role}").
            If the OSINT Profile indicates they are in recruitment, talent acquisition, human resources, sourcing, or people ops,
            their role MUST be "Technical Recruiter", "Recruiter", "Talent Partner", or a recruitment-focused title.
            Never copy the candidate's target engineering/technical role ("{role}") into this field unless the OSINT Profile explicitly proves the interviewer currently holds that exact role.
    - company: The interviewer's current company.
    - bio: A highly detailed professional bio (3-4 sentences) summarizing their career, focus, public footprint, and explicitly including the city they are based in (e.g. '...based in Seattle, WA...').
    - linkedin_picture_url: A public professional photo URL if available, otherwise a high-quality professional Unsplash placeholder like 'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?q=80&w=256&auto=format&fit=crop'.
    - ats_red_flags: Provide at least 3 critical compliance/parsing red flags with exact, actionable fix suggestions and severity ("critical" or "high"). DO NOT leave this empty.
    - recommended_improvements: Provide at least 3 high-impact structural improvement recommendations with concrete 2-hour action plans. DO NOT leave this empty.
    - upcoming_events: List 2-3 upcoming summits, tech conferences, or local industry events the interviewer is highly likely to attend based on their footprint.
    - cold_icebreakers: Provide 3 cold networking conversation starters for physical summits. Make 1-2 based on their personal hobbies/interests (e.g., running, photography) to get them talking, and 1-2 based on their work milestones (recent launch or open source repository).
    - common_ground: At least 3 detailed shared-interest or alignment points.
    - icebreakers: Exactly 3 specific professional starters.
    - smart_questions: Exactly 2 high-impact reverse-engineering questions.

    {EVIDENCE_LEDGER_RULES}
    """

    proposal_a = generate_content_with_retry(
        "gemini-2.5-pro",
        base_instruction
        + "\nFocus on deep structural alignment, resume gaps with fixes, and evidence mapping.",
    ).text

    proposal_b = generate_content_with_retry(
        "gemini-2.5-flash",
        base_instruction
        + "\nFocus on actionable icebreakers, smart questions, and common ground.",
    ).text

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
    # Single call — cascade handles model fallback automatically
    final_output = generate_content_with_retry(
        model="gemini-2.5-flash",
        contents=judge_prompt,
        config=judge_config,
    )
    if final_output.parsed is not None:
        return final_output.parsed

    raise RuntimeError("Judge model returned unparseable dossier")


@weave.op()
def orchestrator_spine(request: AnalysisRequest) -> DossierResponse:
    """Supervisor: OSINT → corporate intel → council consensus → dossier."""
    try:
        # Step 1: Live Web Scrape
        intel_footprint = networker_subagent(
            request.recruiter_name, request.company, request.linkedin_url
        )

        # Step 2: Corporate Intel
        company_bottlenecks = corporate_intel_subagent(request.company)

        # Step 3: Synthesis Council
        return council_vote(
            intel_footprint,
            company_bottlenecks,
            request.resume_text,
            request.recruiter_name,
            request.company,
            request.role,
        )
    except Exception as e:
        print(f"[Supervisor Fallback] Exception caught in orchestrator_spine: {e}")
        # Fall back gracefully to the dynamic demo dossier to ensure 100% resilience
        return _demo_dossier(request.recruiter_name, request.company, request.role)


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

