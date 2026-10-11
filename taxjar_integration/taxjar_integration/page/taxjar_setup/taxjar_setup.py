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

``addresses`` is a third list with no child table behind it at all. The company
address TaxJar prices from is an ordinary ERPNext Address linked to the Company,
so it is read live per company - through the very same get_default_address()
the tax call itself uses - rather than mirrored into this doctype, where it
could disagree with what get_tax_data() will actually read.
"""

import taxjar
import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.password import get_decrypted_password

from taxjar_integration.taxjar_integration.access import require_permission
from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	settings_write_lock,
)
from taxjar_integration.taxjar_integration.taxjar_integration import (
	_validate_address_with_taxjar,
	company_address_names,
)
from taxjar_integration.telemetry import (
	capture,
	capture_once,
	record_setup_finished,
)

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
	require_permission(SETTINGS, "read")

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

	# Read on TaxJar Settings is what makes a TaxJar User, who never replaces a
	# token. The last 4 characters are there for the Manager who does, so a
	# reader gets none and the token is not even decrypted for them.
	can_manage = frappe.has_permission(SETTINGS, "write")
	if can_manage and not settings.setup_complete:
		capture_once("taxjar_setup_started")

	credentials = [
		{
			"company": cred.company,
			"token_last4": _token_last4(cred, token_field) if can_manage else None,
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
			"include_exports": bool(cfg.get("taxjar_include_exports")),
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
		"addresses": [_company_address(cred["company"]) for cred in credentials],
		"nexus_by_company": _nexus_by_company(settings),
		"nexus_last_synced": settings.nexus_last_synced,
	}


@frappe.whitelist()
def get_setup_status():
	"""Whether the guided setup has been finished.

	Deliberately lighter than get_setup_state(), and deliberately not guarded on
	TaxJar Settings: the workspace banner renders for everyone who can open the
	workspace, including users who cannot read that doctype, and whether setup
	has run is not a secret. Everything that is stays in get_setup_state(),
	which does guard.
	"""
	return {"setup_complete": bool(frappe.db.get_single_value(SETTINGS, "setup_complete"))}


@frappe.whitelist(methods=["POST"])
def test_connection(company: str, token: str | None = None, mode: str | None = None):
	"""Verify a TaxJar token against a lightweight endpoint, without persisting.

	If ``token`` is omitted, falls back to the already-saved credential for
	``company`` (e.g. re-testing a previously connected company). ``mode``
	defaults to the settings' current API Mode so a not-yet-saved mode change
	on Step 2 can still be tested before Continue is pressed.
	"""
	require_permission(SETTINGS, "write")

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
		_connection_tested("no_token", mode)
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
			_connection_tested("invalid_token", mode)
			return {"ok": False, "message": _("Invalid token (401). Check you copied the {0} token.").format(mode)}
		_connection_tested("rejected", mode)
		return {"ok": False, "message": _("TaxJar rejected the request.")}
	except taxjar.exceptions.TaxJarConnectionError:
		_connection_tested("unreachable", mode)
		return {"ok": False, "message": _("Could not reach TaxJar. Check your connection and try again.")}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "TaxJar: test_connection failed")
		_connection_tested("error", mode)
		return {"ok": False, "message": _("Something went wrong testing this connection.")}

	_connection_tested("ok", mode)
	return {"ok": True, "company": company, "mode": mode}


def _connection_tested(result, mode):
	capture("taxjar_setup_connection_tested", result=result, api_mode=(mode or "Live").lower())


@frappe.whitelist(methods=["POST"])
def save_connection(
	mode: str,
	credentials: list | str | None = None,
	enable_taxjar_logging: int | str | None = None,
	log_retention_days: int | str | None = None,
):
	"""Persist API mode + per-company tokens. A blank token in the payload means
	"keep the existing one" (the masked field wasn't retyped), not "clear it".

	Two changes here leave the stored nexus regions belonging to something else,
	and both are detected below so the stamp that gates the auto-fetch can be
	cleared:

	* a new API mode, because _api_mode() then reads the other token field and
	  the regions on file were fetched from the other TaxJar account;
	* a company that had no credential before, because the nexus sync iterates
	  company_config and has therefore never seen it.

	Neither is reported to the client. The guided setup walks every step after
	any edit, so it has no routing decision to make - clearing the stamp is the
	whole of what these two facts are for.
	"""
	require_permission(SETTINGS, "write")

	credentials = frappe.parse_json(credentials) if isinstance(credentials, str) else (credentials or [])

	# Read and save inside the lock: two writers of this Single at once deadlock
	# in the database rather than queue (see SETTINGS_WRITE_LOCK).
	with settings_write_lock():
		settings = frappe.get_single(SETTINGS)

		# Measured before anything is written. With no stored credential this is the
		# first Connect save, and there is nothing downstream to invalidate - every
		# company is new only in the sense that the wizard has not run yet.
		known = {cred.company for cred in (settings.table_hvjw or []) if cred.company}
		mode_changed = bool(known) and settings.api_mode != mode
		company_added = bool(known) and any(
			row.get("company") and row.get("company") not in known for row in credentials
		)

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

		# Both changes leave `nexus` holding regions that belong to a TaxJar account,
		# or a company set, that no longer matches. Clearing the stamp re-arms
		# on_update's own auto-fetch, which is gated on nexus_last_synced being empty
		# - without this it never fires again after the very first sync, and a mode
		# switch keeps the old account's regions for ever.
		if mode_changed or company_added:
			settings.nexus_last_synced = None

		settings.save()

	capture("taxjar_setup_step_completed", step="connect")
	return {"ok": True}


@frappe.whitelist()
def get_default_ledgers(company: str):
	"""Preview the standard-CoA ledger lookup for a company, without persisting
	anything - lets the Accounts step pre-fill blank fields before the admin sees
	them. Read-only counterpart to save_company_accounts()."""
	require_permission(SETTINGS, "read")

	from taxjar_integration.taxjar_integration.regional.united_states import (
		resolve_default_ledgers,
	)

	return resolve_default_ledgers(company)


@frappe.whitelist(methods=["POST"])
def save_company_accounts(rows: list | str):
	"""Upsert company_config account heads. Both heads are mandatory on the
	child doctype, so an incomplete row surfaces that as a normal save error."""
	require_permission(SETTINGS, "write")

	rows = frappe.parse_json(rows) if isinstance(rows, str) else (rows or [])

	# Read and save inside the lock: two writers of this Single at once deadlock
	# in the database rather than queue (see SETTINGS_WRITE_LOCK).
	with settings_write_lock():
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

	capture("taxjar_setup_step_completed", step="accounts")
	return {"ok": True}


# ── Company address ──────────────────────────────────────────────────────────
#
# TaxJar prices a sale from the company's own address, which
# get_company_address_details() resolves through get_default_address("Company",
# company) - whose sort key is is_primary_address, the field the Address doctype
# labels "Preferred Billing Address". So the BILLING flag, not the shipping one,
# decides which address becomes from_street/from_city/from_state/from_zip.
#
# That is ERPNext's rule and this step does not get to invent a different one:
# a wizard that treated Preferred Shipping as the origin would disagree with
# what get_tax_data() reads at invoice time, which is worse than either rule on
# its own. The endpoints below surface it instead - _set_preferred_billing() is
# what makes a pick stick, and get_setup_state() reports the address the same
# lookup resolves rather than a second opinion about it.

# What TaxJar needs from an address before it can price anything against it.
# Checked here rather than left to validate_address(): that hook only applies
# while taxjar_serves_any_company() holds, which is still false at this point in
# the wizard (the Features step has not run), so it is inert on exactly the
# addresses this step creates.
_REQUIRED_ADDRESS_FIELDS = ("address_line1", "city", "taxjar_state_code", "pincode")

# Client-settable Address fields. An allowlist, not a passthrough - these
# endpoints write a doctype this app does not own, on behalf of a page that has
# no business setting `disabled`, `links` or anything else it does not show.
# `state` is absent deliberately; see _address_values().
_WRITABLE_ADDRESS_FIELDS = (
	"address_title", "address_line1", "address_line2", "city", "pincode",
	"taxjar_state_code", "is_primary_address", "is_shipping_address",
)

_ADDRESS_READ_FIELDS = (
	"address_title", "address_line1", "address_line2", "city", "state",
	"taxjar_state_code", "pincode", "country",
	"is_primary_address", "is_shipping_address",
)


def _company_address(company, address=None):
	"""One card's worth of address state: what TaxJar will use, and what is wrong with it.

	``address`` overrides the lookup, for previewing a selection the user has
	made but not yet saved - the card still has to render it before Continue
	pins it.

	``linked_count`` is what lets the client tell "nothing to pick" from "several
	candidates, none of them pinned" - with no address flagged Preferred Billing,
	``is_primary_address DESC`` sorts a column that is 0 for every row and
	``limit 1`` returns whichever one the database hands back. Harmless with a
	single address, silently arbitrary with several.

	``company_has_preferred_billing`` is that second half, and it is deliberately
	about the COMPANY rather than about the address being shown. Whether this
	address is pinned (``is_primary_address``, below) is a different question:
	looking at a company's non-pinned address is perfectly ordinary and means
	nothing is wrong, while no address anywhere being pinned is the arbitrary
	case. Answering the first question and reporting it as the second told a
	user whose company was properly pinned that nothing was.
	"""
	from frappe.contacts.doctype.address.address import get_default_address

	linked = company_address_names(company)
	address = address or get_default_address("Company", company)

	if not address:
		return {"company": company, "address": None, "linked_count": len(linked), "missing": []}

	row = frappe.db.get_value("Address", address, _ADDRESS_READ_FIELDS, as_dict=True) or {}
	return {
		"company": company,
		"address": address,
		**{field: row.get(field) for field in _ADDRESS_READ_FIELDS},
		"linked_count": len(linked),
		"company_has_preferred_billing": bool(
			frappe.db.exists("Address", {"name": ["in", linked], "is_primary_address": 1})
		),
		"missing": [f for f in _REQUIRED_ADDRESS_FIELDS if not (row.get(f) or "").strip()],
	}


@frappe.whitelist()
def get_company_address_state(company: str, address: str | None = None):
	"""Re-read one company's address card, optionally for a not-yet-saved pick.

	The Link field can point at an address before save_company_address() has
	pinned it, and the card still has to preview it - including whether it is
	complete, which is _REQUIRED_ADDRESS_FIELDS' business and not the client's to
	re-derive.
	"""
	require_permission(SETTINGS, "read")

	if address:
		require_permission("Address", "read", doc=address)
		if address not in company_address_names(company):
			frappe.throw(
				_("{0} is not an address of {1}.").format(address, company),
				title=_("Address Not Linked"),
			)

	return _company_address(company, address)


def _address_values(values):
	"""Allowlisted Address fields from the client, with ``state`` derived.

	The dialog asks for the two-letter code only, and ``state`` is filled in from
	it here - the same pairing public/js/address.js keeps in lockstep on the
	Address form itself. Accepting both from the client would let them disagree,
	and get_state_code() reads one while a human reads the other.
	"""
	from taxjar_integration.taxjar_integration.taxjar_integration import US_STATE_NAMES

	values = frappe.parse_json(values) if isinstance(values, str) else (values or {})

	out = {field: values.get(field) for field in _WRITABLE_ADDRESS_FIELDS if field in values}
	for flag in ("is_primary_address", "is_shipping_address"):
		if flag in out:
			out[flag] = cint(out[flag])

	code = (out.get("taxjar_state_code") or "").strip().upper()
	if code:
		out["taxjar_state_code"] = code
		out["state"] = US_STATE_NAMES.get(code, code)

	return out


def _set_preferred_billing(company, address):
	"""Pin ``address`` as the company's Preferred Billing Address, clearing its siblings.

	Only rows whose flag actually changes are written. An untouched address
	should not be re-saved - its own validate() would run for nothing, and the
	user would need write permission on an address this call never meant to
	change.
	"""
	linked = company_address_names(company)
	if address not in linked:
		frappe.throw(
			_("{0} is not an address of {1}.").format(address, company),
			title=_("Address Not Linked"),
		)

	for name in linked:
		wanted = 1 if name == address else 0
		if cint(frappe.db.get_value("Address", name, "is_primary_address")) == wanted:
			continue
		require_permission("Address", "write", doc=name)
		doc = frappe.get_doc("Address", name)
		doc.is_primary_address = wanted
		doc.save()


@frappe.whitelist(methods=["POST"])
def save_company_address(rows: list | str):
	"""Pin each company's chosen address as its Preferred Billing Address.

	is_shipping_address is deliberately untouched. It is the user's, set in the
	dialog, read by other parts of ERPNext, and nothing in the TaxJar path
	depends on it - rewriting it from here would be a side effect nobody asked
	for.
	"""
	require_permission(SETTINGS, "write")

	rows = frappe.parse_json(rows) if isinstance(rows, str) else (rows or [])

	for row in rows:
		company, address = row.get("company"), row.get("address")
		if company and address:
			_set_preferred_billing(company, address)

	capture("taxjar_setup_step_completed", step="address")
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def create_company_address(company: str, values: dict | str):
	"""Create an Address already linked to ``company``.

	Country is fixed to United States rather than taken from the client: every
	company that reaches this step is a US company - company_scope() refuses any
	other and the Connect step's link filter never offers one - so it is the only
	value that can be correct here.
	"""
	require_permission(SETTINGS, "write")
	require_permission("Company", "read", doc=company)
	require_permission("Address", "create")

	doc = frappe.new_doc("Address")
	doc.update(_address_values(values))
	# address_type is mandatory on the doctype and this dialog does not ask for
	# it - there is one address per company here and its type is not a thing the
	# wizard has an opinion about. "Billing" matches the flag that actually
	# decides the tax origin (see the section comment above).
	doc.address_type = "Billing"
	doc.country = "United States"
	doc.append("links", {"link_doctype": "Company", "link_name": company})
	doc.insert()

	if cint(doc.is_primary_address):
		_set_preferred_billing(company, doc.name)

	return {"ok": True, "address": doc.name}


@frappe.whitelist(methods=["POST"])
def update_company_address(company: str, address: str, values: dict | str):
	"""Edit one of ``company``'s own addresses.

	Scoped to the company's linked addresses so this cannot be used as a general
	"write any Address" endpoint on the strength of a TaxJar Settings permission.
	"""
	require_permission(SETTINGS, "write")
	require_permission("Address", "write", doc=address)

	if address not in company_address_names(company):
		frappe.throw(
			_("{0} is not an address of {1}.").format(address, company),
			title=_("Address Not Linked"),
		)

	doc = frappe.get_doc("Address", address)
	doc.update(_address_values(values))
	doc.save()

	if cint(doc.is_primary_address):
		_set_preferred_billing(company, address)

	return {"ok": True, "address": address}


@frappe.whitelist(methods=["POST"])
def verify_company_address(company: str, address: str):
	"""Ask TaxJar whether it can find this address, during setup.

	No gate on company_scope(company).uses_taxjar - a condition that is false by
	definition while this step runs, since the Features step that turns a
	feature on comes after it. With that gate, the button would answer
	"out_of_scope" on every first run, which is the setup wizard reporting that
	setup is not finished.

	The gate here is the one that actually matters for the call: a credential for
	this company, which the Connect step has already proven works. Both go
	through the same _validate_address_with_taxjar(), so the verdict, the
	logging and the country guard are identical.
	"""
	require_permission(SETTINGS, "write")
	require_permission("Address", "read", doc=address)

	doc = frappe.get_doc("Address", address)
	# Returns None when the company has no usable credential for the current API
	# mode; say which of the two it is rather than passing None to the client.
	verdict = _validate_address_with_taxjar(doc, company) or {
		"checked": False,
		"reason": "no_credential",
	}
	capture("taxjar_setup_address_verified", result=_address_result(verdict))
	return verdict


def _address_result(verdict):
	if verdict.get("checked"):
		return "valid" if verdict.get("valid") else "not_found"
	return verdict.get("reason")


@frappe.whitelist(methods=["POST"])
def save_features(company_flags: list | str | None = None):
	"""Set each company's Calculate/File/Include Exports flags. Flags for a company without an
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
	require_permission(SETTINGS, "write")

	company_flags = (
		frappe.parse_json(company_flags) if isinstance(company_flags, str) else (company_flags or [])
	)

	# Read and save inside the lock: two writers of this Single at once deadlock
	# in the database rather than queue (see SETTINGS_WRITE_LOCK).
	with settings_write_lock():
		settings = frappe.get_single(SETTINGS)
		existing = {cfg.company: cfg for cfg in (settings.company_config or [])}
		for row in company_flags:
			cfg = existing.get(row.get("company"))
			if not cfg:
				continue
			cfg.taxjar_calculate_tax = cint(row.get("calculate"))
			cfg.taxjar_create_transactions = cint(row.get("file"))
			# Only meaningful while transactions are filed at all. The card hides
			# the switch when filing is off, so a client that files nothing sends
			# nothing about exports - and the stored answer stays as it was,
			# ready for the day filing is turned back on.
			if cfg.taxjar_create_transactions:
				cfg.taxjar_include_exports = cint(row.get("include_exports"))

		if any(
			cfg.taxjar_calculate_tax or cfg.taxjar_create_transactions
			for cfg in (settings.company_config or [])
		):
			settings.taxjar_enabled = 1

		settings.save()

	capture("taxjar_setup_step_completed", step="features")
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def remove_company(company: str):
	"""Drop a company from the guided setup entirely — its credential, its
	company_config row and its nexus regions — so it disappears from every later
	step too rather than leaving an orphaned config with no credential behind
	it."""
	require_permission(SETTINGS, "write")

	# Read and save inside the lock: two writers of this Single at once deadlock
	# in the database rather than queue (see SETTINGS_WRITE_LOCK).
	with settings_write_lock():
		settings = frappe.get_single(SETTINGS)
		settings.set("table_hvjw", [c for c in (settings.table_hvjw or []) if c.company != company])
		settings.set("company_config", [c for c in (settings.company_config or []) if c.company != company])
		# `nexus` is keyed by company too. Left behind, its rows kept reporting
		# regions for a company the wizard no longer lists anywhere else, because
		# nothing re-reads that table until the next full sync.
		settings.set("nexus", [n for n in (settings.nexus or []) if n.company != company])
		settings.save()

	capture("taxjar_company_removed")
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def fetch_nexus():
	"""Pull nexus regions from TaxJar for every configured company (wraps the
	doctype's own update_nexus_list, which also saves) and return them grouped
	by company, same shape as get_setup_state()'s nexus_by_company."""
	require_permission(SETTINGS, "write")

	settings = frappe.get_single(SETTINGS)
	if not settings.company_config:
		frappe.throw(
			_("Please add at least one company's accounts before fetching nexus."),
			title=_("Company Accounts Required"),
		)

	settings.update_nexus_list()

	capture("taxjar_setup_step_completed", step="nexus")
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
	require_permission(SETTINGS, "write")

	# The Activate button reaches here. The Nexus step it sits on starts a nexus
	# sync as it opens, and that sync rewrites the same record this save
	# rewrites - pressing Activate while it ran used to answer "Deadlock
	# Occurred". Under the lock this save waits for the sync instead.
	with settings_write_lock():
		settings = frappe.get_single(SETTINGS)
		settings.setup_complete = 1
		settings.save()

	record_setup_finished()
	_setup_finished(settings)
	return {"ok": True, "setup_complete": True}


def _setup_finished(settings):
	configs = settings.company_config or []
	capture(
		"taxjar_setup_finished",
		api_mode=(settings.api_mode or "Live").lower(),
		companies=len(configs),
		calculate_tax_companies=sum(1 for c in configs if c.taxjar_calculate_tax),
		create_transactions_companies=sum(1 for c in configs if c.taxjar_create_transactions),
		include_exports_companies=sum(
			1 for c in configs if c.taxjar_create_transactions and c.taxjar_include_exports
		),
		nexus_regions=len(settings.nexus or []),
	)
