# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class TaxJarCustomerExemptRegion(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		country: DF.Literal["", "US", "CA"]
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		state: DF.Literal[
			"",
			"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
			"GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
			"MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
			"NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
			"SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
			"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
		]
	# end: auto-generated types

	pass
