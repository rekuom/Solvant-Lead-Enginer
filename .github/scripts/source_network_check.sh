#!/usr/bin/env bash
# Low-level HTTPS reachability check for the Phase 2A source domains.
# Records DNS, proxy, TLS/connect and HTTP outcomes as SEPARATE columns so a
# network-policy block is never confused with an upstream refusal.
# One GET per URL, no retries, no crawling. Never prints environment values.
# Usage: source_network_check.sh [output_dir]
set -uo pipefail

OUT_DIR="${1:-network-check}"
mkdir -p "$OUT_DIR"
TSV="$OUT_DIR/curl_results.tsv"
MD="$OUT_DIR/curl_results.md"
UA="SolvantSignalEngine-network-test/0.1 (+https://solvant.io)"

DOMAINS=(
  "www.contractsfinder.service.gov.uk"
  "www.find-tender.service.gov.uk"
  "community.n8n.io"
  "community.make.com"
)
PATHS=("/robots.txt" "/")

# Proxy presence only (set/unset) — values are never printed.
for v in HTTPS_PROXY https_proxy HTTP_PROXY http_proxy; do
  if [ -n "${!v:-}" ]; then echo "proxy env $v: set"; else echo "proxy env $v: unset"; fi
done

printf "domain\tpath\tdns\tresolved_ip\tproxy_connect\tcurl_exit\tcurl_error_class\thttp_status\tredirects\tfinal_url\tcontent_type\tseconds\tverdict\n" > "$TSV"

classify_exit() {  # curl exit code -> failure class
  case "$1" in
    0)  echo "none" ;;
    5)  echo "proxy_dns_failure" ;;
    6)  echo "dns_failure" ;;
    7)  echo "connect_refused" ;;
    28) echo "timeout" ;;
    35|53|54|58|59|60|66|77|80|82|83|90|91) echo "tls_failure" ;;
    47) echo "too_many_redirects" ;;
    52|56) echo "connection_reset_or_proxy_refused" ;;
    *)  echo "curl_error_$1" ;;
  esac
}

for d in "${DOMAINS[@]}"; do
  # 1) DNS, independent of curl
  if ip=$(getent ahosts "$d" 2>/dev/null | awk 'NR==1{print $1}') && [ -n "$ip" ]; then
    dns="resolved"
  else
    dns="FAILED"; ip="-"
    if [ -n "${HTTPS_PROXY:-${https_proxy:-}}" ]; then dns="FAILED_LOCAL(proxy resolves)"; fi
  fi
  for p in "${PATHS[@]}"; do
    url="https://${d}${p}"
    # 2) HTTPS request, following up to 5 redirects; body discarded.
    w=$(curl -sS -o /dev/null -L --max-redirs 5 --connect-timeout 8 --max-time 15 -A "$UA" \
          -w '%{http_code}|%{num_redirects}|%{url_effective}|%{content_type}|%{time_total}|%{http_connect}' \
          "$url" 2>"$OUT_DIR/.curl_err")
    rc=$?
    # '|' (not tab) so empty fields are preserved: tab is IFS-whitespace and would merge them.
    IFS='|' read -r code redirs final ctype secs pconnect <<< "$w"
    cls=$(classify_exit "$rc")
    # A non-2xx CONNECT answer means the PROXY refused, not the website.
    if [ -n "${pconnect:-}" ] && [ "${pconnect}" != "000" ] && [ "${pconnect:0:1}" != "2" ]; then
      proxy="REFUSED_${pconnect}"; cls="proxy_block"
    elif [ -n "${pconnect:-}" ] && [ "${pconnect}" != "000" ]; then
      proxy="ok_${pconnect}"
    else
      proxy="no_proxy_used"
    fi
    if [ "$rc" -eq 0 ] && [ "${code:0:1}" = "2" ]; then verdict="REACHABLE"
    elif [ "$rc" -eq 0 ] && [ "${code:0:1}" = "3" ]; then verdict="REACHABLE_REDIRECT_LIMIT"
    elif [ "$rc" -eq 0 ] && [ "$code" = "401" ]; then verdict="REACHABLE_AUTH_REQUIRED"
    elif [ "$rc" -eq 0 ] && [ "$code" = "403" ]; then verdict="REACHABLE_UPSTREAM_FORBIDDEN"
    elif [ "$rc" -eq 0 ] && [ "$code" = "404" ]; then verdict="REACHABLE_NOT_FOUND"
    elif [ "$rc" -eq 0 ] && [ "$code" = "429" ]; then verdict="REACHABLE_RATE_LIMITED"
    elif [ "$rc" -eq 0 ]; then verdict="REACHABLE_HTTP_${code}"
    elif [ "$cls" = "proxy_block" ]; then verdict="BLOCKED_BY_PROXY"
    elif [ "$cls" = "dns_failure" ] || [ "$cls" = "proxy_dns_failure" ]; then verdict="DNS_FAILURE"
    elif [ "$dns" = "FAILED" ] && [ "$proxy" = "no_proxy_used" ]; then verdict="DNS_FAILURE"
    else verdict="UNREACHABLE_${cls}"
    fi
    err=$(head -c 160 "$OUT_DIR/.curl_err" | tr '\t\n' '  ')
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
      "$d" "$p" "$dns" "$ip" "$proxy" "$rc" "$cls${err:+ ($err)}" "${code:-000}" "${redirs:-0}" \
      "${final:-$url}" "${ctype:--}" "${secs:-0}" "$verdict" >> "$TSV"
  done
done
rm -f "$OUT_DIR/.curl_err"

{
  echo "### HTTPS reachability (curl)"
  echo
  echo "| domain | path | DNS | proxy CONNECT | curl exit / class | HTTP | redirects | final URL | content-type | verdict |"
  echo "|---|---|---|---|---|---|---|---|---|---|"
  tail -n +2 "$TSV" | while IFS=$'\t' read -r d p dns ip proxy rc cls code redirs final ctype secs verdict; do
    echo "| $d | $p | $dns | $proxy | $rc / ${cls//|//} | $code | $redirs | $final | $ctype | **$verdict** |"
  done
} > "$MD"

column -t -s $'\t' "$TSV" 2>/dev/null || cat "$TSV"
echo
echo "=== Per-domain reachability ==="
for d in "${DOMAINS[@]}"; do
  if awk -F'\t' -v d="$d" '$1==d && $13 ~ /^REACHABLE/ {f=1} END{exit !f}' "$TSV"; then
    echo "REACHABLE      $d"
  else
    echo "NOT REACHABLE  $d  ($(awk -F'\t' -v d="$d" '$1==d{print $13}' "$TSV" | sort -u | tr '\n' ' '))"
  fi
done
exit 0  # diagnostic: never fail the job on reachability
