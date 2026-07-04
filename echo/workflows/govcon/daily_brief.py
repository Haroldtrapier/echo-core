"""A. Daily GovCon Brief — the flagship Echo GovCon workflow.

Assembles a daily intelligence brief from live signals (SAM.gov opportunities,
USASpending award movement, FEMA disaster readiness) plus an evergreen
certification tip and a recommended action, closes with a Sturgeon CTA, and
queues the whole thing as a reviewable draft. Degrades to an honest
"no live signals today" brief when providers/keys are absent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from echo.core.registry import register
from echo.core.workflow import WorkflowResult
from echo.modules.ai_generator import generate_content
from echo.workflows.govcon import pack

# Rotating evergreen certification / compliance tips (deterministic, no AI needed).
CERT_TIPS = [
    "SDVOSB: keep your VA CVE / SBA verification current — set a renewal reminder 90 days out.",
    "8(a): the 9-year program clock starts at admission; plan your graduation-year pipeline early.",
    "WOSB/EDWOSB: re-certify annually in certify.SBA.gov and keep your NAICS set-aside eligibility mapped.",
    "HUBZone: monitor your principal-office and 35%-residency status — HUBZone maps update periodically.",
    "SAM.gov: renew your registration before it lapses — an expired UEI drops you from award eligibility.",
    "Capability statement: lead with NAICS codes, UEI/CAGE, past performance, and differentiators — one page.",
]


@register
class DailyGovConBriefWorkflow(pack.GovConWorkflow):
    slug = "govcon_daily_brief"
    name = "Daily GovCon Brief"
    description = (
        "Assembles a daily GovCon intelligence brief (top opportunities, agency "
        "movement, FEMA readiness signals, certification tip, recommended action, "
        "Sturgeon CTA) and queues it as a reviewable draft."
    )
    trigger_type = "scheduled"
    output_type = "brief"
    connector_targets = ("sam_gov", "usaspending", "fema", "slack")
    input_schema = {
        "keywords": "list[str] — search terms (default IT/cyber/cloud)",
        "state": "str? — optional 2-letter state for FEMA signals",
        "brand": "str? — brand context for the brief",
    }

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        keywords = payload.get("keywords") or ["information technology", "cybersecurity", "cloud"]
        if isinstance(keywords, str):
            keywords = [keywords]
        state = payload.get("state")

        opportunities = pack.safe_sam_opportunities(keywords, limit=payload.get("sam_limit", 5))
        awards = pack.safe_recent_awards(keywords, limit=payload.get("awards_limit", 5))
        declarations = pack.safe_fema_declarations(state=state, limit=3)

        tip_index = datetime.now(timezone.utc).timetuple().tm_yday % len(CERT_TIPS)
        cert_tip = CERT_TIPS[tip_index]

        body = self._compose(keywords, opportunities, awards, declarations, cert_tip)

        queued = pack.queue_draft(
            db,
            workflow=self.slug,
            draft_type="brief",
            title=f"Daily GovCon Brief — {', '.join(keywords)}",
            body=body,
            payload=payload,
            topic=", ".join(keywords),
            content_type="daily_brief",
            campaign="govcon_daily_brief",
            cta_text="See live GovCon opportunities",
            extra_metadata={
                "opportunities": len(opportunities),
                "awards": len(awards),
                "fema_declarations": len(declarations),
            },
        )

        return WorkflowResult(
            success=True,
            data={
                **queued,
                "brief": body,
                "opportunities_found": len(opportunities),
                "awards_found": len(awards),
                "fema_declarations_found": len(declarations),
            },
            message=(
                f"Daily GovCon brief drafted (post_id={queued['post_id']}, "
                f"approval_id={queued['approval_id']}) — pending review"
            ),
        )

    # ── composition ──────────────────────────────────────────────────────────

    def _compose(
        self,
        keywords: list[str],
        opportunities: list[dict[str, Any]],
        awards: list[dict[str, Any]],
        declarations: list[dict[str, Any]],
        cert_tip: str,
    ) -> str:
        today = datetime.now(timezone.utc).strftime("%B %d, %Y")
        lines: list[str] = [f"# Daily GovCon Brief — {today}", ""]

        lines.append("## Top Opportunities")
        if opportunities:
            for o in opportunities[:5]:
                title = o.get("title") or "Untitled opportunity"
                deadline = o.get("responseDeadLine") or o.get("deadline") or "TBD"
                naics = o.get("naicsCode") or o.get("naics") or "—"
                lines.append(f"- **{title}** · NAICS {naics} · due {deadline}")
        else:
            lines.append("- No new matching solicitations surfaced today (or SAM.gov not configured).")
        lines.append("")

        lines.append("## Agency Movement")
        if awards:
            for a in awards[:5]:
                agency = a.get("Awarding Agency") or a.get("agency") or "Unknown agency"
                recipient = a.get("Recipient Name") or a.get("recipient") or "—"
                amount = a.get("Award Amount") or a.get("amount") or "—"
                lines.append(f"- {agency} → {recipient} ({amount})")
        else:
            lines.append("- No recent award signals available (or USASpending not configured).")
        lines.append("")

        lines.append("## FEMA / Disaster Readiness Signals")
        if declarations:
            for d in declarations[:3]:
                itype = d.get("incidentType") or "Incident"
                st = d.get("state") or "—"
                dtitle = d.get("declarationTitle") or ""
                lines.append(f"- {itype} — {st} {('· ' + dtitle) if dtitle else ''}".rstrip())
            lines.append("- Readiness angle: pre-position supply/logistics capability for public-assistance procurement.")
        else:
            lines.append("- No active disaster declarations in window — monitor for FEMA/SEMA surge procurement.")
        lines.append("")

        lines.append("## Certification / Compliance Tip")
        lines.append(f"- {cert_tip}")
        lines.append("")

        lines.append("## Recommended Action")
        if opportunities:
            top = opportunities[0].get("title") or "the top opportunity above"
            lines.append(f"- Prioritize a go/no-go on **{top}** and confirm your NAICS + set-aside eligibility today.")
        else:
            lines.append("- Refresh your saved searches and capability statement; seed tomorrow's pipeline while volume is low.")
        lines.append("")

        lines.append("## Analyze in Sturgeon")
        lines.append(pack.sturgeon_cta())

        base = "\n".join(lines)

        # Optional AI polish — only when a key is present; otherwise return the
        # deterministic brief unchanged (generate_content returns a placeholder
        # string when unconfigured, which we deliberately do NOT substitute in).
        try:
            from echo.config import ANTHROPIC_API_KEY

            if ANTHROPIC_API_KEY:
                narrative = generate_content(
                    "Rewrite this GovCon daily brief to be crisp and executive-ready. "
                    "Keep every section heading and the Sturgeon CTA intact.\n\n" + base,
                    system="You are a GovCon market-intelligence analyst.",
                    max_tokens=1200,
                )
                if narrative and "AI generation unavailable" not in narrative:
                    return narrative
        except Exception:  # noqa: BLE001
            pass
        return base
