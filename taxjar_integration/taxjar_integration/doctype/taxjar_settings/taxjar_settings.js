// Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// The Nexus tab draws the same markup as the standalone "Nexus & Product
// Category" page (/app/taxjar-nexus), so the markup itself lives in the shared
// bundle (public/js/taxjar_utils.js) and the two functions below only hand it
// this form's own wrappers and data.
function _render_nexus_html(frm) {
	taxjar_integration.render_nexus_cards(frm.fields_dict.nexus_html.$wrapper, frm.doc.nexus);
}

function _render_product_tax_category_html(frm) {
	frm.call({
		doc: frm.doc,
		method: 'get_product_tax_category_summary',
		callback: (r) => {
			taxjar_integration.render_product_tax_category_summary(
				frm.fields_dict.product_tax_category_html.$wrapper, r.message || {}
			);
		},
	});
}

function _set_setup_intro(frm) {
	// Always offered, whether or not setup is complete - the wizard is safe to
	// re-run any time (make_custom_fields() etc. are all idempotent), so there is
	// no "done, stop asking" state to check for. Manual editing of the form below
	// stays fully available either way.
	//
	// What changes is what the banner offers. An unfinished setup gets the
	// invitation; a finished one gets the way back to the summary. The word is
	// "Review", not "Edit", because the page opens on the record and the button
	// there is what starts the edit. Same colour and wording as the workspace
	// banner, because it is the same link -
	// a blue "go and set this up" on a site that finished setup months ago is
	// what this reads off setup_complete to avoid.
	const done = !!frm.doc.setup_complete;
	frm.set_intro(
		done
			? `<a href="/app/taxjar-setup">${__("Review configuration")} →</a>`
			: `<a href="/app/taxjar-setup">${__("Go to guided setup experience")} →</a>`,
		done ? "green" : "blue"
	);
}

const API_MODE_DESCRIPTIONS = {
	Sandbox: 'Requests & response payloads are validated. Tax rates might be stale and no transactions are recorded. API calls does not consume plan quota.',
	Live: 'Sales tax calculations based on nexus, transactions are recorded for reporting and auto-filing. API calls consume plan quota.',
};

// Button controls hide their own label (button.js's toggle_label(false)) -
// the button text is the label - so .control-input holds nothing but the
// <button>, making it a safe place to append a sibling without fighting
// frappe's own layout. Re-rendered rather than built once: the value changes
// after every Update Nexus List click, and nexus_last_synced itself is
// hidden (see the doctype JSON) so there is no field-level refresh to piggy-
// back on.
function _render_nexus_last_synced(frm) {
	const field = frm.fields_dict.update_nexus_list_btn;
	if (!field) return;

	// A lone full-width field gets frappe's own .input-max-width (form.scss:
	// ".form-column.col-sm-12 > form > .input-max-width { max-width: 50% }"),
	// which is fine for a button by itself but caps "Last updated" well short
	// of the table's own right edge below it. set_max_width() only runs once,
	// at control construction, so removing the class here is a one-time,
	// idempotent fix rather than something re-fought on every refresh.
	field.$wrapper.removeClass('input-max-width');

	const $input_area = $(field.input_area).css({
		display: 'flex',
		'align-items': 'center',
		'justify-content': 'space-between',
		gap: '12px',
	});
	$input_area.find('.taxjar-nexus-last-synced').remove();
	$(`
		<span class="taxjar-nexus-last-synced" style="color: var(--text-muted); font-size: 12px;">
			${__('Last updated')}: ${taxjar_integration.format_last_synced(frm.doc.nexus_last_synced)}
		</span>
	`).appendTo($input_area);
}

function _set_api_mode_description(frm) {
	const desc = API_MODE_DESCRIPTIONS[frm.doc.api_mode]
		|| 'Select a mode to use TaxJar API Features';
	frm.set_df_property('api_mode', 'description', desc);
}

// A ledger is only valid for the company it belongs to, and the account fields'
// filter is evaluated when the account is picked - not again afterwards. Changing
// the company on a row would otherwise leave the previous company's ledgers sitting
// there, which is what reaches a transaction as "Account ... does not belong to
// company ...", naming neither TaxJar nor this row.
frappe.ui.form.on('TaxJar Company Config', {
	company(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.tax_account_head && !row.shipping_account_head) return;

		frappe.model.set_value(cdt, cdn, 'tax_account_head', null);
		frappe.model.set_value(cdt, cdn, 'shipping_account_head', null);
		frappe.show_alert({
			message: __('Ledger accounts cleared — pick them from {0}’s chart of accounts.', [row.company || __('the new company')]),
			indicator: 'orange',
		});
	},
});

frappe.ui.form.on('TaxJar Settings', {
	// This record decides what every transaction form is allowed to do, and the
	// forms memoise that answer per company for the life of the page (see
	// taxjar_integration.scope). Desk routing never reloads the page, so a save
	// here used to leave every invoice opened afterwards reporting the old
	// configuration until a hard refresh.
	after_save() {
		taxjar_integration.clear_scope_cache();
	},

	refresh(frm) {
		_set_setup_intro(frm);
		_render_nexus_html(frm);
		_render_nexus_last_synced(frm);
		_render_product_tax_category_html(frm);
		_set_api_mode_description(frm);

		// A TaxJar User reads these settings; only a TaxJar Manager (write)
		// syncs the two lists. Frappe keeps a Button field visible on a
		// read-only form, so these are hidden here. The server refuses the sync
		// either way.
		frm.toggle_display(
			['update_nexus_list_btn', 'update_product_tax_category_btn'],
			!!(frm.perm && frm.perm[0] && frm.perm[0].write)
		);

		const account_query = (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return { filters: { company: row.company, is_group: 0 } };
		};
		frm.set_query('tax_account_head', 'company_config', account_query);
		frm.set_query('shipping_account_head', 'company_config', account_query);
	},

	api_mode(frm) {
		_set_api_mode_description(frm);
	},

	update_nexus_list_btn(frm) {
		frm.call({
			doc: frm.doc,
			method: 'update_nexus_list',
			callback: () => {
				frm.refresh();
				_render_nexus_html(frm);
				_render_nexus_last_synced(frm);
				frappe.show_alert({ message: __('Nexus regions fetched and updated.'), indicator: 'green' }, 5);
			},
		});
	},

	update_product_tax_category_btn(frm) {
		frm.call({
			doc: frm.doc,
			method: 'refresh_product_tax_categories',
			callback: () => {
				_render_product_tax_category_html(frm);
				frappe.show_alert({ message: __('Product tax categories fetched and updated.'), indicator: 'green' }, 5);
			},
		});
	},
});
