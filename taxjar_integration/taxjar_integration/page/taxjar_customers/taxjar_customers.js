// Data fetch lives in on_page_show, not the constructor - see the comment at
// the top of taxjar_transactions.js for why (cached desk pages, and the first
// on_page_show firing straight after on_page_load).
frappe.pages["taxjar-customers"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("TaxJar Customer Configuration"),
		single_column: true,
	});

	wrapper.taxjar_customers = new TaxJarCustomerConfig(page);
	$(wrapper).on("hide", () => wrapper.taxjar_customers.on_hide());
};

frappe.pages["taxjar-customers"].on_page_show = function (wrapper) {
	wrapper.taxjar_customers.on_show();
};

const EXEMPTION_OPTIONS = ["", "Wholesale", "Government", "Non Exempt", "Other"];

const STATUS_COLORS = {
	Synced: "green",
	Failed: "red",
	Queued: "blue",
};

const SYNC_UPDATE_EVENT = "taxjar_customers_update";

// Whether an exemption is configured is the tab, not a filter - so there is
// only ever one way to express it. "Non Exempt" is a configured answer, not
// an exemption, so it gets its own tab rather than folding into Exempted or
// Not Configured - see _NON_EXEMPT on the server.
const ALL_TAB = "all";
const EXEMPT_TAB = "exempt";
const NON_EXEMPT_TAB = "non_exempt";
const NOT_CONFIGURED_TAB = "not_configured";

const TABS = [
	{ name: ALL_TAB, label: __("All"), is_active: true },
	{ name: EXEMPT_TAB, label: __("Exempted") },
	{ name: NON_EXEMPT_TAB, label: __("Non-Exempted") },
	{ name: NOT_CONFIGURED_TAB, label: __("Not Configured") },
];

// Header search fields. Every one is a LIKE term the server resolves against
// its own allowlist (_SEARCHABLE_COLUMNS), so the fieldname must match the
// Customer column it searches.
const SEARCH_FIELDS = [
	{ fieldname: "customer_name", label: __("Customer Name"), fieldtype: "Data" },
	{
		fieldname: "customer_group",
		label: __("Customer Group"),
		fieldtype: "Link",
		options: "Customer Group",
	},
	{ fieldname: "taxjar_customer_id", label: __("TaxJar Customer ID"), fieldtype: "Data" },
];

class TaxJarCustomerConfig {
	constructor(page) {
		this.page = page;
		this.current_page = 1;
		this.page_size = 20;
		this.active_tab = ALL_TAB;
		this.status_filter = null;

		// Same reasoning as taxjar_transactions.js: one stable reference so
		// off() can detach it, debounced so a bulk sync of N customers doesn't
		// fire N refreshes.
		this._on_sync_update = frappe.utils.debounce(() => this.refresh(), 500);

		this.make_filters();
		this.make_summary();
		this.make_tabs();
		this.make_not_configured_panel();
	}

	on_show() {
		frappe.realtime.doctype_subscribe("Customer");
		frappe.realtime.off(SYNC_UPDATE_EVENT, this._on_sync_update);
		frappe.realtime.on(SYNC_UPDATE_EVENT, this._on_sync_update);
		this.refresh();
	}

	// Detaches the handler without doctype_unsubscribe - see on_hide() in
	// taxjar_transactions.js for why leaving the room would be unsafe.
	on_hide() {
		frappe.realtime.off(SYNC_UPDATE_EVENT, this._on_sync_update);
		this._on_sync_update.cancel();
		this._hide_sync_popover();
	}

	// ── Shell ─────────────────────────────────────────────────────────────

	// page.add_field() puts these in the desk's own header filter row. They
	// narrow the whole result set server-side, not the loaded page - with
	// 20-row pages, searching a customer who is on page 3 would otherwise
	// silently report nothing found.
	make_filters() {
		this.filter_controls = {};

		for (const df of SEARCH_FIELDS) {
			this.filter_controls[df.fieldname] = this.page.add_field({
				...df,
				change: () => {
					this.current_page = 1;
					this.reset_selection();
					this.refresh();
				},
			});
		}
	}

	make_summary() {
		this.summary_area = $('<div class="taxjar-summary"></div>').appendTo(this.page.main);
	}

	// frappe.ui.tabs, not a frappe.ui.FieldGroup of Tab Break fields - the
	// latter needed a form Layout to fight (hidden-field workarounds, an
	// event-delegation dodge, see the pre-Espresso comments this replaced),
	// none of which a real tabs component needs. Each tab's `content` is a
	// function that builds and caches this page's own table wrapper div,
	// mirroring the lazy build-once-per-tab pattern this page already used.
	make_tabs() {
		this.tabs_wrapper = $('<div class="taxjar-page-tabs"></div>').appendTo(this.page.main);
		this.tab_content_wrappers = {};

		this.tabsInstance = new frappe.ui.Tabs({
			tabs: TABS.map((tab) => ({
				label: tab.label,
				content: () => {
					const $wrapper = $('<div class="taxjar-tab-panel"></div>');
					this.tab_content_wrappers[tab.name] = $wrapper;
					return $wrapper;
				},
			})),
			on_change: (index) => {
				this.enter_tab(TABS[index].name);
				this.refresh();
			},
		});
		this.tabs_wrapper.append(this.tabsInstance.$el);

		this.make_tab_actions();

		this.paginator = new taxjar_integration.Paginator({
			$wrapper: $('<div class="taxjar-pagination"></div>').appendTo(this.page.main),
			on_page: (page) => {
				this.current_page = page;
				this.reset_selection();
				this.refresh();
			},
			on_page_size: (size) => {
				this.page_size = size;
				this.current_page = 1;
				this.reset_selection();
				this.refresh();
			},
		});
	}

	// Built detached; render_table() moves it above the active tab's table.
	make_tab_actions() {
		this.$tab_actions = $('<div class="taxjar-tab-actions"></div>');
		this.$selection_count = $('<span class="taxjar-selection-count"></span>').appendTo(this.$tab_actions);

		this.bulk_action = new taxjar_integration.BulkActionButton({
			$wrapper: this.$tab_actions,
			label: __("Bulk Action"),
		});
	}

	enter_tab(name) {
		this.active_tab = name;
		this.current_page = 1;
		this.status_filter = null;
		this.reset_selection();
		// Each tab's own card is its indicator - the card keys are the tab names.
		this.summary?.set_active(name);
	}

	// silent: true - enter_tab() runs the state side of the switch itself,
	// and every go_to_tab() caller already calls refresh() right after; without
	// it, set_active()'s on_change would fire a second, redundant refresh.
	go_to_tab(name) {
		this.tabsInstance.set_active(TABS.findIndex((t) => t.name === name), { silent: true });
		this.enter_tab(name);
	}

	make_not_configured_panel() {
		this.not_configured_panel = $('<div class="taxjar-not-configured"></div>')
			.hide()
			.appendTo(this.page.main);
	}

	show_not_configured() {
		this.summary_area.hide();
		this.tabs_wrapper.hide();
		this.paginator.$wrapper.hide();
		taxjar_integration.render_not_configured_panel(this.not_configured_panel);
		this.not_configured_panel.show();
	}

	hide_not_configured() {
		this.not_configured_panel.hide();
		this.summary_area.show();
		this.tabs_wrapper.show();
		this.paginator.$wrapper.show();
	}

	// ── Data ──────────────────────────────────────────────────────────────

	// What the page is scoped to. The summary counts describe exactly this
	// population - the status drill-down is deliberately not part of it.
	get_scope_filters() {
		const filters = {};
		const search = {};

		for (const [fieldname, control] of Object.entries(this.filter_controls)) {
			const value = control.get_value();
			if (value) search[fieldname] = value;
		}

		if (Object.keys(search).length) filters.search = search;

		return filters;
	}

	// The scope plus the status drill-down, which only the table honours -
	// feeding it to the summary would collapse every other number to zero the
	// moment you clicked one.
	get_filters() {
		const filters = this.get_scope_filters();

		if (this.status_filter) filters.sync_status = this.status_filter;

		return filters;
	}

	refresh() {
		const filters = this.get_filters();

		Promise.all([
			frappe.xcall(
				"taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.get_customers",
				{ filters, page: this.current_page, scope: this.active_tab, page_size: this.page_size }
			),
			frappe.xcall(
				"taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.get_summary",
				{ filters: this.get_scope_filters() }
			),
		]).then(([data, summary]) => {
			if (data.not_configured) {
				this.show_not_configured();
				return;
			}
			this.hide_not_configured();
			this.customers = data.customers;
			this.render_summary(summary);
			this.render_table();
			this.paginator.render(data);
			this.update_bulk_state();
		});
	}

	// The four group captions are the four tabs, so clicking one switches
	// tab; the sync statuses inside the Exemptions group filter within it.
	render_summary(summary) {
		const groups = [
			{
				label: __("Total Customers"),
				cards: [{ value: summary.total, value_key: ALL_TAB }],
			},
			{
				label: __("Exemptions"),
				cards: [
					{ label: __("Synced"), value: summary.exempt.synced, value_key: "Synced", indicator: "green" },
					{ label: __("Queued"), value: summary.exempt.queued, value_key: "Queued", indicator: "blue" },
					{ label: __("Failed"), value: summary.exempt.failed, value_key: "Failed", indicator: "red" },
				],
			},
			{
				label: __("Non-Exempted"),
				cards: [{ value: summary.non_exempt, value_key: NON_EXEMPT_TAB }],
			},
			{
				label: __("Not Configured"),
				cards: [
					{ value: summary.not_configured, value_key: NOT_CONFIGURED_TAB },
				],
			},
		];

		if (!this.summary) {
			this.summary = new taxjar_integration.SummaryStrip({
				$wrapper: this.summary_area,
				groups,
				on_select: (card) => this.on_summary_select(card),
			});
			this.summary.set_active(this.active_tab);
			return;
		}

		const active = this.summary.active_key;
		this.summary.update(groups);
		this.summary.set_active(active);
	}

	on_summary_select(card) {
		const tab = TABS.map((t) => t.name).find((name) => name === card?.value_key);
		if (tab) {
			this.go_to_tab(tab);
			this.refresh();
			return;
		}

		// A sync status only describes an exempt customer, so drill into the
		// Exemptions tab alongside it.
		if (this.active_tab !== EXEMPT_TAB) this.go_to_tab(EXEMPT_TAB);
		this.status_filter = card?.value_key || null;
		this.summary.set_active(this.status_filter);
		this.current_page = 1;
		this.reset_selection();
		this.refresh();
	}

	// ── Table ─────────────────────────────────────────────────────────────

	get_columns() {
		const columns = [
			{
				label: __("Customer Name"),
				fieldname: "customer_name",
				_html: (value, row) =>
					`<a href="/app/customer/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(
						value || row.name
					)}</a>`,
			},
			{
				label: __("TaxJar Customer ID"),
				fieldname: "taxjar_customer_id",
				width: 170,
				// Empty means no successful create in TaxJar yet - a dash,
				// same as every other empty cell in this table, rather than
				// a word that reads as its own status.
				_html: (value) =>
					value
						? `<span class="taxjar-customer-id">${frappe.utils.escape_html(value)}</span>`
						: `<span class="text-muted">-</span>`,
			},
			{
				label: __("Customer Group"), fieldname: "customer_group", width: 160,
				_html: (value) => frappe.utils.escape_html(value || "-"),
			},
		];

		columns.push({
			label: __("Exemption Type"),
			fieldname: "taxjar_exemption_type",
			width: 180,
			// Read-only: a region-scoped exemption type needs at least
			// one exempt region to be a valid save (see
			// _validate_exempt_regions on the server), so type can no
			// longer be set on its own here. The pencil in the
			// Configure cell is the only way to change it, since that's
			// the one path that carries both fields into one Apply.
			_html: (value) => this.render_exemption_type_cell(value),
		});

		columns.push({
			label: __("Sync Status"),
			fieldname: "taxjar_customer_sync_status",
			width: 120,
			_html: (value, row) => this.render_sync_status_cell(row),
		});

		// Kept after Sync Status: sync state describes what's already been
		// sent, so it reads before the control that changes what's sent next.
		// This is the one path that lets a not-configured row be configured
		// without first selecting it for the bulk action.
		columns.push({
			label: __("Configure"),
			fieldname: "exempt_region_count",
			width: 110,
			align: "center",
			_html: (value, row) => this.render_regions_cell(row),
		});

		return columns;
	}

	// Plain text, not a badge - blank is a common enough state (it's what
	// the whole Not Configured tab is) that a colored pill on every row read
	// as noisier status signalling than this column actually carries. A
	// dash, same as every other empty cell in this table, rather than the
	// word "Not Configured" repeating what the tab itself already says.
	render_exemption_type_cell(value) {
		return value
			? frappe.utils.escape_html(value)
			: `<span class="text-muted">-</span>`;
	}

	// The pencil is on every row, including rows with no exemption type - it
	// is the only way to set one, so it can never read as "nothing to do
	// here". The desk's own icon rather than a text glyph, whose size and
	// baseline shift from platform to platform. "square-pen", not "edit":
	// frappe.utils.icon() builds a <use href="#icon-{name}">, and an unknown
	// name resolves to nothing and renders blank rather than failing loudly -
	// which is exactly what "edit", absent from frappe's sprite, did here.
	render_regions_cell(row) {
		const count = row.exempt_region_count || 0;

		// The count span always renders, blank or not - a fixed-width slot
		// (see .taxjar-region-count in the stylesheet) keeps the pencil icon
		// planted in the same spot whether the row has 0, 1, or 2+ regions,
		// instead of the icon visibly shifting with the digit count.
		return `<button type="button"
			class="taxjar-configure-link"
			data-customer="${frappe.utils.escape_html(row.name)}"
			title="${__("Configure exemption")}"
			><span class="taxjar-region-count">${count || ""}</span>${frappe.utils.icon("square-pen", "sm")}</button>`;
	}

	// Failed pairs the pill with a separate info icon (never nested inside the
	// pill) carrying the error, since the pill text alone doesn't say why -
	// same split as the Sync Status column on the Transaction Sync page.
	// Queued and Synced say all they have to say in the pill itself.
	render_sync_status_cell(row) {
		const status = row.taxjar_customer_sync_status;
		const color = STATUS_COLORS[status];
		// No exemption configured yet means no TaxJar customer has been
		// created to sync in the first place - a state worth naming rather
		// than an empty cell, same as the TaxJar Customer ID column above.
		if (!color) return frappe.ui.badge.html({ label: __("NA"), theme: "gray" });

		const pill = frappe.ui.badge.html({ label: __(status), theme: color });
		if (status !== "Failed") return pill;

		const info_text = row.taxjar_customer_sync_error || __("Unknown error");
		const icon = `<button type="button" class="taxjar-sync-icon taxjar-sync-trigger" data-info="${frappe.utils.escape_html(
			info_text
		)}">${frappe.utils.icon("info", "sm")}</button>`;
		return `${pill}${icon}`;
	}

	// Delegated once per table (rather than rebound on every render) so it
	// keeps working across re-renders. Shows immediately on hover - no
	// native-tooltip delay - and also toggles on click, since hover never
	// fires on touch devices. Own small copy rather than shared with the
	// Transaction Sync page's identical pattern - see the note on
	// taxjar_integration.render_sync_status_sidebar_pill for why.
	bind_sync_popover($wrapper) {
		$wrapper.on("mouseenter", ".taxjar-sync-trigger", (e) =>
			this._show_sync_popover($(e.currentTarget))
		);
		$wrapper.on("mouseleave", ".taxjar-sync-trigger", () => this._hide_sync_popover());
		$wrapper.on("click", ".taxjar-sync-trigger", (e) => {
			e.stopPropagation();
			this._show_sync_popover($(e.currentTarget));
		});
	}

	_show_sync_popover($trigger) {
		this._hide_sync_popover();
		const text = $trigger.attr("data-info") || "";
		const $pop = $(`<div class="taxjar-sync-pop">${frappe.utils.escape_html(text)}</div>`).appendTo("body");
		// position: fixed + getBoundingClientRect() are both viewport-relative,
		// so no scroll-offset math is needed here. Sync Status is the table's
		// last column, right up against the viewport edge, so the popover's
		// own width is clamped back on-screen rather than just using rect.left.
		const rect = $trigger[0].getBoundingClientRect();
		const pop_width = $pop.outerWidth();
		const left = Math.min(rect.left, window.innerWidth - pop_width - 12);
		$pop.css({ top: rect.bottom + 6, left: Math.max(12, left) });
		this._active_pop = $pop;
		$(document).on("click.taxjarCustomerSyncPop", () => this._hide_sync_popover());
	}

	_hide_sync_popover() {
		if (this._active_pop) {
			this._active_pop.remove();
			this._active_pop = null;
		}
		$(document).off("click.taxjarCustomerSyncPop");
	}

	// One DataTable per tab: the columns differ between them, and each tab
	// has its own content wrapper (see make_tabs()) to render into. Brings
	// this table to parity with the Transaction Sync page's own table, which
	// already uses DataTableManager instead of a hand-rolled <table> -
	// checkbox column, select-all, and inline filtering all come from
	// frappe.DataTable itself rather than being re-implemented here.
	render_table() {
		const $table_wrapper = this.tab_content_wrappers[this.active_tab];
		const key = this.active_tab;

		if (!this.datatables) this.datatables = {};

		if (!this.datatables[key]) {
			this.datatables[key] = new taxjar_integration.DataTableManager({
				$wrapper: $table_wrapper,
				columns: this.get_columns(),
				data: this.customers,
				options: {
					checkboxColumn: true,
					// This page's search lives in the header fields
					// (make_filters()), not a second, unwired inline filter
					// row - DataTableManager's own on_filter_change wiring
					// is what the Transaction Sync page uses instead, since
					// it has no header search fields of its own.
					inlineFilters: false,
					noDataMessage: __("No customers found"),
				},
				on_check_row: () => this.update_bulk_state(),
			});
			this.bind_row_actions($table_wrapper);
			this.bind_sync_popover($table_wrapper);
		} else {
			this.datatables[key].refresh(this.customers);
		}

		// Move rather than copy, so the one instance of each - handlers and all
		// - follows whichever tab is showing. Both live inside the table
		// wrapper so they share its padding and line up with the table's edges
		// instead of merely happening to sit at the same inset.
		this.$tab_actions.prependTo($table_wrapper);
		this.paginator.$wrapper.appendTo($table_wrapper);
	}

	get datatable() {
		return this.datatables?.[this.active_tab];
	}

	// Delegated once per tab wrapper so it survives every DataTable redraw.
	// Exemption Type is read-only here - the pencil is the only way to change
	// it, and it always opens the combined dialog so type and regions are
	// applied together in one save.
	bind_row_actions($wrapper) {
		$wrapper.on("click", ".taxjar-configure-link", (e) => {
			e.preventDefault();
			const name = $(e.currentTarget).attr("data-customer");
			const row = (this.customers || []).find((c) => c.name === name);
			if (!row) return;

			this.open_configure_dialog([row]);
		});
	}

	// ── Selection ─────────────────────────────────────────────────────────

	// Scoped to the rows on screen. A selection that outlived the page it was
	// made on would leave the count claiming rows nobody can see, and the bulk
	// actions acting on them - so every navigation clears it.
	reset_selection() {
		this.datatable?.clear_checked_items();
	}

	get_checked() {
		return this.datatable?.get_checked_items().filter(Boolean) || [];
	}

	// ── Bulk actions ──────────────────────────────────────────────────────

	update_bulk_state() {
		const checked = this.get_checked();
		const failed = checked.filter((row) => row.taxjar_customer_sync_status === "Failed");

		this.$selection_count.text(checked.length ? __("{0} selected", [checked.length]) : "");

		if (!checked.length) {
			this.bulk_action.disabled_title = __("Select one or more records to run an action");
			this.bulk_action.set_items([]);
			return;
		}

		const items = [
			{
				label: __("Configure Exemption…"),
				action: () => this.open_configure_dialog(checked),
			},
		];

		// Clearing is a no-op on a tab where nothing has an exemption.
		if (this.active_tab !== NOT_CONFIGURED_TAB) {
			items.push({ label: __("Clear Exemption"), action: () => this.clear_exemption(checked) });
		}

		if (failed.length) {
			items.push({ divider: true });
			items.push({
				label: __("Resync with TaxJar"),
				action: () => this.retry_failed(failed),
			});
		}

		this.bulk_action.set_items(items);
	}

	clear_exemption(rows) {
		frappe
			.xcall(
				"taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.bulk_clear_exemption",
				{ customers: rows.map((r) => r.name) }
			)
			.then((r) => {
				frappe.show_alert({
					message: __("Exemption cleared for {0} customers", [r.updated]),
					indicator: "green",
				});
				this.after_bulk_action();
			});
	}

	retry_failed(rows) {
		frappe
			.xcall(
				"taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.bulk_sync_to_taxjar",
				{ customers: rows.map((r) => r.name) }
			)
			.then((r) => {
				frappe.show_alert({
					message: __("{0} customers queued for sync", [r.queued]),
					indicator: "blue",
				});
				this.after_bulk_action();
			});
	}

	after_bulk_action() {
		this.reset_selection();
		this.refresh();
	}

	// ── Configure Exemption dialog ────────────────────────────────────────

	// Type and regions in one dialog: they are one decision, and splitting
	// them is what previously let a customer keep exempt regions after its
	// exemption type was cleared.
	open_configure_dialog(rows) {
		const single = rows.length === 1 ? rows[0] : null;

		const prefill_regions = single
			? frappe.xcall(
					"taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.get_exempt_regions",
					{ customer: single.name }
			  )
			: Promise.resolve([]);

		prefill_regions.then((regions) => {
			this.show_configure_dialog(rows, single?.taxjar_exemption_type || "", regions || []);
		});
	}

	show_configure_dialog(rows, exemption_type, existing_regions) {
		const selected = new Set(existing_regions.map((r) => `${r.country}:${r.state}`));
		const title = rows.length === 1
			? __("Configure Exemption: {0}", [rows[0].customer_name || rows[0].name])
			: __("Configure Exemption: {0} customers", [rows.length]);

		const fields = [
			{
				fieldtype: "Select",
				fieldname: "exemption_type",
				label: __("Exemption Type"),
				options: EXEMPTION_OPTIONS.map((opt) => ({
					label: opt || __("Not Configured"),
					value: opt,
				})),
				default: exemption_type,
				change: () => update_requirement(),
			},
		];
		if (rows.length > 1) {
			fields.push({
				fieldtype: "HTML",
				fieldname: "taxjar_bulk_note",
				options: `<p class="text-muted small">${__(
					"Applying will replace the exempt regions on all {0} selected customers.",
					[rows.length]
				)}</p>`,
			});
		}
		fields.push(...taxjar_integration.build_region_multicheck_fields(selected));

		const dialog = new frappe.ui.Dialog({
			title,
			size: "large",
			fields,
			primary_action_label: __("Apply"),
			primary_action: () => {
				const type = dialog.get_value("exemption_type");
				const regions = type ? taxjar_integration.get_selected_regions(dialog) : [];

				dialog.hide();
				this.save_exemption(rows, type, regions);
			},
		});

		const update_requirement = taxjar_integration.wire_exemption_dialog(dialog);
		dialog.show();
		update_requirement();
	}

	save_exemption(rows, exemption_type, regions) {
		frappe
			.xcall(
				"taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.configure_exemption",
				{ customers: rows.map((r) => r.name), exemption_type, regions }
			)
			.then((r) => {
				frappe.show_alert({
					message: __("Updated {0} customers", [r.updated]),
					indicator: "green",
				});
				this.after_bulk_action();
			});
	}

}
