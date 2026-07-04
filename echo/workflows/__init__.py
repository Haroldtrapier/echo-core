"""Echo Core workflows — import all to trigger registration."""
from echo.workflows import (  # noqa: F401
    weekly_report,
    govcon_daily_intelligence,
    linkedin_signal_post,
    fema_disaster_monitor,
    sam_opportunity_watch,
    approved_publisher,
    content_calendar_archive,
    prospect_dm,
    strategic_comment,
    social_post,
    produce_media,
)

# Echo GovCon automation pack (approval-first GovCon recipes)
from echo.workflows import govcon  # noqa: F401,E402
