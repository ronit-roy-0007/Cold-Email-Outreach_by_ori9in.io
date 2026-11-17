# IntentLead AI — AI Provider & Personalization Setup Guide

IntentLead AI uses Large Language Models to conduct automated website intelligence audits and craft hyper-personalized cold outreach pitches.

---

## 1. Supported Providers & Models

### Native Google Gemini (Recommended)
IntentLead AI includes native integration with Google Gemini:
- **`gemini-1.5-flash`** (Default): Fast, cost-efficient, and optimized for high-volume analysis.
- **`gemini-1.5-pro`**: Higher capacity reasoning for complex enterprise service pitches.

### Custom / OpenAI-Compatible Endpoints
Through `USER_LLM_BASE_URL`, you can route requests to any OpenAI-compatible API gateway (LiteLLM, Ollama, LocalAI, vLLM, Groq).

---

## 2. Obtaining a Google Gemini API Key

1. Visit [Google AI Studio](https://aistudio.google.com/).
2. Sign in with your Google account.
3. Click **"Get API key"** and create a key in a new or existing Google Cloud project.
4. Copy the API key (`AIzaSy...`).

---

## 3. Configuration

In your `.env` file:

```bash
# Google Gemini API Key
USER_LLM_API_KEY=AIzaSyYourGeneratedGeminiKeyHere
USER_LLM_MODEL=gemini-1.5-flash

# Optional: Custom OpenAI-compatible gateway (leave blank for native Gemini)
USER_LLM_BASE_URL=
```

---

## 4. Built-in Quota Protection & Pacing

Google Gemini's Free Tier has a rate limit of **15 Requests Per Minute (RPM)**.
IntentLead AI includes an automatic sliding-window `GeminiRateLimiter`:
- Ceilings outgoing requests to **14 RPM** per worker.
- Enforces minimum **4.1-second spacing** between consecutive calls.
- Smooths burst traffic so your campaigns never encounter HTTP 429 quota errors.

---

## 5. Graceful Fallback (Zero Crash Guarantee)

If `USER_LLM_API_KEY` is omitted or temporarily unavailable:
- The system **never crashes**.
- Campaigns automatically fall back to the built-in, conversion-tested cold outreach templates.
- Outbound campaigns continue smoothly without interruption.

---

## 6. How AI Personalization Works

For each discovered prospect, the intelligence engine:
1. Crawls the prospect's public website (subject to `robots.txt` and SSRF IP safety filters).
2. Extracts contact details, forms, social links, meta tags, and interactive widgets.
3. Detects concrete technical and business gaps (e.g. absence of mobile responsiveness, lack of appointment booking, missing 24/7 AI chat, slow lead intake).
4. Feeds verified evidence to the LLM with strict copywriting rules:
   - Starts with `Hi {Business Name},`
   - Identifies the verified gap in the first sentence.
   - Explains how your recommended service resolves it.
   - Concludes with a low-friction call-to-action:
     *"Should I show you the demo how it works? Then we can talk further if you are interested."*
   - Signs off with your configured sender name.

---

## 7. AI Draft Studio (Manual Lead Personalization)

IntentLead AI features an interactive, operator-controlled **AI Draft Studio** inside the individual lead detail view (`/leads/{lead_id}`).

### Key Capabilities
- **On-Demand Generation**: Click **"Generate with AI"** on any individual prospect. Generation is strictly on demand—opening a lead never triggers unauthorized LLM calls.
- **Dual Output**: Simultaneously generates both a punchy, curiosity-driven **Subject Line** and a 3-sentence personalized **Email Body**.
- **Independent Field Editing**: Operators can modify the subject line and email body in real time.
- **Draft Versioning & Concurrency Protection**: Each draft increment tracks a monotonic `version` number. If multiple operators attempt to update the draft simultaneously, an optimistic concurrency conflict (HTTP 409) protects edits from being silently overwritten.
- **PostgreSQL Persistence**: Clicking **"Save Draft"** commits the subject, body, version, and timestamp to the `message_drafts` table, surviving browser reloads and server restarts.
- **Regeneration Safeguard**: If an operator has unsaved edits and clicks **"Regenerate"**, the UI prompts for confirmation before replacing the working draft with a fresh generation preview.
- **Copy Controls**: One-click clipboard actions for **Copy Subject**, **Copy Email**, and **Copy Full Email**.

### Architectural Separation of Outreach Modes

IntentLead AI strictly isolates three distinct outreach modes:

| Mode | Trigger | Scope | Personalization |
|---|---|---|---|
| **Path A: Universal High-Converting Template** | Telegram Step 6 = YES | Entire Campaign | Proven universal copy (Score ≥ 40 benchmark) |
| **Path B: Automated Campaign Personalization** | Telegram Step 6 = NO / Pipeline | Entire Campaign | Background batch LLM generation per prospect audit |
| **AI Draft Studio** | Web Dashboard "Generate with AI" button | Individual Selected Lead | On-demand interactive generation, editing & manual saving |

### Strict Safety & Approval Invariants
- **AI Generate NEVER sends an email.**
- **Regenerate NEVER sends an email.**
- **Save Draft NEVER sends an email.**
- **Saving a draft NEVER automatically approves a lead.** Gate 0 human approval remains strictly enforced before any draft enters the dispatch engine.
- `OUTREACH_DRY_RUN=True` remains active in all environments until explicit live deployment flags are toggled.

