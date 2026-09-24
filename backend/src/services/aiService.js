const Setting = require('../models/Setting');

const TKSR_SERVICES = [
  {
    id: 'AI Strategy Consulting',
    label: 'AI Strategy Consulting',
    description: 'Tailored enterprise AI roadmaps, executive alignment, and ROI use case prioritization.'
  },
  {
    id: 'AI Readiness and Opportunity Assessments',
    label: 'AI Readiness and Opportunity Assessments',
    description: 'Comprehensive system audits, workflow evaluations, and data readiness benchmarks.'
  },
  {
    id: 'AI & Automation Workshops',
    label: 'AI & Automation Workshops',
    description: 'Hands-on prototyping sessions to turn workflow ideas into production automation.'
  },
  {
    id: 'AI Training',
    label: 'AI Training',
    description: 'Upskilling engineering, operations, and leadership teams on Generative AI and modern tooling.'
  },
  {
    id: 'AI Governance and Responsible AI',
    label: 'AI Governance and Responsible AI',
    description: 'Enterprise compliance frameworks, data privacy guardrails, and risk mitigation.'
  },
  {
    id: 'AI Data Strategy',
    label: 'AI Data Strategy',
    description: 'Vector databases, RAG architecture, data lineage, and integration pipelines.'
  }
];

/**
 * Helper to retrieve AI configuration from DB or process.env
 * Supports gemini, openai, and local ollama providers.
 * Ollama requires no API key; its base URL defaults to the local Ollama server.
 */
const getAiConfig = async () => {
  let geminiKey = process.env.GEMINI_API_KEY;
  let openaiKey = process.env.OPENAI_API_KEY;
  let ollamaBaseUrl = process.env.OLLAMA_BASE_URL || 'http://127.0.0.1:11434';
  let provider = process.env.AI_PROVIDER || 'ollama';
  let model = process.env.AI_MODEL || 'qwen2.5-coder:7b-instruct';

  try {
    const setting = await Setting.findOne({ key: 'global_settings' });
    if (setting?.ai) {
      provider = setting.ai.provider || provider;
      geminiKey = setting.ai.geminiApiKey || geminiKey;
      openaiKey = setting.ai.openaiApiKey || openaiKey;
      ollamaBaseUrl = setting.ai.ollamaBaseUrl || ollamaBaseUrl;
      model = setting.ai.model || model;
    }
  } catch (err) {
    console.warn('Could not fetch global settings from DB, using env fallback:', err.message);
  }

  // Ensure a sensible default model whenever provider is ollama but no model is explicitly set
  if (provider === 'ollama' && (!model || model.startsWith('gemini') || model.startsWith('gpt-'))) {
    model = process.env.AI_MODEL || 'qwen2.5-coder:7b-instruct';
  }

  return { provider, geminiKey, openaiKey, ollamaBaseUrl, model };
};

/**
 * Call Gemini API with JSON formatting
 */
const callGemini = async (prompt, systemInstruction, apiKey, model = 'gemini-1.5-pro') => {
  if (!apiKey) throw new Error('Gemini API key is required');
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;

  const payload = {
    contents: [
      {
        role: 'user',
        parts: [{ text: prompt }]
      }
    ],
    generationConfig: {
      temperature: 0.2,
      responseMimeType: 'application/json'
    }
  };

  if (systemInstruction) {
    payload.systemInstruction = {
      parts: [{ text: systemInstruction }]
    };
  }

  const apiTimeoutMs = Number(process.env.AI_REQUEST_TIMEOUT) || 120000;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(apiTimeoutMs)
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Gemini API error (${res.status}): ${errText}`);
  }
  const data = await res.json();
  const text = data?.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!text) throw new Error('Empty response from Gemini API');

  return JSON.parse(text);
};

/**
 * Call OpenAI API with JSON mode
 */
const callOpenAI = async (prompt, systemInstruction, apiKey, model = 'gpt-4o') => {
  if (!apiKey) throw new Error('OpenAI API key is required');
  const url = 'https://api.openai.com/v1/chat/completions';

  const messages = [];
  if (systemInstruction) {
    messages.push({ role: 'system', content: systemInstruction });
  }
  messages.push({ role: 'user', content: prompt });

  const apiTimeoutMs = Number(process.env.AI_REQUEST_TIMEOUT) || 120000;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model,
      messages,
      temperature: 0.2,
      response_format: { type: 'json_object' }
    }),
    signal: AbortSignal.timeout(apiTimeoutMs)
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`OpenAI API error (${res.status}): ${errText}`);
  }
  const data = await res.json();
  const text = data?.choices?.[0]?.message?.content;
  if (!text) throw new Error('Empty response from OpenAI API');

  return JSON.parse(text);
};

/**
 * Call a locally running Ollama model (e.g. qwen2.5-coder:7b-instruct) via the /api/chat endpoint.
 * Ollama is local so no API key is required.
 * Handles timeouts and safely parses JSON (with format=json the model returns a JSON string,
 * but it may also return a bare object or malformed/truncated text).
 * @param {string} prompt - The user prompt
 * @param {string} [systemInstruction] - Optional system message
 * @param {string} [baseUrl='http://127.0.0.1:11434'] - Ollama server base URL
 * @param {string} [model='qwen2.5-coder:7b-instruct'] - Model name to use
 * @returns {Promise<Object>} Parsed JSON object from the model
 */
const callOllama = async (prompt, systemInstruction = '', baseUrl = 'http://127.0.0.1:11434', model = 'qwen2.5-coder:7b-instruct') => {
  const cleanBase = (baseUrl || 'http://127.0.0.1:11434').replace(/\/+$/, '');
  if (!model) throw new Error('Ollama model is required');

  const messages = [];
  if (systemInstruction && typeof systemInstruction === 'string' && systemInstruction.trim()) {
    messages.push({ role: 'system', content: systemInstruction });
  }
  messages.push({ role: 'user', content: prompt });

  let baseRes;
  try {
    baseRes = await fetch(`${cleanBase}/api/tags`, { signal: AbortSignal.timeout(4000) });
  } catch (err) {
    if (err.name === 'TimeoutError' || err.name === 'AbortError') {
      throw new Error('Ollama is not running (request timed out). Ensure Ollama is started.');
    }
    throw new Error('Ollama is not running. Ensure Ollama is started.');
  }
  if (!baseRes.ok) {
    throw new Error('Ollama is not running. Ensure Ollama is started.');
  }

  let available = false;
  try {
    const tags = await baseRes.json();
    const models = (tags && tags.models) || [];
    available = models.some((m) => m && typeof m.name === 'string' && m.name.split(':')[0].toLowerCase() === model.split(':')[0].toLowerCase());
  } catch {
    available = false;
  }
  if (!available) {
    throw new Error(`Ollama model ${model} is unavailable. Pull it with: ollama pull ${model}`);
  }

  const requestTimeoutMs = Number(process.env.OLLAMA_REQUEST_TIMEOUT) || 180000;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), requestTimeoutMs);

  try {
    const res = await fetch(`${cleanBase}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model,
        messages,
        stream: false,
        format: 'json'
      }),
      signal: controller.signal
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`Ollama API error (${res.status}): ${errText.slice(0, 200)}`);
    }

    const data = await res.json();
    const rawContent = data && data.message && data.message.content;

    if (rawContent === undefined || rawContent === null || String(rawContent).trim() === '') {
      throw new Error('Ollama returned an empty response');
    }

    // If content is already an object, use it directly
    if (typeof rawContent === 'object') {
      return rawContent;
    }

    let parsed;
    try {
      parsed = JSON.parse(rawContent);
    } catch {
      throw new Error('Ollama returned invalid JSON');
    }

    if (parsed === null || parsed === undefined) {
      throw new Error('Ollama returned invalid JSON');
    }
    return parsed;
  } catch (err) {
    if (err.name === 'AbortError' || err.message.includes('timed out') || err.message.includes('aborted')) {
      throw new Error('Ollama request timed out');
    }
    if (err.message === 'Ollama returned invalid JSON' || err.message === 'Ollama returned an empty response') {
      throw err;
    }
    if (err.message.includes('Ollama API error')) {
      throw err;
    }
    throw new Error(`Ollama is not running. Ensure Ollama is started. (${err.message})`);
  } finally {
    clearTimeout(timeoutId);
  }
};

/**
 * Whether an AI provider is effectively available (has enough config to be invoked).
 * Ollama requires no key, so provider === 'ollama' is always considered available.
 */
const canUseAI = (aiConfig) => {
  if (!aiConfig) return false;
  if (aiConfig.provider === 'ollama') return true;
  if (aiConfig.provider === 'gemini') return Boolean(aiConfig.geminiKey);
  if (aiConfig.provider === 'openai') return Boolean(aiConfig.openaiKey);
  return false;
};

/**
 * Dispatcher that routes to the configured provider.
 * Preserves the exact Gemini/OpenAI behavior and adds Ollama support.
 * @returns {Promise<Object>} Parsed JSON object from the chosen provider
 */
const callAI = async (prompt, systemInstruction, aiConfig) => {
  if (!aiConfig) throw new Error('No AI configuration provided');
  if (aiConfig.provider === 'gemini' && aiConfig.geminiKey) {
    return callGemini(prompt, systemInstruction, aiConfig.geminiKey, aiConfig.model);
  }
  if (aiConfig.provider === 'openai' && aiConfig.openaiKey) {
    return callOpenAI(prompt, systemInstruction, aiConfig.openaiKey, aiConfig.model);
  }
  if (aiConfig.provider === 'ollama') {
    return callOllama(prompt, systemInstruction, aiConfig.ollamaBaseUrl, aiConfig.model);
  }
  throw new Error('No usable AI provider configured');
};

/**
 * Fallback Intelligent Research synthesizer
 */
const generateFallbackResearch = (company, pages = []) => {
  const companyName = company.companyName;
  const pageTitles = pages.map(p => p.title).filter(Boolean).slice(0, 5);

  return {
    summary: `${companyName} operates in the ${company.industry || 'B2B technology'} sector, offering specialized solutions and services. Analysis of their digital footprint reveals active operations and strong potential for targeted AI integration and automated workflow transformation.`,
    valueProposition: `Delivers high-quality ${company.industry || 'technology and service'} capabilities designed to drive efficiency, client outcomes, and digital growth.`,
    targetAudience: `Enterprise clients, decision-makers, and teams seeking ${company.industry || 'operational'} excellence and modern technology solutions.`,
    coreOfferings: [
      `${company.industry || 'B2B'} Core Solutions`,
      'Digital Implementation Services',
      'Client Success & Strategic Delivery'
    ],
    techStack: ['Cloud Infrastructure', 'Web Frameworks', 'Analytics Tools', 'Modern API Integration'],
    detectedPainPoints: [
      {
        title: 'Accelerating AI Strategy & Automation',
        description: `Navigating where to integrate AI into existing ${company.industry || 'operational'} workflows without disrupting core production.`,
        evidenceSnippet: 'Identified opportunity for high-impact AI Readiness Assessment and Strategy Consulting.'
      },
      {
        title: 'Team AI Upskilling & Knowledge Enablement',
        description: 'Enabling engineering and operations teams to effectively adopt Generative AI and automation tools.',
        evidenceSnippet: 'Opportunity for hands-on AI & Automation Workshops and team training.'
      },
      {
        title: 'AI Data Architecture & Governance',
        description: 'Ensuring enterprise data hygiene, RAG vector retrieval, and governance guardrails for safe AI scaling.',
        evidenceSnippet: 'Identified need for structured AI Data Strategy and Responsible AI compliance.'
      }
    ],
    icebreakers: [
      `I was exploring ${companyName}'s work in ${company.industry || 'your industry'} and was really impressed by your approach to client delivery.`,
      `I noticed ${companyName}'s focus on innovation and wanted to reach out regarding accelerating your AI roadmap.`,
      `Given ${companyName}'s current growth trajectory, I wanted to discuss how modern AI & automation strategies could unlock significant leverage.`
    ],
    icpFitScore: 92,
    icpFitReasoning: `Strong alignment with TKSR Product Services. ${companyName} has an active web presence and complex workflows that benefit directly from targeted AI Strategy Consulting, Readiness Assessments, and Automation Workshops.`,
    // Never fabricate a person: only include a real contact name when the source
    // data provides one. No name -> no invented "Executive Leadership" entry.
    keyPersonnel: company.contactName
      ? [
          {
            name: company.contactName,
            title: 'Chief Executive Officer / Founder',
            relevance: 'Key decision maker for enterprise AI strategy and technological partnerships.'
          }
        ]
      : [],
    recommendedTksrServices: [
      'AI Strategy Consulting',
      'AI Readiness and Opportunity Assessments',
      'AI & Automation Workshops',
      'AI Training',
      'AI Governance and Responsible AI',
      'AI Data Strategy'
    ],
    aiProvider: 'heuristic_synthesizer',
    confidenceScore: 0.88
  };
};

/**
 * Fallback Intelligent Outreach generator focused on the single most relevant problem and best-fit TKSR service
 */
const generateFallbackOutreach = (company, research, contact, sender, angle, tone, focusService = null) => {
  const companyName = company.companyName;
  const isInbox = contact?.seniority === 'general' || contact?.roleCategory === 'general' || ['support', 'contact', 'info', 'sales', 'hello', 'help'].some(prefix => contact?.email?.toLowerCase().startsWith(prefix + '@'));
  
  const contactGreeting = isInbox ? `Hi ${companyName} Team` : `Hi ${contact?.name?.split(' ')[0] || 'there'}`;
  const contactName = isInbox ? `${companyName} Team` : (contact?.name || company.contactName || 'there');
  const contactTitle = contact?.title || (isInbox ? 'Leadership Team' : 'Executive');
  const senderName = sender?.senderName || 'Nagendra';
  const senderTitle = sender?.senderTitle || 'Business Analyst';
  const myCompany = sender?.companyName || 'TKSR Product Services';

  // Determine single best-fit service based on contact role or selection
  let selectedService = focusService;
  if (!selectedService) {
    if (contact?.roleCategory === 'cto' || contact?.roleCategory === 'cio') {
      selectedService = 'AI Data Strategy';
    } else if (contact?.roleCategory === 'coo') {
      selectedService = 'AI Readiness and Opportunity Assessments';
    } else if (contact?.roleCategory === 'dept_head' && contact?.department?.toLowerCase().includes('governance')) {
      selectedService = 'AI Governance and Responsible AI';
    } else {
      selectedService = 'AI Strategy Consulting';
    }
  }
  
  const serviceDetails = {
    'AI Strategy Consulting': {
      serviceName: 'AI Strategy Consulting',
      painPoint: `prioritizing high-ROI AI initiatives and aligning technology investments with measurable business outcomes`,
      solution: `We help leadership teams audit current capabilities, uncover high-impact use cases, and build an actionable, step-by-step AI implementation roadmap tailored to ${companyName}.`,
      actionPrompt: `explore whether an AI Strategy roadmap could accelerate your current initiatives`
    },
    'AI Readiness and Opportunity Assessments': {
      serviceName: 'AI Readiness and Opportunity Assessments',
      painPoint: `evaluating data infrastructure and workflow maturity before committing significant capital to AI projects`,
      solution: `Our AI Readiness Assessment evaluates your systems, team workflows, and compliance constraints to identify low-risk, high-impact opportunities with zero disruption to active operations.`,
      actionPrompt: `review where an initial AI Readiness audit could uncover quick-win efficiencies`
    },
    'AI & Automation Workshops': {
      serviceName: 'AI & Automation Workshops',
      painPoint: `bridging the gap between conceptual AI ideas and working production automations`,
      solution: `Through structured, hands-on workshops, we partner with your engineering and operations teams to ideate, prototype, and build production-ready automation workflows in days.`,
      actionPrompt: `discuss a tailored workshop session for your technical and operations teams`
    },
    'AI Training': {
      serviceName: 'AI Training',
      painPoint: `enabling internal teams to confidently and safely utilize Generative AI and LLM tools`,
      solution: `We provide practical, role-specific training courses that empower your staff with hands-on prompt engineering, workflow automation tools, and safety guardrails.`,
      actionPrompt: `discuss tailored upskilling tracks for your team`
    },
    'AI Governance and Responsible AI': {
      serviceName: 'AI Governance and Responsible AI',
      painPoint: `ensuring compliance, data privacy, and security guardrails as AI systems scale`,
      solution: `We design enterprise AI governance frameworks, establish audit trails, and implement safety policies so your organization can deploy AI with complete accountability and regulatory confidence.`,
      actionPrompt: `explore how our AI Governance framework can safeguard your scaling systems`
    },
    'AI Data Strategy': {
      serviceName: 'AI Data Strategy',
      painPoint: `structuring disparate data pipelines and vector retrieval architectures for reliable AI models`,
      solution: `We help engineering organizations modernize their data architecture, RAG pipelines, and vector databases to ensure clean, high-precision data foundations for enterprise AI.`,
      actionPrompt: `explore how an optimized AI Data Architecture could enhance your model performance`
    }
  };

  const service = serviceDetails[selectedService] || serviceDetails['AI Strategy Consulting'];
  const icebreaker = research?.icebreakers?.[0] || `I came across ${companyName}'s work in ${company.industry || 'your sector'} and was impressed by your team's execution.`;

  const linkedinNote = isInbox
    ? `Hi ${companyName} Team, saw your work in ${company.industry || 'tech'} and wanted to connect regarding how TKSR Product Services helps companies accelerate ${service.serviceName}.`
    : `Hi ${contact?.name?.split(' ')[0] || 'there'}, noticed your leadership as ${contactTitle} at ${companyName}. Would love to connect and share insights on ${service.serviceName} for growing teams.`;

  const linkedinInmail = `Hi ${contactName},\n\nI've been following ${companyName}'s growth in ${company.industry || 'your market'}.\n\nAs ${contactTitle}, a key operational priority is often ${service.painPoint}.\n\nAt ${myCompany}, our ${service.serviceName} focuses directly on this: ${service.solution}\n\nWould you be open to a brief 10-minute exchange this week to ${service.actionPrompt}?\n\nBest regards,\n${senderName}\n${senderTitle} | ${myCompany}`;

  return [
    {
      step: 1,
      stepLabel: 'Initial Outreach',
      subject: `Accelerating AI & Automation at ${companyName}`,
      angle: angle || 'pain_point',
      tone: tone || 'conversational',
      focusService: selectedService,
      delayDays: 0,
      recipientEmail: contact?.email || '',
      recipientName: contactName,
      bodyHtml: `<p>${contactGreeting},</p>
<p>${icebreaker}</p>
<p>As ${contactTitle} at <strong>${companyName}</strong>, a key strategic priority is often <strong>${service.painPoint}</strong>.</p>
<p>At <strong>${myCompany}</strong>, we specialize in <strong>${service.serviceName}</strong>. ${service.solution}</p>
<p>Would you be open to a brief 10-minute introductory conversation this week to ${service.actionPrompt}?</p>
<p>Best regards,<br/><strong>${senderName}</strong><br/>${senderTitle} | ${myCompany}</p>`,
      bodyText: `${contactGreeting},\n\n${icebreaker}\n\nAs ${contactTitle} at ${companyName}, a key strategic priority is often ${service.painPoint}.\n\nAt ${myCompany}, we specialize in ${service.serviceName}. ${service.solution}\n\nWould you be open to a brief 10-minute introductory conversation this week to ${service.actionPrompt}?\n\nBest regards,\n${senderName}\n${senderTitle} | ${myCompany}`,
      linkedinNote,
      linkedinInmail
    },
    {
      step: 2,
      stepLabel: 'Follow-up: Practical Implementation',
      subject: `Re: Accelerating AI & Automation at ${companyName}`,
      angle: 'value_prop',
      tone: tone || 'conversational',
      focusService: selectedService,
      delayDays: 3,
      recipientEmail: contact?.email || '',
      recipientName: contactName,
      bodyHtml: `<p>${contactGreeting},</p>
<p>Following up on my note earlier this week regarding <strong>${service.serviceName}</strong> for ${companyName}.</p>
<p>Organizations in your space frequently encounter challenges when moving from initial AI experimentation to robust production workflows. Our focused approach helps teams eliminate operational bottlenecks and achieve rapid, quantifiable ROI.</p>
<p>Do you have 10 minutes on Thursday or Friday to connect briefly?</p>
<p>Best regards,<br/><strong>${senderName}</strong><br/>${senderTitle} | ${myCompany}</p>`,
      bodyText: `${contactGreeting},\n\nFollowing up on my note earlier this week regarding ${service.serviceName} for ${companyName}.\n\nOrganizations in your space frequently encounter challenges when moving from initial AI experimentation to robust production workflows. Our focused approach helps teams eliminate operational bottlenecks and achieve rapid, quantifiable ROI.\n\nDo you have 10 minutes on Thursday or Friday to connect briefly?\n\nBest regards,\n${senderName}\n${senderTitle} | ${myCompany}`,
      linkedinNote,
      linkedinInmail
    },
    {
      step: 3,
      stepLabel: 'Break-up / Low-Friction Invitation',
      subject: `Closing the loop: AI Strategy for ${companyName}`,
      angle: 'icebreaker',
      tone: tone || 'conversational',
      focusService: selectedService,
      delayDays: 6,
      recipientEmail: contact?.email || '',
      recipientName: contactName,
      bodyHtml: `<p>${contactGreeting},</p>
<p>I know schedules can be hectic, so I wanted to send one final note.</p>
<p>If you're currently evaluating AI roadmaps or workflow automations at <strong>${companyName}</strong>, we'd be delighted to share a tailored <strong>${service.serviceName}</strong> briefing whenever the timing is right.</p>
<p>If now isn't the best time, feel free to keep us in mind for future initiatives.</p>
<p>Best regards,<br/><strong>${senderName}</strong><br/>${senderTitle} | ${myCompany}</p>`,
      bodyText: `${contactGreeting},\n\nI know schedules can be hectic, so I wanted to send one final note.\n\nIf you're currently evaluating AI roadmaps or workflow automations at ${companyName}, we'd be delighted to share a tailored ${service.serviceName} briefing whenever the timing is right.\n\nIf now isn't the best time, feel free to keep us in mind for future initiatives.\n\nBest regards,\n${senderName}\n${senderTitle} | ${myCompany}`,
      linkedinNote,
      linkedinInmail
    }
  ];
};

module.exports = {
  getAiConfig,
  callGemini,
  callOpenAI,
  callOllama,
  canUseAI,
  callAI,
  generateFallbackResearch,
  generateFallbackOutreach,
  TKSR_SERVICES
};
