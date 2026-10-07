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
    company_name = company.get('companyName', '')
    is_inbox = (
        (contact and (contact.get('seniority') == 'general' or contact.get('roleCategory') == 'general')) or
        any((contact.get('email') or '').lower().startswith(f"{prefix}@") for prefix in ['support', 'contact', 'info', 'sales', 'hello', 'help'])
    )

    contact_first = contact.get('name', '').split(' ')[0] if contact and contact.get('name') else 'there'
    contact_greeting = f"Hi {company_name} Team" if is_inbox else f"Hi {contact_first}"
    contact_name = f"{company_name} Team" if is_inbox else (contact.get('name') if contact else (company.get('contactName') or 'there'))
    contact_title = contact.get('title') if contact else ('Leadership Team' if is_inbox else 'Executive')
    sender_name = sender.get('senderName') or 'Nagendra'
    sender_title = sender.get('senderTitle') or 'Business Analyst'
    my_company = sender.get('companyName') or 'TKSR Product Services'

    company_rec = (company.get('recommendedService') or '').strip()
    if company_rec:
        selected_service = company_rec
    elif focus_service:
        selected_service = focus_service
    else:
        role_cat = contact.get('roleCategory') if contact else ''
        if role_cat in ('cto', 'cio'):
            selected_service = 'AI Data Strategy'
        elif role_cat == 'coo':
            selected_service = 'AI Readiness and Opportunity Assessments'
        elif role_cat == 'dept_head' and 'governance' in (contact.get('department') or '').lower():
            selected_service = 'AI Governance and Responsible AI'
        else:
            selected_service = 'AI Strategy Consulting'

    service_details = {
        'AI Strategy Consulting': {
            'serviceName': 'AI Strategy Consulting',
            'painPoint': 'prioritizing high-ROI AI initiatives and aligning technology investments with measurable business outcomes',
            'solution': f"We help leadership teams audit current capabilities, uncover high-impact use cases, and build an actionable, step-by-step AI implementation roadmap tailored to {company_name}.",
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

    service = service_details.get(
        selected_service,
        {
            'serviceName': selected_service,
            'painPoint': f"advancing initiatives in {selected_service}",
            'solution': f"At {my_company}, our structured {selected_service} practice helps teams solve operational friction and achieve measurable outcomes.",
            'actionPrompt': f"explore opportunities in {selected_service}"
        }
    )

    company_evidence = (company.get('evidence') or '').strip()
    if company_evidence:
        evidence_clean = company_evidence.rstrip('.')
        icebreaker = f"Your recent initiative around {evidence_clean} caught our attention at {my_company}."
        f2_evidence_ref = f"Following up on my note regarding {evidence_clean} and how it connects with {service['serviceName']} for {company_name}."
        f3_evidence_ref = f"I know schedules are demanding. As you continue your work around {evidence_clean}, I wanted to send one final note regarding {service['serviceName']}."
    else:
        icebreakers = research.get('icebreakers') if research else []
        icebreaker = icebreakers[0] if icebreakers else f"I came across {company_name}'s work in {company.get('industry') or 'your sector'} and was impressed by your team's execution."
        f2_evidence_ref = f"Following up on my note earlier this week regarding {service['serviceName']} for {company_name}."
        f3_evidence_ref = f"I know schedules can be hectic, so I wanted to send one final note regarding {service['serviceName']}."

    linkedin_note = (
        f"Hi {company_name} Team, saw your work in {company.get('industry') or 'tech'} and wanted to connect regarding how TKSR Product Services helps companies accelerate {service['serviceName']}."
        if is_inbox else
        f"Hi {contact_first}, noticed your leadership as {contact_title} at {company_name}. Would love to connect and share insights on {service['serviceName']} for growing teams."
    )

    linkedin_inmail = f"Hi {contact_name},\n\nI've been following {company_name}'s growth in {company.get('industry') or 'your market'}.\n\nAs {contact_title}, a key operational priority is often {service['painPoint']}.\n\nAt {my_company}, our {service['serviceName']} focuses directly on this: {service['solution']}\n\nWould you be open to a brief 10-minute exchange this week to {service['actionPrompt']}?\n\nBest regards,\n{sender_name}\n{sender_title} | {my_company}"

    return [
        {
            'step': 1,
            'stepLabel': 'Initial Outreach',
            'subject': f"Accelerating {service['serviceName']} at {company_name}",
            'angle': angle or 'pain_point',
            'tone': tone or 'conversational',
            'focusService': selected_service,
            'evidenceUsed': company_evidence,
            'recommendedServiceUsed': selected_service,
            'delayDays': 0,
            'recipientEmail': contact.get('email') if contact else '',
            'recipientName': contact_name,
            'bodyHtml': f"<p>{contact_greeting},</p>\n<p>{icebreaker}</p>\n<p>As {contact_title} at <strong>{company_name}</strong>, a key strategic priority is often <strong>{service['painPoint']}</strong>.</p>\n<p>At <strong>{my_company}</strong>, we specialize in <strong>{service['serviceName']}</strong>. {service['solution']}</p>\n<p>Would you be open to a brief 10-minute introductory conversation this week to {service['actionPrompt']}?</p>\n<p>Best regards,<br/><strong>{sender_name}</strong><br/>{sender_title} | {my_company}</p>",
            'bodyText': f"{contact_greeting},\n\n{icebreaker}\n\nAs {contact_title} at {company_name}, a key strategic priority is often {service['painPoint']}.\n\nAt {my_company}, we specialize in {service['serviceName']}. {service['solution']}\n\nWould you be open to a brief 10-minute introductory conversation this week to {service['actionPrompt']}?\n\nBest regards,\n{sender_name}\n{sender_title} | {my_company}",
            'linkedinNote': linkedin_note,
            'linkedinInmail': linkedin_inmail
        },
        {
            'step': 2,
            'stepLabel': 'Follow-up: Practical Implementation',
            'subject': f"Re: Accelerating {service['serviceName']} at {company_name}",
            'angle': 'value_prop',
            'tone': tone or 'conversational',
            'focusService': selected_service,
            'evidenceUsed': company_evidence,
            'recommendedServiceUsed': selected_service,
            'delayDays': 3,
            'recipientEmail': contact.get('email') if contact else '',
            'recipientName': contact_name,
            'bodyHtml': f"<p>{contact_greeting},</p>\n<p>{f2_evidence_ref}</p>\n<p>Organizations in your space frequently encounter challenges when moving from initial exploration to robust production workflows. Our focused approach helps teams eliminate operational bottlenecks and achieve rapid, quantifiable ROI with <strong>{service['serviceName']}</strong>.</p>\n<p>Do you have 10 minutes on Thursday or Friday to connect briefly?</p>\n<p>Best regards,<br/><strong>{sender_name}</strong><br/>{sender_title} | {my_company}</p>",
            'bodyText': f"{contact_greeting},\n\n{f2_evidence_ref}\n\nOrganizations in your space frequently encounter challenges when moving from initial exploration to robust production workflows. Our focused approach helps teams eliminate operational bottlenecks and achieve rapid, quantifiable ROI with {service['serviceName']}.\n\nDo you have 10 minutes on Thursday or Friday to connect briefly?\n\nBest regards,\n{sender_name}\n{sender_title} | {my_company}",
            'linkedinNote': linkedin_note,
            'linkedinInmail': linkedin_inmail
        },
        {
            'step': 3,
            'stepLabel': 'Break-up / Low-Friction Invitation',
            'subject': f"Closing the loop: {service['serviceName']} for {company_name}",
            'angle': 'icebreaker',
            'tone': tone or 'conversational',
            'focusService': selected_service,
            'evidenceUsed': company_evidence,
            'recommendedServiceUsed': selected_service,
            'delayDays': 6,
            'recipientEmail': contact.get('email') if contact else '',
            'recipientName': contact_name,
            'bodyHtml': f"<p>{contact_greeting},</p>\n<p>{f3_evidence_ref}</p>\n<p>If you're currently evaluating initiatives at <strong>{company_name}</strong>, we'd be delighted to share a tailored <strong>{service['serviceName']}</strong> briefing whenever the timing is right.</p>\n<p>If now isn't the best time, feel free to keep us in mind for future initiatives.</p>\n<p>Best regards,<br/><strong>{sender_name}</strong><br/>{sender_title} | {my_company}</p>",
            'bodyText': f"{contact_greeting},\n\n{f3_evidence_ref}\n\nIf you're currently evaluating initiatives at {company_name}, we'd be delighted to share a tailored {service['serviceName']} briefing whenever the timing is right.\n\nIf now isn't the best time, feel free to keep us in mind for future initiatives.\n\nBest regards,\n{sender_name}\n{sender_title} | {my_company}",
            'linkedinNote': linkedin_note,
            'linkedinInmail': linkedin_inmail
        }
    ]
