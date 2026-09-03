// Desk pages are built once and cached in frappe.pages[name]; revisiting the
// route only un-hides the existing DOM and fires on_page_show. So the data
// fetch lives in on_page_show, not the constructor - otherwise the page keeps
// showing whatever it loaded the first time until a browser reload. The
// constructor deliberately does NOT fetch: on first visit the "show" handler is
// bound before container.change_to() runs, so on_page_show already fires right
// after on_page_load and doing both would double-fetch every load.
frappe.pages["taxjar-transactions"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("TaxJar Transaction Sync"),
		single_column: true,
	});

	wrapper.taxjar_transactions = new TaxJarTransactionSync(page);

	// Frappe has no on_page_hide page event; container.js triggers a plain
	// "hide" on the outgoing container div, which is this wrapper.
	$(wrapper).on("hide", () => wrapper.taxjar_transactions.on_hide());
};

frappe.pages["taxjar-transactions"].on_page_show = function (wrapper) {
	wrapper.taxjar_transactions.on_show();
};

const STATUS_COLORS = {
	Synced: "green",
	Failed: "red",
	Queued: "blue",
	Excluded: "gray",
};

// Submitted is the normal resting state, so it stays quiet; Cancelled is the
// one worth noticing in a list that mixes the two.
const DOC_STATUS_COLORS = { Submitted: "blue", Cancelled: "red" };

const SYNC_UPDATE_EVENT = "taxjar_transactions_update";

// The two tabs: what TaxJar has, and what it never received. The Excluded tab
// holds both drafts and submitted-but-not-applicable rows, told apart by its
// Status column. Nothing there has been acted on, so it carries no sync status,
// no checkboxes and no bulk actions.
const INCLUDED_TAB = "included";
const EXCLUDED_TAB = "excluded";

// The two halves of the Excluded tab, as the summary drills into them.
const KIND_DRAFT = "Draft";
const KIND_NOT_APPLICABLE = "Not Applicable";

const TABS = [
	{ name: INCLUDED_TAB, label: __("Included"), is_active: true },
	{ name: EXCLUDED_TAB, label: __("Excluded") },
];

class TaxJarTransactionSync {
	constructor(page) {
		this.page = page;
		this.current_page = 1;
		this.page_size = 20;
		this.active_tab = INCLUDED_TAB;
		this.status_filter = null;
		this.excluded_kind = null;
		this.column_search = {};

		// Built once so on_hide() has the same reference to pass to
		// frappe.realtime.off(). Debounced because a bulk retry of N invoices
		// publishes N events and each refresh() is two server calls - without
		// this, retrying 500 rows would fire 500 refreshes.
		this._on_sync_update = frappe.utils.debounce(() => this.refresh(), 500);

		this.make_filters();
		this.make_summary();
		this.make_tabs();
		this.make_not_configured_panel();
	}

	on_show() {
		// Joining is idempotent, and the server permission-checks the join.
		frappe.realtime.doctype_subscribe("Sales Invoice");
		// off() first so a stray double-show can't stack the same handler.
		frappe.realtime.off(SYNC_UPDATE_EVENT, this._on_sync_update);
		frappe.realtime.on(SYNC_UPDATE_EVENT, this._on_sync_update);
		this.refresh();
	}

	// Detaches our handler but deliberately does NOT doctype_unsubscribe: the
	// Sales Invoice list view subscribes to the same room and only sets itself
	// up once (guarded by its realtime_events_setup flag), so leaving the room
	// on our behalf could silently kill its auto-refresh.
	on_hide() {
		frappe.realtime.off(SYNC_UPDATE_EVENT, this._on_sync_update);
		this._on_sync_update.cancel();
		this._hide_sync_popover();
	}

	// ── Shell ─────────────────────────────────────────────────────────────

	make_filters() {
		this.filter_area = $('<div class="taxjar-filters"></div>').appendTo(this.page.main);

		this.filter_company = this.add_filter({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			// Same default every ERPNext report opens with, so the page lands on
			// the company you actually work in rather than every company at once.
			default: frappe.defaults.get_user_default("Company"),
		});

		this.filter_from_date = this.add_filter({
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		});

		this.filter_to_date = this.add_filter({
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		});

		this.filter_transaction_type = this.add_filter({
			fieldname: "transaction_type",
			label: __("Transaction Type"),
			fieldtype: "Select",
			options: [
				{ label: __("All"), value: "" },
				{ label: __("Sales Invoice"), value: "Sales Invoice" },
				{ label: __("Credit Note"), value: "Credit Note" },
				{ label: __("Debit Note"), value: "Debit Note" },
			],
		});
	}

	// frappe.ui.form.make_control() directly, rather than page.add_field(),
	// since add_field() hardcodes only_input: true and drops the label,
	// leaving just a placeholder - fine for the standard page toolbar, not
	// for a filter row that needs visible labels.
	add_filter(df) {
		df.change = () => {
			this.current_page = 1;
			this.refresh();
		};
		const control = frappe.ui.form.make_control({
			df,
			parent: this.filter_area,
			only_input: false,
		});
		control.refresh();
		if (df.default) control.set_input(df.default);
		return control;
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
				this.refresh();
			},
			on_page_size: (size) => {
				// Every page boundary moves, so the old page number is meaningless.
				this.page_size = size;
				this.current_page = 1;
				this.refresh();
			},
		});
	}

	// Selection count + Bulk Action. Built detached and moved into the active
	// tab's table wrapper by render_table(), so it sits directly above the rows
	// it acts on and inherits that wrapper's padding.
	make_tab_actions() {
		this.$tab_actions = $('<div class="taxjar-tab-actions"></div>');
		this.$selection_count = $('<span class="taxjar-selection-count"></span>').appendTo(this.$tab_actions);

		this.bulk_action = new taxjar_integration.BulkActionButton({
			$wrapper: this.$tab_actions,
			label: __("Bulk Action"),
		});
	}

	// State side of a tab switch, without touching frappe's tab UI - safe to
	// call both from a user click (where frappe already switched) and from
	// go_to_tab (which drives the UI first).
	enter_tab(name) {
		this.active_tab = name;
		this.current_page = 1;
		this.status_filter = null;
		this.excluded_kind = null;
		// The Draft card doubles as the Draft tab's own indicator.
		this.summary?.set_active(name === EXCLUDED_TAB ? EXCLUDED_TAB : null);
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
	// population, which is why the status drill-down is NOT part of it - see
	// get_filters().
	get_scope_filters() {
		const filters = {};

		const company = this.filter_company?.get_value();
		if (company) filters.company = company;

		const from_date = this.filter_from_date?.get_value();
		if (from_date) filters.from_date = from_date;

		const to_date = this.filter_to_date?.get_value();
		if (to_date) filters.to_date = to_date;

		const transaction_type = this.filter_transaction_type?.get_value();
		if (transaction_type) filters.transaction_type = transaction_type;

		// The datatable's inline filter row, resolved server-side so it
		// narrows the whole result set rather than the loaded page.
		if (Object.keys(this.column_search).length) filters.search = this.column_search;

		return filters;
	}

	// The scope plus the status drill-down, which only the table honours.
	// Feeding it to the summary too would make clicking "Failed" collapse every
	// other number to zero - the strip is what you drill *from*, so it has to
	// keep standing still while you do.
	get_filters() {
		const filters = this.get_scope_filters();

		if (this.status_filter && this.active_tab === INCLUDED_TAB) {
			filters.sync_status = this.status_filter;
		}

		if (this.excluded_kind && this.active_tab === EXCLUDED_TAB) {
			filters.excluded_kind = this.excluded_kind;
		}

		return filters;
	}

	refresh() {
		const filters = this.get_filters();

		Promise.all([
			frappe.xcall(
				"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.get_transactions",
				{ filters, page: this.current_page, scope: this.active_tab, page_size: this.page_size }
			),
			frappe.xcall(
				"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.get_summary",
				{ filters: this.get_scope_filters() }
			),
		]).then(([data, summary]) => {
			if (data.not_configured) {
				this.show_not_configured();
				return;
			}
			this.hide_not_configured();
			this.invoices = data.invoices;
			this.render_summary(summary);
			this.render_table();
			this.paginator.render(data);
			this.update_bulk_state();
		});
	}

	// Two captioned groups so "All Transactions" and "Draft" read as
	// separate totals. Every number drills the table down without disturbing
	// the company/date filters above.
	render_summary(summary) {
		const groups = [
			{
				label: __("Included"),
				cards: [
					{ label: __("Synced"), value: summary.submitted.synced, value_key: "Synced", indicator: "green" },
					{ label: __("Queued"), value: summary.submitted.queued, value_key: "Queued", indicator: "blue" },
					{ label: __("Failed"), value: summary.submitted.failed, value_key: "Failed", indicator: "red" },
				],
			},
			{
				// The two ways a transaction ends up outside TaxJar: not
				// submitted yet, or submitted and deliberately not sent.
				label: __("Excluded"),
				cards: [
					{ label: __("Draft"), value: summary.draft.total, value_key: KIND_DRAFT },
					{
						// The stored status is "Excluded" - the group heading
						// already says that, so the card names the case instead.
						label: __("Not Applicable"),
						value: summary.submitted.excluded,
						value_key: KIND_NOT_APPLICABLE,
						indicator: "grey",
					},
				],
			},
		];

		if (!this.summary) {
			this.summary = new taxjar_integration.SummaryStrip({
				$wrapper: this.summary_area,
				groups,
				on_select: (card) => this.on_summary_select(card),
			});
			return;
		}

		const active = this.summary.active_key;
		this.summary.update(groups);
		this.summary.set_active(active);
	}

	on_summary_select(card) {
		// The Excluded counts are not sync statuses - they pick which half of
		// the Excluded tab to show.
		if (card?.value_key === KIND_DRAFT || card?.value_key === KIND_NOT_APPLICABLE) {
			this.go_to_tab(EXCLUDED_TAB);
			this.excluded_kind = card.value_key;
			this.summary.set_active(card.value_key);
			this.refresh();
			return;
		}

		if (this.active_tab !== INCLUDED_TAB) this.go_to_tab(INCLUDED_TAB);

		// "" is the Total card: a filter of nothing, i.e. show everything.
		this.status_filter = card?.value_key || null;
		this.current_page = 1;
		this.refresh();
	}

	// ── Table ─────────────────────────────────────────────────────────────

	get_columns() {
		const columns = [
			{
				label: __("Posting Date"),
				fieldname: "posting_date",
				fieldtype: "Date",
			},
			{
				label: __("Transaction ID"),
				fieldname: "name",
				_html: (value) =>
					`<a href="/app/sales-invoice/${encodeURIComponent(value)}">${frappe.utils.escape_html(
						value
					)}</a>`,
			},
			{ label: __("Customer"), fieldname: "customer_name" },
			{ label: __("Type"), fieldname: "transaction_type" },
			{
				label: __("Grand Total"),
				fieldname: "grand_total",
				fieldtype: "Currency",
				align: "right",
			},
		];

		// Which half of the Excluded tab a row belongs to. Only this tab mixes
		// the two; everywhere else it would read the same on every row.
		if (this.active_tab === EXCLUDED_TAB) {
			columns.push({
				label: __("Status"),
				fieldname: "doc_status",
				resizable: false,
				_html: (value) =>
					frappe.ui.badge.html({
						label: value === "Draft" ? __("Draft") : __("Not Applicable"),
						theme: "gray",
					}),
			});
		}

		// Both only mean something on the Included tab. Nothing in Excluded has
		// a sync status - it is defined as the rows that never got one.
		if (this.active_tab === INCLUDED_TAB) {
			columns.push({
				label: __("Transaction Status"),
				fieldname: "doc_status",
				_html: (value) =>
					value
						? frappe.ui.badge.html({ label: __(value), theme: DOC_STATUS_COLORS[value] || "gray" })
						: "",
			});
			columns.push({
				label: __("Sync Status"),
				fieldname: "taxjar_sync_status",
				_html: (value, row) => this.render_sync_status_cell(row),
			});
		}

		return columns;
	}

	render_table() {
		const $wrapper = this.tab_content_wrappers[this.active_tab];
		const key = this.active_tab;

		// Columns differ per tab, and so does checkboxColumn - both are fixed
		// at construction in frappe.DataTable, so each tab keeps its own
		// instance rather than one being reconfigured on the fly.
		if (!this.datatables) this.datatables = {};

		if (!this.datatables[key]) {
			this.datatables[key] = new taxjar_integration.DataTableManager({
				$wrapper,
				columns: this.get_columns(),
				data: this.invoices,
				options: {
					checkboxColumn: key === INCLUDED_TAB,
					noDataMessage: __("No transactions found"),
				},
				on_check_row: () => this.update_bulk_state(),
				on_filter_change: (search) => {
					this.column_search = search;
					this.current_page = 1;
					this.refresh();
				},
			});
			this.bind_sync_popover($wrapper);
		} else {
			this.datatables[key].refresh(this.invoices);
		}

		// Move rather than copy, so the one instance of each - handlers and all
		// - follows whichever tab is showing. Both live inside the table's own
		// wrapper so they share its padding and line up with its edges instead
		// of merely happening to sit at the same inset.
		this.$tab_actions.prependTo($wrapper);
		this.paginator.$wrapper.appendTo($wrapper);
	}

	get datatable() {
		return this.datatables?.[this.active_tab];
	}

	// Synced rows carry their detail (last-synced time) as a hover/click
	// popover on the pill itself - no separate info icon needed since the
	// pill's own text already says everything else. Failed pairs the pill with
	// a separate info icon (never nested inside the pill) for its popover,
	// since the pill text alone doesn't carry the error. Queued and Excluded
	// say all they have to say in the pill.
	render_sync_status_cell(row) {
		const status = row.taxjar_sync_status;
		if (!status) return "";

		const color = STATUS_COLORS[status] || "gray";
		const label = __(status);

		if (status === "Synced") {
			if (!row.taxjar_last_synced) {
				return frappe.ui.badge.html({ label, theme: color });
			}
			const info_text = __("Last synced: {0}", [frappe.datetime.prettyDate(row.taxjar_last_synced)]);
			return frappe.ui.badge.html({
				label, theme: color, css_class: "taxjar-sync-trigger",
				attrs: { "data-info": info_text },
			});
		}

		const pill = frappe.ui.badge.html({ label, theme: color });

		if (status !== "Failed") return pill;

		const info_text = row.taxjar_sync_error || __("Unknown error");
		const icon = `<button type="button" class="taxjar-sync-icon taxjar-sync-trigger" data-info="${frappe.utils.escape_html(
			info_text
		)}">${frappe.utils.icon("info", "sm")}</button>`;
		return `${pill}${icon}`;
	}

	// Delegated once per table (rather than rebound on every render) so it
	// keeps working across re-renders. Shows immediately on hover - no
	// native-tooltip delay - and also toggles on click, since hover never
	// fires on touch devices.
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
		$(document).on("click.taxjarSyncPop", () => this._hide_sync_popover());
	}

	_hide_sync_popover() {
		if (this._active_pop) {
			this._active_pop.remove();
			this._active_pop = null;
		}
		$(document).off("click.taxjarSyncPop");
	}

	// ── Bulk actions ──────────────────────────────────────────────────────

	get_checked() {
		return this.datatable?.get_checked_items().filter(Boolean) || [];
	}

	// The menu names the eligible subset up front ("Retry 2 Failed") and the
	// counter spells out the gap, so a mixed selection can't silently drop
	// rows the way a bare "Retry Selected" did.
	update_bulk_state() {
		if (this.active_tab !== INCLUDED_TAB) {
			this.$tab_actions.hide();
			return;
		}
		this.$tab_actions.show();

		const checked = this.get_checked();
		const failed = checked.filter((row) => row.taxjar_sync_status === "Failed");

		this.$selection_count.text(
			checked.length
				? __("{0} selected · {1} retryable", [checked.length, failed.length])
				: ""
		);

		this.bulk_action.set_items(
			failed.length ? [{ label: __("Resync with TaxJar"), action: () => this.bulk_retry(failed) }] : []
		);

		if (checked.length && !failed.length) {
			this.bulk_action.disabled_title = __("Nothing in this selection can be retried");
			this.bulk_action.toggle_disabled(true);
		} else {
			this.bulk_action.disabled_title = __("Select one or more records to run an action");
		}
	}

	bulk_retry(failed) {
		frappe
			.xcall(
				"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.bulk_retry",
				{ invoices: failed.map((row) => row.name) }
			)
			.then((r) => {
				frappe.show_alert({
					message: __("{0} transactions queued for retry", [r.queued]),
					indicator: "blue",
				});
				this.datatable?.clear_checked_items();
				this.refresh();
			});
	}
}
