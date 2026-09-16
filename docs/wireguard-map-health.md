# WireGuard topology and health (2026-09-16)

The map distinguishes **node connections**, **matched interface-pair tunnels**, and **unidentified peers**. Reciprocal peer reports are deduplicated. Multiple interfaces between two nodes produce one map line with a tunnel count; health is evaluated separately for each tunnel. Unknown or colocated endpoints remain in the list rather than receiving fabricated coordinates.

## Health semantics

- Green: both fresh directional ICMP probes succeeded (5 replies each).
- Orange: a fresh probe observed packet loss; a handshake-only warning is labelled as such, not passed off as an ICMP failure.
- Red: a fresh directional ICMP probe received no response.
- Gray: absent/expired observations, missing permissions/tools, or an unidentified endpoint.

A ping success does not guarantee every TCP application works, and ICMP loss can be affected by endpoint policies. The UI exposes direction, timestamp, sent/received counts, loss and RTT rather than treating recent WireGuard handshakes as data-plane reachability.

`GET /agent/map-targets` authenticates the reporting agent token. Targets are derived only from unique matched public-key fingerprints and peer-interface IPv4 addresses, checked against the local interface's unique longest-prefix AllowedIPs owner. The agent validates these constraints again and binds ping to that WG interface. Each collection permits at most eight targets, two workers, five packets each and a bounded deadline; no shell, arbitrary endpoints or root ping command.

Probe results use the existing bounded AppConfig snapshots; no schema migration. Old reports remain readable and show health unknown until updated. A report's target must match the remote interface and route owner before its measurement can establish health.

Runtime repairs and before/after evidence are documented outside the application repository in `/opt/hermes-workstation/docs/2026-09-16-WG-repair/`. The repair added TYO UDP443 as an alternate transport for the local peer, and restricted HK UDP relay ports for affected home-to-LAX WireGuard traffic. These preserve WG end-to-end encryption and logical peer identities; the map line is a logical tunnel, not proof of a direct geographic route. The relay is currently scoped to the verified home public IP; a future home public-IP change requires updating that source allowlist. No host reboot or default-route replacement was performed.
