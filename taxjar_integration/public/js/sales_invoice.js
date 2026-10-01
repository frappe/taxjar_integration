frappe.ui.form.on("Sales Invoice", {
	// Registered once per form load (not refresh, which reruns repeatedly
	// and would stack duplicate listeners). The background sync job/cron
	// retry/bulk retry all funnel through _set_sync_status, which publishes
	// this event once the DB write is committed - frappe already scopes
	// delivery to clients viewing this exact document (doc:{doctype}/{name}
	// room, joined automatically on form load), so no docname check is
	// needed here.
	setup(frm) {
		frappe.realtime.on("taxjar_invoice_sync_update", () => frm.reload_doc());
	},

	refresh(frm) {
		taxjar_integration.toggle_taxjar_ui(frm);
		taxjar_integration.render_shipping_taxability(frm);
		taxjar_integration.render_tax_breakdown(frm);
		taxjar_integration.render_sync_status_sidebar_pill(frm);
		_add_taxjar_buttons(frm);
		taxjar_integration.render_status_cards(frm);
		taxjar_integration.render_addresses(frm);
		taxjar_integration.show_no_address_tax_message(frm);
		taxjar_integration.apply_region_exemption(frm);
	},

	// Destination decides whether the customer's region-scoped exemption
	// applies, so both address fields re-evaluate it - and, with no separate
	// shipping address, the billing address is also what nexus is judged on.
	customer_address(frm) {
		taxjar_integration.apply_region_exemption(frm);
		taxjar_integration.show_no_address_tax_message(frm);
		// The draft pill reads the destination too (see
		// render_sync_status_sidebar_pill), so it is repainted here rather than
		// left saying "Submit to Sync" beside a strip that already says the sale
		// is an export.
		taxjar_integration.render_sync_status_sidebar_pill(frm);
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

	// A filing company's credit note has to name the invoice it reverses, and
	// validate_return_against refuses the save without it. Ask here, where the
	// user has just said the document is a return, rather than at the save -
	// and open the picker that takes the Return / Credit Note route for them.
	//
	// Fires on the user's own tick and on set_value alike, which is why the
	// entry point re-reads is_return rather than assuming this means "ticked".
	is_return(frm) {
		return taxjar_integration.prompt_for_return_reference(frm);
	},

	// A missing nexus is reported in the form's own message strip rather than
	// a modal, so there is nothing here for a caller to await before saving -
	// the strip can appear while the save runs without racing anything.
	shipping_address_name(frm) {
		taxjar_integration.apply_region_exemption(frm);
		taxjar_integration.show_no_address_tax_message(frm);
		taxjar_integration.render_sync_status_sidebar_pill(frm);
	}
});

function _add_taxjar_buttons(frm) {
	if (!frm.doc.docstatus || !frm.fields_dict.taxjar_sync_status || !frm.doc.company) return;

	const status = frm.doc.taxjar_sync_status;
	if (status !== "Failed" && status !== "Excluded") return;

	// An export this company keeps out. The button files a document, and this
	// one would be excluded again the moment it was pressed - the worker asks
	// the same question before it builds anything. Turning Include Export
	// Transactions on is what files it, and that is a settings change rather
	// than a button on the invoice.
	if (frm.doc.taxjar_exclusion_reason === "Export Transaction") return;

	// TaxJar version 15 may have sent this invoice already, under another
	// provider. Sending it again would file it twice. The pre-upgrade invoice
	// check answers first, and the button returns once it has said "not found".
	if (frm.doc.taxjar_exclusion_reason === "Submitted before upgrade, not yet checked") return;

	// resync_transaction refuses to file for a company whose "create
	// transactions" flag is off, so the button is not offered there either -
	// it would otherwise sit directly beneath a sidebar pill saying this company
	// does not file, offering to do the one thing it cannot.
	//
	// Asked live for the same reason the sidebar pill asks live (see
	// render_sync_status_sidebar_pill): the flag can change after the document
	// was last written, and a cancelled document is never written again. The
	// answer lands after refresh() has finished, which is fine - add_inner_button
	// dedupes by label, so a late callback cannot stack a second button.
	const docname = frm.doc.name;
	taxjar_integration.scope(frm.doc.company).then((scope) => {
		if (!scope || !scope.files || frm.doc.name !== docname) return;
		_add_sync_button(frm);
	});
}

function _add_sync_button(frm) {
	frm.add_custom_button(__("Sync to TaxJar"), function () {
		frappe.call({
			method: "taxjar_integration.taxjar_integration.taxjar_integration.resync_transaction",
			args: { invoice_name: frm.doc.name },
			freeze: true,
			freeze_message: __("Syncing to TaxJar..."),
			callback() {
				frm.reload_doc().then(() => {
					if (frm.doc.taxjar_sync_status === "Failed") {
						taxjar_integration.show_taxjar_sync_error(
							__("TaxJar Sync Failed"),
							frm.doc.taxjar_sync_error || __("Sync failed.")
						);
					} else {
						frappe.show_alert({ message: __("Sync complete"), indicator: "green" }, 5);
					}
				});
			}
		});
	}, __("TaxJar"));
}
