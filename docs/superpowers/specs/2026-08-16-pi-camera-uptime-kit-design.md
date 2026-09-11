# Pi Camera Uptime Kit Design

**Date:** 2026-08-16

## Objective

Create a zero-startup-cost, low-intervention digital product for operators who
run Raspberry Pi camera, RTSP, livestream, or kiosk installations unattended.
The product should reduce setup and recovery time rather than sell generic
camera scripts that already exist for free.

The initial price hypothesis is **$29 one time**. That price is an experiment,
not a revenue forecast. The repository continues to report `$0.00` until real,
permitted payment evidence is recorded.

## Market conclusion

The market already contains free camera images, streaming projects, watchdogs,
and monitoring scripts. A generic “turn a Pi into a camera” bundle is therefore
too weak. The paid value must be the tested operating system around a camera:
preflight checks, safe installation, self-recovery, diagnostics, rollback, and
a short operator runbook.

Three approaches were considered:

1. **Reliability kit for unattended Pi cameras — selected.** This matches the
   owner's demonstrated Pi, camera, systemd, streaming, and home-lab skills. It
   can be delivered once and used without recurring seller labor.
2. **FunnelSleuth DIY audit kit.** This reuses the existing site, but generic CRO
   checklists are crowded and the current $79 audit still implies manual work.
3. **Affiliate content for Pi hardware.** This is slower, depends on affiliate
   accounts and disclosures, and creates a traffic-heavy content obligation.

## Product promise

“Make an unattended Raspberry Pi camera recover cleanly from the failures that
usually require an SSH session or power cycle.”

The kit is for technically comfortable hobbyists, makers, lab operators, and
small teams already running Raspberry Pi OS. It is not sold as a security
system, safety system, surveillance guarantee, managed service, or substitute
for backups.

## Product contents

The paid bundle contains:

- a read-only preflight that reports supported OS, architecture, camera tools,
  ports, disk headroom, service conflicts, and network exposure;
- an installer for a narrowly scoped health service and systemd watchdog;
- a deterministic status command with redacted diagnostics;
- a recovery policy for a stalled camera process, bounded restart attempts,
  and a visible degraded state instead of an infinite restart loop;
- uninstall and rollback commands that preserve recordings and operator config;
- a compatibility matrix for current Raspberry Pi OS releases and supported Pi
  architectures;
- a 10-minute quick-start, troubleshooting decision tree, and recovery runbook;
- a manifest containing the product version and checksums.

The bundle does not include cloud storage, email/SMS alerts, credential capture,
internet exposure, port forwarding, payment code, or customer-specific setup.

## Free asset and conversion path

A free “Pi Camera Reliability Check” contains only the read-only preflight and
an educational results page. It gives a useful result without collecting an
email address and links to the paid kit for operators who want automated
recovery and rollback.

The public asset must make the scope and price clear. It may state tested facts
about the kit, but must not use fabricated testimonials, invented scarcity,
guaranteed uptime, or unobserved revenue claims.

## Repository and product-boundary architecture

This GitHub repository is public. It must never receive a private paid archive,
buyer data, Stripe secret, download password, or unpublished delivery URL.

The repository may contain:

- product metadata and the public free checker;
- safe packaging code and tests;
- documentation describing how a local release is built;
- a manifest schema and redacted sample output;
- a non-interactive checkout-status component that cannot be mistaken for a
  live purchase path.

The sellable archive is built into a gitignored local staging directory. Before
sale, the owner chooses and explicitly approves a delivery mechanism. A raw
Stripe redirect to a static file is not treated as access control; the design
must label that trade-off honestly. No product is called live until a real
owner-configured checkout and post-payment delivery path have both been tested.

## Components

### 1. Product manifest

A bounded JSON document defines product ID, version, price hypothesis, included
files, supported platforms, checksums, and checkout state. Checkout state is one
of `not_configured`, `configured_unverified`, or `verified`. Only `verified` may
render a buy action.

### 2. Read-only preflight

The checker performs local inspection only. It prints no secrets, makes no
network requests, installs nothing, uses no `sudo`, and changes no services. It
returns a stable machine-readable result plus a concise human summary.

### 3. Recovery service

The paid recovery service watches a configured local camera process or local
RTSP endpoint. It uses bounded timeouts and restart budgets. After the budget is
exhausted, it reports `degraded` and stops automatic restarts until the cooldown
or an operator reset. Defaults bind status endpoints to loopback or the local
network, never the public internet.

### 4. Installer and rollback

Installation stages files, validates them, writes operator config separately,
and swaps the release atomically. Reinstallation preserves config and data.
Rollback targets an immutable local release and never deletes recordings.

### 5. Packaging

A deterministic packaging command reads paid inputs from an owner-controlled,
gitignored local source directory, validates required files, rejects secrets and
absolute owner paths, writes checksums, and produces a versioned archive outside
Git tracking. A clean rebuild must reproduce the same logical file manifest.

### 6. Public product page

The page explains audience, supported systems, contents, limitations, and
current checkout and legal-readiness state. With no verified payment link and
owner-approved sale terms it shows “checkout not configured” rather than a dead
or fake button.

## Data flow

1. An operator downloads and runs the free checker locally.
2. The checker reports compatibility and reliability gaps without transmitting
   results.
3. The results page presents the $29 kit as an optional fix path.
4. After explicit owner setup, a recognized Stripe or PayPal hosted checkout
   handles payment.
5. An owner-approved delivery system provides the versioned archive.
6. Payment evidence enters Money Agent only through an existing permitted,
   deduplicated evidence lane; checkout availability never counts as revenue.

## Safety and approval boundaries

Repository work may create and test local assets. It may not:

- create or modify Stripe, PayPal, hosting, marketplace, or financial accounts;
- upload a paid archive or publish a checkout without explicit approval;
- deploy to the Pi, expose a port, restart a service, or alter payment settings;
- send marketing or transactional messages;
- create legal, tax, privacy, refund, warranty, or license terms on the owner's
  behalf;
- copy third-party code without a compatible license and attribution review.

The existing camera scripts are prototypes, not approved product inputs. They
contain network-facing behavior, privileged package changes, and third-party
downloads that require separate hardening, version pinning, checksum validation,
and license review before reuse.

## Error handling

- Unsupported systems fail before any install action.
- Missing tools and conflicts produce actionable, redacted messages.
- Downloads used by the paid installer require immutable versions and verified
  checksums; verification failure aborts without replacing the current release.
- Partial installation leaves the previous release runnable.
- Restart storms transition to `degraded` instead of looping indefinitely.
- Packaging fails closed if a required file, checksum, license record, or version
  is missing, or if a secret-like value or owner-specific absolute path appears.
- Missing checkout configuration never renders a purchase as available.

## Testing and acceptance criteria

The implementation plan must use test-driven development and cover:

- preflight read-only behavior under command stubs;
- supported and unsupported platform fixtures;
- secret and owner-path redaction;
- restart budget, cooldown, recovery, and degraded transitions;
- atomic install, preservation, rollback, and injected partial failures;
- deterministic manifest generation and packaging rejection cases;
- checkout state rendering and no-revenue truthfulness;
- shell syntax, Python tests, clean-tree packaging, and installer integration.

The repository milestone is complete when all local and CI checks pass and the
public PR remains recoverable. The commercial milestone is separate: checkout
and delivery must be owner-configured and independently verified before the
product is described as live or capable of collecting payment.

## Success measures

The first measurement sequence is:

1. free-checker availability;
2. verified checkout readiness;
3. checkout views from provider analytics, only after an approved read-only
   adapter exists;
4. completed payments from owner or provider evidence;
5. refunds or support burden, if the owner supplies permitted evidence.

No conversion rate or monthly-income claim is made before those observations
exist. A zero-payment result is recorded honestly and used to revise the offer,
audience, price, or distribution path.

## Explicitly deferred

- payment-link creation or modification;
- delivery-platform selection and account setup;
- deployment or publication;
- buyer authentication, license servers, subscriptions, telemetry, analytics,
  email collection, outreach, affiliates, ads, and paid traffic;
- warranties, refund policy, tax treatment, and other legal terms.
