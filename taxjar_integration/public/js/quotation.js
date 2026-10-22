frappe.ui.form.on("Quotation", {
	refresh(frm) {
		taxjar_integration.toggle_taxjar_ui(frm);
		taxjar_integration.render_shipping_taxability(frm);
		taxjar_integration.render_tax_breakdown(frm);
		taxjar_integration.render_status_cards(frm);
		taxjar_integration.render_addresses(frm);
		taxjar_integration.show_no_address_tax_message(frm);
		taxjar_integration.apply_region_exemption(frm);
	},

	// Destination decides whether the customer's region-scoped exemption
	// applies, so both address fields re-evaluate it - and both re-ask about
	// nexus, which the same destination decides.
	shipping_address_name(frm) {
		taxjar_integration.apply_region_exemption(frm);
		taxjar_integration.show_no_address_tax_message(frm);
	},

	customer_address(frm) {
		taxjar_integration.apply_region_exemption(frm);
		taxjar_integration.show_no_address_tax_message(frm);
	},

	validate(frm) {
		return taxjar_integration
			.confirm_foreign_tax_rows(frm)
			.then(() => taxjar_integration.check_shipping_address(frm))
			// After the picker, not before it: this reads the fields of the
			// address the document ends up with, and that one may have just
			// been chosen.
			.then(() => taxjar_integration.check_destination_address(frm));
	},
});
