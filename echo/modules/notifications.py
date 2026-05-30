"""Notifications module — send alerts via Slack and email."""
from __future__ import annotations

from typing import Any

from echo.core.logger import get_logger

log = get_logger("echo.modules.notifications")


def notify_slack(
    message: str,
    *,
    channel: str | None = None,
    webhook_url: str | None = None,
    level: str = "info",
) -> bool:
    """Send a Slack notification. Returns True on success."""
    from echo.config import SLACK_WEBHOOK_URL

    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        log.warning("SLACK_WEBHOOK_URL not configured — skipping Slack notification")
        return False

    try:
        import urllib.request
        import json

        icon = {"info": ":information_source:", "warning": ":warning:", "error": ":red_circle:"}.get(level, ":bell:")
        payload = {"text": f"{icon} {message}"}
        if channel:
            payload["channel"] = channel

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
        if ok:
            log.info("Slack notification sent level=%s", level)
        return ok
    except Exception as exc:
        log.exception("Slack notification failed: %s", exc)
        return False


def notify_workflow_failure(workflow_slug: str, run_id: str, error: str) -> None:
    """Alert on workflow failure — logs always, Slack if configured."""
    log.error("Workflow failure slug=%s run_id=%s error=%s", workflow_slug, run_id, error)
    notify_slack(
        f"*Workflow failed*: `{workflow_slug}` (run `{run_id}`)\nError: {error}",
        level="error",
    )


def notify_approval_required(
    approval_id: str,
    run_id: str | None,
    requested_by: str,
    reason: str | None = None,
) -> None:
    """Alert that a workflow is waiting for human approval."""
    msg_parts = [f"*Approval required* — ID: `{approval_id}`"]
    if run_id:
        msg_parts.append(f"Run: `{run_id}`")
    msg_parts.append(f"Requested by: `{requested_by}`")
    if reason:
        msg_parts.append(f"Reason: {reason}")
    notify_slack("\n".join(msg_parts), level="warning")


def notify_publish_success(platform: str, content_preview: str, live_url: str | None = None) -> None:
    """Alert on successful live publish."""
    msg = f"*Published* to `{platform}`: _{content_preview[:120]}_"
    if live_url:
        msg += f"\n<{live_url}|View post>"
    notify_slack(msg, level="info")


def build_summary_notification(summary: dict[str, Any]) -> str:
    """Format an analytics summary dict into a human-readable Slack message."""
    wf = summary.get("workflows", {})
    content = summary.get("content", {})
    logs = summary.get("logs", {})
    integrations = summary.get("integrations", {})

    lines = [
        "*Echo Daily Summary*",
        f"• Workflows: {wf.get('runs_last_24h', 0)} runs in last 24h "
        f"({wf.get('success_rate', 0)}% success rate)",
        f"• Content: {content.get('total', 0)} items, {content.get('published', 0)} published",
        f"• Errors (24h): {logs.get('errors_last_24h', 0)}",
        f"• Integrations: {integrations.get('healthy', 0)} healthy, {integrations.get('down', 0)} down",
    ]
    return "\n".join(lines)
