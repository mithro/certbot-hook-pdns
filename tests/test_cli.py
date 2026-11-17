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


class TestFindZone:
    """The hook runs on more than one site (welland, monarto), each with
    its own zone. The zone and its file come from the pdns bind-backend
    config rather than a constant, so one deployment fits every site."""

    CONF = (
        'zone "welland.mithis.com" { type primary; '
        'file "/etc/powerdns/zones-external/welland.mithis.com.zone"; };\n'
        'zone "birds.mithis.com" { type primary; '
        'file "/etc/powerdns/zones-external/birds.mithis.com.zone"; };\n'
    )

    def write_conf(self, tmp_path, text=None):
        conf = tmp_path / "bind-external.conf"
        conf.write_text(self.CONF if text is None else text)
        return str(conf)

    def test_subdomain_maps_to_its_zone_and_file(self, tmp_path):
        conf = self.write_conf(tmp_path)
        zone, zone_file = cli.find_zone("ten64.welland.mithis.com", conf)
        assert zone == "welland.mithis.com"
        assert zone_file == "/etc/powerdns/zones-external/welland.mithis.com.zone"

    def test_apex_maps_to_itself(self, tmp_path):
        conf = self.write_conf(tmp_path)
        zone, _ = cli.find_zone("birds.mithis.com", conf)
        assert zone == "birds.mithis.com"

    def test_longest_matching_zone_wins(self, tmp_path):
        conf = self.write_conf(tmp_path, (
            'zone "mithis.com" { type primary; file "/z/mithis.com.zone"; };\n'
            'zone "welland.mithis.com" { type primary; '
            'file "/z/welland.mithis.com.zone"; };\n'
        ))
        zone, zone_file = cli.find_zone("bmc.x.welland.mithis.com", conf)
        assert zone == "welland.mithis.com"
        assert zone_file == "/z/welland.mithis.com.zone"

    def test_label_boundary_is_respected(self, tmp_path):
        # "notwelland.mithis.com" ends with "welland.mithis.com" as a string
        # but is not inside that zone.
        conf = self.write_conf(tmp_path)
        with pytest.raises(SystemExit):
            cli.find_zone("notwelland.mithis.com", conf)

    def test_domain_outside_every_zone_is_an_error(self, tmp_path):
        conf = self.write_conf(tmp_path)
        with pytest.raises(SystemExit):
            cli.find_zone("example.org", conf)

    def test_monarto_conf(self, tmp_path):
        conf = self.write_conf(tmp_path, (
            'zone "monarto.mithis.com" { type primary; '
            'file "/etc/powerdns/zones-external/monarto.mithis.com.zone"; };\n'
        ))
        zone, zone_file = cli.find_zone("ten64.monarto.mithis.com", conf)
        assert zone == "monarto.mithis.com"
        assert zone_file.endswith("/monarto.mithis.com.zone")
