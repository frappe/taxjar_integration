// Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// str_to_user() converts system tz -> user tz via moment-timezone and just
// formats it - no comparison against the browser's local clock, so it can't
// hit comment_when()/prettyDate()'s "future date" guard (pretty_date.js:21,
// `if (day_diff < 0) return ""`), which blanked this out whenever the site's
// System Settings timezone drifted far enough from the browser's own.
// Shared by Nexus and Product Tax Category - both are "when did this list
// last come from TaxJar" and were duplicating the same three lines.
function _format_last_synced(value) {
	return value ? frappe.datetime.str_to_user(value) : __('Never');
}

// Espresso's own component CSS (.es-badge, and the shared radius/spacing
// tokens the classes below key off) is already loaded on every desk page -
// only the card/table layout specific to this grouped-by-company list needs
// injecting, same pattern as taxjar_utils.js's _inject_status_card_styles().
function _inject_nexus_table_styles() {
	if (document.getElementById('taxjar-nexus-table-styles')) return;
	const style = document.createElement('style');
	style.id = 'taxjar-nexus-table-styles';
	style.textContent = `
		.taxjar-nexus-card {
			border: 1px solid var(--border-color);
			border-radius: var(--radius-md);
			margin-bottom: 16px;
			overflow: hidden;
		}
		.taxjar-nexus-card-h {
			display: flex; align-items: center; gap: 8px;
			background: var(--subtle-fg);
			padding: 10px 16px;
			font-weight: 600;
			font-size: 13px;
			color: var(--heading-color);
			border-bottom: 1px solid var(--border-color);
		}
		.taxjar-nexus-table-wrap { overflow-x: auto; }
		.taxjar-nexus-table { width: 100%; border-collapse: collapse; font-size: 12px; }
		.taxjar-nexus-table th {
			text-align: left; padding: 8px 16px; color: var(--text-muted);
			font-weight: 500; border-bottom: 1px solid var(--border-color); white-space: nowrap;
		}
		.taxjar-nexus-table td { padding: 8px 16px; white-space: nowrap; }
		.taxjar-nexus-table tr:not(:last-child) td { border-bottom: 1px solid var(--border-color); }
	`;
	document.head.appendChild(style);
}

function _render_nexus_html(frm) {
	const wrapper = frm.fields_dict.nexus_html.$wrapper;
	const rows = frm.doc.nexus || [];

	if (!rows.length) {
		wrapper.empty().append(frappe.ui.empty_state({
			icon: 'map-pin',
			title: __('No nexus regions loaded'),
			description: __('Use "Update Nexus List" above to fetch them from TaxJar.'),
			css_class: 'my-2',
		}));
		return;
	}

	_inject_nexus_table_styles();

	// Group rows by company
	const by_company = {};
	for (const row of rows) {
		const key = row.company || '(No Company)';
		if (!by_company[key]) by_company[key] = [];
		by_company[key].push(row);
	}

	wrapper.empty();
	for (const [company, company_rows] of Object.entries(by_company)) {
		const rows_html = company_rows.map((r) => `
			<tr>
				<td>${frappe.utils.escape_html(r.region || '—')}</td>
				<td><code>${frappe.utils.escape_html(r.region_code || '—')}</code></td>
				<td>${frappe.utils.escape_html(r.country || '—')}</td>
				<td><code>${frappe.utils.escape_html(r.country_code || '—')}</code></td>
			</tr>`).join('');

		const $card = $(`
			<div class="taxjar-nexus-card">
				<div class="taxjar-nexus-card-h">${frappe.utils.escape_html(company)}</div>
				<div class="taxjar-nexus-table-wrap">
					<table class="taxjar-nexus-table">
						<thead>
							<tr>
								<th>${__('Region')}</th>
								<th>${__('Code')}</th>
								<th>${__('Country')}</th>
								<th>${__('Country Code')}</th>
							</tr>
						</thead>
						<tbody>${rows_html}</tbody>
					</table>
				</div>
			</div>
		`).appendTo(wrapper);

		$card.find('.taxjar-nexus-card-h').append(
			frappe.ui.badge({ label: String(company_rows.length), theme: 'blue', size: 'sm' })
		);
	}
}

function _render_product_tax_category_html(frm) {
	const wrapper = frm.fields_dict.product_tax_category_html.$wrapper;

	frm.call({
		doc: frm.doc,
		method: 'get_product_tax_category_summary',
		callback: (r) => {
			const summary = r.message || {};
			const count = summary.count || 0;

			if (!count) {
				wrapper.empty().append(frappe.ui.empty_state({
					icon: 'tag',
					title: __('No product tax categories loaded'),
					description: __('Use "Update Product Tax Category List" above to fetch them from TaxJar.'),
					css_class: 'my-2',
				}));
				return;
			}

			const last_updated = _format_last_synced(summary.last_updated);

			wrapper.html(`
				<div style="
					border: 1px solid var(--border-color);
					border-radius: var(--radius-md);
					padding: 16px;
					text-align: center;
					/* Last thing in the section - without this the box's border
					   sits flush against the next section's divider. Matches the
					   empty-state box below so the gap doesn't change when the
					   list is loaded. */
					margin-bottom: 16px;
				">
					<div style="font-size: 13px;">
						<a href="/app/product-tax-category">${count} ${__('Product Tax Categories')}</a>
						${__('are configured.')}
					</div>
					<div style="color: var(--text-muted); font-size: 12px; margin-top: 4px;">
						${__('Last updated')}: ${last_updated}
					</div>
				</div>
			`);
		},
	});
}

function _set_setup_intro(frm) {
	// Guided-setup banner: always offered, whether or not setup is complete -
	// the wizard is safe to re-run any time (make_custom_fields() etc. are all
	// idempotent), so there is no "done, stop asking" state to check for.
	// Manual editing of the form below stays fully available either way.
	frm.set_intro(
		`<a href="/app/taxjar-setup">${__("Try the guided setup experience")} →</a>`,
		"blue"
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
			${__('Last updated')}: ${_format_last_synced(frm.doc.nexus_last_synced)}
		</span>
	`).appendTo($input_area);
}

function _set_api_mode_description(frm) {
	const desc = API_MODE_DESCRIPTIONS[frm.doc.api_mode]
		|| 'Select a mode to use TaxJar API Features';
	frm.set_df_property('api_mode', 'description', desc);
}

frappe.ui.form.on('TaxJar Settings', {
	refresh(frm) {
		_set_setup_intro(frm);
		_render_nexus_html(frm);
		_render_nexus_last_synced(frm);
		_render_product_tax_category_html(frm);
		_set_api_mode_description(frm);

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
