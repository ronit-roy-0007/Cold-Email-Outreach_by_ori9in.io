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
