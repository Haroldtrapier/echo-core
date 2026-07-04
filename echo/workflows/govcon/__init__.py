"""Echo GovCon automation pack — GovCon-specific, approval-first workflows.

Importing this package registers all six pack workflows:
  A. daily_brief.DailyGovConBriefWorkflow          → govcon_daily_brief
  B. opportunity_to_content.OpportunityToContent…  → opportunity_to_content
  C. fema_procurement_watch.FemaProcurementWatch…  → fema_procurement_watch
  D. certification_education.CertificationEducat…  → certification_education
  E. lead_nurture.LeadNurtureWorkflow              → lead_nurture
  F. weekly_performance.WeeklyPerformanceTracker…  → weekly_performance_tracker
"""
from echo.workflows.govcon import (  # noqa: F401
    daily_brief,
    opportunity_to_content,
    fema_procurement_watch,
    certification_education,
    lead_nurture,
    weekly_performance,
)
