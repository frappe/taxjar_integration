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

// ── Pre-Upgrade Invoices tab ────────────────────────────────────────────
// Shown only on a site that ran TaxJar version 15 (legacy_cutoff_date is set by
// the mark_pre_upgrade_invoices patch). The check itself is legacy_check.py.
// Built from the desk's own components - alert, badge, progress, button and
// empty state - so the tab looks like every other TaxJar screen.

const LEGACY_CHECK = 'taxjar_integration.taxjar_integration.legacy_check';
const LEGACY_PROGRESS_EVENT = 'taxjar_legacy_check_progress';
const LEGACY_STATUS_THEMES = { Pending: 'gray', Running: 'blue', Done: 'green', Failed: 'red' };

function _refresh_legacy_tab(frm) {
	if (!frm.doc.legacy_cutoff_date || !frm.fields_dict.legacy_check_html) return;

	// Only the newest answer is drawn. A reload while a call is in flight
	// would otherwise let the older answer land last.
	const request = (frm._legacy_request = (frm._legacy_request || 0) + 1);
	frappe.call({ method: `${LEGACY_CHECK}.get_legacy_check_state` }).then((r) => {
		if (request !== frm._legacy_request || !r.message) return;
		_render_legacy_tab(frm, r.message);
	});
}

function _render_legacy_tab(frm, state) {
	frm._legacy_progress = {};

	frm.fields_dict.legacy_intro_html.$wrapper.html(frappe.ui.alert.html({
		title: __('Version 15 did not record which invoices it sent to TaxJar.'),
		description: __('This check asks TaxJar for its orders and refunds, and marks each old invoice as found or not found.'),
	}));

	const $companies = frm.fields_dict.legacy_check_html.$wrapper.empty();

	if (!state.companies.length) {
		frm.fields_dict.legacy_check_status_html.$wrapper.empty();
		frm.toggle_display('run_legacy_check_btn', false);
		$companies.append(frappe.ui.empty_state({
			icon: 'file-check',
			title: __('No invoices to check'),
			description: __('This site has no submitted invoices from before the upgrade on {0}. There is nothing to compare with TaxJar.', [frappe.datetime.str_to_user(state.cutoff_date)]),
		}));
		return;
	}

	frm.fields_dict.legacy_check_status_html.$wrapper.html(`
		<div class="form-group">
			<div class="clearfix"><label class="control-label">${__('Status')}</label></div>
			${frappe.ui.badge.html({ label: __(state.status), theme: LEGACY_STATUS_THEMES[state.status], size: 'lg' })}
		</div>
	`);

	_set_legacy_button(frm, state);
	$companies.append(_legacy_companies_table(frm, state));

	const $alerts = $('<div class="taxjar-legacy-alerts"></div>')
		.css({ display: 'grid', gap: 'var(--margin-sm)', 'margin-top': 'var(--margin-md)' })
		.appendTo($companies);
	_legacy_alerts(state).forEach((alert) => $alerts.append(alert));
}

function _set_legacy_button(frm, state) {
	const live = state.api_mode === 'Live';
	const running = state.status === 'Running';
	const first_run = state.status === 'Pending';

	let description = __('About 2 API calls per month of history for each company.');
	if (!live) description = __('Change API Mode to Live in TaxJar Setup to run the check.');
	else if (running) description = __('The check runs in the background. You can leave this page.');
	else if (!state.pending) description = __('Every invoice from before the upgrade is checked.');

	frm.toggle_display('run_legacy_check_btn', true);
	frm.set_df_property('run_legacy_check_btn', 'label', first_run ? __('Run Check') : __('Check Again'));
	frm.set_df_property('run_legacy_check_btn', 'description', description);
	// After set_df_property, which draws the button again.
	frm.fields_dict.run_legacy_check_btn.$input?.prop('disabled', !live || running || !state.pending);
}

function _legacy_companies_table(frm, state) {
	const $table = $(`
		<div class="table-responsive">
			<table class="table table-bordered" style="margin: 0;">
				<thead><tr>
					<th>${__('Company')}</th>
					<th>${__('Range')}</th>
					<th class="text-right">${__('Not checked')}</th>
					<th class="text-right">${__('Found')}</th>
					<th class="text-right">${__('Not found')}</th>
					<th class="text-right">${__('Cancelled, still in TaxJar')}</th>
					<th style="min-width: 180px;">${__('Result')}</th>
				</tr></thead>
				<tbody></tbody>
			</table>
		</div>
	`);
	const $body = $table.find('tbody');

	state.companies.forEach((row) => {
		const first_month = row.first_month || '';
		const range = first_month ? `${first_month} → ${state.cutoff_month}` : '—';
		const $row = $(`
			<tr>
				<td>${frappe.utils.escape_html(row.company)}</td>
				<td style="font-variant-numeric: tabular-nums;">${range}</td>
				<td class="text-right legacy-pending"></td>
				<td class="text-right legacy-found"></td>
				<td class="text-right legacy-not-found"></td>
				<td class="text-right legacy-stale"></td>
				<td class="legacy-result"></td>
			</tr>
		`).appendTo($body);

		const open = (tab) => _open_transactions(row.company, first_month, state.cutoff_date, tab);
		$row.find('.legacy-pending').append(_legacy_count(row.pending, () => open('not_applicable')));
		$row.find('.legacy-found').append(_legacy_count(row.found, () => open('synced')));
		$row.find('.legacy-not-found').append(_legacy_count(row.not_found, () => open('not_applicable')));
		$row.find('.legacy-stale').append(_legacy_count(row.cancelled_in_taxjar, () => open('failed')));
		$row.find('.legacy-result').append(_legacy_result(frm, state, row));
	});

	return $table;
}

function _legacy_count(value, onclick) {
	if (value === undefined || value === null) return $('<span class="text-muted">—</span>');
	if (!value) return $('<span class="text-muted">0</span>');
	return $('<a href="#" style="font-variant-numeric: tabular-nums;"></a>')
		.text(format_number(value, null, 0))
		.on('click', (e) => {
			e.preventDefault();
			onclick();
		});
}

function _legacy_result(frm, state, row) {
	if (row.pending && !row.has_credential) {
		return frappe.ui.badge.html({ label: __('No credential'), theme: 'amber' });
	}
	if (row.pending && state.api_mode !== 'Live') {
		return frappe.ui.badge.html({ label: __('Sandbox mode'), theme: 'amber' });
	}
	if (row.pending && state.status === 'Running') {
		const progress = { month: 0, months: 0 };
		progress.bar = frappe.ui.progress({
			value: 0,
			size: 'md',
			hint: () => (progress.months
				? __('Month {0} of {1}', [progress.month, progress.months])
				: __('Starting…')),
		});
		frm._legacy_progress[row.company] = progress;
		return progress.bar;
	}
	if (row.result === 'failed') {
		return frappe.ui.badge.html({ label: __('Failed'), theme: 'red', title: row.error || '' });
	}
	if (row.result === 'done' && !row.pending) {
		return frappe.ui.badge.html({ label: __('Done'), theme: 'green' });
	}
	return frappe.ui.badge.html({ label: __('Not checked') });
}

function _legacy_alerts(state) {
	const alerts = [];
	const open_setup = () => frappe.ui.button({
		label: __('Open TaxJar Setup'),
		icon: 'settings',
		size: 'sm',
		variant: 'outline',
		onclick: () => _open_setup_connection(),
	});
	const waiting = state.companies.filter((row) => row.pending);

	if (waiting.length && state.api_mode !== 'Live') {
		alerts.push(frappe.ui.alert({
			theme: 'yellow',
			title: __('The check runs in Live mode only.'),
			description: __('Version 15 sent sandbox invoices to the sandbox account. A match there does not prove that the live account has the invoice. Change API Mode to Live in TaxJar Setup, then run the check.'),
			footer: open_setup(),
		}));
		return alerts;
	}

	state.companies.forEach((row) => {
		if (row.result === 'failed' && row.pending) {
			alerts.push(frappe.ui.alert({
				theme: 'red',
				title: __('TaxJar did not answer the check for {0}.', [row.company]),
				description: __('{0} No invoice of this company changed. Check the live token in TaxJar Setup, then click Check Again.', [row.error || '']),
				footer: open_setup(),
			}));
		}

		if (row.cancelled_in_taxjar && !row.pending) {
			alerts.push(frappe.ui.alert({
				theme: 'yellow',
				title: __('{0} invoices of {1} are cancelled in ERPNext but are still in TaxJar.', [row.cancelled_in_taxjar, row.company]),
				description: __('Their status is Failed. Retry them on the Transaction Sync page to remove them from TaxJar.'),
				footer: frappe.ui.button({
					label: __('Open in Transaction Sync'),
					icon: 'external-link',
					size: 'sm',
					variant: 'outline',
					onclick: () => _open_transactions(row.company, row.first_month, state.cutoff_date, 'failed'),
				}),
			}));
		}

		if (row.pending && !row.has_credential) {
			alerts.push(frappe.ui.alert({
				theme: 'blue',
				title: __('{0} invoices of {1} are not checked.', [row.pending, row.company]),
				description: __('This company has no live token. Add one in TaxJar Setup, then run the check.'),
				footer: open_setup(),
			}));
		}
	});

	return alerts;
}

// The Connection card holds the token and the API mode. frappe.set_route puts
// route_options in the URL, and the setup page reads `focus` from there.
function _open_setup_connection() {
	frappe.route_options = { focus: 'connect' };
	frappe.set_route('taxjar-setup');
}

function _open_transactions(company, first_month, cutoff_date, tab) {
	// set_route writes these into the URL, where an undefined value would
	// arrive as the word "undefined".
	frappe.route_options = { company, to_date: cutoff_date, tab };
	if (first_month) frappe.route_options.from_date = `${first_month}-01`;
	frappe.set_route('taxjar-transactions');
}

function _on_legacy_progress(frm, message) {
	if (message.done) {
		frm.reload_doc();
		return;
	}
	const progress = frm._legacy_progress?.[message.company];
	if (!progress) return;
	progress.month = message.month;
	progress.months = message.months;
	progress.bar.data('es-progress')?.set_value(Math.round((message.month / message.months) * 100));
}

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
		_refresh_legacy_tab(frm);

		if (!frm._legacy_listener) {
			frm._legacy_listener = (message) => _on_legacy_progress(frm, message);
			frappe.realtime.on(LEGACY_PROGRESS_EVENT, frm._legacy_listener);
		}

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

	run_legacy_check_btn(frm) {
		frappe.call({
			method: `${LEGACY_CHECK}.run_legacy_check`,
			type: 'POST',
			freeze: true,
			callback: () => frm.reload_doc(),
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
