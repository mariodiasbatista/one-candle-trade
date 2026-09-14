#!/usr/bin/env bash
# Daily disk guard for the One Candle Trade host.
#
# Background: on 2026-09-14 the root filesystem hit 98% (626M free). The cause
# was /root/.npm/_cacache at 16G — npm's tarball cache, which has no size limit
# and is never pruned on its own. The bot's own log (324M, unrotated since
# 2026-05-07) was a secondary contributor. Log rotation is handled by
# one-candle-trade-logrotate.timer; this script covers the caches that rotation
# does not touch.
#
# Everything removed here is regenerable cache. No trade data, database, or
# archived log is ever touched.

set -uo pipefail

NPM_CACHE_LIMIT_MB=${NPM_CACHE_LIMIT_MB:-2048}
ARCHIVE_DIR=/var/projects/one-candle-trade/logs/archive
ARCHIVE_RETENTION_DAYS=90
# Alert while there is still room to act. At 85% of this 24G disk roughly 3.5G
# remains free — the last incident was only noticed at 626M.
WARN_PCT=${WARN_PCT:-85}

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [disk-guard] $*"; }

log "disk before: $(df -h / | awk 'NR==2{print $3" used, "$4" free ("$5")"}')"

# 1. npm tarball cache — regenerable, the cause of the 2026-09-14 incident.
if [ -d /root/.npm/_cacache ]; then
    npm_mb=$(du -sm /root/.npm/_cacache 2>/dev/null | cut -f1)
    if [ -n "${npm_mb:-}" ] && [ "$npm_mb" -gt "$NPM_CACHE_LIMIT_MB" ]; then
        log "npm cache ${npm_mb}MB exceeds ${NPM_CACHE_LIMIT_MB}MB — clearing"
        npm cache clean --force >/dev/null 2>&1 && log "npm cache cleared"
    else
        log "npm cache ${npm_mb:-0}MB — within limit"
    fi
fi

# 2. Age out old rotated logs. logrotate keeps 14 by count; this also bounds
#    them by age so a burst of hourly rotations cannot retain months of data.
if [ -d "$ARCHIVE_DIR" ]; then
    # The pre-rotation forensic archives are named main.log-<start>-<end>.gz and
    # trade-events-*.log; -name 'main.log-????????*' matches only the dated files
    # logrotate produces, so the long-range archives are left alone.
    deleted=$(find "$ARCHIVE_DIR" -maxdepth 1 -type f \
        \( -name 'main.log-????????' -o -name 'main.log-????????.gz' \) \
        -mtime +"$ARCHIVE_RETENTION_DAYS" -print -delete 2>/dev/null | wc -l)
    log "archived logs older than ${ARCHIVE_RETENTION_DAYS}d removed: $deleted"
fi

# 3. Trim the apt cache — safe, apt re-downloads on demand.
if command -v apt-get >/dev/null 2>&1; then
    apt-get clean >/dev/null 2>&1 && log "apt cache cleaned"
fi

# 4. Warn if still tight after cleanup — to the journal AND to Telegram.
#    The journal alone is not enough: the 2026-09-14 fill took four months and
#    nobody saw it, because the only warning went to a file no one reads.
use_pct=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if [ "${use_pct:-0}" -ge "$WARN_PCT" ]; then
    log "WARNING: root filesystem at ${use_pct}% after cleanup — investigate"
    log "top consumers:"
    top_consumers=$(du -xh --max-depth=2 / 2>/dev/null | sort -rh | head -8)
    echo "$top_consumers" | sed 's/^/  /'

    avail=$(df -h / | awk 'NR==2{print $4}')
    # cd first so load_dotenv() in src/config finds .env.
    if cd /var/projects/one-candle-trade 2>/dev/null; then
        python3 -c "
import sys
from src.reporting.telegram import send_system_alert
ok = send_system_alert(
    'Disk ${use_pct}% full on the trading host (${avail} free).\n\n'
    'Automatic cleanup already ran and did not bring it under ${WARN_PCT}%.\n\n'
    'Top consumers:\n' + sys.stdin.read()
)
sys.exit(0 if ok else 1)
" <<< "$top_consumers" && log "Telegram alert sent" || log "Telegram alert FAILED"
    fi
fi

log "disk after:  $(df -h / | awk 'NR==2{print $3" used, "$4" free ("$5")"}')"
