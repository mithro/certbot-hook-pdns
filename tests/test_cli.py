"""Tests for certbot_hook_pdns.cli"""

from unittest.mock import patch

import pytest

from certbot_hook_pdns import cli

SOA_FMT = ("welland.mithis.com. 3600 IN SOA welland.mithis.com. "
           "hostmaster.mithis.com. {serial} 10800 3600 604800 300")


def soa_serial(lines: list[str]) -> int:
    fields = lines[0].split()
    return int(fields[fields.index("SOA") + 3])


class TestBumpSerial:
    """The zone has SOA-EDIT=INCEPTION-EPOCH, so pdns serves
    max(file serial, epoch of the last Thursday 00:00 UTC). The file
    serial must therefore jump to the current epoch time, never merely
    increment, or secondaries see no change."""

    def test_stale_serial_jumps_to_now(self):
        # Serial from a generator deploy on 2026-10-27; "now" is 2026-11-17,
        # well past the Thursday 2026-11-12 inception epoch (1794441600).
        lines = [SOA_FMT.format(serial=1793061036), "a. 60 IN A 10.0.0.1"]
        with patch.object(cli.time, "time", return_value=1794875000.7):
            cli.bump_serial(lines)
        assert soa_serial(lines) == 1794875000
        assert lines[1] == "a. 60 IN A 10.0.0.1"

    def test_serial_already_ahead_of_clock_still_increments(self):
        # Two hook runs inside the same second, or a clock step backwards:
        # the serial must still move forward monotonically.
        lines = [SOA_FMT.format(serial=1794875000)]
        with patch.object(cli.time, "time", return_value=1794875000.2):
            cli.bump_serial(lines)
        assert soa_serial(lines) == 1794875001

    def test_no_soa_line_is_an_error(self):
        with pytest.raises(SystemExit):
            cli.bump_serial(["a. 60 IN A 10.0.0.1"])
