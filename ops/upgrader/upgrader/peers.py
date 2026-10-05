"""The pod's own addresses: a request from one of them did not come through the ingress (D6)."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from pathlib import Path


def own_addresses(proc: Path = Path("/proc/net")) -> frozenset[ipaddress._BaseAddress]:
    found: set[ipaddress._BaseAddress] = set()
    try:
        trie = (proc / "fib_trie").read_text()
        found.update(ipaddress.ip_address(a) for a in re.findall(r"\|-- (\S+)\n\s+/32 host LOCAL", trie))
    except OSError:
        pass
    try:
        for line in (proc / "if_inet6").read_text().splitlines():
            found.add(ipaddress.IPv6Address(int(line.split()[0], 16)))
    except (OSError, ValueError, IndexError):
        pass
    try:
        found.update(ipaddress.ip_address(info[4][0].split("%")[0])
                     for info in socket.getaddrinfo(socket.gethostname(), None))
    except (OSError, ValueError):
        pass
    return frozenset(found)


def local(addresses: frozenset[ipaddress._BaseAddress]) -> Callable[[str | None], bool]:
    def is_local(host: str | None) -> bool:
        try:
            address = ipaddress.ip_address((host or "").split("%")[0])
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_loopback or address.is_unspecified or address in addresses

    return is_local
