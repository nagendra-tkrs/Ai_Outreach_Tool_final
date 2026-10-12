import os
import json
import httpx
from app.config.database import get_db

TKSR_SERVICES = [
    {
        'id': 'AI Strategy Consulting',
        'label': 'AI Strategy Consulting',
        'description': 'Tailored enterprise AI roadmaps, executive alignment, and ROI use case prioritization.'
    },
    {
        'id': 'AI Readiness and Opportunity Assessments',
        'label': 'AI Readiness and Opportunity Assessments',
        'description': 'Comprehensive system audits, workflow evaluations, and data readiness benchmarks.'
    },
    {
        'id': 'AI & Automation Workshops',
        'label': 'AI & Automation Workshops',
        'description': 'Hands-on prototyping sessions to turn workflow ideas into production automation.'
    },
    {
        'id': 'AI Training',
        'label': 'AI Training',
        'description': 'Upskilling engineering, operations, and leadership teams on Generative AI and modern tooling.'
    },
    {
        'id': 'AI Governance and Responsible AI',
        'label': 'AI Governance and Responsible AI',
        'description': 'Enterprise compliance frameworks, data privacy guardrails, and risk mitigation.'
    },
    {
        'id': 'AI Data Strategy',
        'label': 'AI Data Strategy',
        'description': 'Vector databases, RAG architecture, data lineage, and integration pipelines.'
    }
]

# ---------------------------------------------------------------------------
# Canonical TKSR signature — used on every TKSR-generated email.
# ---------------------------------------------------------------------------
TKSR_SIGNER_NAME = "Nagendra Singh"
TKSR_SIGNER_COMPANY = "TKSR Product Services"
TKSR_SIGNER_WEBSITE = "https://tksrproductservices.com/"
TKSR_SIGNER_EMAIL = "info@tksrproductservices.com"

TKSR_SIGNATURE_HTML = (
    "Best regards,<br/><strong>Nagendra Singh</strong><br/>"
    "TKSR Product Services<br/>"
    '<a href="https://tksrproductservices.com/">https://tksrproductservices.com/</a><br/>'
    '<a href="mailto:info@tksrproductservices.com">info@tksrproductservices.com</a>'
)
TKSR_SIGNATURE_TEXT = (
    "Best regards,\n"
    "Nagendra Singh\n"
    "TKSR Product Services\n"
    "https://tksrproductservices.com/\n"
    "info@tksrproductservices.com"
)

# Per-service copy blocks used by the deterministic builders below.
TKSR_SERVICE_DETAILS = {
    'AI Strategy Consulting': {
        'serviceName': 'AI Strategy Consulting',
        'painPoint': 'prioritizing high-ROI AI initiatives and aligning technology investments with measurable business outcomes',
        'solution': 'We help leadership teams audit current capabilities, uncover high-impact use cases, and build an actionable, step-by-step AI implementation roadmap tailored to your company.',
        'actionPrompt': 'explore whether an AI Strategy roadmap could accelerate your current initiatives'
    },
    'AI Readiness and Opportunity Assessments': {
        'serviceName': 'AI Readiness and Opportunity Assessments',
        'painPoint': 'evaluating data infrastructure and workflow maturity before committing significant capital to AI projects',
        'solution': 'Our AI Readiness Assessment evaluates your systems, team workflows, and compliance constraints to identify low-risk, high-impact opportunities with zero disruption to active operations.',
        'actionPrompt': 'review where an initial AI Readiness audit could uncover quick-win efficiencies'
    },
    'AI & Automation Workshops': {
        'serviceName': 'AI & Automation Workshops',
        'painPoint': 'bridging the gap between conceptual AI ideas and working production automations',
        'solution': 'Through structured, hands-on workshops, we partner with your engineering and operations teams to ideate, prototype, and build production-ready automation workflows in days.',
        'actionPrompt': 'discuss a tailored workshop session for your technical and operations teams'
    },
    'AI Training': {
        'serviceName': 'AI Training',
        'painPoint': 'enabling internal teams to confidently and safely utilize Generative AI and LLM tools',
        'solution': 'We provide practical, role-specific training courses that empower your staff with hands-on prompt engineering, workflow automation tools, and safety guardrails.',
        'actionPrompt': 'discuss tailored upskilling tracks for your team'
    },
    'AI Governance and Responsible AI': {
        'serviceName': 'AI Governance and Responsible AI',
        'painPoint': 'ensuring compliance, data privacy, and security guardrails as AI systems scale',
        'solution': 'We design enterprise AI governance frameworks, establish audit trails, and implement safety policies so your organization can deploy AI with complete accountability and regulatory confidence.',
        'actionPrompt': 'explore how our AI Governance framework can safeguard your scaling systems'
    },
    'AI Data Strategy': {
        'serviceName': 'AI Data Strategy',
        'painPoint': 'structuring disparate data pipelines and vector retrieval architectures for reliable AI models',
        'solution': 'We help engineering organizations modernize their data architecture, RAG pipelines, and vector databases to ensure clean, high-precision data foundations for enterprise AI.',
        'actionPrompt': 'explore how an optimized AI Data Architecture could enhance your model performance'
    }
}

_SIGNOFF_MARKERS = (
    "best regards", "kind regards", "warm regards", "regards,",
    "sincerely,", "thanks,", "thank you,", "cheers,",
)


def sanitize_evidence(evidence) -> str:
    """Normalize the persisted Evidence field for embedding in generated copy.

    Returns '' when the field is missing, empty, a literal placeholder
    ("None", "N/A", "-", ...) or unusable. Never fabricates content.
    """
    if not evidence:
        return ""
    clean = str(evidence).strip().strip('"\'“”‘’').strip()
    if clean.lower() in ("none", "n/a", "na", "null", "-", "--"):
        return ""
    if len(clean) > 320:
        clean = clean[:317].rstrip() + "..."
    return clean


def _embed(text: str) -> str:
    """Lowercase the first character so the phrase reads mid-sentence."""
    if not text:
        return ""
    return text[0].lower() + text[1:] if len(text) > 1 else text.lower()


def _strip_signoff(content) -> str:
    """Remove any trailing salutation block so the canonical TKSR signature is
    the only sign-off in the email body."""
    if not content:
        return ""
    lowered = content.lower()
    cut = -1
    for marker in _SIGNOFF_MARKERS:
        idx = lowered.rfind(marker)
        if idx != -1 and idx > len(content) * 0.5 and idx > cut:
            cut = idx
    if cut > 0:
        return content[:cut].rstrip()
    return content.strip()


def apply_tksr_signature(body_html, body_text):
    """Normalize both HTML and plain-text bodies to end with the canonical TKSR
    signature block (replacing whatever sign-off an LLM added)."""
    html = _strip_signoff(body_html or "").rstrip()
    text = _strip_signoff(body_text or "").rstrip()
    if html:
        if not html.endswith("</p>"):
            html += "</p>"
        signed_html = html + f"<p>{TKSR_SIGNATURE_HTML}</p>"
    else:
        signed_html = f"<p>{TKSR_SIGNATURE_HTML}</p>"
    signed_text = (text + "\n\n" + TKSR_SIGNATURE_TEXT) if text else TKSR_SIGNATURE_TEXT
    return signed_html, signed_text


def _first_name(name) -> str:
    if not name:
        return ""
    parts = str(name).strip().split()
    return parts[0] if parts else ""


def _is_inbox_address(email) -> bool:
    e = (email or "").lower()
    return any(e.startswith(f"{p}@") for p in ("support", "contact", "info", "sales", "hello", "help"))


def _service_description(service: str) -> str:
    for s in TKSR_SERVICES:
        if s['id'] == service:
            return s.get('description', '')
    details = TKSR_SERVICE_DETAILS.get(service)
    return details.get('solution', '') if details else ''


def build_primary_email(company, contact=None, sender=None, service=None, tone='conversational'):
    """Deterministic, evidence-based Step 1 (primary) outreach email.

    Uses ONLY the persisted Evidence and Recommended Service for
    personalization. When evidence is missing or insufficient it silently
    produces a conservative template — nothing is ever invented (no metrics,
    case studies, initiatives, or AI-adoption claims).
    """
    company_name = (company.get('companyName') or '').strip()
    evidence = sanitize_evidence(company.get('evidence'))
    service = (service or company.get('recommendedService') or '').strip()
    if not service:
        service = 'AI Strategy Consulting'

    email = (contact or {}).get('email') or ''
    is_inbox = _is_inbox_address(email)
    first = _first_name((contact or {}).get('name') or company.get('contactName'))

    if is_inbox:
        greeting = f"Hi {company_name} Team," if company_name else "Hello,"
    elif first:
        greeting = f"Hi {first},"
    else:
        greeting = "Hello,"

    service_desc = _service_description(service)
    if evidence:
        ev = _embed(evidence)
        observation = f"I was looking into {company_name} and noticed that {ev}."
        opportunity = (
            f"Work like that often raises a practical question: where AI and automation "
            f"can create the most value without disrupting what is already working."
        )
    else:
        observation = f"I was researching {company_name} and wanted to share a brief idea."
        opportunity = (
            "Many growing teams are asking where AI and automation can deliver the "
            "most value with the least disruption."
        )

    value = (
        f"At TKSR Product Services, we help teams plan and adopt {service} in a "
        f"practical, step-by-step way. {service_desc}"
        if service_desc else
        f"At TKSR Product Services, we help teams plan and adopt {service} in a "
        f"practical, step-by-step way."
    )
    cta = "If a short conversation would be useful, I would be happy to find 15 minutes this week — no obligation."

    subject = f"Quick note on {service} for {company_name}"

    body_text = (
        f"{greeting}\n\n{observation}\n\n{opportunity} {value}\n\n{cta}\n\n{TKSR_SIGNATURE_TEXT}"
    )
    body_html = (
        f"<p>{greeting}</p><p>{observation}</p><p>{opportunity} {value}</p><p>{cta}</p>"
        f"<p>{TKSR_SIGNATURE_HTML}</p>"
    )

    evidence_short = evidence[:120].rstrip() if evidence else ''
    if evidence and first and not is_inbox:
        linkedin_note = (
            f"Hi {first}, I'm Nagendra from TKSR Product Services. I came across "
            f"{company_name} and noticed {_embed(evidence_short)}. Would connecting be useful?"
        )
    elif not is_inbox:
        linkedin_note = (
            f"Hi {first}, I'm Nagendra from TKSR Product Services. I came across "
            f"{company_name} and wanted to share a quick idea on {service}. Open to connecting?"
        )
    else:
        linkedin_note = (
            f"Hi {company_name} Team, I'm Nagendra from TKSR Product Services. "
            f"Would connecting be useful? Happy to share a brief note on {service}."
        )
    linkedin_inmail = (
        f"Hi {first or (company_name or 'there')},\n\n{observation}\n\n{value}\n\n{cta}\n\n"
        "Best regards,\nNagendra Singh\nTKSR Product Services"
    )

    return {
        "subject": subject,
        "bodyText": body_text,
        "bodyHtml": body_html,
        "linkedinNote": linkedin_note[:300],
        "linkedinInmail": linkedin_inmail,
    }


def build_followup_email(step, company, contact=None, sender=None, service=None, evidence='', tone='conversational'):
    """Deterministic Step 2 / Step 3 follow-up copy.

    Copy stays purpose-specific (Step 2 = practical value, Step 3 = low-friction
    closing) and is never a copy of the Step 1 body. Only the Evidence + service
    are referenced; nothing is invented.
    """
    company_name = (company.get('companyName') or '').strip()
    service = (service or '').strip() or 'AI Strategy Consulting'
    evidence = sanitize_evidence(evidence)
    first = _first_name((contact or {}).get('name') or company.get('contactName'))
    is_inbox = _is_inbox_address((contact or {}).get('email'))
    if is_inbox:
        greeting = f"Hi {company_name} Team," if company_name else "Hello,"
    elif first:
        greeting = f"Hi {first},"
    else:
        greeting = "Hello,"

    if step == 2:
        subject = f"Re: {service} for {company_name}"
        if evidence:
            ref = f"Following up on my earlier note about your work on {_embed(evidence)} and how it connects with {service}."
        else:
            ref = f"Following up on my earlier note regarding {service} for {company_name}."
        para = (
            f"Teams in a similar position often find it useful to look at where AI and automation "
            f"can remove friction without disrupting operations. At TKSR Product Services we "
            f"specialise in {service} — a practical, step-by-step path from assessment to adoption."
        )
        cta = "Would a 10-minute call on Thursday or Friday be useful?"
    else:
        subject = f"Closing the loop: {service} for {company_name}"
        if evidence:
            ref = f"I know schedules are demanding. As you continue your work on {_embed(evidence)}, I wanted to send one final note."
        else:
            ref = f"I know schedules can be hectic, so I wanted to send one final note regarding {service}."
        para = (
            f"If you are currently evaluating AI and automation initiatives at {company_name}, "
            f"we would be glad to share a tailored {service} briefing whenever the timing is right."
        )
        cta = "If now is not the best time, feel free to keep us in mind for future initiatives."

    body_text = f"{greeting}\n\n{ref}\n\n{para}\n\n{cta}\n\n{TKSR_SIGNATURE_TEXT}"
    body_html = (
        f"<p>{greeting}</p><p>{ref}</p><p>{para}</p><p>{cta}</p><p>{TKSR_SIGNATURE_HTML}</p>"
    )
    linkedin_note = (
        f"Hi {first or (company_name or 'there')}, following up on my earlier note regarding "
        f"{service} for {company_name}."
    )
    linkedin_inmail = (
        f"Hi {first or (company_name or 'there')},\n\n{ref}\n\n{para}\n\n{cta}\n\n"
        "Best regards,\nNagendra Singh\nTKSR Product Services"
    )
    return {
        "subject": subject,
        "bodyText": body_text,
        "bodyHtml": body_html,
        "linkedinNote": linkedin_note[:300],
        "linkedinInmail": linkedin_inmail,
    }


async def get_ai_config() -> dict:
    ollama_base_url = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    provider = os.getenv('AI_PROVIDER', 'ollama')
    model = os.getenv('AI_MODEL', 'llama3')

    try:
        db = get_db()
        if db is not None:
            setting = await db.settings.find_one({"key": "global_settings"})
            if setting and setting.get('ai'):
                s_ai = setting['ai']
                provider = s_ai.get('provider') or provider
                ollama_base_url = s_ai.get('ollamaBaseUrl') or ollama_base_url
                model = s_ai.get('model') or model
    except Exception as e:
        print(f"Could not fetch global settings from DB, using env fallback: {e}")

    return {
        'provider': provider,
        'ollamaBaseUrl': ollama_base_url,
        'model': model
    }


async def call_ollama(prompt: str, system_instruction: str = '', base_url: str = 'http://127.0.0.1:11434', model: str = 'qwen2.5-coder:7b-instruct') -> dict:
    clean_base = (base_url or 'http://127.0.0.1:11434').rstrip('/')
    if not model:
        raise ValueError('Ollama model is required')

    messages = []
    if system_instruction and isinstance(system_instruction, str) and system_instruction.strip():
        messages.append({'role': 'system', 'content': system_instruction})
    messages.append({'role': 'user', 'content': prompt})

    timeout_sec = float(os.getenv('OLLAMA_REQUEST_TIMEOUT', 180000)) / 1000.0

    async with httpx.AsyncClient() as client:
        # Check if Ollama is running
        try:
            base_res = await client.get(f"{clean_base}/api/tags", timeout=4.0)
            if base_res.status_code != 200:
                raise RuntimeError('Ollama is not running. Ensure Ollama is started.')
        except Exception:
            raise RuntimeError('Ollama is not running. Ensure Ollama is started.')

        # Post chat request
        res = await client.post(
            f"{clean_base}/api/chat",
            json={
                'model': model,
                'messages': messages,
                'stream': False,
                'format': 'json'
            },
            timeout=timeout_sec
        )
        if res.status_code != 200:
            raise RuntimeError(f"Ollama API error ({res.status_code}): {res.text[:200]}")

        data = res.json()
        raw_content = data.get('message', {}).get('content')
        if not raw_content or not str(raw_content).strip():
            raise RuntimeError('Ollama returned an empty response')

        if isinstance(raw_content, dict):
            return raw_content

        try:
            return json.loads(raw_content)
        except Exception:
            raise RuntimeError('Ollama returned invalid JSON')

def can_use_ai(ai_config: dict) -> bool:
    if not ai_config:
        return False
    return ai_config.get('provider') == 'ollama'

async def call_ai(prompt: str, system_instruction: str = '', ai_config: dict = None) -> dict:
    if not ai_config:
        ai_config = await get_ai_config()

    provider = ai_config.get('provider')
    if provider == 'ollama':
        return await call_ollama(prompt, system_instruction, ai_config.get('ollamaBaseUrl'), ai_config.get('model', 'llama3'))

    raise RuntimeError('No usable AI provider configured')


def generate_fallback_research(company: dict, pages: list = None) -> dict:
    if pages is None:
        pages = []
    company_name = company.get('companyName', '')
    industry = company.get('industry') or 'B2B technology'

    return {
        'summary': f"{company_name} operates in the {industry} sector, offering specialized solutions and services. Analysis of their digital footprint reveals active operations and strong potential for targeted AI integration and automated workflow transformation.",
        'valueProposition': f"Delivers high-quality {industry} capabilities designed to drive efficiency, client outcomes, and digital growth.",
        'targetAudience': f"Enterprise clients, decision-makers, and teams seeking operational excellence and modern technology solutions.",
        'coreOfferings': [
            f"{industry} Core Solutions",
            'Digital Implementation Services',
            'Client Success & Strategic Delivery'
        ],
        'techStack': ['Cloud Infrastructure', 'Web Frameworks', 'Analytics Tools', 'Modern API Integration'],
        'detectedPainPoints': [
            {
                'title': 'Accelerating AI Strategy & Automation',
                'description': f"Navigating where to integrate AI into existing operational workflows without disrupting core production.",
                'evidenceSnippet': 'Identified opportunity for high-impact AI Readiness Assessment and Strategy Consulting.'
            },
            {
                'title': 'Team AI Upskilling & Knowledge Enablement',
                'description': 'Enabling engineering and operations teams to effectively adopt Generative AI and automation tools.',
                'evidenceSnippet': 'Opportunity for hands-on AI & Automation Workshops and team training.'
            },
            {
                'title': 'AI Data Architecture & Governance',
                'description': 'Ensuring enterprise data hygiene, RAG vector retrieval, and governance guardrails for safe AI scaling.',
                'evidenceSnippet': 'Identified need for structured AI Data Strategy and Responsible AI compliance.'
            }
        ],
        'icebreakers': [
            f"I was exploring {company_name}'s work in {industry} and was really impressed by your approach to client delivery.",
            f"I noticed {company_name}'s focus on innovation and wanted to reach out regarding accelerating your AI roadmap.",
            f"Given {company_name}'s current growth trajectory, I wanted to discuss how modern AI & automation strategies could unlock significant leverage."
        ],
        'icpFitScore': 92,
        'icpFitReasoning': f"Strong alignment with TKSR Product Services. {company_name} has an active web presence and complex workflows that benefit directly from targeted AI Strategy Consulting, Readiness Assessments, and Automation Workshops.",
        'keyPersonnel': [
            {
                'name': company.get('contactName'),
                'title': 'Chief Executive Officer / Founder',
                'relevance': 'Key decision maker for enterprise AI strategy and technological partnerships.'
            }
        ] if company.get('contactName') else [],
        'recommendedTksrServices': [
            'AI Strategy Consulting',
            'AI Readiness and Opportunity Assessments',
            'AI & Automation Workshops',
            'AI Training',
            'AI Governance and Responsible AI',
            'AI Data Strategy'
        ],
        'aiProvider': 'heuristic_synthesizer',
        'confidenceScore': 0.88
    }

def generate_fallback_outreach(company: dict, research: dict, contact: dict, sender: dict, angle: str = None, tone: str = None, focus_service: str = None) -> list[dict]:
    """Deterministic 3-step sequence used when the local LLM is unavailable.

    Step 1 comes from `build_primary_email` (evidence + recommended service,
    canonical TKSR signature). Steps 2/3 come from `build_followup_email` and
    stay purpose-specific — they never reuse the Step 1 body.
    """
    company_name = company.get('companyName', '')

    company_rec = (company.get('recommendedService') or '').strip()
    if company_rec:
        selected_service = company_rec
    elif focus_service:
        selected_service = focus_service
    else:
        selected_service = 'AI Strategy Consulting'

    company_evidence = (company.get('evidence') or '').strip()

    step1 = build_primary_email(company, contact or None, sender, selected_service, tone or 'conversational')
    step2 = build_followup_email(2, company, contact or None, sender, selected_service, company_evidence, tone or 'conversational')
    step3 = build_followup_email(3, company, contact or None, sender, selected_service, company_evidence, tone or 'conversational')

    def wrap(step, label, delay_days, content):
        return {
            'step': step,
            'stepLabel': label,
            'subject': content['subject'],
            'angle': angle or 'pain_point',
            'tone': tone or 'conversational',
            'focusService': selected_service,
            'evidenceUsed': company_evidence,
            'recommendedServiceUsed': selected_service,
            'delayDays': delay_days,
            'recipientEmail': (contact or {}).get('email', '') if contact else '',
            'recipientName': (contact or {}).get('name') if contact else (company.get('contactName') or 'Lead'),
            'bodyHtml': content['bodyHtml'],
            'bodyText': content['bodyText'],
            'linkedinNote': content.get('linkedinNote', ''),
            'linkedinInmail': content.get('linkedinInmail', '')
        }

    return [
        wrap(1, 'Initial Outreach', 0, step1),
        wrap(2, 'Follow-up: Practical Implementation', 3, step2),
        wrap(3, 'Break-up / Low-Friction Invitation', 6, step3),
    ]
