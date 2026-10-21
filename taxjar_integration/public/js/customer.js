// Exemption type + region are configured together through the "Manage
// Exemption" dialog, which writes via configure_exemption - the single path
// that keeps type and regions from disagreeing (see its own docstring). The
// raw taxjar_exemption_type/taxjar_exempt_regions fields stay on the doc
// (hidden=1, not deleted) so this dialog and configure_exemption can still
// read/write them directly.
const EXEMPTION_OPTIONS = ["", "Wholesale", "Government", "Non Exempt", "Other"];

// How many region chips a country shows before the rest go behind one control.
// Matches REGIONS_SHOWN on the Nexus page, which solves the same problem in
// the same shape - two rows of chips in a card at this width.
const REGIONS_SHOWN = 8;

// The two countries this app stores regions for, and every word each one needs.
// Kept together so a country's name, its "all of them" caption and its count
// cannot drift apart, and so adding a third country is one entry rather than a
// hunt through three functions.
const EXEMPTION_COUNTRIES = [
	{
		code: "US",
		name: () => __("United States"),
		all_codes: () => taxjar_integration.US_STATE_CODES,
		all_selected: () => __("All states exempted"),
		count: (n) => (n === 1 ? __("1 state") : __("{0} states", [n])),
	},
	{
		code: "CA",
		name: () => __("Canada"),
		all_codes: () => taxjar_integration.CA_PROVINCE_CODES,
		all_selected: () => __("All provinces exempted"),
		count: (n) => (n === 1 ? __("1 province") : __("{0} provinces", [n])),
	},
];

// A long list opens in place: the same chips, in the same row, so the only
// thing the control changes is how many of them there are. Lifted from the
// Nexus page's _render_chips, which chose it over a hover panel because a
// panel is closed to a keyboard and to touch, and drew the hidden regions in a
// second style in a second place.
//
// The cap is per country, so a customer exempt in both opens one without the
// other. Every render starts closed - the card is rebuilt from the document on
// every refresh, so there is no open card to carry.
function _render_region_chips($chips, names, open) {
	$chips.empty();

	const hidden = open ? 0 : Math.max(names.length - REGIONS_SHOWN, 0);
	const shown = hidden ? names.slice(0, REGIONS_SHOWN) : names;
	shown.forEach((name) =>
		frappe.ui
			.badge({ label: name, variant: "subtle", size: "lg", css_class: "taxjar-region-chip" })
			.appendTo($chips)
	);

	if (!hidden && !open) return;

	// On a line of its own, under the chips, whether or not the last chip row
	// had room for it. Sharing a row, it sat one gap past a pill and read as a
	// region that had lost its own pill; on its own line it reads as the end of
	// the list. The line is a full-width flex item, so the row breaks before it
	// and the control keeps its own width inside it.
	$('<div class="taxjar-region-more-line"></div>').appendTo($chips).append(
		frappe.ui.button({
			label: hidden ? __("+{0} more", [hidden]) : __("Show fewer"),
			// The chips are the data. This is the one action in the row, so it
			// carries no pill and no icon of its own - grey words with a rule
			// under them, from the espresso button stripped to its text (see
			// .taxjar-region-more in the scss). A pill here read as one more
			// region, and a chevron beside two words said what the words say.
			//
			// It stays a button, not a link: it opens the rest of the list in
			// place and goes nowhere, and the button brings the keyboard, the
			// focus ring and the hover with it.
			variant: "ghost",
			size: "xs",
			// text-sm is the desk's own 13px step, the step the chips are set
			// in. The card names no size of its own.
			css_class: "taxjar-region-more text-sm",
			onclick: () => _render_region_chips($chips, names, !open),
		})
	);
}

// One row per country: its flag and name, the count of what is selected on the
// right, and underneath either the regions as chips or a caption saying every
// one of them is covered.
//
// Null once that country has no regions checked at all, so the caller can drop
// the row rather than leave an empty band between two dividers.
function _exemption_country_row(country, regions) {
	const codes = regions.filter((r) => r.country === country.code).map((r) => r.state);
	if (!codes.length) return null;

	const all = codes.length === country.all_codes().length;

	const $row = $('<div class="taxjar-exemption-row"></div>');
	const $head = $('<div class="taxjar-exemption-country"></div>').appendTo($row);
	$head.append(taxjar_integration.country_flag_html(country.code));
	$('<span class="text-base-semibold text-ink-gray-8"></span>')
		.text(country.name())
		.appendTo($head);

	// Only when the chips are cut short. Beside "All states exempted" the count
	// would say the same thing twice, in numbers.
	if (!all) {
		$('<span class="taxjar-exemption-count text-p-sm text-ink-gray-5"></span>')
			.text(country.count(codes.length))
			.appendTo($head);
	}

	const $detail = $('<div class="taxjar-exemption-detail"></div>').appendTo($row);
	if (all) {
		$('<div class="text-p-sm text-ink-gray-5"></div>').text(country.all_selected()).appendTo($detail);
	} else {
		const names = codes
			.map((code) => taxjar_integration.region_full_name(country.code, code))
			.sort();
		_render_region_chips($('<div class="taxjar-region-chips"></div>').appendTo($detail), names);
	}

	return $row;
}

// The card's own header: what the exemption is, and the one control that
// changes it. A rule under it separates the decision from the regions it
// applies to, the same way each country is separated from the next.
function _exemption_header(frm) {
	const type = frm.doc.taxjar_exemption_type;
	const $head = $('<div class="taxjar-exemption-row taxjar-exemption-header"></div>');

	if (type === "Non Exempt") {
		$('<span class="text-base-semibold text-ink-gray-8"></span>')
			.text(__("Non-Exempted"))
			.appendTo($head);
	} else {
		$('<span class="text-base-semibold text-ink-gray-8"></span>')
			.text(__("Exempted"))
			.appendTo($head);
		$('<span class="text-base text-ink-gray-5">&#183;</span>').appendTo($head);
		$('<span class="text-base text-ink-gray-5"></span>').text(type).appendTo($head);
	}

	$head.append(
		frappe.ui.button({
			icon: "pencil",
			variant: "ghost",
			size: "sm",
			// The button carries no label, so `tooltip` is both the bubble on
			// hover and the name a screen reader reads. It says what the dialog
			// is called, so the two match.
			tooltip: __("Manage Exemption"),
			css_class: "taxjar-exemption-edit taxjar-manage-exemption-btn",
			onclick: () => open_manage_exemption_dialog(frm),
		})
	);

	return $head;
}

// Mirrors frappe's own Address card (frappe/public/js/frappe/form/templates/
// address_list.html + the .address-box rules in controls.scss), which frappe
// rebuilt on its espresso components: an empty state with its own actions
// while there is nothing to show, then a bordered card once there is.
//
// The card is this app's own rather than frappe's .address-box, because it
// holds more than an address does: a header, then a band per country, divided
// so the eye can find one country without reading the other. Its colours,
// radius and spacing are still the desk's own tokens, so it sits in a form
// beside frappe's cards without looking foreign.
function render_exemption_summary(frm) {
	if (!frm.fields_dict.taxjar_exemption_summary_html) return;
	const wrapper = frm.fields_dict.taxjar_exemption_summary_html.$wrapper;
	wrapper.empty();
	// empty() drops the children, not the handlers bound on the wrapper itself.
	// The empty state delegates its click from here, and the card's own
	// control carries the same class - so once a customer went from no
	// exemption to one, the wrapper still held that delegation, the control
	// answered a single click twice, and the dialog opened on top of itself.
	// Cleared on every render, before either state binds anything.
	wrapper.off("click", ".taxjar-manage-exemption-btn");

	if (!frm.doc.taxjar_exemption_type) {
		// The markup form of empty_state, not the element form, because the
		// only click here is Manage Exemption - and that is delegated off the
		// wrapper below, through the class both states share. An onclick could
		// not survive the string anyway.
		wrapper.html(
			frappe.ui.empty_state.html({
				icon: "receipt-text",
				title: __("No exemption configured"),
				description: __("Set exemption to stop collecting sales tax"),
				actions: [
					{
						label: __("Manage Exemption"),
						variant: "subtle",
						// The gear, not a plus: the button opens the dialog
						// that sets the exemption type and its regions. A plus
						// says a row is about to be added to a list.
						icon: "settings",
						css_class: "taxjar-manage-exemption-btn",
					},
				],
			})
		);

		// Only the empty state needs this: the card below binds its own
		// control directly, because it builds that button as an element.
		wrapper.on("click", ".taxjar-manage-exemption-btn", () =>
			open_manage_exemption_dialog(frm)
		);
		return;
	}

	const $card = $('<div class="taxjar-exemption-card"></div>').appendTo(wrapper);
	$card.append(_exemption_header(frm));

	// Non Exempt is one global answer: the customer pays sales tax wherever
	// they buy. Nothing reads their regions under it - the server's own
	// _customer_master_exemption returns before it so much as looks at the
	// table. So the card lists no region either, even when rows survive from a
	// type the customer held earlier. Listed here, those rows would read as
	// places the customer is exempt in, which is the opposite of what the same
	// card says one band lower.
	const non_exempt = frm.doc.taxjar_exemption_type === "Non Exempt";
	const regions = non_exempt ? [] : frm.doc.taxjar_exempt_regions || [];
	const rows = EXEMPTION_COUNTRIES.map((country) => _exemption_country_row(country, regions)).filter(
		Boolean
	);

	// Defensive fallback - nothing else should reach this state past
	// _validate_exempt_regions, which requires at least one region for every
	// type that reaches here (Non Exempt has no regions and needs none).
	if (!rows.length && !non_exempt) {
		$card.append(
			$('<div class="taxjar-exemption-row"></div>').append(
				$('<div class="text-p-sm text-ink-gray-5"></div>').text(__("No regions selected"))
			)
		);
	}
	rows.forEach(($row) => $card.append($row));

	if (non_exempt) {
		$card.append(
			$('<div class="taxjar-exemption-row"></div>').append(
				$('<div class="text-p-sm text-ink-gray-5"></div>').text(__("Sales tax is applicable."))
			)
		);
	}
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

// A Customer is not company-scoped, but a TaxJar account is, so the press has
// to name one. It used to send frappe.defaults.get_user_default("Company") - a
// guess about the user rather than a fact about the customer. Where that
// default was not a TaxJar company the press marked the customer Failed, and
// where it was another company's, the customer went into that account.
//
// The server owns the list: TaxJar Settings decides which companies sync at
// all, and the customer's own Restrict to Companies narrows it. One company
// needs no question; several do, because the form carries one sync status and
// can report one account's result.
function _sync_to_taxjar(frm) {
	return frappe
		.xcall(
			"taxjar_integration.taxjar_integration.taxjar_integration.get_customer_sync_companies",
			{ customer_name: frm.doc.name }
		)
		.then((companies) => {
			if (!companies || !companies.length) {
				frappe.msgprint({
					title: __("Nothing to Sync To"),
					message: __(
						"No company this customer belongs to is set up for TaxJar. Check TaxJar Settings, and the customer's own Restrict to Companies."
					),
					indicator: "orange",
				});
				return;
			}

			if (companies.length === 1) return _sync_to_company(frm, companies[0]);

			// Deliberately one company per press, not all of them: a save
			// decides to sync and to remove together, and only the save knows
			// which companies it just dropped. See get_customer_sync_companies.
			const dialog = new frappe.ui.Dialog({
				title: __("Sync to TaxJar"),
				fields: [
					{
						fieldname: "company",
						fieldtype: "Select",
						label: __("Company"),
						options: companies,
						default: companies[0],
						reqd: 1,
						description: __("Which company's TaxJar account to send this customer to."),
					},
				],
				primary_action_label: __("Sync"),
				primary_action: (values) => {
					dialog.hide();
					_sync_to_company(frm, values.company);
				},
			});
			dialog.show();
		});
}

function _sync_to_company(frm, company) {
	return frappe
		.xcall("taxjar_integration.taxjar_integration.taxjar_integration.resync_customer", {
			customer_name: frm.doc.name,
			company,
		})
		.then(() => frm.reload_doc())
		.then(() => {
			if (frm.doc.taxjar_customer_sync_status === "Failed") {
				taxjar_integration.show_taxjar_sync_error(
					__("TaxJar Sync Failed"),
					frm.doc.taxjar_customer_sync_error || __("Sync failed.")
				);
			} else {
				frappe.show_alert({ message: __("Customer sync queued"), indicator: "green" });
			}
		});
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
			frm.add_custom_button(__("Sync to TaxJar"), () => _sync_to_taxjar(frm), __("TaxJar"));
		}

		render_exemption_summary(frm);
	},
});
