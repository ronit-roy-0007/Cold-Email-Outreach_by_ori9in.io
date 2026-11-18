# Lead Discovery with Scrapling & Web Crawling

IntentLead AI incorporates an autonomous local business discovery pipeline powered by **Scrapling** and concurrent HTTP crawlers.

---

## 🔍 What Scrapling Does

[Scrapling](https://github.com/D4Vinci/Scrapling) is a high-performance Python web scraping framework that combines:
- **Patchright**: Undetected browser automation that defeats advanced fingerprinting.
- **curl_cffi**: High-speed TLS/JA3 client impersonation to match real browser network handshakes.

In IntentLead AI, Scrapling powers two distinct stages of the acquisition engine:
1. **Google Maps Harvester**: Discovers candidate business listings (name, address, locality, phone, rating, reviews, website) for a given niche and geographic market without requiring paid Google Maps Platform API keys.
2. **Website Reconnaissance Crawler**: Follows discovered business websites to extract contact emails, social profiles, and detect actionable conversion gaps (missing mobile responsiveness, slow appointment booking, absence of 24/7 chat).

---

## ⚙️ Discovery Pipeline Architecture

```text
[Operator Query] (e.g. "Dental Clinics in Chicago")
       │
       ▼
[Geographic Radius Expansion] (Multi-ring radial sectors)
       │
       ▼
[Google Maps Harvester (Scrapling)]
       │
       ▼
[Domain Affinity & Filter Gate] (Excludes portals, Yelp, YellowPages)
       │
       ▼
[Concurrent Website Crawler] (Scrapes homepage, /contact, /about)
       │
       ▼
[Gap & Friction Detection] (Mobile, booking, AI chat, reviews)
       │
       ▼
[0–100 Evidence-Based Scoring]
```

---

## ⚠️ Realistic Expectations & Operational Realities

To maintain trust and technical rigor, operators should understand the real-world operational boundaries of browser-based scraping:

1. **Not an Official Google Maps API**:
   - This repository does **not** use the official paid Google Maps Places API.
   - It parses publicly visible listings directly from Google Maps search feeds.
2. **Lead Counts Are Not Guaranteed**:
   - Listing yield varies significantly based on geographic search density, metro area size, and whether businesses have published websites with accessible contact information.
   - If a market has only 15 listings for a specific niche, the engine will discover those 15 and gracefully report completion rather than inventing fabricated records.
3. **Bot Detection & Rate Limiting**:
   - Google and third-party websites employ dynamic anti-bot mechanisms (such as Cloudflare Turnstile, perimeter rate limits, and network blocklists).
   - Sending excessive concurrent requests from a single residential or datacenter IP may result in temporary HTTP 429 (Too Many Requests) or CAPTCHA challenges.
4. **Responsible Scraping Practices**:
   - **Worker Concurrency Capped**: The crawling engine limits concurrent requests (default: 16 workers) to avoid overwhelming target websites.
   - **Pre-Flight SSRF Guard**: Private RFC 1918 subnets (`127.0.0.1`, `10.0.0.0/8`, `192.168.0.0/16`, AWS metadata `169.254.169.254`) are strictly blocked before issuing any HTTP request.
   - **Ethical B2B Outreach Only**: IntentLead is intended for legitimate B2B relationship building. Operators must comply with CAN-SPAM, GDPR, and CASL regulations.

---

## 🛠️ Configuration Options

Configure your discovery scraper in `.env`:

```bash
# Discovery Provider: "scrapling" (default), "google_maps" (microservice), or "mock" (testing)
DISCOVERY_PROVIDER=scrapling

# Optional Go Google Maps Scraper Service (if running an external scraper daemon)
GOOGLE_MAPS_SCRAPER_BASE_URL=http://localhost:8080
GOOGLE_MAPS_SCRAPER_API_TOKEN=
```
