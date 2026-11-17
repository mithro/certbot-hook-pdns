# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Certbot DNS-01 `--manual-auth-hook` / `--manual-cleanup-hook` for a PowerDNS
**bind-backend hidden primary** whose zone is published by external
secondaries (Rollernet for `welland.mithis.com` and `monarto.mithis.com`).
Distributed as a Python package with a `certbot-hook-pdns` CLI entry point.

Deployed on both Ten64 routers (`ten64.welland.mithis.com`,
`ten64.monarto.mithis.com`) inside the certbot venv:
`/opt/certbot/hooks/certbot-hook-pdns` (git clone) installed editable, giving
`/opt/certbot/bin/certbot-hook-pdns`. The venv self-heal in
`/etc/certbot/renew-guarded` preserves `hooks/` and reinstalls every package
found there, so the hook survives a Python minor-version upgrade **only**
because it lives under `hooks/` as a package.

## Project Structure

```
certbot_hook_pdns/
    __init__.py      # __version__
    __main__.py      # python -m certbot_hook_pdns
    cli.py           # the whole hook: zone-file edit, serial, reload+notify, wait
tests/
    test_cli.py
pyproject.toml
```

## How it works

`cli.py` `main()` first calls `find_zone(CERTBOT_DOMAIN)`, which parses
`/etc/powerdns/bind-external.conf` and returns the longest declared zone
containing the domain (label-boundary match) together with its zone file.
Nothing site-specific is hardcoded: the same code runs on welland and
monarto. It then dispatches on `argv[1]`:

- `auth-hook`: `edit_zone(zone_file, fqdn, token)` appends a 60 s TXT line and rewrites
  the SOA serial, `reload_and_notify(zone)` runs `pdns_control bind-reload-now`
  then `notify`, `wait_for_public()` polls `dig @ns1.rollernet.us` for up to
  240 s and exits 1 if the token never appears.
- `cleanup-hook`: `edit_zone(zone_file, fqdn, None)` drops all TXT lines for the fqdn,
  rewrites the serial, reload + notify. No wait.

The zone file is **generator-owned** (gdoc2netcfg writes it on deploy, with
the serial set to the generation time). Challenge lines are transient; a
generator redeploy restores canonical content.

## The serial rule (do not regress this)

The zone carries `SOA-EDIT = INCEPTION-EPOCH` (`pdnsutil --config-name=external
get-meta welland.mithis.com`). PowerDNS then *serves* `max(file serial,
epoch of last Thursday 00:00 UTC)`. A plain `old + 1` bump is therefore
invisible once the file serial falls behind the weekly inception value: the
primary reloads and NOTIFYs, but the served serial is unchanged, the
secondaries never AXFR, and the auth hook times out with
"TXT ... not visible on ns1.rollernet.us after 240s". This broke every DNS-01
renewal on welland from 2026-10-29 until fixed (see the git history).

`bump_serial` must write `max(old + 1, int(time.time()))`. Verify after any
change by comparing the file serial with `dig +short SOA <zone> @<primary>`.

## Development

```bash
uv run --with pytest pytest
```

External commands (`pdns_control`, `dig`) are only called from `run()` and
`wait_for_public()`; tests patch `subprocess.run`.
