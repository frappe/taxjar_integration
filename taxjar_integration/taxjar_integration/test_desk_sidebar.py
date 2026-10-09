import json
from pathlib import Path

import frappe
from frappe.tests import UnitTestCase

APP = Path(frappe.get_app_path("taxjar_integration"))


class TestDeskSidebarName(UnitTestCase):
	"""The desk names a sidebar by its Workspace Sidebar record (sidebar.current_module).

	The sidebar code once compared an older property, `workspace_title`. Frappe
	removed it, and the check failed with no error, so the code stopped running.
	"""

	def test_the_js_names_the_sidebar_that_the_app_ships(self):
		shipped = json.loads((APP / "taxjar_integration/sidebar/taxjar/taxjar.json").read_text())["name"]
		source = (APP / "public/js/desk_sidebar.js").read_text()

		self.assertIn(f'const TAXJAR_SIDEBAR = "{shipped}";', source)
		self.assertIn("sidebar.current_module === TAXJAR_SIDEBAR", source)

	def test_no_code_reads_the_removed_property(self):
		for name in ("desk_sidebar.js", "csat_card.js"):
			with self.subTest(file=name):
				self.assertNotIn("workspace_title", (APP / "public/js" / name).read_text())
