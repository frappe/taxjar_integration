import frappe

# Set by this patch. Read by the patches that copy version-15 data, through
# is_version_15_upgrade(). Deleted by clear_version_15_upgrade_marker, the last
# patch in the list.
MARKER = "taxjar_upgrading_from_version_15"


def execute():
	"""Record that this migrate is the first one from version 15 to version 16.

	Version 16 creates its Customer columns, taxjar_exemption_type among them,
	from make_custom_fields(). Version 15 never created that column. So a site
	without it has never run version 16, and this migrate is its upgrade.

	This is a pre_model_sync patch so that it reads the site before anything in
	this migrate changes it. Several post_model_sync patches call
	make_custom_fields() themselves, and after_migrate calls it again. By the
	time a post_model_sync patch runs, the column is there on every site.

	A new install never runs this patch, because Frappe marks every patch as
	done when it installs the app.

	The answer is stored in the database rather than in frappe.flags. If this
	migrate fails after this patch, the next migrate does not run it again, and
	a flag would be gone by then.
	"""
	if frappe.db.has_column("Customer", "taxjar_exemption_type"):
		return

	frappe.db.set_global(MARKER, "1")


def is_version_15_upgrade():
	"""Return True on the migrate that upgrades this site from version 15."""
	return bool(frappe.db.get_global(MARKER))
