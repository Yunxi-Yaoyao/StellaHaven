"""Numeric management target boundary, manually mirrored in downloadable Agent."""


def _parse_entry_scope(targets, ranges):
    """Parse the entire bounded scope before membership; None means trusted absence."""
    import ipaddress
    if targets is not None and (not isinstance(targets, list) or len(targets) > 64):
        raise ValueError('invalid entry targets')
    if not isinstance(ranges, list) or len(ranges) > 16:
        raise ValueError('invalid entry ranges')
    exact = []
    for value in targets if targets is not None else []:
        if not isinstance(value, str) or not 1 <= len(value) <= 64 or '%' in value:
            raise ValueError('invalid entry target')
        ipaddress.ip_address(value)
        exact.append(value)  # Preserve the existing canonical-string exact match.
    networks = []
    for value in ranges:
        if not isinstance(value, str) or not 1 <= len(value) <= 64 or '%' in value:
            raise ValueError('invalid entry range')
        networks.append(ipaddress.ip_network(value, strict=True))
    return None if targets is None else exact, networks


def _entry_scope(scope):
    """Raw envelopes distinguish absent targets from explicit invalid null."""
    if not isinstance(scope, dict) or ('targets' in scope and scope['targets'] is None):
        raise ValueError('invalid raw entry scope')
    return _parse_entry_scope(scope.get('targets'), scope.get('approved_ranges', []))


def _entry_ip_allowed(value, targets, ranges):
    """Numeric-only pinning. Never permit metadata/special-purpose destinations."""
    import ipaddress
    try:
        exact_targets, networks = _parse_entry_scope(targets, ranges)
        if not isinstance(value, str) or not 1 <= len(value) <= 64 or '%' in value:
            return False
        ip = ipaddress.ip_address(value)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast
                or ip.is_reserved or str(ip) in {'100.100.100.200', '168.63.129.16', 'fd00:ec2::254'}):
            return False
        exact = exact_targets is not None and str(ip) in exact_targets
        approved = any(ip in network for network in networks if network.version == ip.version)
        if exact_targets is not None and not (exact or approved):
            return False
        private = ip in ipaddress.ip_network('10.0.0.0/8') if ip.version == 4 else ip in ipaddress.ip_network('fc00::/7')
        if ip.version == 4:
            private = private or ip in ipaddress.ip_network('172.16.0.0/12') or ip in ipaddress.ip_network('192.168.0.0/16')
        return (ip.is_global or private) and (not private or exact or approved)
    except (ValueError, TypeError):
        return False
