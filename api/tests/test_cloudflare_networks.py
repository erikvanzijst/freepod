import ipaddress

import httpx
import pytest

from app.services.hostnames import CLOUDFLARE_NETWORKS

CLOUDFLARE_IPS_API = "https://api.cloudflare.com/client/v4/ips"


def _published_networks() -> set:
    try:
        response = httpx.get(CLOUDFLARE_IPS_API, timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"Cloudflare's IP list is unreachable: {exc}")
    result = response.json()["result"]
    return {ipaddress.ip_network(cidr) for cidr in result["ipv4_cidrs"] + result["ipv6_cidrs"]}


def test_cloudflare_networks_match_the_published_list():
    published = _published_networks()
    ours = set(CLOUDFLARE_NETWORKS)

    missing = sorted(map(str, published - ours))
    stale = sorted(map(str, ours - published))
    assert not (missing or stale), (
        f"CLOUDFLARE_NETWORKS in app/services/hostnames.py differs from {CLOUDFLARE_IPS_API}: "
        f"add {missing or 'nothing'}, remove {stale or 'nothing'}"
    )
