#!/usr/bin/env bash
# Post-09:12 verification for a frozen morning report. Run on the VPS.
# Usage: bash verify-morning-report.sh [YYYY-MM-DD]
set -euo pipefail
BASE=/home/jadhavdnyaneshwar701/market-news-db
DAY=${1:-$(TZ=Asia/Kolkata date '+%Y-%m-%d')}
PSQL=(docker compose -p market-news-db --env-file "$BASE/config/news.env" -f "$BASE/current/ops/news-stack/compose.yaml" exec -T postgres psql -U news_admin -d market_news -Atqc)

echo "--- release and timers ---"
readlink -f "$BASE/current"
cat "$BASE/last_verified_news_commit"
systemctl is-active market-news-collect.timer market-news-morning.timer
systemctl show market-news-morning.timer -p NextElapseUSecRealtime

echo "--- morning service activations ---"
systemctl show market-news-morning.service -p Result -p ExecMainStartTimestamp -p ExecMainExitTimestamp
journalctl -u market-news-morning.service --since "$DAY 07:55" --no-pager \
  | grep -E 'Starting|Finished|Failed|result=|status|EVIDENCE|READY|NO_TRADE|UNAVAILABLE|DEADLINE' \
  | tail -n 30 || true

echo "--- report row ---"
"${PSQL[@]}" "select 'rows|' || count(*) from news_morning_reports where session_date='$DAY';"
"${PSQL[@]}" "select 'schema|' || coalesce(report->>'schema_version','MISSING') ||
  '|status=' || coalesce(report->>'status','MISSING') ||
  '|execution_enabled=' || coalesce(report->>'execution_enabled','MISSING') ||
  '|cutoff=' || coalesce(report->>'news_cutoff_at','MISSING') ||
  '|generated=' || coalesce(report->>'generated_at','MISSING') ||
  '|signals=' || coalesce(json_array_length(report->'signals')::text,'0')
from news_morning_reports where session_date='$DAY';"

echo "--- signals ---"
"${PSQL[@]}" "select 'signal|' || s->>'side' || '|' || s->>'symbol' || '|rank=' || coalesce(s->>'rank','') ||
  '|first_available=' || coalesce(s->>'first_available_at','')
from news_morning_reports, json_array_elements(report->'signals') s
where session_date='$DAY' order by 1;"
"${PSQL[@]}" "select 'long|' || count(*) from news_morning_reports, json_array_elements(report->'signals') s
  where session_date='$DAY' and s->>'side'='LONG';"
"${PSQL[@]}" "select 'short|' || count(*) from news_morning_reports, json_array_elements(report->'signals') s
  where session_date='$DAY' and s->>'side'='SHORT';"
"${PSQL[@]}" "select 'long_over_5|' || count(*) from news_morning_reports, json_array_elements(report->'signals') s
  where session_date='$DAY' and s->>'side'='LONG'
  group by report->>'session_date' having count(*) > 5;"
"${PSQL[@]}" "select 'short_over_5|' || count(*) from news_morning_reports, json_array_elements(report->'signals') s
  where session_date='$DAY' and s->>'side'='SHORT'
  group by report->>'session_date' having count(*) > 5;"

echo "--- cutoff checks ---"
"${PSQL[@]}" "select 'late_signal|' || count(*) from news_morning_reports, json_array_elements(report->'signals') s
  where session_date='$DAY' and (s->>'first_available_at')::timestamptz >= (report->>'news_cutoff_at')::timestamptz;"
"${PSQL[@]}" "select 'late_source|' || count(*) from news_morning_reports,
  json_array_elements(report->'signals') s, json_array_elements(s->'sources') src
  where session_date='$DAY' and (src->>'published_at')::timestamptz >= (report->>'news_cutoff_at')::timestamptz;"
"${PSQL[@]}" "select 'late_evidence|' || count(*) from news_morning_reports, json_array_elements(evidence->'items') e
  where session_date='$DAY' and (e->>'published_at')::timestamptz >= (report->>'news_cutoff_at')::timestamptz;"
"${PSQL[@]}" "select 'unverified_origin|' || count(*) from news_morning_reports, json_array_elements(evidence->'items') e
  where session_date='$DAY' and coalesce((e->>'verified_origin')::boolean, false) is false;"

echo "--- critic audit ---"
"${PSQL[@]}" "select 'critic|' || coalesce(evidence->'review_audit'->'critic'->>'provider','none') ||
  '|model=' || coalesce(evidence->'review_audit'->'critic'->>'model','') ||
  '|independent=' || coalesce(evidence->'review_audit'->'critic'->>'independent','') ||
  '|status=' || coalesce(evidence->'review_audit'->'critic'->>'status','') ||
  '|review_status=' || coalesce(evidence->'review_audit'->>'review_status','')
from news_morning_reports where session_date='$DAY';"

echo "--- draft ---"
"${PSQL[@]}" "select 'draft|' || status || '|' || to_char(completed_at at time zone 'Asia/Kolkata','YYYY-MM-DD HH24:MI:SS') ||
  '|signals=' || coalesce(json_array_length(signals)::text,'0')
from news_morning_drafts where session_date='$DAY';"

echo "--- source health (latest check per source, not a cutoff snapshot) ---"
"${PSQL[@]}" "select 'checked|' || count(*) || '|ok=' || count(*) filter (where status='OK') ||
  '|failed=' || count(*) filter (where status='ERROR') ||
  '|blocked=' || count(*) filter (where status='BLOCKED_ROBOTS')
from news_source_checks;"

echo "--- report json (for offline schema validation) ---"
echo "REPORT_JSON_BEGIN"
"${PSQL[@]}" "select report::text from news_morning_reports where session_date='$DAY';"
echo "REPORT_JSON_END"
