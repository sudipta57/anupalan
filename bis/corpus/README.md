# BIS corpus

One YAML file per document. `backend/scripts/ingest_bis.py` reads this directory, hands each file to
`services/bis/ingest.ingest()`, and then embeds whatever is new.

```yaml
source_type: mandatory_cert_list     # one of the eight kinds below
title: Products under Compulsory Certification
url: https://www.bis.gov.in/...      # where the text came from, quoted back in every citation
published_at: 2026-04-15             # optional; feeds the freshness stamp on an answer
text: |
  The page's own words, as published.
```

## The eight admissible kinds

`qco_gazette` · `mandatory_cert_list` · `crs_list` · `scheme_guide` · `faq` · `hallmarking` ·
`lab_directory` · `catalogue_metadata`

`ingest.screen()` refuses anything else, and refuses any document whose text reads like a priced
standard whatever it was labelled — see `PRICED_STANDARD_BLOCKLIST` and CLAUDE.md §3.5. **Never add
the body of an Indian Standard here.** Full IS documents are copyrighted and sold by BIS; this corpus
holds public material only.

## Why files, and why they are curated by hand

Every document here is quoted back to a user as the source of an answer. A file in this directory is
reviewable in a diff, reproducible on another machine, and fixed in time — so in a year it is still
possible to say exactly what text an answer was given from. That is worth more than a scraper's
convenience.

Two practical warnings, both learned the hard way while seeding this directory:

- **bis.gov.in serves soft 404s.** A wrong URL returns HTTP 200 with a generic page, not an error.
  Two such pages were caught here only because their extracted text was byte-identical. Check that a
  document's text is actually about its title before committing it.
- **The pages are mostly navigation.** A whole-page text dump is menus, and chunks of menu text get
  retrieved and cited. Take the content region only.

## Adding a document

Paste the text from a page you have opened and read, fill in the four required keys, then:

```bash
cd backend && .venv/bin/python -m scripts.ingest_bis
```

Re-running is safe: documents are keyed by the sha256 of their content, so unchanged files are a
no-op, and an amended document becomes a new row rather than an edit.
