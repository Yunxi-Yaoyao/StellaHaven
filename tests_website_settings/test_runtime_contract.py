import pytest
from app.services.website_check import safe_address
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_explicit_ipv6_loopback_is_valid_self_hosted_target():
    assert safe_address('::1')=='::1'
@pytest.mark.parametrize('address',['::','fe80::1','fd00:ec2::254','169.254.169.254','100.100.100.200','2001:db8::1'])
def test_loopback_exception_does_not_allow_metadata_or_reserved(address):
    with pytest.raises(ValueError):safe_address(address)
def test_runtime_and_ci_install_real_js_syntax_checker():
    assert 'install -y --no-install-recommends ffmpeg nodejs' in (ROOT/'Dockerfile').read_text()
    assert 'install -y --no-install-recommends ffmpeg sudo nodejs' in (ROOT/'.gitlab-ci.yml').read_text()
