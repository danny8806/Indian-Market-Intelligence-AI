# Independent CLI discovery and the Codex morning decision

Python polls exchange, issuer, publisher and broker routes on the VPS every
ten minutes. Codex discovery performs its own live search on eligible slots.
Other CLIs get staggered, independent assignments. The intake normalizes their
results and checks the original publication or exchange feed. It stores the
discoverer's identity separately from the original publisher.

On regular NSE sessions, Codex reviews the combined database at 08:00, 08:30,
08:55 and 09:00 IST. Routine Codex discovery yields its 08:00, 08:30 and 09:00
slots to this review and resumes at 09:30. On closed sessions, routine
discovery keeps its half-hour schedule. Python polling continues throughout.
A provider quota can still block the reserved local calls.

The analyst and critic run before the 09:05 cutoff. The critic is
provider-independent if a separate compatible endpoint is configured. At
09:05 the lock uses verified evidence observed since 15:00 on the previous
regular NSE session. Reviewed picks with changed evidence are dropped. The
lock fills available slots from current verified directional news, up to
five LONG and five SHORT. It makes no model calls. The 09:10 retry is
idempotent and the hard deadline is 09:12. The saved report is research-only.

## Assigned searches

| CLI | Independent assignment | Operator reference |
| --- | --- | --- |
| Codex CLI | Broad fresh filings and financial news | [OpenAI](https://learn.chatgpt.com/docs/non-interactive-mode) |
| Antigravity | Issuer investor-relations releases and filings | [Google](https://antigravity.google/docs/cli/headless/) |
| Claude Code | Governance, auditors and enforcement | [Anthropic](https://code.claude.com/docs/en/headless) |
| Qwen Code | Contracts, capex and smaller companies | [Qwen](https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/) |
| OpenCode | Earnings, guidance and corrections | [OpenCode](https://opencode.ai/docs/websearch/) |
| Kimi Code | Corporate actions and ownership disclosures | [Moonshot](https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html) |
| Mistral Vibe | RBI, SEBI and government releases | [Mistral](https://docs.mistral.ai/vibe/code/cli/work-with-cli) |
| Kiro CLI | BSE and BSE-only issuer announcements | [Kiro](https://kiro.dev/docs/cli/headless/) |
| Copilot CLI | M&A, financing, buybacks and credit changes | [GitHub](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference) |
| Grok Build | Material disruptions and adverse disclosures | [xAI](https://docs.x.ai/build/cli/headless-scripting) |
| Cursor CLI | Follow-up filings and corrections | [Cursor](https://docs.cursor.com/en/cli/headless) |

## Connecting a runner

The stock news service ships with Python and Codex CLI. The other ten assignments
are registered, but each requires a separately installed, authenticated runner
with a working live web tool. A CLI having a headless mode is insufficient.
Connect and smoke-test a provider before provisioning its private inbox directory.

Run the CLI outside the collector as a dedicated account or isolated container,
with its own auth, a fresh working directory, web-only tools, timeout and quota.
It must have no access to the news database, the stock desk or option selling.
Never enable blanket tool approval. Generate the current assignment with
python -m news_collector.agent_intake PROVIDER. Give the agent only its assignment,
without Python results or other agents' findings.

Use a trusted runner to normalize the CLI's actual tool transcript to a JSON
result with provider, assignment_id, scheduled_at, finished_at and status.
RETRIEVED also requires up to eight original HTTPS urls and a retrieval_event
with kind web_search or web_fetch and the CLI's actual tool event id. Capture the
event outside the model's free text. Use AUTH_REQUIRED, NO_LIVE_WEB, QUOTA_LIMIT,
TIMEOUT, NOT_INSTALLED, CLI_ERROR, NO_RESULTS or ACCESS_BLOCKED when applicable.
Failure reports carry no URLs. Atomically rename each result to
<assignment_id>.json inside its provider subdirectory in the cli_inbox volume.
The collector accepts up to two reports per pass. Use one terminal report per
hourly assignment and keep aggregate runner throughput within intake capacity.
Absent lanes are logged as NOT_CONFIGURED. The repository does not contain
provider credentials or a default installer for the additional CLIs.
