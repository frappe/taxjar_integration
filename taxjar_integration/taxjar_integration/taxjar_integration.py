import hashlib
import json
import re
import traceback
from types import SimpleNamespace

import frappe
import taxjar
from frappe import _
from frappe.contacts.doctype.address.address import get_company_address
from frappe.realtime import get_doctype_room
from frappe.utils import cint, flt
from frappe.utils.password import get_decrypted_password

from erpnext import get_region
from erpnext.setup.utils import get_exchange_rate

SUPPORTED_COUNTRY_CODES = [
	"AT",
	"AU",
	"BE",
	"BG",
	"CA",
	"CY",
	"CZ",
	"DE",
	"DK",
	"EE",
	"ES",
	"FI",
	"FR",
	"GB",
	"GR",
	"HR",
	"HU",
	"IE",
	"IT",
	"LT",
	"LU",
	"LV",
	"MT",
	"NL",
	"PL",
	"PT",
	"RO",
	"SE",
	"SI",
	"SK",
	"US",
]
SUPPORTED_STATE_CODES = [
	"AL",
	"AK",
	"AZ",
	"AR",
	"CA",
	"CO",
	"CT",
	"DE",
	"DC",
	"FL",
	"GA",
	"HI",
	"ID",
	"IL",
	"IN",
	"IA",
	"KS",
	"KY",
	"LA",
	"ME",
	"MD",
	"MA",
	"MI",
	"MN",
	"MS",
	"MO",
	"MT",
	"NE",
	"NV",
	"NH",
	"NJ",
	"NM",
	"NY",
	"NC",
	"ND",
	"OH",
	"OK",
	"OR",
	"PA",
	"RI",
	"SC",
	"SD",
	"TN",
	"TX",
	"UT",
	"VT",
	"VA",
	"WA",
	"WV",
	"WI",
	"WY",
]

# Display label for the tax row TaxJar adds to the taxes table. Cosmetic only -
# TaxJar-owned rows are identified by account_head (see _remove_taxjar_rows),
# not by this text, so retitling it here is safe.
TAXJAR_ROW_DESCRIPTION = "Sales Tax"

# Provider identifier sent to TaxJar so transactions/refunds created via ERPNext
# are addressable (show/delete) under the ERPNext provider namespace.
TAXJAR_PROVIDER = "ERPNext"
PROVIDER_PARAMS = {"provider": TAXJAR_PROVIDER}


def _get_taxjar_logger():
	return frappe.logger("taxjar_integration", allow_site=True, file_count=20)


def _safe_json(data):
	try:
		return json.loads(json.dumps(data, default=str))
	except Exception:
		return str(data)


def _taxjar_response_payload(response):
	if response is None:
		return None

	for attr in ("full_response", "__dict__"):
		value = getattr(response, attr, None)
		if value:
			return _safe_json(value)

	return _safe_json(response)


def _write_taxjar_ui_log(log_data):
	if not frappe.db.exists("DocType", "TaxJar API Log"):
		return

	reference_doctype = (log_data.get("context") or {}).get("doctype")
	reference_name = (log_data.get("context") or {}).get("name")

	frappe.get_doc(
		{
			"doctype": "TaxJar API Log",
			"action": log_data.get("action"),
			"status": log_data.get("status"),
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"payload": json.dumps(log_data.get("payload"), default=str)
			if log_data.get("payload") is not None
			else None,
			"response": json.dumps(log_data.get("response"), default=str)
			if log_data.get("response") is not None
			else None,
			"error": json.dumps(log_data.get("error"), default=str)
			if log_data.get("error") is not None
			else None,
		}
	# ignore_permissions: log writes must succeed regardless of the triggering user's role.
	# TaxJar API Log is read-restricted to System Manager; this does not grant the user read access.
	).insert(ignore_permissions=True)


def _is_taxjar_logging_enabled():
	cached_value = getattr(frappe.flags, "taxjar_logging_enabled", None)
	if cached_value is not None:
		return cached_value

	try:
		stored_value = frappe.db.get_single_value("TaxJar Settings", "enable_taxjar_logging")
		enabled = 1 if stored_value is None else cint(stored_value)
	except Exception:
		enabled = 1

	frappe.flags.taxjar_logging_enabled = enabled
	return enabled


def log_taxjar_call(action, status, payload=None, response=None, error=None, context=None):
	if not _is_taxjar_logging_enabled():
		return

	log_data = {
		"action": action,
		"status": status,
		"context": context or {},
		"payload": _safe_json(payload) if payload is not None else None,
		"response": _taxjar_response_payload(response),
		"error": _safe_json(error) if error is not None else None,
	}

	logger = _get_taxjar_logger()
	message = json.dumps(log_data, default=str)
	if status == "error":
		logger.error(message)
	else:
		logger.info(message)

	try:
		_write_taxjar_ui_log(log_data)
	except Exception:
		logger.error("Failed to write TaxJar API Log DocType entry")
		logger.error(traceback.format_exc())


def get_company_config(company):
	"""Return the TaxJar Company Config row for the given company, or None."""
	taxjar_settings = frappe.get_single("TaxJar Settings")
	for config in taxjar_settings.company_config or []:
		if config.company == company:
			return config
	return None


def get_client(company=None):
	taxjar_settings = frappe.get_single("TaxJar Settings")
	is_sandbox = taxjar_settings.api_mode == "Sandbox"
	api_url = taxjar.SANDBOX_API_URL if is_sandbox else taxjar.DEFAULT_API_URL
	token_field = "sandbox_token" if is_sandbox else "live_token"

	api_key = None
	for cred in taxjar_settings.table_hvjw or []:
		if not company or cred.company == company:
			if getattr(cred, token_field, None):
				api_key = get_decrypted_password("TaxJar API Credential", cred.name, token_field)
			break

	if api_key and api_url:
		client = taxjar.Client(api_key=api_key, api_url=api_url)
		client.set_api_config("headers", {"x-api-version": "2022-01-24"})
		return client


def enqueue_taxjar_sync(doc, method):
	"""on_submit hook: enqueue background TaxJar transaction sync."""
	if not company_creates_transactions(doc.company):
		return
	if not get_client(doc.company):
		return

	doc.db_set("taxjar_sync_status", "Queued", update_modified=False)
	_publish_transaction_update(doc.name, "Queued")

	frappe.enqueue(
		"taxjar_integration.taxjar_integration.taxjar_integration.sync_transaction_to_taxjar",
		invoice_name=doc.name,
		queue="short",
		enqueue_after_commit=True,
		job_id=f"taxjar_transaction_create_{doc.name}",
		deduplicate=True,
		now=frappe.flags.in_test,
	)


def enqueue_taxjar_delete(doc, method):
	"""on_cancel hook: enqueue background TaxJar transaction deletion."""
	if not company_creates_transactions(doc.company):
		return
	if not get_client(doc.company):
		return

	doc.db_set("taxjar_sync_status", "Queued", update_modified=False)
	_publish_transaction_update(doc.name, "Queued")

	# Deliberately its own job_id, not shared with enqueue_taxjar_sync(): a
	# shared job_id used to make deduplicate=True silently drop this enqueue
	# whenever the create job was still QUEUED *or* STARTED - and RQ only
	# clears STARTED once the create worker fully exits, well after it takes
	# its last look at docstatus. A cancellation committing in that gap got
	# its delete dropped with nothing left to notice: the create had already
	# set status Synced, so there was no Failed row for the retry cron to
	# pick up either - the transaction stayed stranded in TaxJar for good.
	# Running independently is safe because both workers already treat a
	# cancellation as authoritative over their own stale read: this delete
	# defers to a genuinely not-yet-created order with a handled 404 (see
	# delete_transaction_from_taxjar), and sync_transaction_to_taxjar checks
	# docstatus both on entry and again right after its create call,
	# deleting what it just made if the invoice was cancelled meanwhile. At
	# worst the two race into a redundant, idempotent double delete - never
	# a dropped one.
	frappe.enqueue(
		"taxjar_integration.taxjar_integration.taxjar_integration.delete_transaction_from_taxjar",
		invoice_name=doc.name,
		queue="short",
		enqueue_after_commit=True,
		job_id=f"taxjar_transaction_delete_{doc.name}",
		deduplicate=True,
		now=frappe.flags.in_test,
	)


@frappe.whitelist(methods=["POST"])
def resync_transaction(invoice_name: str):
	"""Permission-checked entry point for the Sales Invoice "Sync to TaxJar" button.

	Runs the sync inline rather than enqueuing it: the button reloads the form in
	its callback and reports the resulting status, so it needs the work finished
	by the time it returns. The worker below is deliberately not whitelisted -
	frappe.enqueue resolves a dotted path without it, so the on_submit hook, the
	retry cron and the bulk actions all keep working unchanged, while HTTP has
	exactly one way in and it checks permission first.
	"""
	frappe.has_permission("Sales Invoice", "write", doc=invoice_name, throw=True)
	return sync_transaction_to_taxjar(invoice_name)


def sync_transaction_to_taxjar(invoice_name):
	"""Background worker: create order/refund in TaxJar for a submitted Sales Invoice."""
	doc = frappe.get_doc("Sales Invoice", invoice_name)
	ctx = {"doctype": "Sales Invoice", "name": invoice_name}

	if doc.docstatus == 2:
		delete_transaction_from_taxjar(invoice_name)
		return

	client = get_client(doc.company)
	if not client:
		_set_sync_status(invoice_name, "Failed", error="TaxJar is not configured for this company.", retryable=True)
		return

	# Matched by account_head, not description - the row's description is
	# free text a user can retitle before submit, same reason
	# _remove_taxjar_rows() matches on account_head rather than text.
	company_config = get_company_config(doc.company)
	sales_tax = sum(
		tax.tax_amount for tax in doc.taxes
		if company_config and tax.account_head == company_config.tax_account_head
	)

	tax_dict = get_tax_data(doc)
	if not tax_dict:
		_set_sync_status(
			invoice_name,
			"Failed",
			error="No TaxJar payload could be built for this document - check the company's TaxJar configuration.",
			retryable=True,
		)
		log_taxjar_call(action="create_transaction", status="skipped", error="No TaxJar payload generated", context=ctx)
		return

	tax_dict["transaction_id"] = doc.name
	tax_dict["transaction_date"] = str(doc.posting_date)
	tax_dict["sales_tax"] = sales_tax
	# get_tax_data() already derives "amount" correctly from the actual
	# line_items + shipping being sent (see its own comment) - overriding it
	# with doc.total here was wrong on two counts: doc.total excludes any
	# document-level Additional Discount, and adding tax_dict["shipping"]
	# on top double-counted shipping, which get_tax_data() already folds in.
	# This was a real, live-verified TaxJar rejection ("amount must be equal
	# to the sum of line items and shipping"), not a hypothetical.
	tax_dict["provider"] = TAXJAR_PROVIDER

	if doc.is_return and doc.return_against:
		tax_dict["transaction_reference_id"] = doc.return_against

	try:
		if doc.is_return:
			log_taxjar_call(action="create_refund", status="request", payload=tax_dict, context=ctx)
			response = client.create_refund(tax_dict)
			log_taxjar_call(action="create_refund", status="success", payload=tax_dict, response=response, context=ctx)
		else:
			log_taxjar_call(action="create_order", status="request", payload=tax_dict, context=ctx)
			response = client.create_order(tax_dict)
			log_taxjar_call(action="create_order", status="success", payload=tax_dict, response=response, context=ctx)

		_set_sync_status(invoice_name, "Synced")

		# doc was read at the top of this function, before the create_order/
		# create_refund call above - if the invoice got cancelled while that
		# call was in flight, doc.docstatus is stale and a concurrent delete
		# job (enqueue_taxjar_delete shares this job_id, so it may have been
		# skipped entirely, or may have already 404'd against an order that
		# didn't exist yet and read that as "nothing to do") can't be relied
		# on to have cleaned this up. Re-check against the database and
		# delete what was just created rather than leave it stranded.
		if frappe.db.get_value("Sales Invoice", invoice_name, "docstatus") == 2:
			delete_transaction_from_taxjar(invoice_name)
	except Exception as err:
		_record_sync_failure(err, "create_transaction", tax_dict, ctx, invoice_name)


def delete_transaction_from_taxjar(invoice_name):
	"""Background worker: delete order/refund from TaxJar for a cancelled Sales Invoice."""
	doc = frappe.get_doc("Sales Invoice", invoice_name)
	ctx = {"doctype": "Sales Invoice", "name": invoice_name}

	client = get_client(doc.company)
	if not client:
		_set_sync_status(invoice_name, "Failed", error="TaxJar is not configured for this company.", retryable=True)
		return

	is_refund = doc.is_return
	action = "delete_refund" if is_refund else "delete_order"
	payload = {"transaction_id": doc.name}
	provider_params = PROVIDER_PARAMS

	try:
		log_taxjar_call(action=action, status="request", payload=payload, context=ctx)
		if is_refund:
			response = client.delete_refund(doc.name, params=provider_params)
		else:
			response = client.delete_order(doc.name, params=provider_params)
		log_taxjar_call(action=action, status="success", payload=payload, response=response, context=ctx)
		_set_sync_status(invoice_name, "Synced")
	except taxjar.exceptions.TaxJarResponseError as err:
		full = getattr(err, "full_response", None)
		if isinstance(full, dict) and full.get("status_code") == 404:
			# Already gone from TaxJar, so the cancellation has nothing left to
			# undo. Read as done rather than Failed - a 404 here can never clear
			# on retry, and delete_customer_from_taxjar() already treats it the
			# same way.
			log_taxjar_call(action=action, status="success", payload=payload, error="404 - already absent in TaxJar", context=ctx)
			_set_sync_status(invoice_name, "Synced")
			return
		_record_sync_failure(err, action, payload, ctx, invoice_name)
	except Exception as err:
		_record_sync_failure(err, action, payload, ctx, invoice_name)


def _publish_transaction_update(invoice_name, status):
	"""Notify the TaxJar Transaction Sync page that an invoice's sync status moved.

	Deliberately a second, separately-named event rather than a wider room on
	the doc-scoped taxjar_invoice_sync_update below: that one is consumed by the
	Sales Invoice form, whose listener calls frm.reload_doc() unconditionally
	and relies purely on room scoping to know the event concerns the doc it has
	open. Widening it would reload every open invoice on any invoice's sync.

	The doctype room (not the site room) keeps the fanout to sockets that opted
	in - every System User auto-joins the site room on connect, so a site-room
	broadcast would wake every logged-in desk user. Joining a doctype room runs
	a server-side permission check first.
	"""
	frappe.publish_realtime(
		"taxjar_transactions_update",
		{"name": invoice_name, "taxjar_sync_status": status},
		room=get_doctype_room("Sales Invoice"),
		after_commit=True,
	)


def _set_sync_status(invoice_name, status, error=None, retryable=False):
	"""Update TaxJar sync status fields on a Sales Invoice via db_set, then
	notify any open form and the Transaction Sync page via realtime so neither
	sits showing a stale status until manually reloaded. This is reached only
	from async contexts (the background sync job, the 15-min cron retry, bulk
	retry from the Transactions page) - the synchronous button-click path
	already reloads via its own frappe.call callback and doesn't need this.

	``retryable`` records whether the failure is one a later, identical attempt
	could clear - see classify_taxjar_error(). It is what retry_failed_taxjar_syncs()
	filters on, so a permanently-rejected document stops being re-sent every 15
	minutes and waits for the Retry button instead.

	Each Failed outcome also bumps taxjar_sync_retry_count; any other status
	resets it to 0. retry_failed_taxjar_syncs() stops re-enqueueing once that
	count reaches TAXJAR_MAX_SYNC_RETRIES, so a document TaxJar keeps rejecting
	doesn't get auto-retried forever.
	"""
	if error and retryable:
		error = f"{error} Automatic retry is scheduled."

	fields = {
		"taxjar_sync_status": status,
		"taxjar_sync_error": error or "",
		"taxjar_sync_retryable": 1 if status == "Failed" and retryable else 0,
		"taxjar_last_synced": frappe.utils.now() if status == "Synced" else None,
	}
	if status == "Failed":
		prior_count = cint(frappe.db.get_value("Sales Invoice", invoice_name, "taxjar_sync_retry_count"))
		fields["taxjar_sync_retry_count"] = prior_count + 1
	else:
		fields["taxjar_sync_retry_count"] = 0

	frappe.db.set_value("Sales Invoice", invoice_name, fields, update_modified=False)
	frappe.publish_realtime(
		"taxjar_invoice_sync_update",
		{"taxjar_sync_status": status},
		doctype="Sales Invoice",
		docname=invoice_name,
		after_commit=True,
	)
	_publish_transaction_update(invoice_name, status)


def _record_sync_failure(err, action, payload, ctx, invoice_name):
	"""One funnel for every exception a transaction sync can raise: classify it,
	send the technical detail to TaxJar API Log, and leave a single readable
	sentence on the invoice.

	Replaces the three per-call-site except branches this used to need, whose
	catch-all wrote a raw traceback into Sync Error - a field users read on the
	form. Tracebacks now stop at the log, where they are useful.
	"""
	info = classify_taxjar_error(err)
	log_taxjar_call(action=action, status="error", payload=payload, error=info["log_detail"], context=ctx)
	if info["kind"] == "unknown":
		_get_taxjar_logger().error(info["log_detail"])
	_set_sync_status(invoice_name, "Failed", error=info["message"], retryable=info["retryable"])


@frappe.whitelist()
def fetch_transaction_from_taxjar(invoice_name: str):
	"""Pull current transaction state from TaxJar and return the response data."""
	frappe.has_permission("Sales Invoice", "read", doc=invoice_name, throw=True)

	doc = frappe.get_doc("Sales Invoice", invoice_name)
	client = get_client(doc.company)
	if not client:
		frappe.throw(_("TaxJar client is not configured for company {0}").format(doc.company))

	ctx = {"doctype": "Sales Invoice", "name": invoice_name}

	provider_params = PROVIDER_PARAMS

	try:
		if doc.is_return:
			log_taxjar_call(action="show_refund", status="request", context=ctx)
			response = client.show_refund(doc.name, params=provider_params)
			log_taxjar_call(action="show_refund", status="success", response=response, context=ctx)
		else:
			log_taxjar_call(action="show_order", status="request", context=ctx)
			response = client.show_order(doc.name, params=provider_params)
			log_taxjar_call(action="show_order", status="success", response=response, context=ctx)
		return _taxjar_response_payload(response)
	except taxjar.exceptions.TaxJarResponseError as err:
		full = getattr(err, "full_response", {}) or {}
		status_code = full.get("status_code") if isinstance(full, dict) else None
		log_taxjar_call(action="show_transaction", status="error", error=getattr(err, "full_response", str(err)), context=ctx)
		if status_code == 404:
			frappe.throw(
				_("Transaction {0} was not found in TaxJar. It may have been created in a different API mode (Sandbox/Live) "
				  "or may not have been synced yet.").format(invoice_name)
			)
		frappe.throw(_linkify_guided_setup(_("Failed to fetch from TaxJar: {0}").format(sanitize_error_response(err))))
	except taxjar.exceptions.TaxJarConnectionError:
		log_taxjar_call(action="show_transaction", status="error", error="TaxJar API is unreachable", context=ctx)
		frappe.throw(_("TaxJar API is unreachable. Please try again later."))
	except Exception as e:
		log_taxjar_call(action="show_transaction", status="error", error=str(e), context=ctx)
		frappe.throw(_("Failed to fetch from TaxJar: {0}").format(str(e)))


@frappe.whitelist(methods=["POST"])
def delete_transaction_manual(invoice_name: str):
	"""Manual deletion of a transaction from TaxJar (for cleanup)."""
	frappe.has_permission("Sales Invoice", "write", doc=invoice_name, throw=True)

	doc = frappe.get_doc("Sales Invoice", invoice_name)
	client = get_client(doc.company)
	if not client:
		frappe.throw(_("TaxJar client is not configured for company {0}").format(doc.company))

	ctx = {"doctype": "Sales Invoice", "name": invoice_name}
	is_refund = doc.is_return
	action = "delete_refund" if is_refund else "delete_order"

	provider_params = PROVIDER_PARAMS

	try:
		log_taxjar_call(action=action, status="request", payload={"transaction_id": doc.name}, context=ctx)
		if is_refund:
			response = client.delete_refund(doc.name, params=provider_params)
		else:
			response = client.delete_order(doc.name, params=provider_params)
		log_taxjar_call(action=action, status="success", response=response, context=ctx)
		_set_sync_status(invoice_name, "Excluded")
		return {"success": True}
	except Exception as e:
		log_taxjar_call(action=action, status="error", error=str(e), context=ctx)
		frappe.throw(_("Failed to delete from TaxJar: {0}").format(str(e)))


def _get_transaction_date(doc):
	return getattr(doc, "posting_date", None) or getattr(doc, "transaction_date", None)


def _get_usd_exchange_rate(doc):
	"""Return the exchange rate from doc.currency to USD, or None if already USD.

	The looked-up rate is memoized on doc.flags so the repeated calls within a
	single document (get_tax_data and set_sales_tax both need it) hit Currency
	Exchange only once. Documents without a flags container (e.g. plain test
	stubs) simply skip the cache and behave as before.
	"""
	currency = getattr(doc, "currency", None) or "USD"
	if currency == "USD":
		return None

	flags = getattr(doc, "flags", None)
	if flags is not None and flags.get("taxjar_usd_rate") is not None:
		return flags.get("taxjar_usd_rate")

	txn_date = _get_transaction_date(doc)
	rate = flt(get_exchange_rate(currency, "USD", txn_date, args="for_selling"))
	if not rate:
		frappe.throw(
			_("Could not find exchange rate from {0} to USD for {1}. "
			  "Please add it in Currency Exchange or configure Currency Exchange Settings."
			).format(currency, txn_date)
		)

	if flags is not None:
		flags.taxjar_usd_rate = rate
	return rate


def get_tax_data(doc):
	company_config = get_company_config(doc.company)
	if not company_config:
		return None

	from_address = get_company_address_details(doc)
	from_shipping_state = from_address.get("state")
	from_country_code = frappe.db.get_value("Country", from_address.country, "code", cache=True)
	from_country_code = from_country_code.upper()

	to_address = get_shipping_address_details(doc)
	to_shipping_state = to_address.get("state")
	to_country_code = frappe.db.get_value("Country", to_address.country, "code", cache=True)
	to_country_code = to_country_code.upper()

	shipping = sum(
		tax.tax_amount for tax in doc.taxes
		if tax.account_head == company_config.shipping_account_head
	)

	line_items = [get_line_item_dict(item, doc.docstatus) for item in doc.items]

	# Foreign Sales Taxes and Charges rows (design doc §4) - a handling fee,
	# a manual "Loyalty Discount", etc - must be folded in before the
	# currency-conversion loop below so they convert identically to real
	# items.
	foreign_rows = _classify_foreign_tax_rows(doc, company_config)
	_apply_item_discounts(line_items, foreign_rows["item_discounts"])
	line_items.extend(foreign_rows["synthetic_items"])

	if from_shipping_state not in SUPPORTED_STATE_CODES:
		from_shipping_state = get_state_code(from_address, "Company")

	if to_shipping_state not in SUPPORTED_STATE_CODES:
		to_shipping_state = get_state_code(to_address, "Shipping")

	usd_rate = _get_usd_exchange_rate(doc)
	if usd_rate:
		shipping = flt(shipping * usd_rate, 2)
		for li in line_items:
			li["unit_price"] = flt(li["unit_price"] * usd_rate, 2)
			if "discount" in li:
				li["discount"] = flt(li["discount"] * usd_rate, 2)
			if "sales_tax" in li:
				li["sales_tax"] = flt(li["sales_tax"] * usd_rate, 2)

	# TaxJar's own validation requires "amount" to equal the sum of line
	# items (unit_price × quantity − discount) plus shipping, excluding
	# sales tax - confirmed live against a real "amount must be equal to
	# the sum of line items and shipping" rejection (design doc §2 had this
	# backwards, describing amount as excluding shipping). Deriving it
	# directly from the final line_items/shipping - already currency-
	# converted above - keeps this invariant correct by construction,
	# rather than by coincidence with doc.net_total.
	amount = shipping + sum(
		flt(li.get("unit_price")) * flt(li.get("quantity")) - flt(li.get("discount", 0))
		for li in line_items
	)

	tax_dict = {
		"from_country": from_country_code,
		"from_zip": from_address.pincode,
		"from_state": from_shipping_state,
		"from_city": from_address.city,
		"from_street": from_address.address_line1,
		"to_country": to_country_code,
		"to_zip": to_address.pincode,
		"to_city": to_address.city,
		"to_street": to_address.address_line1,
		"to_state": to_shipping_state,
		"shipping": shipping,
		"amount": flt(amount, 2),
		"plugin": "erpnext",
		"line_items": line_items,
	}

	taxjar_customer_id = _get_taxjar_customer_id(doc)
	if taxjar_customer_id:
		tax_dict["customer_id"] = taxjar_customer_id

	exemption_type, _exemption_source = _get_effective_exemption(doc)
	if exemption_type:
		tax_dict["exemption_type"] = _map_exemption_type(exemption_type)

	return tax_dict


def get_state_code(address, location):
	if address is not None:
		state_code = get_iso_3166_2_state_code(address)
		if state_code not in SUPPORTED_STATE_CODES:
			frappe.throw(_("Please enter a valid State in the {0} Address").format(location))
	else:
		frappe.throw(_("Please enter a valid State in the {0} Address").format(location))

	return state_code


def _get_item_product_tax_category(item):
	"""Return the product tax category for a transaction line item.

	Prefer the value already on the line item - all three item tables carry the
	field, populated by fetch_from off item_code. Fall back to the Item master
	for programmatically created documents whose rows were never saved through
	the fetch, and for line items with no item_code at all.
	"""
	return item.get("product_tax_category") or (
		frappe.db.get_value("Item", item.get("item_code"), "product_tax_category", cache=True)
		if item.get("item_code")
		else None
	)


def get_line_item_dict(item, docstatus):
	product_tax_code = _get_item_product_tax_category(item)

	# list_rate is the pre-discount unit price - the max of rate_with_margin,
	# price_list_rate, and rate, so that whichever field actually reflects
	# the highest price this line was offered at wins. max() rather than an
	# "or" fallback chain matters for a line with rate typed directly above a
	# stale/lower price_list_rate and no margin fields populated (e.g. a
	# programmatically created document that bypassed ERPNext's client-side
	# margin auto-set) - an "or" chain would pick the lower price_list_rate,
	# clamp the resulting negative discount to 0, and silently under-report
	# the amount actually charged.
	# discount is sourced from net_amount, ERPNext's own final chargeable
	# amount for the line - it already folds in both item-level discount and
	# this line's proportional share of any document-level Additional
	# Discount (except the Grand Total + cash/non-trade mode, where net_amount
	# is deliberately left untouched and discount correctly computes to 0).
	#
	# Clamped to [0, list_amount] on a normal sale, but a credit note/return
	# has qty < 0, which makes list_amount (and so the "natural" discount
	# range) negative too - unit_price stays positive and quantity carries
	# the sign unmodified (see get_tax_data's amount formula below), so
	# discount has to be allowed to go negative in step with list_amount for
	# `unit_price * quantity - discount` to still reconstruct net_amount.
	# min(max(discount, 0), list_amount) assumed list_amount >= 0 and
	# silently clamped a real -$21.40 return-line discount to -$1000
	# instead, which then failed the `discount > 0` check below and got
	# dropped from the TaxJar payload entirely - the return was taxed on
	# the full undiscounted amount instead of the discounted one.
	list_rate = max(flt(item.get("rate_with_margin")), flt(item.get("price_list_rate")), flt(item.get("rate")))
	list_amount = list_rate * flt(item.get("qty"))
	discount = list_amount - flt(item.get("net_amount"))
	discount = max(min(discount, max(0, list_amount)), min(0, list_amount))

	# product_identifier is the Item master's own name - item_code is what
	# the row is fetched from and, by this app's autoname convention
	# (field:item_code), already is that Item doc's name, so no extra lookup
	# is needed. description is "[item_code] item_name - description": the
	# code bracketed up front for a quick cross-reference, then whatever
	# free-text description was added on the child table row itself - each
	# part dropped cleanly when blank rather than leaving stray brackets or
	# a dangling separator.
	item_code = item.get("item_code")
	item_name = item.get("item_name") or ""
	description = item.get("description") or ""

	name_part = f"[{item_code}] {item_name}".strip() if item_code else item_name
	full_description = " - ".join(part for part in (name_part, description) if part)

	tax_dict = dict(
		id=item.get("idx"),
		quantity=item.get("qty"),
		product_tax_code=product_tax_code,
		product_identifier=item_code,
		description=full_description,
		unit_price=list_rate,
	)

	# Not `> 0` - a return's meaningful discount value is negative (it moves
	# in the same direction as list_amount/net_amount there), and `> 0`
	# would drop it from the payload exactly like the clamp above used to.
	if discount:
		tax_dict["discount"] = discount

	if docstatus == 1:
		tax_dict.update({"sales_tax": item.get("tax_collectable")})

	return tax_dict


# Offset for synthetic charge-line ids (design doc §4.4) - Sales Taxes and
# Charges rows are single-digit counts in practice, so a fixed high offset
# can never collide with a real item's idx, without needing to know
# len(doc.items) at every call site that builds or reads one.
_SYNTHETIC_LINE_ID_OFFSET = 1000


def _classify_foreign_tax_rows(doc, company_config):
	"""Classify Sales Taxes and Charges rows that are neither our own tax row
	nor the configured shipping row - a handling fee, a manually entered
	"Loyalty Discount" row, etc (design doc §4.1). These are otherwise
	invisible to TaxJar: they move doc.grand_total but never doc.net_total,
	the taxable base we send.

	A positive row becomes a synthetic taxable line item (§4.2); a negative
	row is distributed as a line-item discount, proportional to net_amount -
	the same math ERPNext's own apply_discount_amount() uses (§4.3).

	Shared by get_tax_data() (the real payload) and the client confirmation
	dialog's preview endpoint, so what the dialog shows is exactly what gets
	sent (§5.3).
	"""
	known_heads = {company_config.tax_account_head, company_config.shipping_account_head}
	foreign_rows = [
		tax for tax in (doc.taxes or [])
		if tax.account_head not in known_heads and flt(tax.tax_amount) != 0
	]

	synthetic_items = [
		_build_synthetic_line_item(row) for row in foreign_rows if flt(row.tax_amount) > 0
	]
	negative_total = sum(-flt(row.tax_amount) for row in foreign_rows if flt(row.tax_amount) < 0)

	return {
		"foreign_rows": foreign_rows,
		"synthetic_items": synthetic_items,
		"item_discounts": _distribute_negative_total(doc, negative_total) if negative_total else {},
	}


def _build_synthetic_line_item(row):
	account_name = frappe.db.get_value("Account", row.account_head, "account_name", cache=True)
	description = f"{account_name or row.account_head} - {row.description}" if row.description \
		else (account_name or row.account_head)
	return dict(
		id=_SYNTHETIC_LINE_ID_OFFSET + row.idx,
		quantity=1,
		product_tax_code=None,
		product_identifier=row.account_head,
		description=description,
		unit_price=flt(row.tax_amount),
	)


def _distribute_negative_total(doc, negative_total):
	"""Spread a foreign negative row's amount across real line items,
	proportional to net_amount - mirrors apply_discount_amount()'s own
	distributed_amount math (design doc §3.1/§4.3)."""
	total_net_amount = sum(flt(item.get("net_amount")) for item in doc.items)
	if not total_net_amount:
		return {}
	return {
		item.get("idx"): flt(negative_total * flt(item.get("net_amount")) / total_net_amount)
		for item in doc.items
	}


def _apply_item_discounts(line_items, item_discounts):
	for line_item in line_items:
		extra_discount = item_discounts.get(line_item.get("id"))
		if extra_discount:
			# Clamp to the line's own price, same as get_line_item_dict()'s own
			# discount - otherwise a large foreign discount row distributed
			# onto a line that already carries a big item-level discount could
			# push the combined discount above unit_price × quantity, sending
			# TaxJar a negative effective taxable amount for that line.
			max_discount = flt(line_item.get("unit_price")) * flt(line_item.get("quantity"))
			total_discount = flt(line_item.get("discount", 0) + extra_discount)
			line_item["discount"] = min(total_discount, max_discount)


@frappe.whitelist()
def preview_foreign_tax_rows(doc_json: dict | str):
	"""Classify a document's foreign Sales Taxes and Charges rows for the
	client confirmation dialog (design doc §5) - built on the exact same
	_classify_foreign_tax_rows() get_tax_data() itself uses, so what the
	dialog shows is guaranteed to match what actually gets sent.

	Takes the client's current (possibly unsaved) doc state as JSON rather
	than a docname - the dialog must reflect in-progress edits before save,
	not what is already in the database.
	"""
	doc_data = json.loads(doc_json) if isinstance(doc_json, str) else doc_json
	frappe.has_permission(doc_data.get("doctype"), "read", throw=True)

	company = doc_data.get("company")
	if not company_calculates_tax(company) or get_region(company) != "United States":
		return {"foreign_rows": []}

	company_config = get_company_config(company)
	if not company_config:
		return {"foreign_rows": []}

	# Not frappe._dict for the top-level container: dict.items is a real
	# bound method, so a "doc.items" attribute lookup would silently return
	# that method instead of the items list. SimpleNamespace has no such
	# collision; the nested tax rows still use frappe._dict for the
	# attribute-style access _classify_foreign_tax_rows() expects.
	doc = SimpleNamespace(
		taxes=[frappe._dict(row) for row in (doc_data.get("taxes") or [])],
		items=doc_data.get("items") or [],
	)

	classification = _classify_foreign_tax_rows(doc, company_config)
	affected_item_count = sum(1 for amount in classification["item_discounts"].values() if amount)

	rows = []
	for row in classification["foreign_rows"]:
		if flt(row.tax_amount) > 0:
			rows.append(dict(
				account_head=row.account_head,
				amount=flt(row.tax_amount),
				treatment="taxable_line_item",
				description=_build_synthetic_line_item(row)["description"],
			))
		else:
			rows.append(dict(
				account_head=row.account_head,
				amount=flt(row.tax_amount),
				treatment="discount",
				description=row.description,
				affected_item_count=affected_item_count,
			))

	return {"foreign_rows": rows}


def set_sales_tax(doc, method):
	_ctx = {"doctype": doc.doctype, "name": doc.name, "company": doc.company}

	if not company_calculates_tax(doc.company):
		log_taxjar_call(action="tax_for_order", status="skipped",
			error="taxjar_calculate_tax is disabled", context=_ctx)
		return

	if get_region(doc.company) != "United States":
		log_taxjar_call(action="tax_for_order", status="skipped",
			error="Company region is not United States", context=_ctx)
		return

	if not doc.items:
		log_taxjar_call(action="tax_for_order", status="skipped",
			error="Document has no items", context=_ctx)
		return

	company_config = get_company_config(doc.company)
	if not company_config:
		log_taxjar_call(action="tax_for_order", status="skipped",
			error="No TaxJar Company Config found for company {0}".format(doc.company), context=_ctx)
		return

	is_exempt, exempt_reason = check_sales_tax_exemption(doc, company_config)
	if is_exempt:
		_set_tax_status_fields(doc,
			customer_taxable=False, customer_reason=exempt_reason)
		log_taxjar_call(action="tax_for_order", status="skipped",
			error="Document or customer is exempt from sales tax", context=_ctx)
		return

	if not doc.shipping_address_name and not doc.customer_address:
		if doc.doctype == "Quotation":
			_set_tax_status_fields(doc,
				nexus_reason="No shipping or billing address set")
			log_taxjar_call(action="tax_for_order", status="skipped",
				error="No shipping or billing address set on Quotation", context=_ctx)
			_remove_taxjar_rows(doc, company_config)
			return

		frappe.throw(
			_("Please set a Shipping Address or Billing Address on this transaction before saving."),
			title=_("Address Required"),
		)

	tax_dict = get_tax_data(doc)

	if not tax_dict:
		log_taxjar_call(action="tax_for_order", status="skipped",
			error="No TaxJar payload generated from addresses/items", context=_ctx)
		_remove_taxjar_rows(doc, company_config)
		return

	if not check_for_nexus(doc, tax_dict):
		return

	# TaxJar Settings' own modified timestamp rides along in the key so that
	# saving Settings - a rotated API token, a Sandbox/Live switch, a changed
	# tax account head - busts every cached result immediately. tax_dict never
	# carries anything that identifies which credential produced it, so
	# without this a stale success for the same cart/address (from before the
	# token changed) would keep being served for up to five minutes with no
	# call to TaxJar at all, silently masking a broken token.
	# doc.company rides along too: company_config above resolves a distinct
	# TaxJar credential per company, so two companies whose carts/addresses
	# happen to produce an identical tax_dict must not share a cache entry -
	# that would serve one company's document a tax result computed through
	# the other company's TaxJar account.
	settings_modified = frappe.db.get_single_value("TaxJar Settings", "modified")
	cache_key = "taxjar_tax:" + hashlib.md5(
		json.dumps(
			{"tax_dict": tax_dict, "settings_modified": str(settings_modified), "company": doc.company},
			sort_keys=True, default=str,
		).encode()
	).hexdigest()
	cached = frappe.cache().get_value(cache_key)

	if cached is not None:
		tax_data = cached
	else:
		tax_data = validate_tax_request(tax_dict, company=doc.company)
		if tax_data is not None:
			frappe.cache().set_value(cache_key, tax_data, expires_in_sec=300)
	if tax_data is not None and tax_data.amount_to_collect is not None:
		_remove_taxjar_rows(doc, company_config)

		usd_rate = _get_usd_exchange_rate(doc)
		tax_amount = flt(tax_data.amount_to_collect)
		if usd_rate:
			tax_amount = flt(tax_amount / usd_rate)

		doc.append(
			"taxes",
			{
				"charge_type": "Actual",
				"description": TAXJAR_ROW_DESCRIPTION,
				"account_head": company_config.tax_account_head,
				"tax_amount": tax_amount,
			},
		)

		for item in (tax_data.breakdown.line_items if tax_data.breakdown else []):
			idx = cint(item.id) - 1
			if 0 <= idx < len(doc.items):
				tc = flt(item.tax_collectable)
				if usd_rate:
					tc = flt(tc / usd_rate)
				doc.get("items")[idx].tax_collectable = tc

		_store_breakdown_data(tax_data, doc, usd_rate=usd_rate)

		product_status, product_reason = _compute_product_taxable(doc, tax_data, usd_rate)
		to_state = tax_dict.get("to_state", "")
		# The status matrix reports what the CUSTOMER MASTER says, not the
		# effective outcome: a transaction-level override used to flip this to
		# "No", hiding the fact that the customer themselves is taxable. The
		# override is a separate, visible fact (taxjar_transaction_exempt), and
		# the card appends it rather than replacing the answer.
		#
		# This is display only - _get_effective_exemption() still decides what is
		# actually sent to TaxJar, and its precedence is unchanged.
		customer_exemption_type = _get_customer_exemption_type(doc)
		customer_taxable = not customer_exemption_type
		if customer_exemption_type:
			customer_reason = f"Customer is exempt ({customer_exemption_type})"
		elif _has_transaction_exemption(doc):
			customer_reason = "Taxable, but transaction is marked as exempt"
		else:
			customer_reason = "Taxable"
		_set_tax_status_fields(doc,
			has_nexus=True,
			nexus_reason=f"Nexus in {to_state}" if to_state else "Nexus in destination state",
			customer_taxable=customer_taxable, customer_reason=customer_reason,
			product_taxable=product_status, product_reason=product_reason,
			ship_from=_format_address_short(tax_dict, "from"),
			ship_to=_format_address_short(tax_dict, "to"),
			freight_taxable=bool(tax_data.freight_taxable),
			# "" not None: _set_tax_status_fields skips None, so a document that
			# was sourced once and now calculates without a tax_source would
			# keep the old value. The empty string clears it.
			tax_source=(tax_data.tax_source or ""),
		)

		doc.run_method("calculate_taxes_and_totals")
		doc.run_method("set_total_in_words")


def validate_return_against(doc, method):
	"""Enforce return_against on credit notes when TaxJar transaction reporting is enabled."""
	if not getattr(doc, "is_return", False):
		return
	if not company_creates_transactions(doc.company):
		return
	if not doc.return_against:
		frappe.throw(
			_(
				"Return Against is mandatory for credit notes when TaxJar transaction reporting is enabled. "
				"Please link the original Sales Invoice."
			),
			title=_("TaxJar: Missing Return Reference"),
		)


def _remove_taxjar_rows(doc, company_config):
	"""Remove all sales tax rows owned by TaxJar for this company and recalculate totals."""
	doc.taxes = [
		tax for tax in doc.taxes
		if tax.account_head != company_config.tax_account_head
	]
	_clear_breakdown_data(doc)
	doc.run_method("calculate_taxes_and_totals")
	doc.run_method("set_total_in_words")


def _clear_breakdown_data(doc):
	if hasattr(doc, "taxjar_breakdown_json"):
		doc.taxjar_breakdown_json = None
	if hasattr(doc, "taxjar_freight_taxable"):
		doc.taxjar_freight_taxable = 0
	# tax_collectable is read back as the per-line sales_tax on create_order, and
	# is read_only - left behind it shows tax on every line of a document that
	# now carries none (exempt customer, no nexus, TaxJar switched off) with no
	# way for the user to correct it.
	for item in (doc.get("items") or []):
		if hasattr(item, "tax_collectable"):
			item.tax_collectable = 0


def _set_tax_status_fields(doc, *, has_nexus=None, nexus_reason=None,
                           customer_taxable=None, customer_reason=None,
                           product_taxable=None, product_reason=None,
                           ship_from=None, ship_to=None, freight_taxable=None,
                           tax_source=None):
	"""Populate persistent TaxJar status fields on a transaction document."""
	_pairs = [
		("taxjar_has_nexus", 1 if has_nexus else 0 if has_nexus is not None else None),
		("taxjar_nexus_reason", nexus_reason),
		("taxjar_customer_taxable", 1 if customer_taxable else 0 if customer_taxable is not None else None),
		("taxjar_customer_taxable_reason", customer_reason),
		("taxjar_product_taxable", product_taxable),
		("taxjar_product_taxable_reason", product_reason),
		("taxjar_ship_from", ship_from),
		("taxjar_ship_to", ship_to),
		("taxjar_freight_taxable", 1 if freight_taxable else 0 if freight_taxable is not None else None),
		("taxjar_tax_source", tax_source),
	]
	for field, value in _pairs:
		if value is not None and hasattr(doc, field):
			setattr(doc, field, value)


def _format_address_short(tax_dict, prefix):
	"""Return 'City, STATE ZIP' from tax_dict keys with the given prefix (from/to)."""
	city = tax_dict.get(f"{prefix}_city") or ""
	state = tax_dict.get(f"{prefix}_state") or ""
	zipcode = tax_dict.get(f"{prefix}_zip") or ""
	parts = [p for p in [city, state] if p]
	result = ", ".join(parts)
	if zipcode:
		result += " " + zipcode
	return result.strip()


def _compute_product_taxable(doc, tax_data, usd_rate=None):
	"""Return (status, reason) for product taxability, read back from TaxJar's
	own per-line taxable_amount rather than guessed from the item's tax
	category code - a real exemption category (e.g. "81100" for books) looks
	just like an ordinary taxable one by code alone, but TaxJar has already
	worked out, per line and per jurisdiction, how much of it was taxable."""
	total = len(doc.items)
	if not total:
		return "", ""

	taxable_by_idx = {}
	for line in (tax_data.breakdown.line_items if (tax_data and tax_data.breakdown) else []):
		idx = cint(line.id) - 1
		if 0 <= idx < total:
			taxable_amount = flt(line.taxable_amount)
			if usd_rate:
				taxable_amount = flt(taxable_amount / usd_rate)
			taxable_by_idx[idx] = taxable_amount

	taxable_count = 0
	for idx, item in enumerate(doc.items):
		net_amount = flt(item.get("net_amount"))
		if taxable_by_idx.get(idx, 0) >= net_amount - 0.01:
			taxable_count += 1

	if taxable_count == total:
		return "Yes", f"{taxable_count} of {total} items taxable"
	elif taxable_count == 0:
		return "No", f"0 of {total} items taxable"
	else:
		return "Partially", f"{taxable_count} of {total} items taxable"


def _extract_breakdown_from_obj(obj, item_amount=None):
	"""Extract jurisdiction rows from a TaxJar breakdown or line_item object.

	Works for both transaction-level (TaxJarBreakdown) and per-item
	(TaxJarBreakdownLineItem) objects. The attribute naming differs between
	the two (e.g. state_tax_collectable vs state_amount, state_tax_rate vs
	state_sales_tax_rate), so we select the correct attribute set based on
	whether item_amount is provided (line item) or not (transaction).
	"""
	rows = []
	is_line_item = item_amount is not None

	# US jurisdictions — attribute names differ between transaction and line item
	_us_jurisdictions = [
		("State", "state_taxable_amount",
		 "state_sales_tax_rate" if is_line_item else "state_tax_rate",
		 "state_amount" if is_line_item else "state_tax_collectable"),
		("County", "county_taxable_amount", "county_tax_rate",
		 "county_amount" if is_line_item else "county_tax_collectable"),
		("City", "city_taxable_amount", "city_tax_rate",
		 "city_amount" if is_line_item else "city_tax_collectable"),
		("Special", "special_district_taxable_amount", "special_tax_rate",
		 "special_district_amount" if is_line_item else "special_district_tax_collectable"),
	]
	for label, taxable_attr, rate_attr, tax_attr in _us_jurisdictions:
		taxable = flt(getattr(obj, taxable_attr, 0))
		rate = flt(getattr(obj, rate_attr, 0))
		tax_amt = flt(getattr(obj, tax_attr, 0))
		if taxable or rate or tax_amt:
			row = {"jurisdiction": label, "rate": rate, "tax_amount": tax_amt}
			if is_line_item:
				row["taxable_amount"] = taxable
				row["exempt_or_non_taxable"] = flt(item_amount - taxable)
			rows.append(row)

	# Canadian GST/PST/QST — same attribute names for both levels
	_ca_jurisdictions = [
		("GST", "gst_taxable_amount", "gst_tax_rate", "gst"),
		("PST", "pst_taxable_amount", "pst_tax_rate", "pst"),
		("QST", "qst_taxable_amount", "qst_tax_rate", "qst"),
	]
	for label, taxable_attr, rate_attr, tax_attr in _ca_jurisdictions:
		taxable = flt(getattr(obj, taxable_attr, 0))
		rate = flt(getattr(obj, rate_attr, 0))
		tax_amt = flt(getattr(obj, tax_attr, 0))
		if taxable or rate or tax_amt:
			row = {"jurisdiction": label, "rate": rate, "tax_amount": tax_amt}
			if is_line_item:
				row["taxable_amount"] = taxable
				row["exempt_or_non_taxable"] = flt(item_amount - taxable)
			rows.append(row)

	# Country-level (EU / AU) — same attribute names for both levels
	country_taxable = flt(getattr(obj, "country_taxable_amount", 0))
	country_rate = flt(getattr(obj, "country_tax_rate", 0))
	country_tax = flt(getattr(obj, "country_tax_collectable", 0))
	if country_taxable or country_rate or country_tax:
		row = {"jurisdiction": "Country", "rate": country_rate, "tax_amount": country_tax}
		if is_line_item:
			row["taxable_amount"] = country_taxable
			row["exempt_or_non_taxable"] = flt(item_amount - country_taxable)
		rows.append(row)

	return rows


def _extract_breakdown_data(tax_data, doc):
	"""Build structured breakdown dict from a TaxJar tax_for_order response."""
	breakdown = tax_data.breakdown
	if not breakdown:
		return None

	transaction_rows = _extract_breakdown_from_obj(breakdown)
	jurisdictions = tax_data.jurisdictions
	if jurisdictions and transaction_rows:
		# TaxJar's jurisdictions object carries no equivalent "special" field -
		# special districts (transit, tourism, Mello-Roos, etc.) often overlap
		# without one clean place name, so there's nothing authentic to show here.
		# A static label beats a blank cell that reads like missing data.
		name_map = {"State": jurisdictions.state, "County": jurisdictions.county,
		            "City": jurisdictions.city, "Special": "SPECIAL DISTRICT"}
		for row in transaction_rows:
			row["name"] = name_map.get(row["jurisdiction"], "")

	result = {
		"transaction": transaction_rows,
		"totals": {
			"rate": flt(tax_data.rate),
			"amount_to_collect": flt(tax_data.amount_to_collect),
			"taxable_amount": flt(tax_data.taxable_amount),
		},
		"line_items": [],
	}

	for li in (breakdown.line_items or []):
		item_idx = cint(li.id) - 1
		item_amount = 0
		if 0 <= item_idx < len(doc.items):
			item = doc.items[item_idx]
			item_amount = flt(item.get("qty")) * flt(item.get("rate"))

		li_rows = _extract_breakdown_from_obj(li, item_amount=item_amount)
		result["line_items"].append({
			"id": li.id,
			"tax_collectable": flt(li.tax_collectable),
			"taxable_amount": flt(li.taxable_amount),
			"item_amount": item_amount,
			"breakdown": li_rows,
		})

	return result


def _convert_breakdown_amounts(data, usd_rate):
	"""Convert monetary amounts in a breakdown dict from USD to transaction currency."""
	rate = usd_rate

	def _convert_rows(rows):
		converted = []
		for r in rows:
			cr = dict(r)
			cr["tax_amount"] = flt(r["tax_amount"] / rate)
			if "taxable_amount" in r:
				cr["taxable_amount"] = flt(r["taxable_amount"] / rate)
			if "exempt_or_non_taxable" in r:
				cr["exempt_or_non_taxable"] = flt(r["exempt_or_non_taxable"] / rate)
			converted.append(cr)
		return converted

	result = {
		"transaction": _convert_rows(data["transaction"]),
		"totals": {
			"rate": data["totals"]["rate"],
			"amount_to_collect": flt(data["totals"]["amount_to_collect"] / rate),
			"taxable_amount": flt(data["totals"]["taxable_amount"] / rate),
		},
		"line_items": [],
	}
	for li in data.get("line_items", []):
		result["line_items"].append({
			"id": li["id"],
			"tax_collectable": flt(li["tax_collectable"] / rate),
			"taxable_amount": flt(li["taxable_amount"] / rate),
			"item_amount": flt(li["item_amount"] / rate),
			"breakdown": _convert_rows(li["breakdown"]),
		})
	return result


def _store_breakdown_data(tax_data, doc, usd_rate=None):
	"""Extract breakdown from tax_data and store JSON on doc and items."""
	usd_data = _extract_breakdown_data(tax_data, doc)
	if not usd_data:
		return

	currency = getattr(doc, "currency", None) or "USD"

	if usd_rate:
		converted = _convert_breakdown_amounts(usd_data, usd_rate)
		breakdown_data = {
			"currency": currency,
			"base_currency": "USD",
			"exchange_rate": usd_rate,
			"exchange_date": str(_get_transaction_date(doc)),
			**converted,
			"usd": {
				"transaction": usd_data["transaction"],
				"totals": usd_data["totals"],
				"line_items": usd_data["line_items"],
			},
		}
	else:
		breakdown_data = {
			"currency": "USD",
			**usd_data,
		}

	if hasattr(doc, "taxjar_breakdown_json"):
		doc.taxjar_breakdown_json = json.dumps(breakdown_data)


def get_taxjar_breakdown_html(doc):
	"""Render the TaxJar Tax Breakdown table (plus, for multi-currency docs,
	the USD sub-table above it) from doc.taxjar_breakdown_json.

	Server-side Jinja render, same tax-break-up / table-bordered / table-hover
	markup as core ERPNext's own Tax Breakup table (get_itemised_tax_breakup_html
	in erpnext.controllers.taxes_and_totals) and india_compliance's GST Breakup
	Table (GSTBreakup in india_compliance.gst_india.utils.jinja) - both render
	their tables server-side rather than in the browser, which is also what
	makes them show up in Print/PDF.

	The shipping-taxability pill is a separate, plain-HTML field
	(taxjar_freight_taxable_html, rendered client-side) rather than part of
	this content - a Text Editor field wraps whatever is here in a boxed
	"like-disabled-input" background, which reads fine for a table but not
	for a standalone indicator.
	"""
	data = None
	if getattr(doc, "taxjar_breakdown_json", None):
		try:
			data = json.loads(doc.taxjar_breakdown_json)
		except (TypeError, ValueError):
			data = None

	# The template path is a literal in this repo, never caller-supplied.
	# nosemgrep: frappe-ssti
	html = frappe.render_template(
		"templates/includes/taxjar_breakup.html",
		dict(
			data=data,
			currency=(data or {}).get("currency") or getattr(doc, "currency", None) or "USD",
			# With no nexus there is no breakdown to render and never will be,
			# so the empty state says why rather than reporting an absence.
			# nexus_reason already reads "No nexus in NJ" (see set_sales_tax).
			no_nexus_reason=(
				getattr(doc, "taxjar_nexus_reason", None)
				if not getattr(doc, "taxjar_has_nexus", None)
				else None
			),
		),
	)
	# Jinja's {% if/for %} control tags leave behind their surrounding blank
	# lines/indentation in the output; a Text Editor field renders that
	# whitespace as real vertical gaps. Same fix india_compliance applies to
	# its own gst_breakup_table render (set_gst_breakup in
	# india_compliance.gst_india.overrides.transaction).
	return html.replace("\n", "").replace("\t", "")


def set_taxjar_breakdown_html(doc, method=None, print_settings=None):
	"""onload / before_print doc event: populate the taxjar_breakdown_html
	virtual field.

	Desk form (onload): pushed via set_onload, since the browser already holds
	a separate copy of the doc by the time this runs - a thin client-side
	shim (render_tax_breakdown in taxjar_utils.js) copies it onto the field.
	Print/PDF (before_print): assigned directly onto doc, since print rendering
	reads this same in-memory object in the same request - see frappe.www.printview.
	"""
	if not doc.meta.has_field("taxjar_breakdown_html"):
		return
	html = get_taxjar_breakdown_html(doc)
	if method == "before_print":
		doc.taxjar_breakdown_html = html
	else:
		doc.set_onload("_taxjar_breakdown_html", html)


def check_for_nexus(doc, tax_dict):
	"""Return True if the delivery is within a nexus. Clears TaxJar rows and returns False if not."""
	company_config = get_company_config(doc.company)
	in_nexus = frappe.db.get_value(
		"TaxJar Nexus",
		filters={"region_code": tax_dict["to_state"], "parent": "TaxJar Settings", "company": doc.company},
	)

	if not in_nexus:
		if company_config:
			_remove_taxjar_rows(doc, company_config)
		to_state = tax_dict.get("to_state", "")
		_set_tax_status_fields(
			doc,
			has_nexus=False,
			nexus_reason=f"No nexus in {to_state}" if to_state else "No nexus in destination state",
			ship_from=_format_address_short(tax_dict, "from"),
			ship_to=_format_address_short(tax_dict, "to"),
		)
		return False

	return True


def check_sales_tax_exemption(doc, company_config):
	"""Return (is_exempt, reason) tuple. Removes TaxJar rows if exempt.

	State-specific exemptions (via TaxJar Customer API exempt_regions) are NOT
	handled here — they flow through to TaxJar via customer_id in the API payload.
	"""
	doc_exempt = hasattr(doc, "exempt_from_sales_tax") and doc.exempt_from_sales_tax

	customer_name = _get_customer_name(doc)
	customer_exempt = False
	exemption_type = None
	if not doc_exempt and customer_name:
		fields = [
			f for f in ("exempt_from_sales_tax", "taxjar_exemption_type")
			if frappe.db.has_column("Customer", f)
		]
		if fields:
			values = frappe.db.get_value(
				"Customer", customer_name, fields, as_dict=True, cache=True
			) or {}
			customer_exempt = values.get("exempt_from_sales_tax")
			if customer_exempt:
				exemption_type = values.get("taxjar_exemption_type")

	if doc_exempt:
		_remove_taxjar_rows(doc, company_config)
		return True, "Document is marked exempt from sales tax"

	if customer_exempt:
		_remove_taxjar_rows(doc, company_config)
		reason = "Customer is exempt"
		if exemption_type:
			reason = f"Customer is exempt ({exemption_type})"
		return True, reason

	return False, None


def _get_customer_exemption_type(doc):
	"""Return the customer's master exemption type where it applies to THIS
	document's destination, else None.

	Feeds both the "Is the customer taxable?" card and, via
	_get_effective_exemption(), the exemption_type sent to TaxJar. Region
	scoping lives in _customer_master_exemption() - see its docstring for why
	the destination matters.
	"""
	return _customer_master_exemption(_get_customer_name(doc), _destination_address(doc))[0]


def _has_transaction_exemption(doc):
	"""Whether the per-transaction override is both ticked and given a reason.

	The reason is mandatory alongside the checkbox, but a doc can be inspected
	mid-edit, so both are required before the override counts as real.
	"""
	return bool(
		getattr(doc, "taxjar_transaction_exempt", None)
		and getattr(doc, "taxjar_transaction_exemption_type", None)
	)


def _destination_address(doc):
	"""Ship-to if set, else bill-to - the same fallback get_shipping_address_details
	uses to decide where the sale is taxed."""
	return getattr(doc, "shipping_address_name", None) or getattr(doc, "customer_address", None)


def _address_state(address):
	"""Destination state code for an Address, or None if it cannot be read."""
	if not address or not frappe.db.exists("Address", address):
		return None
	row = frappe.db.get_value("Address", address, ["taxjar_state_code", "state"], as_dict=True) or {}
	return (row.get("taxjar_state_code") or row.get("state") or "").strip().upper() or None


def _customer_master_exemption(customer, address=None):
	"""Return (exemption_type, state) for the customer's master exemption where
	it applies to this destination, else (None, None).

	Region-scoped, because a customer can be exempt in some states and not
	others (taxjar_exempt_regions). TaxJar applies that scoping itself off the
	matched customer_id, so this exists to agree with it: without it a customer
	exempt only in Florida read as exempt on a New Jersey sale, which both
	mis-stated the status matrix and suppressed the per-transaction override
	that should have taken over there (see _get_effective_exemption).

	No regions listed means exempt everywhere - that is how TaxJar reads an
	empty exempt_regions. A destination we cannot read falls back the same way,
	deliberately: better to keep honouring a customer's standing exemption than
	to start taxing them because an address is missing a state.
	"""
	if not customer or not frappe.db.has_column("Customer", "taxjar_exemption_type"):
		return None, None

	exemption_type = frappe.db.get_value("Customer", customer, "taxjar_exemption_type", cache=True)
	if not exemption_type or exemption_type == "Non Exempt":
		return None, None

	regions = [
		(r.state or "").strip().upper()
		for r in frappe.get_all(
			"TaxJar Customer Exempt Region",
			filters={"parent": customer, "parenttype": "Customer"},
			fields=["state"],
		)
	]
	if not regions:
		return exemption_type, None

	destination = _address_state(address)
	if not destination:
		return exemption_type, None

	if destination in regions:
		return exemption_type, destination

	return None, None


@frappe.whitelist()
def get_region_exemption(customer: str, address: str | None = None):
	"""Whether the customer's master exemption covers this destination.

	Read by the form (apply_region_exemption in taxjar_utils.js) to pre-set and
	lock the per-transaction override, so a sale that is already exempt says so
	before it is saved. Changes no tax on its own.
	"""
	frappe.has_permission("Customer", "read", doc=customer, throw=True)

	exemption_type, state = _customer_master_exemption(customer, address)
	if not exemption_type:
		return {}

	return {"exemption_type": exemption_type, "state": state}


def _get_effective_exemption(doc):
	"""Return (exemption_type, source) describing which exemption applies to
	this document, or (None, None) if neither does.

	The customer's own master-level exemption_type always takes precedence
	when set - this mirrors TaxJar's own documented precedence rule for its
	tax_for_order/transaction endpoints (a matched customer's exemption_type
	overrides whatever order-level exemption_type is sent, unless the
	customer's own type is "non_exempt"). The transaction-level override
	(taxjar_transaction_exempt/taxjar_transaction_exemption_type) only matters
	when the customer has no active exemption on file - exactly the case
	where TaxJar would otherwise have nothing to base an exemption on, e.g. a
	customer never synced to TaxJar's Customer API, or one whose master
	record is explicitly "Non Exempt" but needs a one-off exempt transaction.
	"""
	customer_exemption_type = _get_customer_exemption_type(doc)
	if customer_exemption_type:
		return customer_exemption_type, "customer"

	if getattr(doc, "taxjar_transaction_exempt", None):
		transaction_exemption_type = getattr(doc, "taxjar_transaction_exemption_type", None)
		if transaction_exemption_type:
			return transaction_exemption_type, "transaction"

	return None, None


def validate_tax_request(tax_dict, company=None):
	"""Return the sales tax that should be collected for a given order."""

	client = get_client(company)

	if not client:
		log_taxjar_call(action="tax_for_order", status="skipped", error="TaxJar client is not configured")
		return

	try:
		log_taxjar_call(action="tax_for_order", status="request", payload=tax_dict)
		tax_data = client.tax_for_order(tax_dict)
	except taxjar.exceptions.TaxJarConnectionError:
		log_taxjar_call(
			action="tax_for_order",
			status="error",
			payload=tax_dict,
			error="TaxJar API is unreachable",
		)
		frappe.msgprint(
			_("TaxJar API is unreachable. Tax has not been calculated for this document."),
			indicator="orange",
			alert=True,
		)
		return None
	except taxjar.exceptions.TaxJarResponseError as err:
		log_taxjar_call(
			action="tax_for_order",
			status="error",
			payload=tax_dict,
			error=getattr(err, "full_response", str(err)),
		)
		frappe.throw(_linkify_guided_setup(_(sanitize_error_response(err))))
	except Exception:
		log_taxjar_call(
			action="tax_for_order",
			status="error",
			payload=tax_dict,
			error=traceback.format_exc(),
		)
		raise
	else:
		log_taxjar_call(action="tax_for_order", status="success", payload=tax_dict, response=tax_data)
		return tax_data


def get_company_address_details(doc):
	"""Return company address details for the invoice's company."""
	from erpnext import get_default_company

	company = doc.company if hasattr(doc, "company") and doc.company else get_default_company()

	company_address = get_company_address(company).company_address

	if not company_address:
		frappe.throw(_("Please set a default address for the company {0}.").format(company))

	return frappe.get_doc("Address", company_address)


@frappe.whitelist()
def check_nexus(shipping_address_name: str):
	if not isinstance(shipping_address_name, str) or not shipping_address_name.strip():
		return

	if not _is_taxjar_enabled():
		return

	if not frappe.db.exists("Address", shipping_address_name):
		return

	# After the existence guard, not before it: a doc-level check on a name that
	# does not exist raises DoesNotExistError, and this is called on every
	# shipping_address_name change, where a stale link should stay a quiet
	# no-op rather than an error dialog.
	frappe.has_permission("Address", "read", doc=shipping_address_name, throw=True)

	try:
		address = frappe.get_doc("Address", shipping_address_name)
		state_code = get_iso_3166_2_state_code(address)

		if not frappe.db.get_value("TaxJar Nexus", filters={"region_code": state_code, "parent": "TaxJar Settings"}):
			return {"state": address.state, "state_code": state_code}
	except Exception:
		return


@frappe.whitelist()
def get_customer_addresses(customer: str):
	frappe.has_permission("Address", "read", throw=True)
	return frappe.get_all(
		"Address",
		filters=[
			["Dynamic Link", "link_doctype", "=", "Customer"],
			["Dynamic Link", "link_name", "=", customer],
			["disabled", "=", 0],
		],
		fields=[
			"name", "address_title", "address_line1", "city", "state",
			"pincode", "country", "address_type", "is_shipping_address",
			"is_primary_address",
		],
		order_by="is_shipping_address DESC, is_primary_address DESC",
	)


@frappe.whitelist(methods=["POST"])
def mark_address_as_shipping(address_name: str):
	address = frappe.get_doc("Address", address_name)
	address.check_permission("write")
	address.is_shipping_address = 1
	address.save()


def get_shipping_address_details(doc):
	"""Return customer shipping address details"""

	if doc.shipping_address_name:
		shipping_address = frappe.get_doc("Address", doc.shipping_address_name)
	elif doc.customer_address:
		shipping_address = frappe.get_doc("Address", doc.customer_address)
	else:
		frappe.throw(
			_("No Shipping Address or Billing Address is set on this transaction. "
			  "Please add an address to the Customer and select it on the transaction."),
			title=_("Address Required"),
		)

	return shipping_address


def get_iso_3166_2_state_code(address):
	import pycountry

	# Prefer the explicit TaxJar state code field when present (avoids pycountry guessing).
	taxjar_code = address.get("taxjar_state_code")
	if taxjar_code and taxjar_code in SUPPORTED_STATE_CODES:
		return taxjar_code

	state = address.get("state")
	if not state:
		frappe.throw(_("Please enter a valid State in the address"))

	country_code = frappe.db.get_value("Country", address.get("country"), "code", cache=True)

	error_message = _(
		"""{0} is not a valid state! Check for typos or enter the ISO code for your state."""
	).format(state)
	state = state.upper().strip()

	# The max length for ISO state codes is 3, excluding the country code
	if len(state) <= 3:
		# PyCountry returns state code as {country_code}-{state-code} (e.g. US-FL)
		address_state = (country_code + "-" + state).upper()

		states = pycountry.subdivisions.get(country_code=country_code.upper())
		states = [pystate.code for pystate in states]

		if address_state in states:
			return state

		frappe.throw(_(error_message))
	else:
		try:
			lookup_state = pycountry.subdivisions.lookup(state)
		except LookupError:
			frappe.throw(_(error_message))
		else:
			return lookup_state.code.split("-")[1]


def validate_address(doc, method):
	"""Enforce mandatory address fields for US and Canadian addresses."""
	if not doc.country:
		return

	country_code = (frappe.db.get_value("Country", doc.country, "code", cache=True) or "").upper()

	if country_code in ("US", "CA"):
		if not doc.state:
			frappe.throw(_("State/Province is mandatory for {0} addresses.").format(doc.country))

	if country_code == "US":
		if not doc.get("taxjar_state_code"):
			frappe.throw(_("State Code is mandatory for United States addresses."))
		if not doc.pincode:
			frappe.throw(_("Postal Code is mandatory for United States addresses."))

		if _is_taxjar_enabled():
			_validate_address_with_taxjar(doc)


def _is_taxjar_enabled(settings=None):
	"""Return whether TaxJar is active at all: the master switch is on AND at least
	one company has a feature (calculate tax / create transactions) enabled.

	Feature flags are per-company (on the TaxJar Company Config rows); this "any
	company" gate is for concerns that are not company-scoped — Item field
	visibility, Address validation and Customer sync. Pass an already-loaded TaxJar
	Settings doc to read from it directly.
	"""
	if settings is None:
		# Cheap master-switch short-circuit before loading the full single doc.
		if not cint(frappe.db.get_single_value("TaxJar Settings", "taxjar_enabled")):
			return False
		settings = frappe.get_single("TaxJar Settings")
	elif not settings.taxjar_enabled:
		return False
	return any(
		config.taxjar_calculate_tax or config.taxjar_create_transactions
		for config in (settings.company_config or [])
	)


def company_calculates_tax(company, config=None):
	"""Whether sales-tax calculation is on for a company (master switch AND the
	company's own Calculate Sales Tax flag)."""
	if not cint(frappe.db.get_single_value("TaxJar Settings", "taxjar_enabled")):
		return False
	if config is None:
		config = get_company_config(company)
	return bool(config and config.taxjar_calculate_tax)


def company_creates_transactions(company, config=None):
	"""Whether transaction filing is on for a company (master switch AND the
	company's own File Transactions flag)."""
	if not cint(frappe.db.get_single_value("TaxJar Settings", "taxjar_enabled")):
		return False
	if config is None:
		config = get_company_config(company)
	return bool(config and config.taxjar_create_transactions)


@frappe.whitelist()
def is_taxjar_enabled_for_company(company: str):
	"""Live read for the sidebar sync-status pill (see render_sync_status_sidebar_pill
	in taxjar_utils.js) - checked on every form refresh rather than cached on the
	transaction doc, since a stored flag would go stale for a Draft left unsaved
	or a Cancelled doc (which is never saved again) after the company's TaxJar
	config changes.
	"""
	frappe.has_permission("Sales Invoice", "read", throw=True)
	return company_creates_transactions(company)


def _validate_address_with_taxjar(doc):
	"""Call TaxJar's address validation endpoint for US addresses.

	A found address (or a normalized/standardized suggestion of one) is a
	silent pass - no dialog. An address TaxJar can't resolve blocks the save:
	confirmed via the local taxjar package and taxjar-ruby's own SDK fixtures
	that a 2xx with an empty "addresses" array is how "no match" is reported
	(not an HTTP error), but a literal 404 is handled the same way too since
	that isn't documented publicly and either is plausible. Any other error
	(401/422/5xx, connection issues) is not this address's fault, so it
	doesn't block the save - same tolerant handling as before.
	"""
	client = get_client()
	if not client:
		return

	address_data = {
		"country": "US",
		"state": doc.get("taxjar_state_code") or "",
		"zip": doc.pincode or "",
		"city": doc.city or "",
		"street": doc.address_line1 or "",
	}

	ctx = {"doctype": "Address", "name": doc.name}

	try:
		log_taxjar_call(action="validate_address", status="request", payload=address_data, context=ctx)
		result = client.validate_address(address_data)
		log_taxjar_call(action="validate_address", status="success", payload=address_data, response=result, context=ctx)
	except taxjar.exceptions.TaxJarConnectionError:
		log_taxjar_call(action="validate_address", status="error", error="TaxJar API is unreachable", context=ctx)
		return
	except taxjar.exceptions.TaxJarResponseError as err:
		full = getattr(err, "full_response", {}) or {}
		status_code = full.get("status_code") if isinstance(full, dict) else None
		log_taxjar_call(action="validate_address", status="error", error=getattr(err, "full_response", str(err)), context=ctx)
		if status_code == 404:
			_throw_invalid_address()
		return
	except Exception:
		log_taxjar_call(action="validate_address", status="error", error=traceback.format_exc(), context=ctx)
		return

	matches = list(result) if hasattr(result, "__iter__") else []
	if not matches:
		_throw_invalid_address()


def _throw_invalid_address():
	"""TaxJar found no real-world match for this address. Its "no match"
	response carries no further reason to pass on.

	Not reusing _describe_response_error()/classify_taxjar_error() here:
	their 404 wording ("Transaction not found in TaxJar") is specific to the
	transaction-sync endpoints and would be actively misleading for an
	address that was simply never found, not a transaction gone missing.
	"""
	frappe.throw(
		_("The given address is not valid, please reverify the street, city, state, or postal code."),
		title=_("Invalid Address"),
	)


def _get_customer_name(doc):
	"""Return the Customer name for a transaction document, or None."""
	if doc.doctype == "Quotation":
		if getattr(doc, "quotation_to", None) == "Customer":
			return doc.party_name
		return None
	return getattr(doc, "customer", None)


def _get_taxjar_customer_id(doc):
	"""Return the customer_id to send TaxJar for this document's customer.

	Must match whatever sync_customer_to_taxjar() actually stored on TaxJar
	(Customer.taxjar_customer_id, normalized via _make_safe_customer_id) - not
	the raw ERPNext customer name. TaxJar matches a transaction against its
	stored customer record (and that customer's exempt_regions) by exact
	customer_id, so sending the unnormalized name (e.g. "Alan Houk" instead of
	the synced "Alan-Houk") silently misses the match and the customer's
	exemption is never applied - tax gets calculated as if they had none.
	"""
	customer_name = _get_customer_name(doc)
	if not customer_name:
		return None
	taxjar_customer_id = frappe.db.get_value("Customer", customer_name, "taxjar_customer_id")
	return taxjar_customer_id or _make_safe_customer_id(customer_name)


# ── TaxJar error classification ──────────────────────────────────────────────

# python-taxjar collapses every failure into four exception classes
# (taxjar/exceptions.py) and carries no status-code table of its own, so the
# taxonomy below is ours. The status it does surface is the one TaxJar puts in
# the JSON error body ("status"), which TaxJarResponse.raise_response_error()
# re-exposes as full_response["status_code"] - not the HTTP status line.
#
# Retryable means "this exact request could succeed later, unchanged": transport
# failures, rate limiting, and TaxJar-side outages. Everything else needs a human
# to change something first, and re-sending it on a timer only burns API quota
# while rewriting the document's Sync Error with the same text - a duplicate
# transaction_id is never going to stop being a duplicate. retry_failed_taxjar_syncs()
# only picks up documents this classification flagged retryable.
TAXJAR_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

# Ceiling on how many times the 15-min cron will re-enqueue the same document.
# taxjar_sync_retry_count/taxjar_customer_sync_retry_count count consecutive
# Failed outcomes (any source - initial attempt, cron, or a manual Retry) and
# reset to 0 on the next non-Failed status; retry_failed_taxjar_syncs() and
# retry_failed_taxjar_customer_syncs() (tasks.py) stop picking a document up
# once its count reaches this, so a document TaxJar keeps rejecting doesn't
# get re-sent forever. The Retry buttons on the Transactions/Customers pages
# are unaffected - a human asking for it explicitly can always retry again.
TAXJAR_MAX_SYNC_RETRIES = 5

TAXJAR_STATUS_MESSAGES = {
	400: "TaxJar rejected the request as malformed",
	403: "This TaxJar account is not allowed to make that request",
	405: "TaxJar rejected the request method",
	406: "TaxJar cannot answer in the requested format",
	410: "This resource has been removed from TaxJar",
	422: "TaxJar could not process the request",
	429: "TaxJar's API rate limit was reached",
	500: "TaxJar hit an internal server error",
	502: "TaxJar is temporarily unreachable",
	503: "TaxJar is temporarily offline for maintenance",
	504: "TaxJar took too long to respond",
}

# Kept separate from the headline so the same wording serves the background sync
# (where the hint lands in Sync Error) and the interactive throw paths. Only for
# failures with something to act on: the transient ones already read as transient,
# and _set_sync_status() adds the retry sentence for them anyway.
_STATUS_HINTS = {
	403: "Check that the TaxJar plan on this account covers this API.",
}

# Statuses whose own detail never adds anything a user can act on, so the whole
# message is ours.
_FIXED_STATUS_MESSAGES = {
	401: "TaxJar API Token is invalid, go to guided setup to configure.",
	404: "Transaction not found in TaxJar, can't update the latest changes.",
}

# The two rejections this integration hits most often, both close to unreadable
# in TaxJar's own words. Matched against the raw detail, before relabelling.
_DETAIL_OVERRIDES = (
	(
		("already imported", "already exists"),
		"Transaction ID already exists in TaxJar, please create a new transaction.",
	),
	(
		("exemption_type must be",),
		"Exempt transactions cannot have sales tax, please clear exemption or remove sales tax.",
	),
)

# TaxJar names the offending API field in its error text. Relabelled one field at
# a time rather than by blanket-stripping underscores, which used to mangle the
# values TaxJar quotes back ("non_exempt" -> "non exempt") along with the keys.
_API_FIELD_LABELS = {
	"from_country": "Origin Country",
	"from_zip": "Origin Zipcode",
	"from_state": "Origin State",
	"from_city": "Origin City",
	"from_street": "Origin Street",
	"to_country": "Country",
	"to_zip": "Zipcode",
	"to_state": "State",
	"to_city": "City",
	"to_street": "Street",
	"transaction_reference_id": "Original Transaction ID",
	"transaction_date": "Transaction Date",
	"transaction_id": "Transaction ID",
	"customer_id": "Customer ID",
	"exemption_type": "Exemption Type",
	"exempt_regions": "Exempt Regions",
	"product_tax_code": "Product Tax Code",
	"line_items": "Line Items",
	"unit_price": "Unit Price",
	"sales_tax": "Sales Tax",
}

_API_FIELD_PATTERN = re.compile(
	r"\b(" + "|".join(sorted(_API_FIELD_LABELS, key=len, reverse=True)) + r")\b"
)


def classify_taxjar_error(err):
	"""Describe any exception a TaxJar API call can raise.

	Returns a dict of:

	* ``status`` - the TaxJar status code, or None for failures that never reached
	  a TaxJar response body;
	* ``retryable`` - whether re-sending the identical request could succeed
	  (see TAXJAR_RETRYABLE_STATUS_CODES);
	* ``message`` - one plain sentence for the user, safe to store on a document
	  or hand to frappe.throw();
	* ``log_detail`` - the full technical payload for TaxJar API Log, which is
	  where tracebacks and raw responses belong rather than on the document;
	* ``kind`` - which branch classified it, so callers can decide what also
	  deserves an error-log entry.

	Unrecognised exceptions are deliberately classified non-retryable: a retry
	loop we cannot reason about is worse than one failed document waiting for a
	manual retry.
	"""
	if isinstance(err, taxjar.exceptions.TaxJarConnectionError):
		return {
			"status": None,
			"retryable": True,
			"message": "TaxJar is unreachable - the request timed out or the connection failed.",
			"log_detail": f"TaxJarConnectionError: {err}",
			"kind": "connection",
		}

	if isinstance(err, taxjar.exceptions.TaxJarResponseError):
		full = getattr(err, "full_response", None)
		if not isinstance(full, dict):
			full = {}
		status = cint(full.get("status_code")) or None
		return {
			"status": status,
			"retryable": status in TAXJAR_RETRYABLE_STATUS_CODES,
			"message": _describe_response_error(status, full.get("detail")),
			"log_detail": full or str(err),
			"kind": "response",
		}

	if isinstance(err, frappe.ValidationError):
		# Raised by our own pre-flight checks (get_state_code, address validation),
		# already worded for the user - re-wrapping it would only bury it.
		return {
			"status": None,
			"retryable": False,
			"message": str(err),
			"log_detail": _format_exception(err),
			"kind": "validation",
		}

	if isinstance(err, json.JSONDecodeError):
		# TaxJarResponse.data_from_request() calls request.json() before looking at
		# the status code, so a gateway error page (HTML, or an empty body) never
		# becomes a TaxJarResponseError - it surfaces here. Always transport-level,
		# so always worth retrying.
		return {
			"status": None,
			"retryable": True,
			"message": "TaxJar returned a response that could not be read, which usually means a temporary outage at TaxJar.",
			"log_detail": _format_exception(err),
			"kind": "unreadable",
		}

	return {
		"status": None,
		"retryable": False,
		"message": f"Unexpected error while calling TaxJar: {type(err).__name__}: {err}",
		"log_detail": _format_exception(err),
		"kind": "unknown",
	}


def _describe_response_error(status, detail):
	"""Turn a TaxJar error body into one readable, actionable sentence."""
	detail = (detail or "").strip()

	for needles, message in _DETAIL_OVERRIDES:
		if any(needle in detail.lower() for needle in needles):
			return message

	if status in _FIXED_STATUS_MESSAGES:
		return _FIXED_STATUS_MESSAGES[status]

	headline = TAXJAR_STATUS_MESSAGES.get(status) or "TaxJar rejected the request"
	if detail:
		detail = _API_FIELD_PATTERN.sub(lambda m: _API_FIELD_LABELS[m.group(0)], detail)
		if not detail.endswith((".", "!", "?")):
			detail += "."
		message = f"{headline}: {detail}"
	else:
		message = f"{headline}."

	hint = _STATUS_HINTS.get(status)
	return f"{message} {hint}" if hint else message


def _format_exception(err):
	"""Full traceback for the log, without depending on being inside an except
	block the way traceback.format_exc() does."""
	return "".join(traceback.format_exception(type(err), err, err.__traceback__))


def sanitize_error_response(response):
	"""The user-facing half of classify_taxjar_error(), kept under its original
	name for the interactive callers that only ever wanted the sentence."""
	return classify_taxjar_error(response)["message"]


def _linkify_guided_setup(message):
	"""Turn a "guided setup" mention into a real link, for a message about to
	reach the user immediately via frappe.throw() (rendered as HTML, same as
	the client-side taxjar_integration.show_taxjar_sync_error).

	Never apply this to a message before it is stored on
	taxjar_sync_error/taxjar_customer_sync_error - those are plain Small Text
	fields, displayed elsewhere as text, and would show the raw tag.
	"""
	return re.sub(
		r"guided setup", f'<a href="/app/taxjar-setup">{_("guided setup")}</a>', message, flags=re.IGNORECASE
	)


# ── TaxJar Customer API ──────────────────────────────────────────────────────


def _make_safe_customer_id(customer_name):
	"""Generate a URL-safe customer_id from an ERPNext customer name.

	The python-taxjar client concatenates customer_id directly into the URL
	path (e.g. "customers/" + customer_id). Names with spaces or special
	characters break the PUT/DELETE endpoints. This function creates a
	deterministic, URL-safe ID that is consistent between POST body and
	URL path.
	"""
	safe = re.sub(r"[^a-zA-Z0-9]+", "-", str(customer_name))
	return safe.strip("-") or customer_name


_EXEMPTION_TYPE_MAP = {
	"Wholesale": "wholesale",
	"Government": "government",
	"Non Exempt": "non_exempt",
	"Other": "other",
}


def _map_exemption_type(label):
	"""Convert a human-readable exemption label to the TaxJar API value."""
	return _EXEMPTION_TYPE_MAP.get(label, "non_exempt")


def _publish_customer_update(customer_name, status):
	"""Notify the TaxJar Customer Configuration page - same reasoning as
	_publish_transaction_update's docstring, for the Customer doctype room."""
	frappe.publish_realtime(
		"taxjar_customers_update",
		{"name": customer_name, "taxjar_customer_sync_status": status},
		room=get_doctype_room("Customer"),
		after_commit=True,
	)


def _set_customer_sync_status(customer_name, status, error=None, retryable=False):
	"""Update TaxJar sync status fields on a Customer, then notify any open
	form via realtime - same reasoning as _set_sync_status's docstring.
	Reached from on_customer_update (fires on ordinary Customer saves, not
	just a submit/cancel event), the 15-min cron retry, and the Customers
	page's bulk sync. ``retryable`` gates the 15-min cron the same way it does
	for invoices, and so does taxjar_customer_sync_retry_count - see
	_set_sync_status().
	"""
	if error and retryable:
		error = f"{error} Automatic retry is scheduled."

	fields = {
		"taxjar_customer_sync_status": status,
		"taxjar_customer_sync_error": error or "",
		"taxjar_customer_sync_retryable": 1 if status == "Failed" and retryable else 0,
	}
	if status == "Failed":
		prior_count = cint(frappe.db.get_value("Customer", customer_name, "taxjar_customer_sync_retry_count"))
		fields["taxjar_customer_sync_retry_count"] = prior_count + 1
	else:
		fields["taxjar_customer_sync_retry_count"] = 0

	frappe.db.set_value(
		"Customer", customer_name,
		fields,
		update_modified=False,
	)
	frappe.publish_realtime(
		"taxjar_customer_sync_update",
		{"taxjar_customer_sync_status": status},
		doctype="Customer",
		docname=customer_name,
		after_commit=True,
	)
	_publish_customer_update(customer_name, status)


def _record_customer_sync_failure(err, action, payload, ctx, customer_name):
	"""_record_sync_failure() for the Customer API side."""
	info = classify_taxjar_error(err)
	log_taxjar_call(action=action, status="error", payload=payload, error=info["log_detail"], context=ctx)
	if info["kind"] == "unknown":
		_get_taxjar_logger().error(info["log_detail"])
	_set_customer_sync_status(customer_name, "Failed", error=info["message"], retryable=info["retryable"])


@frappe.whitelist(methods=["POST"])
def resync_customer(customer_name: str, company: str | None = None):
	"""Permission-checked entry point for the Customer "Sync to TaxJar" button.

	Inline rather than enqueued, for the same reason as resync_transaction: the
	button reloads the form and reports the resulting sync status. The worker
	below stays un-whitelisted so enqueue callers are unaffected.
	"""
	frappe.has_permission("Customer", "write", doc=customer_name, throw=True)
	return sync_customer_to_taxjar(customer_name, company=company)


def sync_customer_to_taxjar(customer_name, company=None):
	"""Create or update a customer record in TaxJar.

	Uses taxjar_customer_id to decide: empty → POST (create), set → PUT (update).
	Designed to run via frappe.enqueue (background).
	"""
	client = get_client(company)
	if not client:
		# Mirrors sync_transaction_to_taxjar's own client-missing branch: without
		# this, a customer queued by bulk_sync_to_taxjar (or on_customer_update)
		# stays at "Queued" forever - invisible to retry_failed_taxjar_customer_syncs,
		# which only ever looks for "Failed" - and the Customers page's Retry
		# action just re-queues the same no-op.
		log_taxjar_call(
			action="sync_customer",
			status="skipped",
			error="TaxJar client is not configured",
			context={"doctype": "Customer", "name": customer_name, "company": company},
		)
		_set_customer_sync_status(customer_name, "Failed", error="TaxJar is not configured for this company.")
		return

	customer_doc = frappe.get_doc("Customer", customer_name)
	exemption_type = _map_exemption_type(customer_doc.get("taxjar_exemption_type"))

	exempt_regions = [
		{"country": r.country, "state": r.state}
		for r in (customer_doc.get("taxjar_exempt_regions") or [])
	]

	existing_customer_id = customer_doc.get("taxjar_customer_id")
	safe_id = existing_customer_id or _make_safe_customer_id(customer_name)

	customer_data = {
		"customer_id": safe_id,
		"exemption_type": exemption_type,
		"name": customer_doc.customer_name,
		"exempt_regions": exempt_regions,
	}

	ctx = {"doctype": "Customer", "name": customer_name, "company": company}

	try:
		if existing_customer_id:
			response = _update_taxjar_customer(client, safe_id, customer_data, ctx)
		else:
			response = _create_taxjar_customer(client, customer_data, ctx)
	except Exception as err:
		_record_customer_sync_failure(err, "sync_customer", customer_data, ctx, customer_name)
		return

	if response is None:
		return

	_set_customer_sync_status(customer_name, "Synced")
	frappe.db.set_value("Customer", customer_name, "taxjar_customer_id", safe_id, update_modified=False)
	frappe.db.set_value("Customer", customer_name, "taxjar_last_synced", frappe.utils.now(), update_modified=False)


def _create_taxjar_customer(client, customer_data, ctx):
	"""POST a new customer to TaxJar. Returns the response or None on failure."""
	log_taxjar_call(action="create_customer", status="request", payload=customer_data, context=ctx)
	try:
		response = client.create_customer(customer_data)
	except taxjar.exceptions.TaxJarResponseError as err:
		# Status is written against ctx["name"], the Customer docname ("David
		# Fox"). customer_data["customer_id"] is the URL-safe TaxJar id
		# ("David-Fox"), which matches no row - writing status against that
		# updated nothing and left the customer showing Queued forever.
		_record_customer_sync_failure(err, "create_customer", customer_data, ctx, ctx["name"])
		return None
	log_taxjar_call(action="create_customer", status="success", payload=customer_data, response=response, context=ctx)
	return response


def _update_taxjar_customer(client, customer_id, customer_data, ctx):
	"""PUT an existing customer to TaxJar. Falls back to create on 404."""
	log_taxjar_call(action="update_customer", status="request", payload=customer_data, context=ctx)
	try:
		response = client.update_customer(customer_id, customer_data)
	except taxjar.exceptions.TaxJarResponseError as err:
		full = getattr(err, "full_response", {}) or {}
		if full.get("status_code") == 404:
			log_taxjar_call(action="update_customer", status="error", payload=customer_data, error="404 — falling back to create", context=ctx)
			return _create_taxjar_customer(client, customer_data, ctx)
		_record_customer_sync_failure(err, "update_customer", customer_data, ctx, ctx["name"])
		return None
	log_taxjar_call(action="update_customer", status="success", payload=customer_data, response=response, context=ctx)
	return response


def _has_taxjar_fields_changed(doc):
	"""Return True if any TaxJar-relevant field changed since last save."""
	if doc.has_value_changed("taxjar_exemption_type"):
		return True

	if doc.has_value_changed("customer_name"):
		return True

	previous = doc.get_doc_before_save()
	if not previous:
		return bool(doc.get("taxjar_exempt_regions"))

	old_regions = {(r.country, r.state) for r in (previous.get("taxjar_exempt_regions") or [])}
	new_regions = {(r.country, r.state) for r in (doc.get("taxjar_exempt_regions") or [])}
	return old_regions != new_regions


# Every text/datetime field a background sync job writes via a raw db_set/
# set_value rather than doc.save() - see _set_customer_sync_status. An open
# form never sees that write, so its in-memory copy goes stale the moment the
# job runs. taxjar_customer_sync_retryable is the same story but a Check
# (0/1) rather than text, so it is left out here rather than folded into a
# blank-string comparison that would silently coerce a real 0 into "".
_CUSTOMER_SYNC_MANAGED_FIELDS = (
	"taxjar_customer_id",
	"taxjar_customer_sync_status",
	"taxjar_customer_sync_error",
	"taxjar_last_synced",
)


def on_customer_validate(doc, method):
	"""Preserve read-only TaxJar fields from being overwritten by stale form data.

	Background jobs write these via frappe.db.set_value/db_set, which an open
	form never sees - so its copy goes stale the moment a job runs. The next
	save from that form (any save, not just a TaxJar-related edit - the whole
	row goes out on every save) round-trips its stale value back over the DB's,
	silently undoing the background write. "Synced" reverting to "Queued" is
	the visible case: the form loaded while a sync was in flight, the job
	finished and flipped the DB to Synced without the form reloading, and the
	next save sent the form's stale "Queued" back over it.

	All of these fields are read_only=1 and never legitimately set on `doc`
	outside a raw db write, so the DB's current value is unconditionally
	authoritative - restoring only applied when the form's copy was blank,
	which is exactly the one case ("Queued", not "") this bug does not produce.

	_validate_exempt_regions() runs unconditionally, create or update: it has
	nothing to do with stale sync fields, and gating it behind is_new() used to
	let a region-scoped exemption type save with zero regions on its first
	insert - the very state the dialog's own "Select at least one exempt
	region" message says can never be saved - only to be rejected on the next,
	otherwise-unrelated save of the same record.
	"""
	_validate_exempt_regions(doc)

	if doc.is_new():
		return

	db_values = frappe.db.get_value(
		"Customer", doc.name, list(_CUSTOMER_SYNC_MANAGED_FIELDS), as_dict=True,
	)
	if not db_values:
		return

	for field in _CUSTOMER_SYNC_MANAGED_FIELDS:
		db_val = db_values.get(field) or ""
		if doc.get(field) != db_val:
			doc.set(field, db_val)


# Single source of truth: derive from SUPPORTED_STATE_CODES so exempt-region
# validation stays in lockstep with tax-calculation state validation.
_US_STATES = set(SUPPORTED_STATE_CODES)

_CA_PROVINCES = {
	"AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT",
}

_STATES_BY_COUNTRY = {"US": _US_STATES, "CA": _CA_PROVINCES}


# The two values that describe a customer's taxability without scoping it to
# specific regions - "" (never configured) and "Non Exempt" (explicitly
# taxable everywhere). Every other option is a real, region-scoped exemption.
_EXEMPTION_TYPES_REQUIRING_REGIONS = {"Wholesale", "Government", "Other"}


def _validate_exempt_regions(doc):
	"""Region rows must be valid for their country, and a region-scoped
	exemption type must actually carry at least one region.

	The second rule is what makes exemption explicit: leaving regions blank
	used to mean "exempt everywhere", which was never a decision anyone
	visibly made. Now "everywhere" means every region was picked (the dialog's
	Select all does exactly that) - an exemption type with zero regions is
	simply not a valid state to save, regardless of which write path reaches
	here (the Manage Exemption dialog's configure_exemption, or a direct
	Customer.save()).
	"""
	regions = doc.get("taxjar_exempt_regions") or []

	if doc.get("taxjar_exemption_type") in _EXEMPTION_TYPES_REQUIRING_REGIONS and not regions:
		frappe.throw(
			_("Select at least one exempt region for this exemption type. Use Select all to apply it everywhere."),
			title=_("Exempt Region Required"),
		)

	for row in regions:
		valid_states = _STATES_BY_COUNTRY.get(row.country)
		if not valid_states:
			continue
		if row.state and row.state not in valid_states:
			frappe.throw(
				_("Row {0}: {1} is not a valid state/province for {2}").format(
					row.idx, row.state, row.country
				)
			)


def on_customer_update(doc, method):
	"""Enqueue TaxJar customer sync when exemption fields change.

	Two cases used to leave taxjar_customer_sync_status stale with no
	indication why: TaxJar disabled, and nothing left to push once the
	exemption is cleared. Both now clear the status explicitly (via
	_set_customer_sync_status, same as a real sync attempt would) instead of
	silently doing nothing - "I changed/cleared the exemption and the status
	didn't move" should never be unexplained.

	A third case - master switch on but no company actually configured -
	needs no equivalent handling here: _is_taxjar_enabled() already requires
	at least one company to have calculate/create on (the exact predicate the
	loop below uses to decide what to enqueue), so reaching the loop at all
	guarantees at least one enqueue.
	"""
	if not _has_taxjar_fields_changed(doc):
		return

	if not _is_taxjar_enabled():
		if doc.get("taxjar_customer_sync_status"):
			_set_customer_sync_status(doc.name, "")
		frappe.msgprint(
			_("TaxJar is disabled, so this customer's exemption details were saved but not sent to TaxJar."),
			indicator="orange",
			alert=True,
		)
		return

	if not doc.get("taxjar_exemption_type") and not doc.get("taxjar_customer_id"):
		# Nothing to push - no exemption to set, no existing TaxJar customer
		# record to update - but a stale Queued/Failed status from an earlier
		# attempt must not linger now that the exemption itself is gone.
		if doc.get("taxjar_customer_sync_status"):
			_set_customer_sync_status(doc.name, "")
		return

	doc.db_set("taxjar_customer_sync_status", "Queued", update_modified=False)
	_publish_customer_update(doc.name, "Queued")

	taxjar_settings = frappe.get_single("TaxJar Settings")
	for config in taxjar_settings.company_config or []:
		if not (config.taxjar_calculate_tax or config.taxjar_create_transactions):
			continue
		frappe.enqueue(
			"taxjar_integration.taxjar_integration.taxjar_integration.sync_customer_to_taxjar",
			customer_name=doc.name,
			company=config.company,
			queue="short",
			deduplicate=True,
			job_id=f"sync_customer_taxjar_{doc.name}_{config.company}",
			now=frappe.flags.in_test,
		)


def on_customer_delete(doc, method):
	"""Delete customer from TaxJar when trashed in ERPNext."""
	taxjar_customer_id = doc.get("taxjar_customer_id")
	if not taxjar_customer_id:
		return

	if not _is_taxjar_enabled():
		return

	taxjar_settings = frappe.get_single("TaxJar Settings")
	for config in taxjar_settings.company_config or []:
		if not (config.taxjar_calculate_tax or config.taxjar_create_transactions):
			continue
		try:
			delete_customer_from_taxjar(taxjar_customer_id, config.company)
		except Exception:
			_get_taxjar_logger().error(traceback.format_exc())
			log_taxjar_call(
				action="delete_customer",
				status="error",
				error=traceback.format_exc(),
				context={"doctype": "Customer", "name": doc.name, "company": config.company},
			)


def delete_customer_from_taxjar(taxjar_customer_id, company=None):
	"""Delete a customer record from TaxJar."""
	client = get_client(company)
	if not client:
		return

	ctx = {"doctype": "Customer", "name": taxjar_customer_id, "company": company}
	log_taxjar_call(action="delete_customer", status="request", context=ctx)
	try:
		response = client.delete_customer(taxjar_customer_id)
	except taxjar.exceptions.TaxJarResponseError as err:
		full = getattr(err, "full_response", {}) or {}
		if full.get("status_code") == 404:
			log_taxjar_call(action="delete_customer", status="success", context=ctx)
			return
		log_taxjar_call(action="delete_customer", status="error", error=getattr(err, "full_response", str(err)), context=ctx)
		raise
	except taxjar.exceptions.TaxJarConnectionError:
		log_taxjar_call(action="delete_customer", status="error", error="TaxJar API is unreachable", context=ctx)
		raise

	log_taxjar_call(action="delete_customer", status="success", response=response, context=ctx)
