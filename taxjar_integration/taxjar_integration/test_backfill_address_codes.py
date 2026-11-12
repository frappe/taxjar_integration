import frappe
from frappe.tests import IntegrationTestCase

from taxjar_integration.patches.backfill_address_codes import backfill_address_codes


def _make_address(title, country, state, pincode="10001"):
	"""An Address with both code fields empty, as on a site from before the install.

	The insert runs the Address hooks. When TaxJar is on, these fill the codes
	and refuse a US state with no match. So the insert uses no state, and the
	set_value call writes the state and empties the codes without a change to
	"modified".
	"""
	address = frappe.get_doc(
		dict(
			doctype="Address",
			address_title=title,
			address_line1="1 Main St",
			city="Springfield",
			country=country,
			state="California" if country == "United States" else "",
			pincode=pincode,
		)
	).insert(ignore_permissions=True)
	frappe.db.set_value(
		"Address",
		address.name,
		{"state": state, "taxjar_state_code": None, "taxjar_region_code": ""},
		update_modified=False,
	)
	return address.name


def _codes(name):
	return frappe.db.get_value(
		"Address", name, ["taxjar_state_code", "taxjar_region_code", "modified"], as_dict=True
	)


class TestBackfillAddressCodes(IntegrationTestCase):
	def test_a_us_address_gets_the_state_code_from_a_name_or_a_code(self):
		by_name = _make_address("Backfill NY", "United States", "New York")
		by_code = _make_address("Backfill CA", "United States", "ca")

		backfill_address_codes()

		self.assertEqual(_codes(by_name).taxjar_state_code, "NY")
		self.assertEqual(_codes(by_code).taxjar_state_code, "CA")
		# The Region Code is for addresses outside the United States only.
		self.assertFalse(_codes(by_name).taxjar_region_code)

	def test_an_address_outside_the_us_gets_the_region_code(self):
		gujarat = _make_address("Backfill GJ", "India", "Gujarat", "380001")

		backfill_address_codes()

		self.assertEqual(_codes(gujarat).taxjar_region_code, "GJ")
		self.assertFalse(_codes(gujarat).taxjar_state_code)

	def test_a_stored_code_stays(self):
		name = _make_address("Backfill kept", "United States", "New York")
		frappe.db.set_value("Address", name, "taxjar_state_code", "NJ", update_modified=False)

		backfill_address_codes()

		self.assertEqual(_codes(name).taxjar_state_code, "NJ")

	def test_a_state_with_no_match_stays_empty(self):
		unknown = _make_address("Backfill unknown", "United States", "Nowhere")

		backfill_address_codes()

		self.assertFalse(_codes(unknown).taxjar_state_code)

	def test_the_backfill_does_not_change_modified(self):
		name = _make_address("Backfill modified", "United States", "Florida")
		before = _codes(name).modified

		backfill_address_codes()

		self.assertEqual(_codes(name).taxjar_state_code, "FL")
		self.assertEqual(_codes(name).modified, before)
