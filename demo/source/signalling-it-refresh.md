---
title: "Signalling Estate IT Refresh: Tender Dossier"
version: v0.9
lang: en
summary: >
  Meridian Rail Infrastructure intends to refresh the IT estate that supports
  its signalling operations: telemetry collection, train describer data
  distribution, and the signalling maintenance workbench. This file is the
  single full-candor source; governed projections are produced per audience
  profile (internal-full, bidder-pack, public-tender).
---

# Signalling Estate IT Refresh: Tender Dossier

> Demonstration document. Every organisation, place, person, figure, and date
> in this dossier is fictional. This is the full-candor source for the
> projection-engine demo: one file, three governed renders.

## 1. Overview

Meridian Rail Infrastructure (MRI) operates the signalling estate across the
Meridian Main Line, the Coastal Loop, and the Harwick freight corridor. The IT
systems that surround that estate (telemetry collection, train describer data
distribution, and the signalling maintenance workbench) have reached the end
of their economic life and will be replaced under a single programme: the
Signalling Estate IT Refresh (SEIR).

This dossier describes the scope, requirements, evaluation approach, and
planning of the procurement. It is issued by the SEIR programme office under
the authority of the Programme Director.

::: {.block lang="fr"}
Une traduction en francais du dossier complet sera fournie aux candidats sur
simple demande au bureau du programme.
:::

::: {.block clearance="internal" releasable="team"}
Internal context, not for release outside the programme team: the maintenance
contract on the current telemetry historians lapses at the end of the next
financial year and cannot be extended a second time, and the internal audit
service has flagged the estate as obsolescent two years running. This is the
real deadline pressure behind SEIR. Do not communicate it to bidders; it
weakens our negotiating position on transition timelines.
:::

## 2. Scope

The procurement covers the replacement of the telemetry collection tier, the
train describer data distribution service, and the signalling maintenance
workbench, together with migration of historical data, integration into MRI
operations tooling, and training.

Out of scope: the interlockings themselves, level crossing control, and any
equipment subject to approval by the national rail safety regulator. The
refresh is confined to the supporting IT estate; safety-approved signalling
equipment is untouched.

::: {.block releasable="bidders"}
Site visits: registered bidders will be offered escorted visits to the Harwick
Junction telemetry room, the Dunmere maintenance depot, and the Aldervale
operations centre. Visits are booked through the programme office. Attendees
without a valid track-side safety briefing certificate remain within office
areas.
:::

## 3. Requirements

Requirements are stated at the level of intended outcome. Detailed interface
specifications are provided to registered bidders as separate annexes.

| ID   | Requirement                                                        | Priority | Verified by                 |
|------|--------------------------------------------------------------------|----------|-----------------------------|
| R-01 | Telemetry collection tier sized for at least 500 lineside concentrators | Must     | Factory acceptance test     |
| R-02 | Train describer data feed with an open, documented interface       | Must     | Interface conformance test  |
| R-03 | Maintenance workbench usable on mobile devices at depots           | Must     | User acceptance test        |
| R-04 | Twelve years of telemetry history migrated and queryable           | Must     | Migration rehearsal         |
| R-05 | Role-based access integrated with the MRI identity provider        | Must     | Security review             |
| R-06 | Monitoring and alerting integrated into the Aldervale operations centre | Should   | Integration test            |
| R-07 | Training delivered for 180 depot technicians and 20 operators      | Should   | Training completion report  |

## 4. Evaluation approach

Offers are evaluated on quality (weight 60) and price (weight 40). The quality
criterion is subdivided into migration approach, service organisation during
the run phase, and usability of the maintenance workbench. The evaluation
panel is appointed by the Programme Director and includes the Head of
Signalling Engineering and the Commercial Officer.

::: {.block audience="programme-team"}
Panel note (programme team only): score each sub-criterion on the shared
worksheet before the moderation session, not during it. Bring written
justifications; the moderation session reconciles scores, it does not produce
them. The worksheet lives with the programme office.
:::

Clarification questions may be submitted in writing through the national
procurement portal until fourteen days before the offer deadline. Answers are
published to all registered bidders.

::: {.block hide="general"}
Registered bidders and the programme team also have access to the SEIR
clarification channel on the programme collaboration space, which mirrors the
portal questions and answers within one working day. Access credentials are
issued at registration.
:::

## 5. Budget and planning

Indicative budget information is communicated to registered bidders in
accordance with the procurement rules. The planning below is indicative and
may be adjusted in the final tender notice.

| Milestone                        | Indicative date    |
|----------------------------------|--------------------|
| Publication of the tender        | 2027 Q1            |
| Bidder registration closes       | 2027 Q2            |
| Offers due                       | 2027 Q3            |
| Award                            | 2027 Q4            |
| Transition and data migration    | 2028 Q1 to 2029 Q2 |
| Full service                     | 2029 Q3            |

::: {.block clearance="commercial-confidential"}
Commercial envelope (in confidence, for registered bidders): the indicative
budget for SEIR is 14.2 million over five years, of which 8.9 million for
implementation and 5.3 million for the run phase including evolutive
maintenance. Offers above the envelope are not automatically excluded but
must justify the excess against the stated requirements.
:::

::: {.block softspot="true"}
Known schedule risk, shared for planning honesty: the migration of twelve
years of telemetry history out of the legacy historians has never been
rehearsed at production scale. The transition window above carries this risk.
Bidders should treat the data migration milestone (R-04) as the critical path
and cost the rehearsal accordingly.
:::

## Annex A: Technical baseline

The current estate is summarised here so that offers can be dimensioned.

::: {.block detail="true"}
Full baseline (internal working detail): 43 virtualised servers across the two
data rooms at Harwick Junction (27) and Aldervale (16); telemetry collection
from 312 lineside concentrators in four hardware generations, of which 41
units are past vendor end-of-support; two historian clusters holding 74 TB of
telemetry history; maintenance workbench with 214 named accounts, of which
about 180 are active depot technicians. The oldest concentrator generation
predates the current train describer interface and requires a protocol
gateway that only one engineer still maintains.
:::

::: {.block variant="abstract"}
The estate comprises roughly 40 virtualised servers across two data rooms, a
telemetry collection tier of around 300 lineside concentrators, and a
maintenance workbench used by approximately 180 depot technicians. Exact
inventories are provided to registered bidders.
:::

## Annex B: Glossary

- Historian: the time-series store holding collected telemetry history.
- Interlocking: the safety installation that sets and locks routes; out of
  scope for SEIR.
- Lineside concentrator: the cabinet unit that aggregates telemetry from
  track-side equipment and forwards it to the collection tier.
- Maintenance workbench: the application used by depot technicians to plan,
  record, and report signalling maintenance work.
- SEIR: Signalling Estate IT Refresh, this programme.
- Train describer: the system that tracks train identities across the
  signalling estate and distributes that data to consuming systems.
