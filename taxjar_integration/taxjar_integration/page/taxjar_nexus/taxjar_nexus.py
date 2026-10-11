"""Server APIs for the Nexus & Product Category desk page (/app/taxjar-nexus).

Both lists also live on the TaxJar Settings form's own "Nexus & Product
Category" tab; this page is the same two summaries without the surrounding
settings form. Every write here delegates to the doctype's own method, which
already carries the write-permission check, the TaxJar call and the save - so
this module never re-implements either fetch, and the two entry points can
never drift apart.

A TaxJar User (read on TaxJar Settings) opens this page read-only. Only a
TaxJar Manager (write) syncs either list, so each sync endpoint checks write
itself, before it loads anything.
"""

import frappe

from taxjar_integration.taxjar_integration.access import require_permission
from taxjar_integration.telemetry import capture

SETTINGS = "TaxJar Settings"


def _summary(settings):
	"""Everything the page renders, in one round trip: the nexus child table
	(grouped by company on the client, same as the settings form does it), when
	it last came from TaxJar, and the Product Tax Category count."""
	return {
		"nexus": [
			{
				"company": row.company,
				"region": row.region,
				"region_code": row.region_code,
				"country": row.country,
				"country_code": row.country_code,
			}
			for row in settings.nexus or []
		],
		"nexus_last_synced": settings.nexus_last_synced,
		"product_tax_categories": settings.get_product_tax_category_summary(),
		# The page draws the two sync buttons only when this is true.
		"can_sync": bool(frappe.has_permission(SETTINGS, "write")),
	}


@frappe.whitelist()
def get_summary():
	require_permission(SETTINGS, "read")

	return _summary(frappe.get_single(SETTINGS))


@frappe.whitelist(methods=["POST"])
def update_nexus_list():
	"""The page's "Update Nexus List" button. update_nexus_list() checks write
	permission itself and saves, so the reloaded summary below reflects what
	TaxJar just returned."""
	require_permission(SETTINGS, "write")
	settings = frappe.get_single(SETTINGS)
	settings.update_nexus_list()

	capture("taxjar_nexus_refreshed")
	return _summary(settings)


@frappe.whitelist(methods=["POST"])
def refresh_product_tax_categories():
	"""The page's "Update Product Tax Category List" button. Same delegation as
	update_nexus_list above - the doctype method checks write permission and
	turns a TaxJar error into a readable message."""
	require_permission(SETTINGS, "write")
	settings = frappe.get_single(SETTINGS)
	settings.refresh_product_tax_categories()

	capture("taxjar_categories_refreshed")
	return _summary(settings)
