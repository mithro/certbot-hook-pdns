#!/opt/certbot/bin/python
"""certbot DNS-01 hook for pdns@external (dns-redesign Phase 5).

Edits the bind-backend ZONE FILE directly: pdnsutil add-record/
delete-rrset need a SQL backend ("backend did not accept the new
RRset" on bind), so the hook appends/removes the _acme-challenge TXT
lines itself, bumps the SOA serial in-file, bind-reload-now's, NOTIFYs
the Rollernet secondaries, and (auth only) WAITS until the record is
visible on ns1.rollernet.us — Let's Encrypt validates against the
public NS, not this hidden primary.

The zone file is generator-owned; challenge lines are transient
(cleanup removes them; a generator redeploy also restores canonical
content). certbot runs renewals sequentially, so file edits don't race.

Usage (from /etc/letsencrypt/renewal/*.conf):
  manual_auth_hook    = /opt/certbot/bin/certbot-hook-pdns auth-hook
  manual_cleanup_hook = /opt/certbot/bin/certbot-hook-pdns cleanup-hook
"""

import os
import subprocess
import sys
import time

ZONE = "welland.mithis.com"
ZONE_FILE = f"/etc/powerdns/zones-external/{ZONE}.zone"
CONFIG = "external"
SOCKET_DIR = f"/var/run/pdns-{CONFIG}"
PUBLIC_NS = "ns1.rollernet.us"
WAIT_SECONDS = 240


def run(*argv: str) -> None:
    subprocess.run(argv, check=True, capture_output=True, text=True)


def challenge_fqdn(domain: str) -> str:
    if not (domain == ZONE or domain.endswith(f".{ZONE}")):
        raise SystemExit(f"domain {domain!r} not under {ZONE}")
    return f"_acme-challenge.{domain}"


def bump_serial(lines: list[str]) -> None:
    """Set the zone's SOA serial to the current UNIX time, in place.

    The zone carries SOA-EDIT=INCEPTION-EPOCH, so pdns *serves*
    max(file serial, epoch of the last Thursday 00:00 UTC). A plain +1 on
    a file serial that has fallen behind that weekly value is invisible:
    the served serial never changes, the secondaries never AXFR, and the
    TXT record never appears on the public NS. Writing the epoch time is
    INCEPTION-EPOCH's documented contract; the max() keeps the serial
    monotonic across two runs in the same second or a clock step back.
    """
    for i, line in enumerate(lines):
        fields = line.split()
        if "SOA" in fields:
            soa_idx = fields.index("SOA")
            serial_idx = soa_idx + 3  # SOA <primary> <hostmaster> <serial>
            old = int(fields[serial_idx])
            fields[serial_idx] = str(max(old + 1, int(time.time())))
            lines[i] = " ".join(fields)
            return
    raise SystemExit(f"no SOA line found in {ZONE_FILE}")


def edit_zone(fqdn: str, add_token: str | None) -> None:
    """Append a TXT for fqdn (auth) or drop all its TXT lines (cleanup),
    bumping the serial either way. Atomic replace."""
    with open(ZONE_FILE) as fh:
        lines = fh.read().splitlines()
    if add_token is not None:
        lines.append(f'{fqdn}. 60 IN TXT "{add_token}"')
    else:
        lines = [
            line for line in lines
            if not (line.startswith(f"{fqdn}. ") and " TXT " in line)
        ]
    bump_serial(lines)
    tmp = f"{ZONE_FILE}.acme-tmp"
    with open(tmp, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, ZONE_FILE)


def reload_and_notify() -> None:
    run("pdns_control", f"--config-name={CONFIG}",
        f"--socket-dir={SOCKET_DIR}", "bind-reload-now", ZONE)
    run("pdns_control", f"--config-name={CONFIG}",
        f"--socket-dir={SOCKET_DIR}", "notify", ZONE)


def wait_for_public(fqdn: str, token: str) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["dig", "+short", "+time=3", "+tries=1", f"@{PUBLIC_NS}",
             fqdn, "TXT"],
            capture_output=True, text=True,
        )
        if token in result.stdout:
            return
        time.sleep(5)
    raise SystemExit(
        f"TXT for {fqdn} not visible on {PUBLIC_NS} after {WAIT_SECONDS}s"
    )


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    domain = os.environ["CERTBOT_DOMAIN"]
    fqdn = challenge_fqdn(domain)

    if mode == "auth-hook":
        token = os.environ["CERTBOT_VALIDATION"]
        edit_zone(fqdn, token)
        reload_and_notify()
        wait_for_public(fqdn, token)
    elif mode == "cleanup-hook":
        edit_zone(fqdn, None)
        reload_and_notify()
    else:
        raise SystemExit(f"unknown mode {mode!r} (auth-hook|cleanup-hook)")


if __name__ == "__main__":
    main()
