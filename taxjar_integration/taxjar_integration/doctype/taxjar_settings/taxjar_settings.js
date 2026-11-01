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

// ── Migration tab ──────────────────────────────────────────────────────
// Shown on every site. Only a site upgraded from TaxJar version 15 has invoices
// to check: the mark_pre_upgrade_invoices patch sets legacy_cutoff_date and
// marks them. Every other site sees "Not needed".
// The check itself is legacy_check.py.
// Built from the desk's own components (Component Explorer,
// /desk/system/component-explorer): badge, button, divider, tooltip, alert,
// empty state and read-only controls. The table is the desk's .table, since
// there is no table component.

const LEGACY_CHECK = 'taxjar_integration.taxjar_integration.legacy_check';
const LEGACY_PROGRESS_EVENT = 'taxjar_legacy_check_progress';

function _refresh_legacy_tab(frm) {
	if (!frm.fields_dict.legacy_check_html) return;

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
	const $root = frm.fields_dict.legacy_check_html.$wrapper.empty();
	const $view = $('<div></div>')
		.css({ display: 'flex', 'flex-direction': 'column', gap: 'var(--margin-lg)', 'margin-bottom': 'var(--margin-xl)' })
		.appendTo($root);

	// No upgrade date: this site never ran version 15.
	if (!state.cutoff_date) {
		$view.append(_legacy_header({}));
		$view.append(frappe.ui.alert({
			variant: 'outline',
			icon: 'circle-check',
			title: __('Nothing to check on this site'),
			description: __("This site didn't upgrade from TaxJar v15, so there are no older invoices to compare. Invoices created in this version are tracked automatically."),
		}));
		return;
	}

	// Upgraded from version 15, with no submitted invoice before the upgrade.
	if (!state.companies.length) {
		$view.append(_legacy_header({}));
		$view.append(frappe.ui.empty_state({
			icon: 'file-check',
			title: __('No invoices to check'),
			description: __('This site has no submitted invoices from before the upgrade on {0}. There is nothing to compare with TaxJar.', [frappe.datetime.str_to_user(state.cutoff_date)]),
		}));
		return;
	}

	$view.append(_legacy_header({ action: _legacy_run_action(frm, state) }));
	$view.append(frappe.ui.divider());
	$view.append(_legacy_dates(state));
	$view.append(_legacy_companies(frm, state));
}

// Title and description on the left; the Run check button on the right.
// Wraps under the text on a narrow screen.
function _legacy_header({ action }) {
	const $header = $(`
		<div style="display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: var(--margin-lg);">
			<div style="display: flex; flex-direction: column; gap: var(--margin-sm); max-width: 620px;">
				<div style="font-size: var(--text-lg); font-weight: 600; color: var(--ink-gray-9);">${__('TaxJar Invoice Sync Status')}</div>
				<div style="font-size: var(--text-base); line-height: 1.55; color: var(--ink-gray-6);">
					${__('Fetch the transaction sync status from TaxJar for the invoices submitted before migration.')}
				</div>
			</div>
		</div>
	`);
	if (action) $header.append(action);
	return $header;
}

function _legacy_run_action(frm, state) {
	const live = state.api_mode === 'Live';
	const running = state.status === 'Running';

	// Why the button is disabled. A disabled button gets no pointer events,
	// so the tooltip sits on a wrapper around it.
	let reason = '';
	if (!frm.perm?.[0]?.write) reason = __('A TaxJar Manager can run the check.');
	else if (!live) reason = __('Change API Mode to Live in TaxJar Setup to run the check.');
	else if (running) reason = __('The check runs in the background. You can leave this page.');
	else if (!state.pending) reason = __('Every invoice from before the upgrade is checked.');

	const $action = $('<span></span>').css({ flex: 'none', display: 'inline-flex' });
	frappe.ui.button({
		label: state.status === 'Pending' ? __('Run check') : __('Run again'),
		loading_label: __('Checking…'),
		variant: 'subtle',
		size: 'md',
		loading: running,
		disabled: Boolean(reason),
		onclick: () => _run_legacy_check(frm),
	}).appendTo($action);
	if (reason) frappe.ui.tooltip($action, { text: reason, side: 'left' });
	return $action;
}

function _run_legacy_check(frm) {
	return frappe.call({
		method: `${LEGACY_CHECK}.run_legacy_check`,
		type: 'POST',
	}).then(() => frm.reload_doc());
}

// Real read-only controls, so the two values look like every other field.
function _legacy_dates(state) {
	const $dates = $('<div></div>').css({
		display: 'grid', 'grid-template-columns': 'repeat(auto-fit, minmax(240px, 1fr))', gap: 'var(--margin-lg)',
	});
	const fields = [
		{
			fieldtype: 'Date',
			label: __('Upgrade Date'),
			value: state.cutoff_date,
			tooltip: __('When this site moved from TaxJar v15. Invoices before this date are checked.'),
		},
		{ fieldtype: 'Datetime', label: __('Last Checked'), value: state.last_run },
	];
	for (const { value, tooltip, ...df } of fields) {
		const control = frappe.ui.form.make_control({
			df: { ...df, fieldname: frappe.scrub(df.label), read_only: 1 },
			parent: $('<div></div>').appendTo($dates),
			render_input: true,
		});
		control.set_value(value || '');
		if (!value) control.$wrapper.find('.control-value').text(__('Never'));
		if (tooltip) frappe.ui.tooltip(control.$wrapper, { text: tooltip });
	}
	return $dates;
}

function _legacy_companies(frm, state) {
	const $section = $('<div style="display: flex; flex-direction: column; gap: var(--margin-md);"></div>');
	$section.append(_legacy_companies_table(frm, state));
	// What needs attention, under the numbers it explains.
	const alerts = _legacy_alerts(state);
	if (alerts.length) {
		$('<div></div>').css({ display: 'grid', gap: 'var(--margin-sm)' }).append(alerts).appendTo($section);
	}
	return $section;
}

function _legacy_total(row) {
	// A finished company keeps its counts in the summary, and none of its
	// invoices wait any longer. The other results only repeat the pending count.
	return (row.pending || 0) + (row.result === 'done' ? (row.checked || 0) : 0);
}

function _legacy_period(first_month, cutoff_month) {
	if (!first_month) return '-';
	const label = (month) => moment(month, 'YYYY-MM').format('MMM YYYY');
	return first_month === cutoff_month ? label(first_month) : `${label(first_month)} – ${label(cutoff_month)}`;
}

function _legacy_companies_table(frm, state) {
	const $table = $(`
		<div class="table-responsive" style="margin: 0; border: 1px solid var(--outline-gray-2); border-radius: var(--radius-lg);">
			<table class="table" style="margin: 0; min-width: 720px; font-variant-numeric: tabular-nums;">
				<thead style="background: var(--surface-gray-1);"><tr>
					<th>${__('Company')}</th>
					<th>${__('Period')}</th>
					<th class="text-right">${__('Invoices')}</th>
					<th class="text-right">${__('Found')}</th>
					<th class="text-right">${__('Not Found')}</th>
					<th class="text-right legacy-stale-head">${__('Stale in TaxJar')}</th>
					<th>${__('Result')}</th>
				</tr></thead>
				<tbody></tbody>
			</table>
		</div>
	`);
	frappe.ui.tooltip($table.find('.legacy-stale-head'), { text: __('Cancelled in ERPNext but still present in TaxJar') });
	const $body = $table.find('tbody');

	state.companies.forEach((row) => {
		const first_month = row.first_month || '';
		const finished = row.result === 'done' && !row.pending;
		const $row = $(`
			<tr>
				<td style="font-weight: 500;"></td>
				<td class="text-muted">${_legacy_period(first_month, state.cutoff_month)}</td>
				<td class="text-right">${format_number(_legacy_total(row), null, 0)}</td>
				<td class="text-right legacy-found"></td>
				<td class="text-right legacy-not-found"></td>
				<td class="text-right legacy-stale"></td>
				<td class="legacy-result"></td>
			</tr>
		`).appendTo($body);
		$row.find('td').first().text(row.company);

		const open = (tab) => _open_transactions(row.company, tab);
		$row.find('.legacy-found').append(_legacy_count(finished, row.found, () => open('synced')));
		$row.find('.legacy-not-found').append(
			_legacy_count(finished, row.not_found, () => open('not_applicable'), 'var(--ink-red-8)')
		);
		$row.find('.legacy-stale').append(
			_legacy_count(finished, row.cancelled_in_taxjar, () => open('failed'), 'var(--ink-amber-8)')
		);
		$row.find('.legacy-result').append(_legacy_result(frm, state, row, finished));
	});

	return $table;
}

// A dash until the company is checked. A count above zero opens those invoices
// on the Transaction Sync page.
function _legacy_count(finished, value, onclick, color) {
	if (!finished) return $('<span class="text-muted">-</span>');
	if (!value) return $('<span class="text-muted">0</span>');
	return $('<a href="#"></a>')
		.css({ 'font-weight': 500, color: color || '' })
		.text(format_number(value, null, 0))
		.on('click', (e) => {
			e.preventDefault();
			onclick();
		});
}

function _legacy_result(frm, state, row, finished) {
	if (row.pending && !row.has_credential) {
		return frappe.ui.badge({ label: __('No Credential'), theme: 'amber' });
	}
	if (row.pending && state.api_mode !== 'Live') {
		return frappe.ui.badge({ label: __('Sandbox Mode'), theme: 'amber' });
	}
	if (row.pending && state.status === 'Running') {
		// "Not checked" until the job reports its first month for this company.
		const $cell = $('<span></span>').append(frappe.ui.badge({ label: __('Not Checked') }));
		frm._legacy_progress[row.company] = $cell;
		return $cell;
	}
	if (row.result === 'failed') {
		return frappe.ui.badge({ label: __('Failed'), theme: 'red', title: row.error || '' });
	}
	if (finished) {
		return row.not_found || row.cancelled_in_taxjar
			? frappe.ui.badge({ label: __('Needs Review'), theme: 'red' })
			: frappe.ui.badge({ label: __('All Found'), theme: 'green' });
	}
	return frappe.ui.badge({ label: __('Not Checked') });
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
			title: __('The check runs in Live mode only'),
			description: __('Change API Mode to Live in TaxJar Setup, then run the check.'),
			footer: open_setup(),
		}));
		return alerts;
	}

	state.companies.forEach((row) => {
		if (row.result === 'failed' && row.pending) {
			// TaxJar's answer on one line, what to do on the next.
			const $failed = frappe.ui.alert({
				theme: 'red',
				title: __('{0}: TaxJar did not answer the check', [row.company]),
				description: [row.error || '', __('Check the live token in TaxJar Setup, then click Run again.')]
					.filter(Boolean)
					.join('\n'),
				footer: open_setup(),
			});
			$failed.find('.es-alert__description').css('white-space', 'pre-line');
			alerts.push($failed);
		}

		if (!row.pending && (row.not_found || row.cancelled_in_taxjar)) {
			alerts.push(_legacy_review_alert(row));
		}

		if (row.pending && !row.has_credential) {
			const $no_token = frappe.ui.alert({
				theme: 'blue',
				title: __('{0}: No live token', [row.company]),
				description: [
					__('Not Checked: {0}', [row.pending === 1 ? __('1 invoice') : __('{0} invoices', [row.pending])]),
					__('Add a live token in TaxJar Setup, then run the check.'),
				].join('\n'),
				footer: open_setup(),
			});
			$no_token.find('.es-alert__description').css('white-space', 'pre-line');
			alerts.push($no_token);
		}
	});

	return alerts;
}

// One alert for each company the check flagged, with a button for each list.
function _legacy_review_alert(row) {
	const open = (tab) => _open_transactions(row.company, tab);
	const $buttons = $('<div></div>').css({ display: 'flex', 'flex-wrap': 'wrap', gap: 'var(--margin-sm)' });
	const button = (label, tab) => frappe.ui.button({
		label, icon: 'external-link', size: 'sm', variant: 'outline', onclick: () => open(tab),
	}).appendTo($buttons);
	const invoices = (count) => (count === 1 ? __('1 invoice') : __('{0} invoices', [count]));

	if (row.not_found) button(__('Show not found'), 'not_applicable');
	if (row.cancelled_in_taxjar) button(__('Show stale'), 'failed');

	// The title names the issue. The description gives the count on one line;
	// one issue adds what to do on the next.
	let title, description;
	if (row.not_found && row.cancelled_in_taxjar) {
		title = __('{0}: Invoices need review', [row.company]);
		description = [
			__('Not in TaxJar: {0}', [invoices(row.not_found)]),
			__('Cancelled in ERPNext, but active in TaxJar: {0}', [invoices(row.cancelled_in_taxjar)]),
		].join('\n');
	} else if (row.not_found) {
		title = __('{0}: Invoices not found in TaxJar', [row.company]);
		description = [
			__('Not in TaxJar: {0}', [invoices(row.not_found)]),
			__('Please open the transaction & sync with TaxJar.'),
		].join('\n');
	} else {
		title = __('{0}: Cancelled invoices still in TaxJar', [row.company]);
		description = [
			__('Cancelled in ERPNext, but active in TaxJar: {0}', [invoices(row.cancelled_in_taxjar)]),
			row.cancelled_in_taxjar === 1
				? __('Retry it on the Transaction Sync page to remove it.')
				: __('Retry them on the Transaction Sync page to remove them.'),
		].join('\n');
	}

	const $alert = frappe.ui.alert({ theme: 'yellow', title, description, footer: $buttons });
	// The description is escaped text, so the list's line break needs pre-line to show.
	$alert.find('.es-alert__description').css('white-space', 'pre-line');
	return $alert;
}

// The Connection card holds the token and the API mode. frappe.set_route puts
// route_options in the URL, and the setup page reads `focus` from there.
function _open_setup_connection() {
	frappe.route_options = { focus: 'connect' };
	frappe.set_route('taxjar-setup');
}

function _open_transactions(company, tab) {
	// pre_upgrade keeps the invoices the check answered. A date range cannot:
	// the check groups invoices by creation month, and the page filters on
	// posting date.
	frappe.route_options = { company, tab, pre_upgrade: 1 };
	frappe.set_route('taxjar-transactions');
}

function _on_legacy_progress(frm, message) {
	if (message.done) {
		frm.reload_doc();
		return;
	}
	const $cell = frm._legacy_progress?.[message.company];
	if (!$cell) return;
	$cell.empty().append(frappe.ui.badge({
		label: __('Checking…'),
		theme: 'blue',
		title: __('Month {0} of {1}', [message.month, message.months]),
	}));
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

		const account_query = (root_type) => (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return { filters: { company: row.company, is_group: 0, root_type } };
		};
		frm.set_query('tax_account_head', 'company_config', account_query('Liability'));
		frm.set_query('shipping_account_head', 'company_config', account_query(['in', ['Income', 'Expense']]));
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
