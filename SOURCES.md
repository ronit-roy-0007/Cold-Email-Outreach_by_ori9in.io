# Upstream Sources and Reuse Boundaries

This project has two upstream repositories with distinct roles.

## 1. Primary: Google Maps Scraper

URL: https://github.com/gosom/google-maps-scraper

Role:
- Initial local-business discovery.
- Retrieves listing fields such as name, category, address, website, phone, ratings/review counts, coordinates, and available review data.
- Can expose CLI, Web UI, and REST API modes according to its current upstream documentation.

IntentLead integration:
- Call its supported API.
- Normalize output into our own schema.
- Preserve original source fields and scrape timestamps.
- Deduplicate before website enrichment.

Do not assume Google Maps results prove a business wants to buy a service.

## 2. Reference: First Customer Finder

URL: https://github.com/Kappaemme-git/codex-first-customer-finder-skill

Role:
- Reference implementation for evidence-first prospect research.
- Learn from its weighted qualification, source checking, feedback/history, stable IDs, duplicate handling, and structured reporting.
- Its README describes it as a Codex skill; it is not the primary Google Maps scraping engine.

IntentLead adaptation:
- Reimplement useful concepts in our own Python/FastAPI service.
- Add tests and adapt scoring to the agency's services.
- Do not make its Codex runtime, scripts, or local history a production dependency.
- Do not copy code wholesale without checking license obligations and attribution.

## 3. License and distribution note

The public GitHub pages surfaced during preparation identify both repositories as MIT licensed. Before redistributing source, verify the current `LICENSE` files and preserve copyright/license notices. This pack does not include upstream source files; it contains links, integration notes, and independently authored project documentation.

## 4. Access note

The GitHub repositories could not be cloned in the ZIP-generation environment. Therefore this pack does not pretend to contain full source snapshots. Clone them from the official URLs using the commands in `github.md`.
