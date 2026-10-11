"""Daily snapshot of how the site has TaxJar set up and how much it uses it.

One taxjar_feature_state event per site per day, run by the daily_long
scheduler. Counts only: no names, amounts or addresses (see FEATURE_STATE in
telemetry_events.py for what each property may hold).

Each count over a time window filters on `creation`, which has an index, so it
reads only the rows of that window. `modified` and `taxjar_last_synced` have no
index, and a filter on them reads the whole table on a large site.
"""

import frappe
from frappe.utils import add_days, cint, now_datetime
from frappe.utils.telemetry import is_pulse_enabled

from taxjar_integration.taxjar_integration.telemetry import (
	capture,
	days_since_setup,
	take_api_call_counts,
	take_sync_error_counts,
)

SETTINGS = "TaxJar Settings"
TAX_DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice")


def capture_feature_state():
	if not is_pulse_enabled():
		return

	state = {}
	for collect in (
		settings_state,
		document_state,
		invoice_state,
		customer_state,
		sync_error_state,
		api_call_state,
	):
		try:
			state.update(collect())
		except Exception:
			frappe.log_error(f"TaxJar feature state telemetry failed: {collect.__name__}")

	if state:
		capture("taxjar_feature_state", **state)


def settings_state() -> dict:
	settings = frappe.get_single(SETTINGS)
	configs = settings.company_config or []
	state = {
		"taxjar_enabled": bool(settings.taxjar_enabled),
		"setup_complete": bool(settings.setup_complete),
		"api_mode": (settings.api_mode or "Live").lower(),
		"logging_enabled": bool(settings.enable_taxjar_logging),
		"companies": len(configs),
		"calculate_tax_companies": sum(1 for c in configs if c.taxjar_calculate_tax),
		"create_transactions_companies": sum(1 for c in configs if c.taxjar_create_transactions),
		"include_exports_companies": sum(
			1 for c in configs if c.taxjar_create_transactions and c.taxjar_include_exports
		),
		"nexus_regions": len(settings.nexus or []),
	}
	days = days_since_setup()
	if days is not None:
		state["days_since_setup"] = days
	return state


def document_state() -> dict:
	since = _since(days=1)
	return {
		"items_with_tax_category": frappe.db.count("Item", {"taxjar_product_tax_category": ["is", "set"]}),
		"documents_calculated_1d": sum(
			frappe.db.count(doctype, {"taxjar_has_nexus": 1, "creation": [">=", since]})
			for doctype in TAX_DOCTYPES
		),
	}


def invoice_state() -> dict:
	synced = {"taxjar_sync_status": "Synced", "docstatus": 1}
	failed = {"taxjar_sync_status": "Failed", "docstatus": 1}
	return {
		"invoices_synced_1d": _count({**synced, "creation": [">=", _since(days=1)]}),
		"invoices_synced_30d": _count({**synced, "creation": [">=", _since(days=30)]}),
		"credit_notes_synced_30d": _count({**synced, "is_return": 1, "creation": [">=", _since(days=30)]}),
		"invoices_failed": _count(failed),
		"invoices_failed_retryable": _count({**failed, "taxjar_sync_retryable": 1}),
		# Excluded is also the default status, so only a stated reason means
		# the app chose not to sync the invoice.
		"invoices_excluded_30d": _count(
			{
				"taxjar_sync_status": "Excluded",
				"taxjar_exclusion_reason": ["is", "set"],
				"docstatus": 1,
				"creation": [">=", _since(days=30)],
			}
		),
	}


def customer_state() -> dict:
	return {
		"exempt_customers": frappe.db.count(
			"Customer", {"taxjar_exemption_type": ["not in", ["", "Non Exempt"]]}
		),
		"customers_synced": frappe.db.count("Customer", {"taxjar_customer_sync_status": "Synced"}),
		"customers_failed": frappe.db.count("Customer", {"taxjar_customer_sync_status": "Failed"}),
	}


def sync_error_state() -> dict:
	"""Failed sync attempts since the last snapshot, by reason. Reading them resets them."""
	return {
		f"{scope}_sync_errors_{reason}": count
		for scope in ("invoice", "customer")
		for reason, count in take_sync_error_counts(scope).items()
	}


def api_call_state() -> dict:
	"""Calls to the live TaxJar API since the last snapshot, by type. Reading them resets them."""
	return {f"api_calls_{call_type}": count for call_type, count in take_api_call_counts().items()}


def _count(filters) -> int:
	return cint(frappe.db.count("Sales Invoice", filters))


def _since(days: int):
	return add_days(now_datetime(), -days)
