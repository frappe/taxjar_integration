"""Every event that the TaxJar app sends to Pulse, and what each property may hold.

This file is the privacy gate. telemetry.capture drops each property that is
not listed here, and each value that the listed kind does not allow:

- a tuple: one of these exact values
- bool: True or False
- int: a count, a whole number of 0 or more
- FreeText: text that a user typed, cleaned first
- Version: a version string such as "16.2.0" or "17.0.0-dev"

Add a property only when it holds no name, amount, address or document name.
docs/analytics-events.md describes each event for the people who read them.
"""

import re
import unicodedata

from frappe.utils import strip_html


class FreeText:
	"""A property that holds text that a user typed and chose to send.

	Pulse and Insights can show the text, so the gate removes HTML and control
	characters before it leaves the site. Control characters include zero-width
	and text-direction characters, which can hide or reorder what a reader sees.
	"""

	def __init__(self, max_length: int):
		self.max_length = max_length

	def clean(self, value) -> str | None:
		if not isinstance(value, str):
			return None
		text = "".join(
			char for char in strip_html(value) if char in "\n\t" or unicodedata.category(char)[0] != "C"
		)
		return text.strip()[: self.max_length].strip() or None


class Version:
	"""A version string: letters, digits and . + - _ only, at most 40 characters."""

	PATTERN = re.compile(r"[0-9A-Za-z.+_-]{1,40}")

	def clean(self, value) -> str | None:
		return value if isinstance(value, str) and self.PATTERN.fullmatch(value) else None


# Sent with every event, so each event can be read against a release.
COMMON = {"app_version": Version(), "frappe_version": Version()}

SURVEYS = ("csat",)
SCORES = (1, 2, 3, 4, 5)
API_MODES = ("live", "sandbox")
SETUP_STEPS = ("welcome", "connect", "accounts", "address", "features", "nexus", "review")
# The two videos on the setup page: the setup walkthrough on the first screen,
# and the features walkthrough on the "TaxJar is configured" screen.
SETUP_VIDEOS = ("setup", "features")
CONNECTION_RESULTS = ("ok", "no_token", "invalid_token", "rejected", "unreachable", "error")
ADDRESS_RESULTS = ("valid", "not_found", "unsupported_country", "unreachable", "error", "no_credential")
FAILURE_KINDS = ("connection", "response", "unexpected")
HTTP_STATUSES = tuple(range(400, 600))
BLOCK_REASONS = (
	"destination_required",
	"return_reference_missing",
	"return_original_not_synced",
	"exchange_rate_missing",
)
ADDRESS_SIDES = ("origin", "destination")
SOURCES = ("form", "bulk")
EXPORT_PAGES = ("transactions", "customers")
CHOICES = ("proceed", "cancel")

# Why a background sync to TaxJar failed. A TaxJar refusal is split by its
# HTTP status; every other kind comes from classify_taxjar_error() as it is.
SYNC_ERROR_REASONS = (
	"connection",
	"auth",
	"rejected",
	"rate_limited",
	"server_error",
	"response_other",
	"validation",
	"unreadable",
	"not_configured",
	"unknown",
)

# The kind of each call to the live TaxJar API, for the commercial terms with
# TaxJar. A document can cause several calls, for example one on each save.
API_CALL_TYPES = (
	"tax_calculation",
	"order_create",
	"order_update",
	"order_delete",
	"order_read",
	"refund_create",
	"refund_update",
	"refund_delete",
	"refund_read",
	"customer_create",
	"customer_update",
	"customer_delete",
	"customer_read",
	"address_validation",
	"nexus_regions",
	"categories",
	"other",
)

FEATURE_STATE = {
	"taxjar_enabled": bool,
	"setup_complete": bool,
	"api_mode": API_MODES,
	"logging_enabled": bool,
	"days_since_setup": int,
	"companies": int,
	"calculate_tax_companies": int,
	"create_transactions_companies": int,
	"include_exports_companies": int,
	"nexus_regions": int,
	"items_with_tax_category": int,
	"exempt_customers": int,
	# Usage volume, kept for the commercial terms with TaxJar.
	"documents_calculated_1d": int,
	"invoices_synced_1d": int,
	"invoices_synced_30d": int,
	"credit_notes_synced_30d": int,
	"invoices_failed": int,
	"invoices_failed_retryable": int,
	"invoices_excluded_30d": int,
	"customers_synced": int,
	"customers_failed": int,
	# Failed attempts since the last snapshot, retries included, by reason.
	**{f"invoice_sync_errors_{reason}": int for reason in SYNC_ERROR_REASONS},
	**{f"customer_sync_errors_{reason}": int for reason in SYNC_ERROR_REASONS},
	# Calls to the live TaxJar API since the last snapshot, by type.
	**{f"api_calls_{call_type}": int for call_type in API_CALL_TYPES},
}

EVENTS = {
	# Daily snapshot of the site (feature_state.py).
	"taxjar_feature_state": FEATURE_STATE,
	# Guided setup funnel.
	"taxjar_setup_started": {},
	"taxjar_setup_step_viewed": {"step": SETUP_STEPS},
	"taxjar_setup_connection_tested": {"result": CONNECTION_RESULTS, "api_mode": API_MODES},
	"taxjar_setup_step_completed": {"step": SETUP_STEPS},
	"taxjar_setup_step_failed": {"step": SETUP_STEPS},
	"taxjar_setup_video_played": {"video": SETUP_VIDEOS},
	"taxjar_setup_address_verified": {"result": ADDRESS_RESULTS},
	"taxjar_setup_finished": {
		"api_mode": API_MODES,
		"companies": int,
		"calculate_tax_companies": int,
		"create_transactions_companies": int,
		"include_exports_companies": int,
		"nexus_regions": int,
	},
	"taxjar_company_removed": {},
	# The app turned off or removed: a strong sign that something went wrong.
	"taxjar_app_disabled": {},
	"taxjar_app_uninstalled": {},
	# Activation: once per site.
	"taxjar_first_tax_calculated": {"days_since_setup": int},
	"taxjar_first_invoice_synced": {"days_since_setup": int},
	# Friction that a user saw.
	"taxjar_tax_calculation_failed": {
		"kind": FAILURE_KINDS,
		"status": HTTP_STATUSES,
		"address_side": ADDRESS_SIDES,
	},
	"taxjar_document_blocked": {"reason": BLOCK_REASONS},
	# Daily use.
	"taxjar_transactions_resynced": {"source": SOURCES, "count": int},
	"taxjar_customers_synced": {"source": SOURCES, "count": int},
	"taxjar_exemption_configured": {"customers": int, "regions": int},
	"taxjar_exemption_cleared": {"customers": int},
	"taxjar_export_downloaded": {"page": EXPORT_PAGES},
	"taxjar_nexus_refreshed": {},
	"taxjar_categories_refreshed": {},
	"taxjar_extra_charges_answered": {"choice": CHOICES},
	# CSAT survey (csat.py).
	"taxjar_csat_shown": {"survey": SURVEYS},
	"taxjar_csat_submitted": {
		"survey": SURVEYS,
		"score": SCORES,
		"comment": FreeText(max_length=1000),
	},
	"taxjar_csat_dismissed": {"survey": SURVEYS, "permanent": bool},
}

# The only events that the browser may send, through telemetry.track.
BROWSER_EVENTS = (
	"taxjar_setup_step_viewed",
	"taxjar_setup_step_failed",
	"taxjar_setup_video_played",
	"taxjar_extra_charges_answered",
)
