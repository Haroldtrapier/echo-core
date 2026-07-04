# Echo GovCon

Echo GovCon is the **GovCon automation pack** that runs on Echo Core. It is a set
of approval-first workflows that turn federal-contracting signals into reviewable
content and route qualified opportunities into Sturgeon AI.

Product boundaries it serves:

- **GovCon Command Center** — education, opportunity discovery, market briefs,
  lead capture, "Send to Sturgeon".
- **Sturgeon AI** — proposal execution, solicitation analysis, compliance.
- **Imani/Apex OS** — the command center that schedules, approves, and monitors.

The pack lives in `echo/workflows/govcon/` and shares one shape via
`govcon/pack.py`: **generate → queue a reviewable draft → human approves →
publish / hand off**. Nothing publishes automatically.

## Included workflows

| Slug | Name | Output | Trigger |
| --- | --- | --- | --- |
| `govcon_daily_brief` | Daily GovCon Brief | brief | scheduled |
| `opportunity_to_content` | Opportunity-to-Content | draft | manual |
| `fema_procurement_watch` | FEMA / Disaster Procurement Watch | alert | scheduled |
| `certification_education` | Certification Education | draft | manual |
| `lead_nurture` | Lead Nurture Sequence | draft | manual |
| `weekly_performance_tracker` | Weekly Performance Tracker | report | scheduled |

### A. Daily GovCon Brief
Assembles top opportunities (SAM.gov), agency movement (USASpending), FEMA/disaster
readiness signals, a rotating certification/compliance tip, a recommended action,
and a Sturgeon CTA. Saved as a run + a `brief` approval draft. Degrades to an
honest "no live signals" brief when providers/keys are absent.

### B. Opportunity-to-Content
Input: an opportunity, solicitation, keyword, agency, or market topic. Produces a
LinkedIn post, an email/newsletter blurb, a "what this means for contractors"
summary, and a Sturgeon CTA — bundled as one `linkedin_post` draft. Approval
required before publishing.

### C. FEMA / Disaster Procurement Watch
Watches FEMA declarations (via the existing FEMA adapter, with a safe mockable
fallback — see `pack.safe_fema_declarations`; TODO: add live NRS/SEMA adapters).
Produces a procurement alert, a contractor action brief, a readiness/supply angle,
and a Sturgeon handoff CTA. Can optionally open a Sturgeon handoff
(`create_handoff: true`).

### D. Certification Education
Educational drafts for SDVOSB, 8(a), WOSB, HUBZone, SAM.gov, UEI/CAGE, and
capability statements. Curated fallback copy guarantees a useful draft even with
no AI key.

### E. Lead Nurture Sequence
A 5-touch email sequence — welcome → education → pain point → Sturgeon CTA →
proposal/human-review offer. Each email is saved as an individually reviewable
`email` draft; **nothing sends automatically**. Records `lead_nurture_created`.

### F. Weekly Performance Tracker
Summarizes the week from the analytics event stream: workflows run, drafts created,
approvals, rejections, published/marked-ready items, Sturgeon handoffs, and
recommendations for next week.

## Sturgeon handoff

The "Send to Sturgeon" path (`echo/modules/sturgeon.py`,
`POST /api/v1/govcon/sturgeon/handoff`) carries: opportunity title, agency,
solicitation number, due date, source URL, summary, requirements, and recommended
next action.

- Every handoff persists an `echo_sturgeon_handoffs` row and records a
  `sturgeon_handoff_created` analytics event.
- If `STURGEON_API_URL` is configured, the payload is POSTed to Sturgeon's intake
  and the row is marked `forwarded`; otherwise it stays `pending` for Sturgeon to
  pull. No network call happens locally, so build/test never needs a real Sturgeon.
- The handoff **only creates intake records** — it never touches proposal credits
  or Stripe.

## Approval-first content model

1. A workflow generates a draft and calls `pack.queue_draft()`, which creates a
   `ContentItem` (`pending_review`) **and** a draft `Approval` (`draft_created`).
2. The draft appears in the approval queue (`/api/v1/govcon/approvals`, or
   `cockpit/approvals.html`).
3. A human approves (`draft_approved`) or rejects (`draft_rejected`), optionally
   editing the content first.
4. Approved drafts can be marked ready (`draft_published_or_marked_ready`) and/or
   published by `approved_publisher` — still gated behind `ECHO_ALLOW_LIVE_PUBLISH`.
5. Qualified opportunities are handed off to Sturgeon.

## Future workflows

- Live NRS / SEMA disaster-procurement adapters (behind the same interface as FEMA).
- Teaming-partner matcher and capability-statement generator.
- Award-protest / recompete watch.
- Direct connector send (LinkedIn/email) on `mark-ready` once connectors are live.
