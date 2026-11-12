import frappe
from frappe.query_builder.functions import Coalesce

_US = "United States"


def backfill_address_codes():
	"""Fill the State Code and the Region Code on addresses that have none.

	The Address hooks and the Address form fill the two codes only when a user
	edits or saves an address. An address that the site held before this app was
	installed gets neither, so its codes stay empty.

	install.setup_taxjar() calls this function on install and on each migrate. A
	patch does not reach a new install, because Frappe marks every patch as done
	without running it.

	The function writes into empty fields only. A stored code is the answer of a
	user, and this function does not change it. The update goes direct to the
	database, so it does not run validate and does not change "modified".
	"""
	# Imported here: that module imports the TaxJar client and much more.
	from taxjar_integration.taxjar_integration.taxjar_integration import (
		_region_code_from_state,
		_us_state_code,
	)

	if not frappe.db.has_column("Address", "taxjar_state_code"):
		return

	country_codes = dict(frappe.get_all("Country", fields=["name", "code"], as_list=True))

	# One update for each country and state pair. A site holds few different
	# pairs, also when it holds many addresses.
	for country, state, fieldname in _blank_pairs():
		if fieldname == "taxjar_state_code":
			code = _us_state_code(state)
		else:
			code = _region_code_from_state((country_codes.get(country) or "").upper(), state)

		if code:
			_fill(country, state, fieldname, code)


def _blank_pairs():
	"""The country and state pairs that have an address with an empty code.

	A United States address keeps its code in taxjar_state_code. All other
	addresses keep it in taxjar_region_code. An address with no state has
	nothing to work out a code from, so it is not in the list.
	"""
	address = frappe.qb.DocType("Address")
	pairs = []
	for fieldname, on_us in (("taxjar_state_code", True), ("taxjar_region_code", False)):
		field = address[fieldname]
		country_filter = address.country == _US if on_us else address.country != _US
		rows = (
			frappe.qb.from_(address)
			.select(address.country, address.state)
			.distinct()
			.where(country_filter)
			.where(Coalesce(address.state, "") != "")
			.where(Coalesce(field, "") == "")
			.run()
		)
		pairs.extend((country, state, fieldname) for country, state in rows)
	return pairs


def _fill(country, state, fieldname, code):
	address = frappe.qb.DocType("Address")
	field = address[fieldname]
	(
		frappe.qb.update(address)
		.set(field, code)
		.where(address.country == country)
		.where(address.state == state)
		.where(Coalesce(field, "") == "")
	).run()
