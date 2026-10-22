// Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Product Tax Category', {
	refresh(frm) {
		// The doc is named after product_tax_code, so core hides that field once
		// saved (cleanup_refresh in form.js). Show it read-only instead, so the
		// Product Tax Code stays visible without being editable out of sync
		// with the document ID — renaming still goes through the Rename dialog.
		if (frm.is_new()) return;

		frm.set_df_property('product_tax_code', 'read_only', 1);
		frm.toggle_display('product_tax_code', true);
	},
});
