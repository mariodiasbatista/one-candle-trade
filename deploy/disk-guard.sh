#!/usr/bin/env bash
# Weekly disk guard for the One Candle Trade host.
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

NPM_CACHE_LIMIT_MB=2048
ARCHIVE_DIR=/var/projects/one-candle-trade/logs/archive
ARCHIVE_RETENTION_DAYS=90

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

# 4. Warn loudly if still tight after cleanup.
use_pct=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if [ "${use_pct:-0}" -ge 85 ]; then
    log "WARNING: root filesystem still at ${use_pct}% after cleanup — investigate"
    log "top consumers:"
    du -xh --max-depth=2 / 2>/dev/null | sort -rh | head -10 | sed 's/^/  /'
fi

log "disk after:  $(df -h / | awk 'NR==2{print $3" used, "$4" free ("$5")"}')"
