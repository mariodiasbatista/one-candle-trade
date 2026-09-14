# System logrotate overrides

These are **system** files, not application config. They live here so the host
can be rebuilt and so the reasoning survives; `originals/` holds the stock
Ubuntu versions as shipped.

    cp rsyslog /etc/logrotate.d/rsyslog
    cp btmp    /etc/logrotate.d/btmp

They are edited in place rather than added as drop-ins because logrotate has no
drop-in mechanism: declaring the same log path in two files is a fatal
"duplicate log entry" error. Because these paths are dpkg conffiles, apt may
prompt on a future rsyslog upgrade — keep the local version and re-apply.

## What changed and why (2026-09-14)

**`rsyslog` — added `maxsize 100M`.** Rotation was weekly with no size ceiling.
When the disk filled, rsyslog logged its "cannot write to /var/log/syslog"
errors *into syslog*, growing it by tens of MB in days — a feedback loop where
running out of disk consumes more disk. The system `logrotate.timer` runs
daily, so `maxsize` is now evaluated daily instead of weekly.

**`rsyslog` — added `create 0640 syslog adm`.** `/var/log` is `root:syslog`
mode 0755, so the `syslog` user cannot create files in it. rsyslog could append
to an existing log but never create one, so the first rotation left it unable
to recreate `syslog` and `auth.log`; its `omfile` action stayed suspended and
**all syslog and authentication logging stopped silently**. logrotate runs as
root, so it now creates the replacement file itself and rsyslog only ever
appends. The alternative fix — making `/var/log` group-writable — was rejected
as it loosens permissions on the whole log directory.

If a log under this block ever goes missing again, recreate it as root with
`install -o syslog -g adm -m 640 /dev/null /var/log/<name>` and restart
rsyslog. Do not chmod `/var/log`.

**`btmp` — added `maxsize 20M`, `compress`, `delaycompress`, `rotate 2`.**
btmp records failed login attempts, which on an internet-facing host arrive
steadily and unpredictably. It was set to `monthly, rotate 1` with no size cap
and no compression, so a busy period could grow it without bound between
rotations. `delaycompress` keeps `btmp.1` readable by `lastb`.

Reviewing btmp volume periodically is worthwhile — a sustained jump is an
operational signal, and capping the log bounds disk use rather than the
underlying cause.
