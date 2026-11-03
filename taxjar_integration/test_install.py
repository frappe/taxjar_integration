from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from taxjar_integration.install import check_versions


def bench_with(frappe_version, erpnext_version):
	versions = {"frappe.__version__": frappe_version, "erpnext.__version__": erpnext_version}
	return patch("taxjar_integration.install.frappe.get_attr", side_effect=versions.__getitem__)


class TestCheckVersions(UnitTestCase):
	def test_passes_on_the_minimum_versions(self):
		with bench_with("16.50.0", "16.52.0"):
			check_versions()

	def test_passes_on_a_later_version_16(self):
		with bench_with("16.61.3", "16.70.0"):
			check_versions()

	def test_blocks_an_erpnext_without_the_corrected_us_chart(self):
		with bench_with("16.50.0", "16.51.2"), self.assertRaises(frappe.ValidationError):
			check_versions()

	def test_blocks_an_older_frappe(self):
		with bench_with("16.49.0", "16.52.0"), self.assertRaises(frappe.ValidationError):
			check_versions()

	def test_blocks_a_develop_bench(self):
		# 17.0.0-dev sorts below 17.0.0, so only the major test catches it.
		with bench_with("17.0.0-dev", "17.0.0-dev"), self.assertRaises(frappe.ValidationError):
			check_versions()

	def test_blocks_version_15(self):
		with bench_with("15.80.0", "15.90.0"), self.assertRaises(frappe.ValidationError):
			check_versions()
