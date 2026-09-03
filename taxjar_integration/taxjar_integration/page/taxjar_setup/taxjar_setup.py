"""Server APIs for the TaxJar guided setup desk page (/app/taxjar-setup).

Every endpoint is permission-guarded against TaxJar Settings and saves go through
doc.save(), so the doctype's own validate()/on_update (mode/credential checks,
field-visibility toggles, nexus auto-fetch) still fire — nothing here bypasses
the doctype's own rules, and nothing writes data the doctype itself can't.

Two child tables, two different lifecycles:

* TaxJar API Credential (table_hvjw) has no mandatory fields — a company can be
  added here (Connect step) before its accounts are known.
* TaxJar Company Config (company_config) requires both account heads, so a row
  can only be created once the Accounts step actually has them. Its two flags
  (taxjar_calculate_tax / taxjar_create_transactions) are edited by the
  Features step, on rows Accounts already created.

get_setup_state() therefore exposes ``credentials`` (from table_hvjw, drives the
Connect step) and ``companies`` (from company_config, drives Accounts/Features/
Review) as two separate lists rather than one merged shape.
"""

import taxjar
import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.password import get_decrypted_password

SETTINGS = "TaxJar Settings"


def _token_last4(cred, field):
	"""Return the last 4 chars of an encrypted credential token, or None.

	Full tokens are never sent to the client — only enough to recognise which token
	is stored for a company.
	"""
	if not cred or not cred.get(field):
		return None
	value = get_decrypted_password(
		"TaxJar API Credential", cred.name, field, raise_exception=False
	)
	return value[-4:] if value else None


def _nexus_by_company(settings):
	nexus_by_company = {}
	for row in settings.nexus or []:
		nexus_by_company.setdefault(row.company or "", []).append({
			"region": row.region,
			"region_code": row.region_code,
			"country": row.country,
			"country_code": row.country_code,
		})
	return nexus_by_company


@frappe.whitelist()
def get_setup_state():
	"""Return the current TaxJar Settings slice the guided setup renders from."""
	frappe.has_permission(SETTINGS, "read", throw=True)

	settings = frappe.get_single(SETTINGS)

	# A DocType JSON "default" only ever applies the very first time a Single
	# doctype field is saved - it never retroactively re-applies to a field
	# that already holds a value, even an old default from before this one
	# changed. Nothing configured yet (no credentials, no company config) is
	# this wizard's own signal for "treat this as a fresh start" - showing the
	# current recommended defaults regardless of whatever stale value sits
	# underneath, without touching a site that's actually mid-configuration.
	is_unconfigured = not settings.table_hvjw and not settings.company_config

	mode = "Live" if is_unconfigured else (settings.api_mode or "Live")
	token_field = "sandbox_token" if mode == "Sandbox" else "live_token"

	credentials = [
		{
			"company": cred.company,
			"token_last4": _token_last4(cred, token_field),
		}
		for cred in (settings.table_hvjw or [])
		if cred.company
	]

	companies = [
		{
			"company": cfg.company,
			"tax_account_head": cfg.tax_account_head,
			"shipping_account_head": cfg.shipping_account_head,
			"calculate": bool(cfg.taxjar_calculate_tax),
			"file": bool(cfg.taxjar_create_transactions),
		}
		for cfg in (settings.company_config or [])
	]

	return {
		"api_mode": mode,
		"enable_taxjar_logging": True if is_unconfigured else bool(settings.enable_taxjar_logging),
		"log_retention_days": 15 if is_unconfigured else settings.log_retention_days,
		"setup_complete": bool(settings.setup_complete),
		"credentials": credentials,
		"companies": companies,
		"nexus_by_company": _nexus_by_company(settings),
		"nexus_last_synced": settings.nexus_last_synced,
	}


@frappe.whitelist(methods=["POST"])
def test_connection(company: str, token: str | None = None, mode: str | None = None):
	"""Verify a TaxJar token against a lightweight endpoint, without persisting.

	If ``token`` is omitted, falls back to the already-saved credential for
	``company`` (e.g. re-testing a previously connected company). ``mode``
	defaults to the settings' current API Mode so a not-yet-saved mode change
	on Step 2 can still be tested before Continue is pressed.
	"""
	frappe.has_permission(SETTINGS, "write", throw=True)

	settings = frappe.get_single(SETTINGS)
	mode = mode or settings.api_mode or "Live"
	is_sandbox = mode == "Sandbox"
	token_field = "sandbox_token" if is_sandbox else "live_token"

	api_key = token
	if not api_key:
		for cred in settings.table_hvjw or []:
			if cred.company == company and getattr(cred, token_field, None):
				api_key = get_decrypted_password(
					"TaxJar API Credential", cred.name, token_field, raise_exception=False
				)
				break

	if not api_key:
		return {"ok": False, "message": _("Enter a token to test.")}

	api_url = taxjar.SANDBOX_API_URL if is_sandbox else taxjar.DEFAULT_API_URL
	client = taxjar.Client(api_key=api_key, api_url=api_url)
	client.set_api_config("headers", {"x-api-version": "2022-01-24"})

	try:
		client.categories()
	except taxjar.exceptions.TaxJarResponseError as err:
		full = getattr(err, "full_response", None) or {}
		status = full.get("status_code") if isinstance(full, dict) else None
		if status == 401:
			return {"ok": False, "message": _("Invalid token (401). Check you copied the {0} token.").format(mode)}
		return {"ok": False, "message": _("TaxJar rejected the request.")}
	except taxjar.exceptions.TaxJarConnectionError:
		return {"ok": False, "message": _("Could not reach TaxJar. Check your connection and try again.")}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "TaxJar: test_connection failed")
		return {"ok": False, "message": _("Something went wrong testing this connection.")}

	return {"ok": True, "company": company, "mode": mode}


@frappe.whitelist(methods=["POST"])
def save_connection(
	mode: str,
	credentials: list | str | None = None,
	enable_taxjar_logging: int | str | None = None,
	log_retention_days: int | str | None = None,
):
	"""Persist API mode + per-company tokens. A blank token in the payload means
	"keep the existing one" (the masked field wasn't retyped), not "clear it"."""
	frappe.has_permission(SETTINGS, "write", throw=True)

	credentials = frappe.parse_json(credentials) if isinstance(credentials, str) else (credentials or [])

	settings = frappe.get_single(SETTINGS)
	settings.api_mode = mode
	if enable_taxjar_logging is not None:
		settings.enable_taxjar_logging = cint(enable_taxjar_logging)
	if log_retention_days is not None:
		settings.log_retention_days = cint(log_retention_days)

	token_field = "sandbox_token" if mode == "Sandbox" else "live_token"
	existing = {cred.company: cred for cred in (settings.table_hvjw or [])}

	for row in credentials:
		company = row.get("company")
		token = row.get("token")
		if not company:
			continue
		cred = existing.get(company)
		if not cred:
			cred = settings.append("table_hvjw", {"company": company})
		if token:
			cred.set(token_field, token)

	settings.save()
	return {"ok": True}


@frappe.whitelist()
def get_default_ledgers(company: str):
	"""Preview the standard-CoA ledger lookup for a company, without persisting
	anything - lets the Accounts step pre-fill blank fields before the admin sees
	them. Read-only counterpart to save_company_accounts()."""
	frappe.has_permission(SETTINGS, "read", throw=True)

	from taxjar_integration.taxjar_integration.regional.united_states import (
		resolve_default_ledgers,
	)

	return resolve_default_ledgers(company)


@frappe.whitelist(methods=["POST"])
def save_company_accounts(rows: list | str):
	"""Upsert company_config account heads. Both heads are mandatory on the
	child doctype, so an incomplete row surfaces that as a normal save error."""
	frappe.has_permission(SETTINGS, "write", throw=True)

	rows = frappe.parse_json(rows) if isinstance(rows, str) else (rows or [])

	settings = frappe.get_single(SETTINGS)
	existing = {cfg.company: cfg for cfg in (settings.company_config or [])}

	for row in rows:
		company = row.get("company")
		if not company:
			continue
		cfg = existing.get(company)
		if not cfg:
			cfg = settings.append("company_config", {"company": company})
		cfg.tax_account_head = row.get("tax_account_head")
		cfg.shipping_account_head = row.get("shipping_account_head")

	settings.save()
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def save_features(company_flags: list | str | None = None):
	"""Set each company's Calculate/File flags. Flags for a company without an
	existing company_config row are silently skipped — the Accounts step must
	run first to create that row.

	The parameter must NOT be named ``flags`` - frappe.call()'s get_newargs()
	unconditionally pops a kwarg literally named "flags" (and
	"ignore_permissions") from every whitelisted API call before dispatch, as a
	security measure, regardless of whether the target function declares that
	parameter. A whitelisted method named ``flags`` therefore always received
	None over real HTTP calls (frappe.xcall from the browser, or any other API
	client) while still "succeeding" from bench execute, which calls the Python
	function directly and bypasses frappe.call() entirely - the discrepancy
	that made this look like it worked in every direct test.

	The master switch (taxjar_enabled) is auto-enabled the moment any company
	ends up with Calculate Sales Tax or File Transactions on - the per-company
	flags this sets are otherwise inert while the switch is off (see
	_is_taxjar_enabled), which read as "the toggle didn't save" even though the
	child row itself was written correctly. It is never auto-disabled here:
	turning individual company flags off does not imply the user wants TaxJar
	off everywhere, so that stays a deliberate action on the TaxJar Settings
	form."""
	frappe.has_permission(SETTINGS, "write", throw=True)

	company_flags = (
		frappe.parse_json(company_flags) if isinstance(company_flags, str) else (company_flags or [])
	)

	settings = frappe.get_single(SETTINGS)
	existing = {cfg.company: cfg for cfg in (settings.company_config or [])}
	for row in company_flags:
		cfg = existing.get(row.get("company"))
		if not cfg:
			continue
		cfg.taxjar_calculate_tax = cint(row.get("calculate"))
		cfg.taxjar_create_transactions = cint(row.get("file"))

	if any(
		cfg.taxjar_calculate_tax or cfg.taxjar_create_transactions
		for cfg in (settings.company_config or [])
	):
		settings.taxjar_enabled = 1

	settings.save()
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def remove_company(company: str):
	"""Drop a company from the guided setup entirely — its credential and (if
	any) its company_config row — so it disappears from every later step too
	rather than leaving an orphaned config with no credential behind it."""
	frappe.has_permission(SETTINGS, "write", throw=True)

	settings = frappe.get_single(SETTINGS)
	settings.set("table_hvjw", [c for c in (settings.table_hvjw or []) if c.company != company])
	settings.set("company_config", [c for c in (settings.company_config or []) if c.company != company])
	settings.save()

	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def fetch_nexus():
	"""Pull nexus regions from TaxJar for every configured company (wraps the
	doctype's own update_nexus_list, which also saves) and return them grouped
	by company, same shape as get_setup_state()'s nexus_by_company."""
	frappe.has_permission(SETTINGS, "write", throw=True)

	settings = frappe.get_single(SETTINGS)
	if not settings.company_config:
		frappe.throw(_("Please add at least one company's accounts before fetching nexus."))

	settings.update_nexus_list()

	return {
		"ok": True,
		"nexus_by_company": _nexus_by_company(settings),
		"nexus_last_synced": settings.nexus_last_synced,
	}


@frappe.whitelist(methods=["POST"])
def finish_setup():
	"""Mark setup complete. Saving runs the doctype's own validate(), so an
	incomplete/invalid configuration surfaces its error instead of being marked done.
	"""
	frappe.has_permission(SETTINGS, "write", throw=True)

	settings = frappe.get_single(SETTINGS)
	settings.setup_complete = 1
	settings.save()

	return {"ok": True, "setup_complete": True}
