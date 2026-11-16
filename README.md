# certbot-hook-pdns

> **Warning:** This project has been vibe coded using [Claude Code](https://claude.ai/claude-code). Review carefully before using in production.

Certbot `--manual-auth-hook` / `--manual-cleanup-hook` for DNS-01 challenges
when the authoritative zone is served by a **PowerDNS bind-backend hidden
primary** and validated against public secondaries.

## Overview

`pdnsutil add-record` / `delete-rrset` do not work on the bind backend
("backend did not accept the new RRset"), so this hook edits the zone file
directly:

1. appends (auth) or removes (cleanup) the `_acme-challenge.<domain>` TXT line,
2. rewrites the SOA serial so the change is visible to secondaries,
3. `pdns_control bind-reload-now` + `pdns_control notify`,
4. (auth only) waits until the TXT is visible on the public nameserver,
   because Let's Encrypt validates against the public NS, not the hidden
   primary.

### Serial handling and `SOA-EDIT=INCEPTION-EPOCH`

DNSSEC-signed zones commonly carry the metadata `SOA-EDIT=INCEPTION-EPOCH`,
under which PowerDNS serves `max(file serial, epoch of the most recent
Thursday 00:00 UTC)`. A file serial that is merely *incremented* stays below
that value and the served serial never changes, so secondaries silently never
transfer. The hook therefore writes the serial as the current UNIX time
(never less than `old + 1`), which is INCEPTION-EPOCH's documented contract.

## Requirements

- Python 3.11+ (no runtime Python dependencies)
- PowerDNS Authoritative Server with the bind backend, `pdns_control`
- `dig` (from `dnsutils` / `bind-utils`)

## Installation

```bash
uv pip install .
```

## Usage

In `/etc/letsencrypt/renewal/<name>.conf`:

```ini
authenticator = manual
pref_challs = dns-01,
manual_auth_hook = /path/to/certbot-hook-pdns auth-hook
manual_cleanup_hook = /path/to/certbot-hook-pdns cleanup-hook
```

Zone, zone-file path, pdns config name, public nameserver and wait time are
module constants in `certbot_hook_pdns/cli.py`.

## Licence

Apache 2.0, see `LICENSE`.
