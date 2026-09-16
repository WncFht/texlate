"""validate_base_url 的 tailnet HTTP 放行（100.64/10 CGNAT + *.ts.net）。"""

import pytest

from texlate.server.settings import validate_base_url


def test_http_tailnet_cgnat_allowed() -> None:
    assert (
        validate_base_url("http://100.105.212.52:3003") == "http://100.105.212.52:3003"
    )


def test_http_ts_net_name_allowed() -> None:
    out = validate_base_url("http://fht-mba.tail109937.ts.net:3003")
    assert out == "http://fht-mba.tail109937.ts.net:3003"


def test_http_localhost_still_allowed() -> None:
    assert validate_base_url("http://127.0.0.1:3003/") == "http://127.0.0.1:3003"


def test_http_public_ip_rejected() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        validate_base_url("http://8.8.8.8:3003")


def test_http_lookalike_suffix_rejected() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        validate_base_url("http://evil.ts.net.attacker.example:3003")


def test_https_remote_still_allowed() -> None:
    assert (
        validate_base_url("https://api.example.com:443/")
        == "https://api.example.com:443"
    )
