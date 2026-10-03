# Technical Note — Scholarship Intelligence Crawler

**Edxso AI Engineer Intern · Assignment 2**  
**Author:** Nishant Agarwal · **Stack:** Python 3.11, httpx, BeautifulSoup, SQLite, FastAPI  
**Length:** ~3 pages

## 1. Architecture

Pipeline (repeatable CLI / script):

`Seeds → Fetch → Discover links → Classify source → Extract → Verify/Score → Upsert SQLite → Dashboard`

Modules live under `src/scholarship_intel/`:

| Module | Role |
|---|---|
| `discovery/classify.py` | Official vs aggregator; source type |
| `fetch.py` | Polite HTTP client |
| `extract/parsers.py` | NSP listing + detail-page extractors |
| `verify/engine.py` | Deterministic confidence |
| `store/db.py` | SQLite schema, upsert, change log |
| `pipeline.py` | Orchestration |
| `web/app.py` | Dashboard |

Seeds in `config/seeds.yaml` are **hubs**, not a one-URL-one-scraper map. The crawler follows in-domain scholarship links and classifies new URLs.

## 2. Technology choices

- **Free only:** no paid scrape APIs, no paid LLMs for scoring.
- **SQLite:** inspectable single-file DB (`data/scholarships.db`).
- **Deterministic extraction** over LLM generation — critical for anti-hallucination.
- **FastAPI + Jinja:** simple product UI for evaluators.

## 3. Discovery methodology

1. Start from curated official seeds (NSP, UGC, AICTE, IIT Kanpur, trusts).
2. Fetch HTML; if listing (NSP All-Scholarships), parse all scheme cards.
3. From hubs, discover further links whose anchors/URLs contain scholarship language **and** resolve to allowlisted official domains.
4. Aggregator domains are never accepted as primary sources.

This satisfies “discovery should not be completely hard-coded” while staying authenticity-first.

## 4. Extraction methodology

- **NSP cards:** scheme title + `Scheme Open from` / `Student Application Open till|Closed on` dates from sibling spans / parent card text.
- **Detail pages (UGC, IITK):** title, amount (`Rs.` patterns), age, income (`lakh/lac`), eligibility paragraphs — only if present in page text.
- Every populated field stores an **evidence snippet** + source URL.
- Missing fields are stored as **`Not specified`** — never inferred.

## 5. Verification & confidence methodology

**Critical rule followed:** the confidence number is **not** produced by an LLM.

Weighted factors (capped at 100):

| Factor | Points |
|---|---|
| Official-domain primary URL | 30 |
| Live page fetch + name present | 20 |
| Application URL retained | 10 |
| Eligibility evidenced | 12 |
| Deadline evidenced | 12 |
| Amount evidenced | 5 |
| Primary not aggregator | 8 |
| Known source type | 3 |
| Information current (ACTIVE/EXPIRING_SOON) | 5 |

- **≥ 95 → `VERIFIED`**
- **< 95 → `REVIEW_REQUIRED`**
- Hard gate: non-official / aggregator primary cannot be VERIFIED (score capped &lt; 95).

Dashboard shows factor breakdown (“Why this score?”).

## 6. Anti-hallucination

1. Extractors only copy values matched in source text.
2. No default income/amount/deadline when absent.
3. Traceability path: **DB field → evidence.snippet → official_source_url**.
4. Aggregators usable only for discovery (not implemented as primary writers).

## 7. Change detection & stale data

On upsert, tracked fields are diffed. Differences write `change_events`:

`field, old_value, new_value, detected_at, source_url, evidence_snippet`

Lifecycle statuses:

`ACTIVE | EXPIRING_SOON | EXPIRED | REVIEW_REQUIRED | NO_LONGER_VERIFIABLE`

- Closing date &lt; today → `EXPIRED`
- Closing within 30 days → `EXPIRING_SOON`
- Previously active records missing from a listing re-crawl → `NO_LONGER_VERIFIABLE`

Demo: `python scripts/finalize_demo.py` (or `scholarship-intel demo-changes`).

## 8. Working output (sample run)

Typical live run against official sources:

- **41** scholarships discovered
- **32** VERIFIED (confidence ≥ 95%) against primary portals / official PDFs
- Source types: `government_portal`, `government`, `university`, `corporate_csr`, `ngo_trust`
- Cross-enrichment fills evidenced amount/eligibility across matching NSP↔UGC names
- Change events + **2 EXPIRED** examples present in DB
- Official PDF cache under `data/official_docs/` (Reliance FAQ, Tata Means Grant, Lady Meherbai)

## 9. How to run

```bash
pip install -r requirements.txt
set PYTHONPATH=src
python -m scholarship_intel.cli crawl
python scripts/finalize_demo.py
python -m scholarship_intel.cli serve
```

Open `http://127.0.0.1:8765` — inspect metrics, search, detail (evidence + change history).

## 10. Limits (honest)

- NSP listing cards often omit amount/income (correctly left **Not specified**).
- Some university/CSR hubs are JS-heavy or return soft-404s; discovery quality varies by site.
- Confidence rewards evidenced fields; thin official pages stay `REVIEW_REQUIRED` by design.
