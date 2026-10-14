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
		this._refresh_soon = frappe.utils.debounce(() => this.refresh(), 500);
		this._on_sync_update = (data) => {
			if (data?.bulk_exemption_done !== undefined) this.report_bulk_exemption(data);
			this._refresh_soon();
		};

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
		this._refresh_soon.cancel();
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
	//
	// Bulk Action acts on the rows the reader ticked; Export acts on the whole
	// tab, so it needs no selection and is rightmost - the row is right-aligned,
	// and the one control that never changes keeps the same place.
	make_tab_actions() {
		this.$tab_actions = $('<div class="taxjar-tab-actions"></div>');
		this.$selection_count = $('<span class="taxjar-selection-count"></span>').appendTo(this.$tab_actions);

		this.bulk_action = new taxjar_integration.BulkActionButton({
			$wrapper: this.$tab_actions,
			label: __("Bulk Action"),
		});

		this.export_button = new taxjar_integration.ExportButton({
			$wrapper: this.$tab_actions,
			method:
				"taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.export_customers",
			// get_filters(), not get_scope_filters(): the sync status drill-down
			// narrows the table, so it narrows the file the table exports to.
			get_args: () => ({ filters: this.get_filters(), scope: this.active_tab }),
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
		// A filter change can start a refresh while an older one is still out.
		// Only the newest may write current_page and the rows.
		const request = (this._refresh_request = (this._refresh_request || 0) + 1);

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
			if (request !== this._refresh_request) return;
			if (data.not_configured) {
				this.show_not_configured();
				return;
			}
			this.hide_not_configured();
			// The server serves the last page for a page past the end, so
			// keep the page it served. The next reload then asks for it.
			this.current_page = data.page;
			this.customers = data.customers;
			this.render_summary(summary);
			this.render_table();
			this.paginator.render(data);
			this.export_button.set_state(data);
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

	// The strip clears its selection when the active card is clicked again, and
	// hands over null. A sync status card clears to its whole tab. A tab card
	// has no "no tab" state to clear to, so it stays where it is.
	on_summary_select(card) {
		if (!card) {
			if (this.status_filter) {
				this.status_filter = null;
				this.current_page = 1;
				this.reset_selection();
				this.refresh();
			}
			this.summary.set_active(this.active_tab);
			return;
		}

		const tab = TABS.map((t) => t.name).find((name) => name === card?.value_key);
		if (tab) {
			this.go_to_tab(tab);
			this.refresh();
			return;
		}

		// A sync status only describes an exempt customer, so drill into the
		// Exemptions tab alongside it.
		if (this.active_tab !== EXEMPT_TAB) this.go_to_tab(EXEMPT_TAB);
		this.status_filter = card.value_key;
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
						? frappe.utils.escape_html(value)
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

		// How many regions the type above is scoped to - the other half of
		// the same answer, so it sits next to it rather than being folded
		// into the Configure control that edits both.
		columns.push({
			label: __("Exempted Regions"),
			fieldname: "exempt_region_count",
			width: 100,
			align: "center",
			_html: (value, row) => this.render_region_count_cell(row),
		});

		// Directly after what it edits, and before Sync Status: the exemption
		// columns are one block, and sync state describes what has already
		// been sent rather than anything you change here. This is the one path
		// that lets a not-configured row be configured without first selecting
		// it for the bulk action.
		columns.push({
			label: __("Configure Exemption"),
			fieldname: "configure",
			// Wide enough for the header itself - the cell below it is one
			// icon, so the column is sized by its label rather than its rows.
			width: 170,
			align: "center",
			_html: (value, row) => this.render_regions_cell(row),
		});

		columns.push({
			label: __("Sync Status"),
			fieldname: "taxjar_customer_sync_status",
			width: 120,
			_html: (value, row) => this.render_sync_status_cell(row),
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
		// aria-label, not title: the name a screen reader reads stays in the
		// markup, and the bubble the pointer gets is the desk's own, bound in
		// bind_configure_tooltips().
		return `<button type="button"
			class="taxjar-configure-link"
			data-customer="${frappe.utils.escape_html(row.name)}"
			aria-label="${__("Configure exemption")}"
			>${frappe.utils.icon("square-pen", "sm")}</button>`;
	}

	// A dash for none, same as every other empty cell in this table - a 0
	// reads as a measured quantity when the truth is that nothing is set. The
	// count itself is the hover-card trigger (bind_region_hover_cards), naming
	// the regions it stands for.
	render_region_count_cell(row) {
		const count = row.exempt_region_count || 0;
		if (!count) return `<span class="text-muted">-</span>`;

		return `<span class="taxjar-regions-trigger" data-customer="${frappe.utils.escape_html(
			row.name
		)}">${count}</span>`;
	}

	// Bound per render rather than delegated: frappe.ui.hover_card attaches its
	// own pointer/focus listeners to the trigger element, and the DataTable
	// builds fresh cells on every refresh. The listeners go with the elements
	// they were bound to, so nothing needs tearing down - only the card that
	// happens to be open, which closes itself once its trigger leaves the DOM.
	//
	// The wizard's "quick preview" timings, not the 700ms default: the count is
	// already on screen and the card only expands it, so waiting most of a
	// second to read what a "5" means is longer than the answer is worth.
	// The desk's own bubble rather than the browser's native title: it reads in
	// the desk's type, and it opens on keyboard focus as well as on hover, so a
	// reader without a pointer learns what the pencil does.
	//
	// Bound per render, for the same reason as the hover cards below: the
	// DataTable builds fresh cells on every refresh, and the listeners go with
	// the elements they were bound to.
	bind_configure_tooltips($wrapper) {
		if (!frappe.ui.tooltip) return;

		$wrapper.find(".taxjar-configure-link").each((_, el) => {
			frappe.ui.tooltip(el, { text: __("Configure exemption") });
		});
	}

	bind_region_hover_cards($wrapper) {
		$wrapper.find(".taxjar-regions-trigger").each((_, el) => {
			const row = this.customers.find((c) => c.name === el.dataset.customer);
			if (!row) return;

			frappe.ui.hover_card(el, {
				content: () => this.build_regions_card(row.exempt_regions || []),
				open_delay: 200,
				close_delay: 150,
			});
		});
	}

	// One section per country, each either the region names or - once every
	// region this app offers for that country is on file - the fact that it is
	// all of them, which is what a 51-name list actually means.
	//
	// The card itself is taxjar_integration.region_hover_card, shared with the
	// guided setup's Nexus card. Only the two sections are this page's own: it
	// stores codes for two known countries, so it resolves the names here and
	// decides "all of them" against the same lists the region picker offers.
	build_regions_card(regions) {
		const section = (country, heading, all_label, codes) => {
			const states = regions.filter((r) => r.country === country).map((r) => r.state);
			return {
				// Flag then country name, the same pair the Customer form's
				// own exemption card heads each block with - this popover
				// shows the very same regions, so it says them the same way.
				heading: `${taxjar_integration.country_flag_html(country)}<span>${frappe.utils.escape_html(
					heading
				)}</span>`,
				names: states.map((state) => taxjar_integration.region_full_name(country, state)),
				all_label: states.length >= codes.length ? all_label : null,
			};
		};

		return taxjar_integration.region_hover_card([
			section("US", __("United States"), __("All states exempted"), taxjar_integration.US_STATE_CODES),
			section("CA", __("Canada"), __("All provinces exempted"), taxjar_integration.CA_PROVINCE_CODES),
		]);
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

		// A queue this row never left. The server decides this (see
		// _is_sync_stalled) because only it knows how long the row has waited.
		// Said in orange with its own reason, rather than in the same calm blue
		// as a sync that started a second ago: the page used to show the two
		// identically, so a worker that had stopped running jobs altogether
		// looked exactly like one that was busy.
		if (row.taxjar_sync_stalled) {
			return `${frappe.ui.badge.html({ label: __("Not Sent"), theme: "orange" })}${this.sync_info_icon(
				__(
					"This customer has been waiting far longer than a sync takes, so the job that would have sent it is not running. Select the row and choose Resync with TaxJar."
				)
			)}`;
		}

		const pill = frappe.ui.badge.html({ label: __(status), theme: color });
		if (status !== "Failed") return pill;

		return `${pill}${this.sync_info_icon(row.taxjar_customer_sync_error || __("Unknown error"))}`;
	}

	// The icon is always a sibling of the pill, never nested inside it - the
	// pill names the state, the icon carries the reason. Shared by Failed and
	// by a stalled row, so both read the same way.
	sync_info_icon(info_text) {
		return `<button type="button" class="taxjar-sync-icon taxjar-sync-trigger" data-info="${frappe.utils.escape_html(
			info_text
		)}">${frappe.utils.icon("info", "sm")}</button>`;
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

		this.bind_configure_tooltips($table_wrapper);
		this.bind_region_hover_cards($table_wrapper);

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
		// Queued belongs here beside Failed. A customer stranded at Queued -
		// its job never created, or gone with the worker that was running it -
		// is exactly the row a human wants to resend, and offering the action
		// on Failed alone left the one status with no way out of it. The
		// server re-sends an idempotent PUT, so asking for it while a sync is
		// genuinely in flight costs one call and changes nothing.
		const resyncable = checked.filter((row) =>
			["Failed", "Queued"].includes(row.taxjar_customer_sync_status)
		);

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

		if (resyncable.length) {
			items.push({ divider: true });
			items.push({
				label: __("Resync with TaxJar"),
				action: () => this.retry_failed(resyncable),
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
				// A queued edit has not happened yet. The job reports the result
				// on the page's realtime event, in report_bulk_exemption().
				frappe.show_alert({
					message: r.queued
						? __("Updating {0} customers in the background", [r.updated])
						: __("Updated {0} customers", [r.updated]),
					indicator: r.queued ? "blue" : "green",
				});
				this.after_bulk_action();
			});
	}

	report_bulk_exemption(data) {
		const failed = data.bulk_exemption_failed || 0;
		frappe.show_alert(
			{
				message: failed
					? __("Updated {0} customers. {1} could not be updated, see the Error Log.", [
							data.bulk_exemption_done,
							failed,
					  ])
					: __("Updated {0} customers", [data.bulk_exemption_done]),
				indicator: failed ? "orange" : "green",
			},
			failed ? 10 : 5
		);
	}

}
