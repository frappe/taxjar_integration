import json
import traceback

import frappe
import taxjar
from frappe import _
from frappe.contacts.doctype.address.address import get_company_address
from frappe.utils import cint, flt

from erpnext import get_default_company, get_region

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
	).insert(ignore_permissions=True)


def _is_taxjar_logging_enabled():
	cached_value = getattr(frappe.flags, "taxjar_logging_enabled", None)
	if cached_value is not None:
		return cached_value

	# Keep logging enabled by default for backward compatibility before migrate adds the field.
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


def get_client():
	taxjar_settings = frappe.get_single("TaxJar Settings")

	if not taxjar_settings.is_sandbox:
		api_key = taxjar_settings.api_key and taxjar_settings.get_password("api_key")
		api_url = taxjar.DEFAULT_API_URL
	else:
		api_key = taxjar_settings.sandbox_api_key and taxjar_settings.get_password("sandbox_api_key")
		api_url = taxjar.SANDBOX_API_URL

	if api_key and api_url:
		client = taxjar.Client(api_key=api_key, api_url=api_url)
		client.set_api_config("headers", {"x-api-version": "2022-01-24"})
		return client


def create_transaction(doc, method):
	TAXJAR_CREATE_TRANSACTIONS = frappe.db.get_single_value(
		"TaxJar Settings", "taxjar_create_transactions"
	)

	"""Create an order transaction in TaxJar"""

	if not TAXJAR_CREATE_TRANSACTIONS:
		log_taxjar_call(
			action="create_transaction",
			status="skipped",
			error="taxjar_create_transactions is disabled",
			context={"doctype": doc.doctype, "name": doc.name},
		)
		return

	client = get_client()

	if not client:
		log_taxjar_call(
			action="create_transaction",
			status="skipped",
			error="TaxJar client is not configured",
			context={"doctype": doc.doctype, "name": doc.name},
		)
		return

	TAX_ACCOUNT_HEAD = frappe.db.get_single_value("TaxJar Settings", "tax_account_head")
	sales_tax = sum([tax.tax_amount for tax in doc.taxes if tax.account_head == TAX_ACCOUNT_HEAD])

	if not sales_tax:
		log_taxjar_call(
			action="create_transaction",
			status="skipped",
			error="No sales tax amount found on document",
			context={"doctype": doc.doctype, "name": doc.name},
		)
		return

	tax_dict = get_tax_data(doc)

	if not tax_dict:
		log_taxjar_call(
			action="create_transaction",
			status="skipped",
			error="No TaxJar payload generated",
			context={"doctype": doc.doctype, "name": doc.name},
		)
		return

	tax_dict["transaction_id"] = doc.name
	tax_dict["transaction_date"] = frappe.utils.today()
	tax_dict["sales_tax"] = sales_tax
	tax_dict["amount"] = doc.total + tax_dict["shipping"]

	try:
		if doc.is_return:
			log_taxjar_call(
				action="create_refund",
				status="request",
				payload=tax_dict,
				context={"doctype": doc.doctype, "name": doc.name},
			)
			response = client.create_refund(tax_dict)
			log_taxjar_call(
				action="create_refund",
				status="success",
				payload=tax_dict,
				response=response,
				context={"doctype": doc.doctype, "name": doc.name},
			)
		else:
			log_taxjar_call(
				action="create_order",
				status="request",
				payload=tax_dict,
				context={"doctype": doc.doctype, "name": doc.name},
			)
			response = client.create_order(tax_dict)
			log_taxjar_call(
				action="create_order",
				status="success",
				payload=tax_dict,
				response=response,
				context={"doctype": doc.doctype, "name": doc.name},
			)
	except taxjar.exceptions.TaxJarResponseError as err:
		log_taxjar_call(
			action="create_transaction",
			status="error",
			payload=tax_dict,
			error=getattr(err, "full_response", str(err)),
			context={"doctype": doc.doctype, "name": doc.name},
		)
		frappe.throw(_(sanitize_error_response(err)))
	except Exception as ex:
		log_taxjar_call(
			action="create_transaction",
			status="error",
			payload=tax_dict,
			error=traceback.format_exc(),
			context={"doctype": doc.doctype, "name": doc.name},
		)
		print(traceback.format_exc(ex))


def delete_transaction(doc, method):
	"""Delete an existing TaxJar order transaction"""
	TAXJAR_CREATE_TRANSACTIONS = frappe.db.get_single_value(
		"TaxJar Settings", "taxjar_create_transactions"
	)

	if not TAXJAR_CREATE_TRANSACTIONS:
		return

	client = get_client()

	if not client:
		return

	try:
		log_taxjar_call(
			action="delete_order",
			status="request",
			payload={"transaction_id": doc.name},
			context={"doctype": doc.doctype, "name": doc.name},
		)
		response = client.delete_order(doc.name)
		log_taxjar_call(
			action="delete_order",
			status="success",
			payload={"transaction_id": doc.name},
			response=response,
			context={"doctype": doc.doctype, "name": doc.name},
		)
	except taxjar.exceptions.TaxJarResponseError as err:
		log_taxjar_call(
			action="delete_order",
			status="error",
			payload={"transaction_id": doc.name},
			error=getattr(err, "full_response", str(err)),
			context={"doctype": doc.doctype, "name": doc.name},
		)
		raise
	except Exception:
		log_taxjar_call(
			action="delete_order",
			status="error",
			payload={"transaction_id": doc.name},
			error=traceback.format_exc(),
			context={"doctype": doc.doctype, "name": doc.name},
		)
		raise


def get_tax_data(doc):
	SHIP_ACCOUNT_HEAD = frappe.db.get_single_value("TaxJar Settings", "shipping_account_head")

	from_address = get_company_address_details(doc)
	from_shipping_state = from_address.get("state")
	from_country_code = frappe.db.get_value("Country", from_address.country, "code", cache=True)
	from_country_code = from_country_code.upper()

	to_address = get_shipping_address_details(doc)
	to_shipping_state = to_address.get("state")
	to_country_code = frappe.db.get_value("Country", to_address.country, "code", cache=True)
	to_country_code = to_country_code.upper()

	shipping = sum([tax.tax_amount for tax in doc.taxes if tax.account_head == SHIP_ACCOUNT_HEAD])

	line_items = [get_line_item_dict(item, doc.docstatus) for item in doc.items]

	if from_shipping_state not in SUPPORTED_STATE_CODES:
		from_shipping_state = get_state_code(from_address, "Company")

	if to_shipping_state not in SUPPORTED_STATE_CODES:
		to_shipping_state = get_state_code(to_address, "Shipping")

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
		"amount": doc.net_total,
		"plugin": "erpnext",
		"line_items": line_items,
	}
	return tax_dict


def get_state_code(address, location):
	if address is not None:
		state_code = get_iso_3166_2_state_code(address)
		if state_code not in SUPPORTED_STATE_CODES:
			frappe.throw(_("Please enter a valid State in the {0} Address").format(location))
	else:
		frappe.throw(_("Please enter a valid State in the {0} Address").format(location))

	return state_code


def get_line_item_dict(item, docstatus):
	tax_dict = dict(
		id=item.get("idx"),
		quantity=item.get("qty"),
		unit_price=item.get("rate"),
		product_tax_code=item.get("product_tax_category"),
	)

	if docstatus == 1:
		tax_dict.update({"sales_tax": item.get("tax_collectable")})

	return tax_dict


def set_sales_tax(doc, method):
	TAX_ACCOUNT_HEAD = frappe.db.get_single_value("TaxJar Settings", "tax_account_head")
	TAXJAR_CALCULATE_TAX = frappe.db.get_single_value("TaxJar Settings", "taxjar_calculate_tax")

	if not TAXJAR_CALCULATE_TAX:
		log_taxjar_call(
			action="tax_for_order",
			status="skipped",
			error="taxjar_calculate_tax is disabled",
			context={"doctype": doc.doctype, "name": doc.name, "company": doc.company},
		)
		return

	if get_region(doc.company) != "United States":
		log_taxjar_call(
			action="tax_for_order",
			status="skipped",
			error="Company region is not United States",
			context={"doctype": doc.doctype, "name": doc.name, "company": doc.company},
		)
		return

	if not doc.items:
		log_taxjar_call(
			action="tax_for_order",
			status="skipped",
			error="Document has no items",
			context={"doctype": doc.doctype, "name": doc.name, "company": doc.company},
		)
		return

	if check_sales_tax_exemption(doc):
		log_taxjar_call(
			action="tax_for_order",
			status="skipped",
			error="Document or customer is exempt from sales tax",
			context={"doctype": doc.doctype, "name": doc.name, "company": doc.company},
		)
		return

	tax_dict = get_tax_data(doc)

	if not tax_dict:
		log_taxjar_call(
			action="tax_for_order",
			status="skipped",
			error="No TaxJar payload generated from addresses/items",
			context={"doctype": doc.doctype, "name": doc.name, "company": doc.company},
		)
		# Remove existing tax rows if address is changed from a taxable state/country
		setattr(doc, "taxes", [tax for tax in doc.taxes if tax.account_head != TAX_ACCOUNT_HEAD])
		return

	# check if delivering within a nexus
	check_for_nexus(doc, tax_dict)

	tax_data = validate_tax_request(tax_dict)
	if tax_data is not None:
		if not tax_data.amount_to_collect:
			setattr(doc, "taxes", [tax for tax in doc.taxes if tax.account_head != TAX_ACCOUNT_HEAD])
		elif tax_data.amount_to_collect > 0:
			# Loop through tax rows for existing Sales Tax entry
			# If none are found, add a row with the tax amount
			for tax in doc.taxes:
				if tax.account_head == TAX_ACCOUNT_HEAD:
					tax.tax_amount = tax_data.amount_to_collect

					doc.run_method("calculate_taxes_and_totals")
					break
			else:
				doc.append(
					"taxes",
					{
						"charge_type": "Actual",
						"description": "Sales Tax",
						"account_head": TAX_ACCOUNT_HEAD,
						"tax_amount": tax_data.amount_to_collect,
					},
				)
			# Assigning values to tax_collectable and taxable_amount fields in sales item table
			for item in tax_data.breakdown.line_items:
				doc.get("items")[cint(item.id) - 1].tax_collectable = item.tax_collectable
				doc.get("items")[cint(item.id) - 1].taxable_amount = item.taxable_amount

			doc.run_method("calculate_taxes_and_totals")


def check_for_nexus(doc, tax_dict):
	TAX_ACCOUNT_HEAD = frappe.db.get_single_value("TaxJar Settings", "tax_account_head")
	if not frappe.db.get_value("TaxJar Nexus", filters={"region_code": tax_dict["to_state"]}):
		for item in doc.get("items"):
			item.tax_collectable = flt(0)
			item.taxable_amount = flt(0)

		for tax in list(doc.taxes):
			if tax.account_head == TAX_ACCOUNT_HEAD:
				doc.taxes.remove(tax)
		return


def check_sales_tax_exemption(doc):
	# if the party is exempt from sales tax, then set all tax account heads to zero
	TAX_ACCOUNT_HEAD = frappe.db.get_single_value("TaxJar Settings", "tax_account_head")

	sales_tax_exempted = (
		hasattr(doc, "exempt_from_sales_tax")
		and doc.exempt_from_sales_tax
		or frappe.db.has_column("Customer", "exempt_from_sales_tax")
		and frappe.db.get_value("Customer", doc.customer, "exempt_from_sales_tax", cache=True)
	)

	if sales_tax_exempted:
		for tax in doc.taxes:
			if tax.account_head == TAX_ACCOUNT_HEAD:
				tax.tax_amount = 0
				break
		doc.run_method("calculate_taxes_and_totals")
		return True
	else:
		return False


def validate_tax_request(tax_dict):
	"""Return the sales tax that should be collected for a given order."""

	client = get_client()

	if not client:
		log_taxjar_call(action="tax_for_order", status="skipped", error="TaxJar client is not configured")
		return

	try:
		log_taxjar_call(action="tax_for_order", status="request", payload=tax_dict)
		tax_data = client.tax_for_order(tax_dict)
	except taxjar.exceptions.TaxJarResponseError as err:
		log_taxjar_call(
			action="tax_for_order",
			status="error",
			payload=tax_dict,
			error=getattr(err, "full_response", str(err)),
		)
		frappe.throw(_(sanitize_error_response(err)))
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
	"""Return company address details from TaxJar Settings"""
	settings_company = frappe.db.get_single_value("TaxJar Settings", "company")
	company = settings_company or get_default_company()

	company_address = get_company_address(company).company_address

	if not company_address:
		frappe.throw(_("Please set a default address for the Taxjar Settings company or the default company."))

	company_address = frappe.get_doc("Address", company_address)
	return company_address


@frappe.whitelist()
def check_nexus(shipping_address_name):
	if not shipping_address_name:
		return

	TAXJAR_CALCULATE_TAX = frappe.db.get_single_value("TaxJar Settings", "taxjar_calculate_tax")
	if not TAXJAR_CALCULATE_TAX:
		return

	if not frappe.db.exists("Address", shipping_address_name):
		return

	try:
		address = frappe.get_doc("Address", shipping_address_name)
		state_code = get_iso_3166_2_state_code(address)

		if not frappe.db.get_value("TaxJar Nexus", filters={"region_code": state_code}):
			return {"state": address.state, "state_code": state_code}
	except Exception:
		return


def get_shipping_address_details(doc):
	"""Return customer shipping address details"""

	if doc.shipping_address_name:
		shipping_address = frappe.get_doc("Address", doc.shipping_address_name)
	elif doc.customer_address:
		shipping_address = frappe.get_doc("Address", doc.customer_address)
	else:
		shipping_address = get_company_address_details(doc)

	return shipping_address


def get_iso_3166_2_state_code(address):
	import pycountry

	country_code = frappe.db.get_value("Country", address.get("country"), "code", cache=True)

	error_message = _(
		"""{0} is not a valid state! Check for typos or enter the ISO code for your state."""
	).format(address.get("state"))
	state = address.get("state").upper().strip()

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


def sanitize_error_response(response):
	response = response.full_response.get("detail")
	response = response.replace("_", " ")

	sanitized_responses = {
		"to zip": "Zipcode",
		"to city": "City",
		"to state": "State",
		"to country": "Country",
	}

	for k, v in sanitized_responses.items():
		response = response.replace(k, v)

	return response
