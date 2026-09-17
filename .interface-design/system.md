# SFU operator dashboards

## Intent

An operator moves from endpoint availability through admission, ICE/DTLS,
media delivery and room/user evidence. Show concurrent conditions and preserve
the incident time range through drilldowns. Keep the view calm and dense.

## Shared component decisions

- Reuse native Grafana typography, surfaces, controls and focus behavior.
- Use Grafana panel surfaces with subtle borders. Avoid background status fills.
- Use the 24-column grid with four or six columns per current status card.
- Use paired 12-column histories when units or measurement scopes differ.
- Green means verified health. Amber means a degraded signal. Red means failure.
- Blue means activity. Gray means idle, missing or unavailable evidence.
- Current Prometheus cards use instant queries and the last reducer.
- Historical charts preserve gaps. Observation counts accompany sampled quality.
- HTTP diagnostics show current configured-server state independently of history.
- Keep status before history and implementation detail below user impact.
- Keep room IDs, user IDs and encoding IDs visible in diagnostic tables.
- The Investigate menu preserves compatible variables and the time range.

## Signature

The investigation follows signaling, transport, media, room and user evidence.
Operations exposes simultaneous boundary states. Transport highlights short
sessions. Media starts with quality and recovery. Room and user tables retain
identity links. Canary pairs the same measurements from independent instances.

## Scope and missing data

Event ratios compare aggregate event rates. They do not identify failed users.
Fanout measures forwarding operations per ingress packet. It is not delivery loss.
No observations do not mean zero loss. Missing worker delay is not zero delay.
Recording capability reflects the documented server revision, not a runtime probe.
