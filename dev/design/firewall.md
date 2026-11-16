# SNAC Firewall: Coexisting with NI Firewall Drop-ins

| | |
|---|---|
| **Status** | Accepted (2026-11-16) |
| **Tracking** | AB#4008296 (Feature AB#2921895) |
| **Targets** | NI Linux RT 2027 Q1 (27.0); next nilrt-snac major release |
| **Components** | `nilrt-snac` (this repo); `meta-nilrt`: `ni-firewall-dropins`, `ni-firewalld-servicedefs` |


## Summary

NI Linux RT 27.0 adds a declarative firewall contract. An NI package that needs an inbound port
ships a firewalld service definition plus a drop-in marker, and the OS opens that service. SNAC
predates this contract. It reaches every NI product through a WireGuard tunnel and a hand-curated
list of ports.

Under this design, any service declared through a drop-in is opened on **both** the plain network
and the WireGuard tunnel. Products that have not onboarded yet stay reachable **only** through the
tunnel, as they are today. Drop-in services go into a new NI-owned firewalld policy, `ni-dropins`,
which applies to the `public` and `work` zones, instead of into the default zone.


## Background

### SNAC's WireGuard tunnel

SNAC sets up a WireGuard endpoint (`wglv0`, 172.16.1.1/24, udp/51820) on the target. The user
configures the other end on their Windows host. NI driver and LabVIEW traffic between the host and
the target then runs inside the tunnel. The tunnel exists for legacy NI products that do not encrypt
their own traffic.

The tunnel is **transitional**. NI products are required to:
* declare their ports through the drop-in contract, and
* implement native on-the-wire encryption.

Both requirements are due by the EU Cyber Resilience Act (CRA) implementation date. Once every
supported product is onboarded, the tunnel and SNAC's legacy port list can be removed.

### How SNAC configures the firewall today

`_FirewallConfig.configure()`:
1. runs `firewall-offline-cmd --reset-to-defaults`,
2. binds `wglv0` to zone `work`,
3. builds four policies:

| Policy | Direction | Target | Allowed |
|---|---|---|---|
| `public-in` | `public` → HOST | CONTINUE | icmp, ssh, wireguard |
| `public-out` | HOST → `public` | REJECT | icmp, dhcp, dhcpv6, dns, ntp, http, https, wireguard |
| `work-in` | `work` → HOST | CONTINUE | icmp, ssh, mdns, **legacy NI list**: ni-labview-realtime, ni-labview-viserver, ni-logos-xt, ni-mxs, ni-orb-rpc-server, ni-service-locator, 55184/tcp |
| `work-out` | HOST → `work` | REJECT | icmp, ssh, http, https, syslog, ni-logos-xt, amqp, salt-master |

After configure, the `public` and `work` zones each contain only `ssh` and `dhcpv6-client`.
Everything NI-specific is reachable only through `work-in`, which means only through the tunnel.

Inbound http/https (80/443) is rejected on both paths. This is intentional:
* Web-Based Configuration is being retired and is not supported under SNAC.
* Hardware Manager workflows have moved to SSH (22).

### The NI firewall drop-in contract (meta-nilrt)

* **`ni-firewalld-servicedefs`**
  * Ships the NI firewalld service XMLs.
  * Ships `ni-firewall-open` / `ni-firewall-close`, which open or close a service in the **default
    zone**, both live and offline.
  * Its postinst opens the always-on core services in the default zone: `ni-service-locator`,
    `ni-mxs`, `ni-logos-xt`, `http`, `https`, `mdns`.
* **`ni-firewall-dropins`**
  * Defines the contract directory, `/etc/ni/firewall/open.d/`. A package installs a marker there
    naming one or more firewalld services.
  * `ni-firewall-apply` reconciles the markers with firewalld at boot (S02, offline, before firewalld
    starts at S03) and after every opkg transaction (an opkg post_invoke hook).
  * It opens services in the **default zone** through `ni-firewall-open`.
  * It records what it opened in `/var/lib/ni/firewall/applied`, so it only ever closes services it
    opened itself.
* **firewalld** starts only when `SystemSettings.firewall.enabled=true` in `ni-rt.ini`. SNAC sets
  this; otherwise it is off by default.


## Problem

Measured on an NI Linux RT 27.0 VM with SNAC configured. A network namespace emulated the Windows
host, reaching the target both directly (plain NIC, zone `public`) and through a WireGuard peer
(`wglv0`, zone `work`).

| Port | Service | Plain NIC | Tunnel |
|---|---|---|---|
| 3079 | `ni-labview-realtime` (SNAC legacy list, plus a drop-in) | OPEN ⚠ | OPEN |
| 49580 | `opcua` (drop-in only) | OPEN | REJECT ⚠ |
| 9999 | undeclared | REJECT | REJECT |

1. **Onboarded products are unreachable through the tunnel.** Drop-ins only open services in the
   default zone (`public`). Hosts already set up to use the tunnel lose those products.
2. **SNAC verify fails when a drop-in names a legacy-list service.** `verify` checks that
   `ni-labview-realtime` is absent from the `public` zone; a drop-in for that service puts it
   there, so `nilrt-snac verify` fails.
3. **`nilrt-snac configure` silently removes drop-ins.** `--reset-to-defaults` wipes them. They come
   back only at the next boot or opkg transaction.


## Goals

* Honor every service declared through the drop-in contract on both the plain network and the
  WireGuard tunnel.
* Keep products that are not yet onboarded reachable only through the tunnel.
* Survive `nilrt-snac configure` re-runs, reboots, and package installs and removals without manual
  steps.
* Leave behavior on non-SNAC systems unchanged.

## Non-goals

* **Egress.** The drop-in contract covers only inbound traffic, and SNAC rejects outbound traffic on
  `public` that isn't in its own allowlist. Outbound requirements for onboarded products will be
  passed to the NI Linux RT team, who will pass them on to IPK owners. This design does not extend
  the contract.
* **Changing the always-on core services.** They stay in the default zone (see
  [Core services](#core-services)).
* **Making the zone set configurable.** The policy's ingress zones are fixed at `public` and `work`.
* **A strict "tunnel-only" SNAC mode.** No customer or compliance requirement needs one.


## Trust model

**A drop-in marker is trusted.**
* The internal mandate that requires products to declare ports through drop-ins comes together with
  the mandate to encrypt their traffic on the wire.
* So a product that ships a marker is treated as safe to expose outside the tunnel.
* SNAC does not attest, allowlist, or second-guess drop-in services.

**Version skew is handled by this model:**
* An older, plaintext build of a product ships no marker, so it stays tunnel-only through the legacy
  list.
* The onboarded build ships a marker and opens on both paths.
* The legacy-list entry has no effect for the onboarded build and can be retired.


## Design

### 1. `ni-dropins` firewalld policy (meta-nilrt, `ni-firewall-dropins`)

Ship `/usr/lib/firewalld/policies/ni-dropins.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<policy target="CONTINUE" priority="100">
  <short>NI drop-ins</short>
  <description>Inbound services declared by NI packages via /etc/ni/firewall/open.d.</description>
  <ingress-zone name="public"/>
  <ingress-zone name="work"/>
  <egress-zone name="HOST"/>
</policy>
```

* **Shipped under `/usr/lib`, not created under `/etc`.**
  * `firewall-offline-cmd --reset-to-defaults` removes only the `/etc` override, so the policy
    survives a SNAC reset. It survives empty, and `ni-firewall-apply` refills it.
  * Adding services writes an `/etc/firewalld/policies/ni-dropins.xml` override; that is normal
    firewalld behavior.
* **Explicit ingress zones, not `ANY`.**
  * Prototyping showed that a policy with ingress `ANY` opens its services even on an interface the
    user placed in the `drop` zone, even at positive priority.
  * With explicit `public` + `work`, a user's `drop`/`block` zone still wins.
* **`target=CONTINUE`.** Traffic not matched by the policy falls through to the normal zone and
  policy evaluation.
* **Without SNAC,** nothing is bound to `work`, so the policy covers exactly what the default zone
  (`public`) covered before. Behavior is unchanged.
* **With SNAC,** `public` is the plain NIC and `work` is `wglv0`, so declared services open on both
  paths with no SNAC-specific wiring.

### 2. Drop-ins write into the policy (meta-nilrt)

**`ni-firewall-open` / `ni-firewall-close`** gain a way to target a policy, for example
`--policy=<name>`.
* Without the option, they keep targeting the default zone. The `ni-firewalld-servicedefs` postinst
  (core services) uses them that way and is unchanged.
* Live and offline handling, permanent and runtime sync, and the "reload if the definition isn't
  loaded" logic apply to policies the same way they do to zones.

**`ni-firewall-apply`**
* Opens and closes marker services in policy `ni-dropins` instead of the default zone.
* Reads enabled state from that policy, permanent and runtime, the same way it reads the default
  zone today.
* **Reconciles against the actual config.** It opens any desired service the policy lacks, even if
  the state file already lists it. That is what lets one re-run restore the policy after a SNAC
  reset. Today's hook already behaves this way against the default zone (confirmed on the VM).
* **One-time migration.**
  * Detect the old state format by the absence of the `# ni-firewall-apply state v2` header in
    `/var/lib/ni/firewall/applied`.
  * First open the services from the old state file that are still declared in `ni-dropins`. Then
    close every service from the old state file in the default zone. A declared service therefore
    stays reachable throughout.
  * Before opening them, record the still-declared services as the hook's own in the policy.
  * The v2 state file keeps ownership and pending cleanup apart: plain lines are services the hook
    owns in the policy, and `zone:<service>` lines are default-zone removals still to be done.
  * If a step fails, write the state file before exiting, and retry the pending removals on the
    next run. Reopening is idempotent. A service whose marker is gone by then is closed in the
    policy like any other owned service, so a partial migration can't leak a policy rule.
  * Services the hook never recorded, such as the core services, are never touched.

**Policy loading on install or upgrade**
* A running firewalld does not load a newly installed policy XML into its running config until it
  reloads. Its config watcher may already have loaded it into the permanent config.
* `ni-firewall-apply` reloads firewalld once if either config reports `INVALID_POLICY` (exit code
  140) for `ni-dropins`.

**Package dependency**
* `ni-firewall-dropins` must provide the `ni-dropins` policy before nilrt-snac depends on it.
* Add `ni-firewall-dropins` to `packagegroup-ni-snac` RDEPENDS.
* The `nilrt-snac` recipe RDEPENDS `ni-firewall-dropins (>= 1.1)`, so installing or upgrading
  nilrt-snac from the feed also upgrades the dropins package.

### 3. nilrt-snac changes (this repo)

**`_FirewallConfig.configure()`**
* Install `ni-firewall-dropins` alongside the other firewall packages.
* Before resetting the firewall, require `ni-firewall-dropins` 1.1 or later.
  * `OpkgHelper.install()` leaves an already installed package alone, and 1.0 would reopen the
    declared services in the default zone.
  * If the installed version is older, run `opkg upgrade ni-firewall-dropins` and check again,
    since opkg can exit 0 without upgrading anything.
  * If it is still too old, stop with `EX_BAD_ENVIRONMENT` and leave the firewall untouched.
* After `--reset-to-defaults`, the SNAC policy setup, and the final `firewall-cmd --reload`, run
  `ni-firewall-apply`.
  * It must run **after** the reload. SNAC edits the configuration offline while the daemon may
    still be running, so before the reload the daemon's permanent view still lists the old
    drop-ins. An apply at that point would change nothing, and the reload would then empty the
    policy.
  * `ni-firewall-apply` is idempotent and serializes itself with `flock`.
  * If it fails (for example, a marker names an unknown service), `configure` logs a warning and
    continues; `verify` reports the missing service.
* Do not create, modify, or reset `ni-dropins`; meta-nilrt owns it.
* Keep `work-in` and its legacy list unchanged. It is the transition path for products that are not
  yet onboarded.

**`_FirewallConfig.verify()`**
* Add these checks:
  * policy `ni-dropins` exists;
  * its ingress zones are exactly {`public`, `work`};
  * its egress zone is `HOST`;
  * its target is `CONTINUE`;
  * every service named by a marker in `/etc/ni/firewall/open.d/` is enabled in `ni-dropins`;
  * no core NI service is enabled in zone `public` (see [Core services](#core-services)).
* The existing assertions keep working.
  * Examples: "`ni-labview-realtime` is not in zone `public`" and "... not in policy `public-in`".
  * Drop-ins no longer touch the `public` zone, so these checks no longer fail when a product
    onboards.
  * They now mean "SNAC itself did not expose this service". They do not mean "this service is
    unreachable on `public`".

**Legacy list lifecycle**
* As each product onboards, remove its entries from `work-in` and from `verify()`.
* When the list is empty (target: the CRA date), the WireGuard module, `work` zone wiring, and
  `work-in`/`work-out` can be removed.
* `ni-dropins` keeps working with `public` alone.

### Core services

`ni-service-locator`, `ni-mxs`, `ni-logos-xt`, `http`, `https` and `mdns` are opened by the
`ni-firewalld-servicedefs` postinst into the default zone, not through drop-ins. This design leaves
them as they are:
* **Non-SNAC:** open on `public`, as today.
* **SNAC:** `--reset-to-defaults` removes them from `public`.
  * `work-in` re-allows `ni-service-locator`, `ni-mxs`, `ni-logos-xt` and `mdns`, so those are
    tunnel-only.
  * `http`/`https` stay closed on both paths, as intended.
  * The `ni-firewalld-servicedefs` postinst runs again on every install or upgrade of that package,
    and reopens all six in `public`. That exposes them on the plain network until the next
    `nilrt-snac configure`. The postinst is deliberately left unchanged. Instead, `nilrt-snac
    verify` fails if any of them is enabled in `public`, and re-running `configure` removes them.

A core service that later meets the encryption mandate can move to a drop-in marker. It then opens on
both paths under SNAC automatically.


## Resulting behavior

| Service class | Non-SNAC (firewalld on) | SNAC, plain NIC | SNAC, tunnel |
|---|---|---|---|
| Declared by drop-in | open | **open** | **open** |
| Legacy list only (no marker) | closed | closed | open |
| Core: service-locator, mxs, logos-xt, mdns | open | closed | open |
| Core: http, https | open | closed | closed |
| ssh | open | open | open |
| Undeclared | closed | closed | closed |
| Any service, interface placed in `drop`/`block` by user | closed | closed | — |


## Compatibility and rollout

* **meta-nilrt and nilrt-snac ship together.**
  * nilrt-snac takes a major version bump at the end of the quarter, so this change may break
    backward compatibility.
  * Only one nilrt-snac version is built per NI Linux RT release, because it ships in the distro
    package feed. Feed versions of the two components therefore always match.
* **Existing SNAC devices.**
  * Upgrading `ni-firewall-dropins` loads `ni-dropins` and migrates any existing drop-ins into it.
  * Declared services become reachable on both paths right away, even before the user re-runs the
    new `nilrt-snac configure`.
  * This is accepted, because it is the target behavior.
* **Non-SNAC devices.** No observable change: drop-in services remain reachable on the default zone
  `public`, now through the policy instead of the zone.


## Validation

### Prototype results

The policy was installed by hand on the NI Linux RT 27.0 VM with SNAC configured. The probe host
reached the target directly and through the tunnel.

| Case | 3079 plain | 3079 tunnel | 49580 plain | 49580 tunnel |
|---|---|---|---|---|
| Drop-ins {`opcua`, `ni-labview-realtime`} in `ni-dropins` | OPEN | OPEN | OPEN | OPEN |
| `ni-labview-realtime` drop-in removed (legacy list only) | REJECT | OPEN | — | — |
| Plain NIC moved to zone `drop` (explicit ingress zones) | — | — | DROP | OPEN |
| Plain NIC moved to zone `drop` (ingress `ANY`, rejected design) | — | — | **OPEN** | OPEN |

After a real `firewall-offline-cmd --reset-to-defaults`, the `/usr/lib` policy was still present,
with no services.

### Required test coverage

* **meta-nilrt ptest for `ni-firewall-apply`:**
  * markers open and close services in `ni-dropins`, offline and live;
  * re-applying after a reset restores the policy;
  * migration moves old default-zone drop-ins into the policy and leaves core services alone.
* **nilrt-snac integration tests:**
  * `configure` installs `ni-firewall-dropins` and runs `ni-firewall-apply`;
  * `verify` checks the `ni-dropins` wiring and marker coverage.
* **nilrt-snac system test, using a host namespace with a direct path and a WireGuard peer:**
  * a drop-in service is reachable on both paths;
  * a legacy-only service is reachable only through the tunnel;
  * an undeclared port is rejected on both;
  * running `nilrt-snac configure` again preserves all of the above.


## Alternatives considered

* **Keep drop-ins in the default zone and have SNAC tolerate them.** SNAC would re-run
  `ni-firewall-apply` after its reset and skip drop-in services in `verify`. Rejected: onboarded
  services would still be unreachable through the tunnel.
* **Policy ingress `ANY`.** Simplest wiring. Rejected: it overrides a user's `drop`/`block` zones
  (see the prototype results).
* **SNAC rewires the policy's ingress zones at configure time** (default zone only without SNAC;
  `public` + `work` with SNAC). Rejected as unnecessary: fixed `public` + `work` gives the same
  result, because `work` is unused without SNAC. It would also give SNAC a second owner for a
  meta-nilrt object.
* **"Legacy guard" policy.** A high-priority policy rejecting legacy-list services on `public`, even
  when a drop-in declares them. Rejected under the trust model: a marker means the product is safe
  to expose.
* **Per-service attestation or a SNAC allowlist.** Markers or SNAC would state which services may
  bypass the tunnel. Rejected under the trust model.
* **Strict tunnel-only SNAC knob.** Rejected: no customer or compliance requirement.


## Related items

* AB#4173548: `nilrt-snac configure` appends a duplicate `ARGS_wglv0` block to
  `/etc/ifplugd/ifplugd.conf` on every run. Found while prototyping this design.
