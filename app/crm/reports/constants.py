"""Allowlists and bounds for CRM report aggregations."""

REPORT_ROW_LIMIT = 200

PIPELINE_GROUPS = frozenset({"stage", "owner", "source", "campaign"})
WIN_LOSS_GROUPS = frozenset({"lost_reason", "owner", "source", "campaign"})
LEAD_CONVERSION_GROUPS = frozenset({"status", "source", "owner", "campaign"})
ACTIVITY_GROUPS = frozenset({"activity_type", "status", "owner"})

DEFAULT_PIPELINE_GROUP = "stage"
DEFAULT_WIN_LOSS_GROUP = "lost_reason"
DEFAULT_LEAD_CONVERSION_GROUP = "status"
DEFAULT_ACTIVITY_GROUP = "activity_type"

UNASSIGNED_KEY = "unassigned"
UNASSIGNED_LABEL = "Unassigned"
