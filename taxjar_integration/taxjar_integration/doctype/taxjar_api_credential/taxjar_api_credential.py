# Copyright (c) 2026,  Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class TaxJarAPICredential(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		company: DF.Link | None
		live_token: DF.Password | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		sandbox_token: DF.Password | None
	# end: auto-generated types

	pass
