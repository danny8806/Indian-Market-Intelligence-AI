# ChatGPT + Codex news collection without OpenAI API billing

This is a *staging inbox* for news URLs found by a **ChatGPT Scheduled** or
**Codex Scheduled** task using the account's ChatGPT/Codex product access.
No `OPENAI_API_KEY` is required for this inbound method.

## ChatGPT scheduled task

Use the connected GitHub app and its create-file action to create ONE new file
on `main` for each run, such as:

    news_collector/chatgpt_inbox/2026-11-10T051500-IST.json

Files must contain one JSON object with this exact format:

```json
{
  "schema": "chatgpt-news-discovery/v1",
  "captured_at_ist": "2026-11-10T05:15:00+05:30",
  "articles": [
    {
      "url": "https://example.org/example-thermax-disclosure",
      "headline": "Thermax Limited announces quarterly financial results",
      "publisher": "Example Publisher",
      "publisher_time_claim": null,
      "evidence_note": "A discovered lead; original filing time not confirmed"
    }
  ]
}
```

The example URL is synthetic. NEVER commit it as live evidence. Use actual
verified HTTPS URLs only. `publisher_time_claim` is a nullable hint, NOT a
verified timestamp. Avoid prose invented from search snippets. Every article
must have an attributable headline and URL. The importer limits payloads to
75 articles/file and 250 KB and never fetches those publisher pages itself.

GitHub workflows trigger on new inbox JSON files, run the existing 80-source
collector, import additional ChatGPT links into the **undated** archive,
and optionally sync the database. No path here can directly create a trade
signal. `published_at` is forced to NULL for all ChatGPT/Codex leads.

The importer writes:
- `news_collector/data/<session>/undated_candidates.jsonl`
- `news_collector/data/<session>/chatgpt_inbox_audit.json`
- `news_collector/data/chatgpt_inbox_processed.json`

**No direct database connection is configured by this file.** For PostgreSQL
storage, `NEWS_DATABASE_URL` must be set in a GitHub Actions secret or on
the VPS, or an authorized database connector must be connected in ChatGPT.

## Ready-to-use Codex scheduled task prompt

> In the GitHub repository danny8806/Indian-Market-Intelligence-AI, act as a
> **read-only NIFTY 500 news research and ingestion maintainer**. Inspect the
> latest collector and GitHub Actions source-health report. Verify that source
> collection succeeds, investigate failed public feeds without bypassing 401/403
> or licensing restrictions, and run `python -m unittest discover -s
> news_collector -p 'test_*.py' -v`. Run the collector where network access
> and rights permit. Preserve proper timestamps and URLs; separate search
> discovery from verified original disclosures. Ingest any new ChatGPT inbox
> files through the importer and confirm the database sync when
> `NEWS_DATABASE_URL` is configured. When no DB connection is available,
> retain durable JSONL in GitHub and clearly mark database sync as pending.
> Never add an OpenAI API request, broker order, trade signal, or automated
> execution. Do not modify working source code unless correcting a reproducible
> test failure; open a PR for review and report missing credentials.

Create the Codex scheduled task through **ChatGPT Scheduled** or a supported
Codex project/environment interface. The task requires a persistent or
reusable repository environment and GitHub authorization. On desktop,
local-project tasks require the computer to remain on; Codex Cloud is an
alternative if available on your plan. ChatGPT Scheduled tasks can run
at most hourly, and may consume subscription usage.

## Important separation

ChatGPT/Codex subscription access supports interactive and scheduled model
work; it is **not** a substitute API token that a standalone Linux VPS
can call. The Python/VPS component runs independently between ChatGPT task
invocations and needs only publisher access and a database connection.
