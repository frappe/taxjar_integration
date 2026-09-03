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
	// applies, so both address fields re-evaluate it.
	customer_address(frm) {
		taxjar_integration.apply_region_exemption(frm);
	},

	validate(frm) {
		return taxjar_integration
			.confirm_foreign_tax_rows(frm)
			.then(() => taxjar_integration.check_shipping_address(frm));
	},

	shipping_address_name(frm) {
		taxjar_integration.apply_region_exemption(frm);

		if (!frm.doc.shipping_address_name) {
			return;
		}

		// Returning this promise (rather than firing-and-forgetting) lets
		// frm.set_value("shipping_address_name", ...) callers await it, so
		// the nexus check finishes - and the warning dialog is already up -
		// before a caller-driven frm.save() starts.
		return frappe.call({
			method: "taxjar_integration.taxjar_integration.taxjar_integration.check_nexus",
			args: { shipping_address_name: frm.doc.shipping_address_name },
			callback(r) {
				if (r.message) {
					taxjar_integration.show_nexus_missing_dialog(r.message.state, r.message.state_code);
				}
			}
		});
	}
});

function _add_taxjar_buttons(frm) {
	if (!frm.doc.docstatus || !frm.fields_dict.taxjar_sync_status) return;

	const status = frm.doc.taxjar_sync_status;
	if (status !== "Failed" && status !== "Excluded") return;

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
