import frappe

from taxjar_integration.patches.mark_version_15_upgrade import MARKER


def execute():
	"""Delete the marker that mark_version_15_upgrade set.

	Every patch that copies version-15 data reads the marker, so it stays until
	the last of them has run. This patch is the last line in patches.txt. A new
	patch that reads the marker goes above it.

	Deleted so that a patch shipped in a later release does not read an old
	answer on a site that upgraded long ago.
	"""
	frappe.db.set_global(MARKER, None)
