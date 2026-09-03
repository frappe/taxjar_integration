// Exemption type + region are configured together through the "Manage
// Exemption" dialog, which writes via configure_exemption - the single path
// that keeps type and regions from disagreeing (see its own docstring). The
// raw taxjar_exemption_type/taxjar_exempt_regions fields stay on the doc
// (hidden=1, not deleted) so this dialog and configure_exemption can still
// read/write them directly.
const EXEMPTION_OPTIONS = ["", "Wholesale", "Government", "Non Exempt", "Other"];

// One country block per side: collapses to the country name plus a caption
// ("All states/provinces selected") once every code for that country is
// checked (mirrors the old whole-list collapse, now per-country) - otherwise
// a bold label ("US States") over a comma-joined, sorted list of full names.
// Three-tier sizing against the type header above (see _exemption_card_body):
// the label/country-name line is regular size and bold so it reads as a
// heading, one step down from the header; the value line (names/caption) is
// `small` and muted, one step down again - smallest and quietest of the
// three. Empty ("") once that country has no regions checked at all, so the
// caller can drop it without a stray gap.
function _exemption_region_block(country, codes, all_codes, country_name, label, all_selected_text) {
	if (!codes.length) return "";
	if (codes.length === all_codes.length) {
		return `
			<p style="margin-bottom: 0;"><strong>${frappe.utils.escape_html(country_name)}</strong></p>
			<p class="text-muted small">${all_selected_text}</p>
		`;
	}
	const names = codes
		.map((code) => taxjar_integration.region_full_name(country, code))
		.sort()
		.join(", ");
	return `
		<p style="margin-bottom: 0;"><strong>${label}</strong></p>
		<p class="text-muted small">${frappe.utils.escape_html(names)}</p>
	`;
}

function _exemption_card_body(frm) {
	const type = frm.doc.taxjar_exemption_type;

	if (type === "Non Exempt") {
		return `
			<p class="h5">${__("Non-Exempted")}</p>
			<p class="text-muted">${__("Sales tax is applicable.")}</p>
		`;
	}

	const regions = frm.doc.taxjar_exempt_regions || [];
	const us_codes = regions.filter((r) => r.country === "US").map((r) => r.state);
	const ca_codes = regions.filter((r) => r.country === "CA").map((r) => r.state);

	const region_html = (us_codes.length || ca_codes.length)
		? _exemption_region_block("US", us_codes, taxjar_integration.US_STATE_CODES, __("United States"), __("US States"), __("All states exempted"))
			+ _exemption_region_block("CA", ca_codes, taxjar_integration.CA_PROVINCE_CODES, __("Canada"), __("CA Provinces"), __("All provinces exempted"))
		// Defensive fallback - nothing else should reach this state past
		// _validate_exempt_regions, which requires at least one region for
		// every type that reaches this branch (Non Exempt is handled above).
		: `<p class="text-muted">${__("No regions selected")}</p>`;

	return `
		<p class="h5 flex flex-wrap">
			<span>${__("Exempted")}</span>&nbsp;&#183;&nbsp;<span class="text-muted">${frappe.utils.escape_html(type)}</span>
		</p>
		${region_html}
	`;
}

// Mirrors frappe's own Address card (frappe/public/js/frappe/form/templates/
// address_list.html + the .address-box/.edit-btn rules in controls.scss): a
// left-aligned "add" button above an always-present bordered box once
// there's nothing to edit yet, then a pencil in the box's own top-right
// corner once there is. Reusing .address-box/.edit-btn/the "pencil" icon
// directly rather than inventing parallel CSS keeps this visually identical
// to that pattern for free.
function render_exemption_summary(frm) {
	if (!frm.fields_dict.taxjar_exemption_summary_html) return;
	const wrapper = frm.fields_dict.taxjar_exemption_summary_html.$wrapper;

	if (!frm.doc.taxjar_exemption_type) {
		wrapper.html(`
			<p>
				<button type="button" class="btn btn-xs btn-default taxjar-manage-exemption-btn">
					${__("Manage Exemption")}
				</button>
			</p>
			<div class="address-box">
				<span class="text-muted">${__("No exemption configured.")}</span>
			</div>
		`);
	} else {
		wrapper.html(`
			<div class="address-box">
				<button type="button" class="btn btn-xs btn-default edit-btn taxjar-manage-exemption-btn" title="${__("Edit")}">
					${frappe.utils.icon("pencil", "xs")}
				</button>
				${_exemption_card_body(frm)}
			</div>
		`);
	}

	wrapper
		.off("click", ".taxjar-manage-exemption-btn")
		.on("click", ".taxjar-manage-exemption-btn", () => open_manage_exemption_dialog(frm));
}

function open_manage_exemption_dialog(frm) {
	const selected = new Set(
		(frm.doc.taxjar_exempt_regions || []).map((r) => `${r.country}:${r.state}`)
	);

	const dialog = new frappe.ui.Dialog({
		title: __("Manage Exemption"),
		size: "large",
		fields: [
			{
				fieldtype: "Select",
				fieldname: "exemption_type",
				label: __("Exemption Type"),
				options: EXEMPTION_OPTIONS.map((opt) => ({
					label: opt || __("Not Configured"),
					value: opt,
				})),
				default: frm.doc.taxjar_exemption_type || "",
				change: () => update_requirement(),
			},
			...taxjar_integration.build_region_multicheck_fields(selected),
		],
		primary_action_label: __("Apply"),
		primary_action: () => {
			const type = dialog.get_value("exemption_type");
			const regions = type ? taxjar_integration.get_selected_regions(dialog) : [];

			dialog.hide();
			frappe
				.xcall(
					"taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.configure_exemption",
					{ customers: [frm.doc.name], exemption_type: type, regions }
				)
				.then(() => frm.reload_doc());
		},
	});

	const update_requirement = taxjar_integration.wire_exemption_dialog(dialog);
	dialog.show();
	update_requirement();
}

frappe.ui.form.on("Customer", {
	// Registered once per form load, not refresh - see sales_invoice.js's
	// identical setup(frm) listener for the full reasoning. on_customer_update
	// (not just a rare submit/cancel event) and the 15-min cron retry both
	// funnel through _set_customer_sync_status, which publishes this event.
	setup(frm) {
		frappe.realtime.on("taxjar_customer_sync_update", () => frm.reload_doc());
	},

	refresh(frm) {
		if (
			!frm.is_new() &&
			frm.doc.taxjar_exemption_type &&
			frm.fields_dict["taxjar_customer_id"]
		) {
			frm.add_custom_button(
				__("Sync to TaxJar"),
				() => {
					frappe.xcall(
						"taxjar_integration.taxjar_integration.taxjar_integration.resync_customer",
						{ customer_name: frm.doc.name },
					).then(() => frm.reload_doc()).then(() => {
						if (frm.doc.taxjar_customer_sync_status === "Failed") {
							taxjar_integration.show_taxjar_sync_error(
								__("TaxJar Sync Failed"),
								frm.doc.taxjar_customer_sync_error || __("Sync failed.")
							);
						} else {
							frappe.show_alert({ message: __("Customer sync queued"), indicator: "green" });
						}
					});
				},
				__("TaxJar"),
			);
		}

		render_exemption_summary(frm);
	},
});
