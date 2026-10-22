import frappe
from frappe import _


def require_permission(doctype, ptype="read", doc=None):
	"""Refuse unless the user has the right.

	The same check as Frappe's has_permission with throw on. That call raises
	with Frappe's own text, which names the record but not what to do about it.
	This one names the right that is missing and tells the user to ask their
	administrator.
	"""
	if frappe.has_permission(doctype, ptype, doc=doc):
		return

	frappe.throw(
		_("You do not have {0} access to {1}, ask your administrator to update permissions for your user.").format(
			frappe.bold(_(ptype)),
			frappe.bold(_(doctype)),
		),
		exc=frappe.PermissionError,
		title=_("Not Permitted"),
	)
