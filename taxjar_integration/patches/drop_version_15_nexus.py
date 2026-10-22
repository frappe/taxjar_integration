import frappe
from frappe.query_builder.functions import Coalesce

PARENT = "TaxJar Settings"


def execute():
	"""Delete the nexus rows version 15 left behind.

	Version 15 held one nexus list for the whole site. Version 16 holds one list
	per company, in the same child table with a `company` column added. So every
	row version 15 wrote arrives with that column blank, and the nexus screens
	group those rows under no company at all.

	The rows are not worth keeping. _sync_nexus_from_taxjar() rebuilds the table
	from company_config and drops whatever matches no configured company, so the
	first fetch removes them anyway. This removes them before a screen shows
	them, and before a company is configured to fetch for.

	One DELETE rather than a loop over the parent document. Saving TaxJar
	Settings here would run its own on_update, which enqueues three jobs.
	"""
	if not frappe.db.has_column("TaxJar Nexus", "company"):
		return

	_delete_query().run()


def _delete_query():
	"""Build the DELETE. Returned rather than run, so a test can read the
	statement."""
	nexus = frappe.qb.DocType("TaxJar Nexus")
	return (
		frappe.qb.from_(nexus)
		.delete()
		.where((nexus.parenttype == PARENT) & (Coalesce(nexus.company, "") == ""))
	)
