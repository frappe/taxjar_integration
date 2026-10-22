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

const DOC_STATUS_COLORS = { Draft: "gray", Submitted: "blue", Cancelled: "red" };

const SYNC_UPDATE_EVENT = "taxjar_transactions_update";

// How long the sync popover waits after the pointer leaves the info icon. It is
// the travel time from the icon to the popover, for a reader going after the
// link inside it - frappe.ui.HoverCard's own close_delay, halved, because this
// popover sits 6px from its trigger rather than across a gap.
const POPOVER_GRACE_MS = 150;

// All Transactions first - the page opens on everything in range, so the
// reader sees the whole population before being sorted into one part of it.
// After it, the same five states the summary strip counts, in the same order
// and the same two groups: first the three TaxJar is answerable for, ordered by
// how much attention each wants - what needs fixing, what is still moving, what
// is done - then the two that are outside its remit. Same order in both means
// card and tab share a column, so clicking a number moves the underline
// straight down rather than sideways. Those five partition the table - every
// invoice in range is in exactly one - and each is the population of the card
// above it, so the strip and the tabs cannot disagree. All Transactions is the
// one tab that overlaps the rest: it is their union, and its card is the total.
const ALL_TAB = "all";
const FAILED_TAB = "failed";
const QUEUED_TAB = "queued";
const SYNCED_TAB = "synced";
const DRAFT_TAB = "draft";
// Named for the label and the stored status; the value is the scope key the
// server switches on, which predates the rename and is not a label, so it stays.
const EXCLUDED_TAB = "not_applicable";

const TABS = [
	{ name: ALL_TAB, label: __("All Transactions"), is_active: true },
	// group_start marks each tab the strip starts a new group on, so the rule
	// falls in the same two places in both rows. Flagged here rather than in
	// make_tabs() so the row's shape is readable from the row's own definition.
	{ name: FAILED_TAB, label: __("Failed"), group_start: true },
	{ name: QUEUED_TAB, label: __("Queued") },
	{ name: SYNCED_TAB, label: __("Synced") },
	{ name: DRAFT_TAB, label: __("Draft"), group_start: true },
	{ name: EXCLUDED_TAB, label: __("Excluded") },
];

// Submitted is the normal resting state and Draft the one before it, so both
// stay quiet; Cancelled is the one worth noticing in a list that mixes them.

class TaxJarTransactionSync {
	constructor(page) {
		this.page = page;
		this.current_page = 1;
		this.page_size = 20;
		this.active_tab = ALL_TAB;
		// The inline filter row's text, one entry per tab. Each tab has its own
		// table and its own filter row, so a search typed on one tab narrows
		// that tab and nothing else.
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
		this.apply_route_options();
		this.refresh();
	}

	// A link from another screen can open the page on a company, a date range
	// and a tab. Read once, then cleared, so a later visit opens on the page's
	// own defaults.
	//
	// The Migration tab on TaxJar Settings also sends pre_upgrade, which keeps
	// the invoices from before the upgrade (see _pre_upgrade_filters on the
	// server). The page shows no control for it and clears it on the next visit.
	// Those invoices are older than the one-month default range, so the dates
	// are cleared with it.
	apply_route_options() {
		const options = frappe.route_options;
		this.pre_upgrade = Boolean(options && options.pre_upgrade);
		if (!options) return;
		frappe.route_options = null;

		if (this.pre_upgrade) {
			this.filter_from_date.set_input("");
			this.filter_to_date.set_input("");
		}
		if (options.company) this.filter_company.set_input(options.company);
		if (options.from_date) this.filter_from_date.set_input(options.from_date);
		if (options.to_date) this.filter_to_date.set_input(options.to_date);
		if (TABS.some((tab) => tab.name === options.tab)) this.go_to_tab(options.tab);
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

		// Nature sits here rather than in the table's own filter row, where
		// Transaction Type would be its only neighbour: that row searches
		// Transaction ID and Customer and nothing else, and a column it cannot
		// narrow would offer a box that does nothing. The server reads the two
		// words, so they are sent untranslated and shown translated.
		this.filter_transaction_nature = this.add_filter({
			fieldname: "transaction_nature",
			label: __("Nature"),
			fieldtype: "Select",
			options: [
				{ label: __("All"), value: "" },
				{ label: __("Domestic"), value: "Domestic" },
				{ label: __("Export"), value: "Export" },
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

		// frappe.ui.Tabs draws a flat row of buttons and knows nothing of groups,
		// so the rules are hung on the buttons afterwards. A class, not a border
		// set here: it lands in the gap beside the button rather than inside it,
		// and the component measures offsetWidth to size the active underline.
		TABS.forEach((tab, index) => {
			if (tab.group_start) {
				this.tabsInstance.tabs[index].button.classList.add("taxjar-tab-group-start");
			}
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

	// Selection count + Resync + Export. Built detached and moved into the
	// active tab's table wrapper by render_table(), so it sits directly above
	// the rows it acts on and inherits that wrapper's padding.
	//
	// The count and Resync are the selection's own controls, so they come
	// and go with it - three of the six tabs hold nothing retryable. Export acts
	// on the whole tab rather than on a selection, so it is on every tab, and it
	// is rightmost: the row is right-aligned, so the one control that is always
	// there keeps the same place while the two beside it appear and go.
	make_tab_actions() {
		this.$tab_actions = $('<div class="taxjar-tab-actions"></div>');

		this.$selection_actions = $('<div class="taxjar-selection-actions"></div>').appendTo(
			this.$tab_actions
		);
		this.$selection_count = $('<span class="taxjar-selection-count"></span>').appendTo(
			this.$selection_actions
		);

		this.bulk_action = new taxjar_integration.ActionButton({
			$wrapper: this.$selection_actions,
			label: __("Resync"),
			// The app's own sync mark, the one the Customer form's Sync button
			// and the settings' fetch controls already carry.
			icon: "refresh-cw",
		});

		this.export_button = new taxjar_integration.ExportButton({
			$wrapper: this.$tab_actions,
			method:
				"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.export_transactions",
			// The page's filters and the open tab, exactly as refresh() sends
			// them - so the file is the table, without the page boundary.
			get_args: () => ({ filters: this.get_table_filters(), scope: this.active_tab }),
		});
	}

	// State side of a tab switch, without touching frappe's tab UI - safe to
	// call both from a user click (where frappe already switched) and from
	// go_to_tab (which drives the UI first).
	enter_tab(name) {
		this.active_tab = name;
		this.current_page = 1;
		// Each card counts exactly one tab's population, so the strip follows
		// the tabs rather than filtering them.
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

	// What the page is scoped to: company, dates, type and nature. Which tab is
	// open is NOT part of it - the tab is sent separately as the scope, so the
	// summary can count every tab's population under the same filters while
	// the table shows one of them.
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

		const transaction_nature = this.filter_transaction_nature?.get_value();
		if (transaction_nature) filters.transaction_nature = transaction_nature;

		if (this.pre_upgrade) filters.pre_upgrade = 1;

		return filters;
	}

	// The scope plus the open tab's inline filter row. The filter row sits in
	// the table, so it narrows the table and the file Export makes of it, and
	// leaves the cards alone: they count the page's scope, and a search typed
	// on one tab must not change the numbers on the others. Resolved
	// server-side so it narrows the whole result set, not the loaded page.
	get_table_filters() {
		const filters = this.get_scope_filters();
		const search = this.column_search[this.active_tab];
		if (search && Object.keys(search).length) filters.search = search;
		return filters;
	}

	refresh() {
		// A filter change can start a refresh while an older one is still out.
		// Only the newest may write current_page and the rows.
		const request = (this._refresh_request = (this._refresh_request || 0) + 1);
		Promise.all([
			frappe.xcall(
				"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.get_transactions",
				{
					filters: this.get_table_filters(),
					page: this.current_page,
					scope: this.active_tab,
					page_size: this.page_size,
				}
			),
			frappe.xcall(
				"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.get_summary",
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
			this.invoices = data.invoices;
			this.render_summary(summary);
			this.render_table();
			this.paginator.render(data);
			this.export_button.set_state(data);
			this.update_bulk_state();
		});
	}

	// Three captioned groups so the total, the statuses TaxJar is answerable
	// for and the two ways of being outside its remit each read as their own
	// count. The cards run in the tabs' order, so every number sits directly
	// above the tab it opens. Each drills the table down without disturbing the
	// company/date filters above.
	render_summary(summary) {
		const groups = [
			{
				// The union of every other card, and the population of the tab
				// the page opens on. Summed here rather than asked for
				// separately: docstatus is 0, 1 or 2 and nothing else, so
				// draft + submitted already is every transaction in range.
				label: __("All Transactions"),
				cards: [{ value: summary.submitted.total + summary.draft.total, value_key: ALL_TAB }],
			},
			{
				// Sent, waiting to be sent, or stopped on the way: all three are
				// TaxJar's to account for, which is what the heading says and what
				// "Included" did not - a failure is included in nothing. Failed
				// leads: it is the only one of the three anyone has to act on.
				label: __("In Scope"),
				cards: [
					{ label: __("Failed"), value: summary.submitted.failed, value_key: FAILED_TAB, indicator: "red" },
					{ label: __("Queued"), value: summary.submitted.queued, value_key: QUEUED_TAB, indicator: "blue" },
					{ label: __("Synced"), value: summary.submitted.synced, value_key: SYNCED_TAB, indicator: "green" },
				],
			},
			{
				// The two ways a transaction ends up outside TaxJar: not submitted
				// yet, or submitted and deliberately kept out. In that order, so the
				// pair reads "not yet" then "never". The heading has to be wider
				// than either card, because one of the cards is now called Excluded.
				label: __("Out of Scope"),
				cards: [
					{ label: __("Draft"), value: summary.draft.total, value_key: DRAFT_TAB },
					{
						// Named for the status it stores, rather than for a phrase
						// that read as though TaxJar had no opinion about the invoice.
						label: __("Excluded"),
						value: summary.submitted.excluded,
						value_key: EXCLUDED_TAB,
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

	// Every card counts one tab, so clicking one opens that tab rather than
	// filtering the current one. The strip toggles its own selection off when
	// the active card is clicked again; there is no "no tab" state to go to,
	// so that just re-asserts where we already are.
	on_summary_select(card) {
		if (!card) {
			this.summary.set_active(this.active_tab);
			return;
		}

		this.go_to_tab(card.value_key);
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
				// The invoice's own field, sent as it is stored. Two words, kept
				// untranslated on the wire so the server's filter can compare
				// them, and translated here where they are read. A row written
				// before the field existed holds a blank until the backfill patch
				// runs, and a blank cell says less than a guess would.
				label: __("Nature"),
				fieldname: "taxjar_transaction_nature",
				_html: (value) => (value ? frappe.utils.escape_html(__(value)) : ""),
			},
			{
				label: __("Grand Total"),
				fieldname: "grand_total",
				fieldtype: "Currency",
				// options names the row field that holds the currency, the
				// same way a Currency docfield does. frappe.format reads it
				// off the row; without it every total takes the system
				// default symbol, whatever the invoice was written in.
				options: "currency",
				align: "right",
			},
		];

		// Both of these used to be dropped from the tabs where every row would
		// give the same answer - Transaction Status off Draft, Sync Status off
		// Draft and Excluded. It saved a repetitive column and cost more than it
		// saved: the columns moved under you as you crossed the tabs, so the
		// same reading sat in a different place on each one and the table stopped
		// being one table. A uniform row is worth a repeated word.
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
					// Failed is where every row can be retried, and All
					// Transactions is where a reader who has not gone looking
					// for the Failed tab meets those same rows. The three
					// between them hold nothing retryable, so a checkbox there
					// would only lead to an empty menu.
					checkboxColumn: key === FAILED_TAB || key === ALL_TAB,
					noDataMessage: __("No transactions found"),
				},
				on_check_row: () => this.update_bulk_state(),
				on_filter_change: (search) => {
					this.column_search[key] = search;
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
	// pill's own text already says everything else. Failed and Excluded each
	// pair the pill with a separate info icon (never nested inside the pill)
	// for its popover, since neither pill text carries what the reader wants:
	// the error, or why the document was kept out. Queued says all it has to
	// say in the pill.
	render_sync_status_cell(row) {
		// Nothing syncs before submit (see enqueue_taxjar_sync's on_submit
		// hook), so whatever the field happens to hold for a draft - "Excluded",
		// by its own default - is not a report about the document, and printing
		// it would say the one thing that is false. The invoice form names this
		// state "Submit to Sync" (see _render_taxjar_sync_status_pill); so does
		// this. No hover: unlike every other state here, the pill is an
		// instruction and complete in itself, and the form's matching sentence
		// repeated down a whole tab of drafts would be noise.
		if (row.docstatus === 0) {
			return frappe.ui.badge.html({ label: __("Submit to Sync"), theme: "amber" });
		}

		const status = row.taxjar_sync_status;
		if (!status) return "";

		const color = STATUS_COLORS[status] || "gray";

		// On a cancelled row, Failed means the cancellation never reached TaxJar -
		// the order is still filed there. That is the opposite of what a reader
		// takes "Failed" beside a Cancelled transaction status to mean, which is
		// that the invoice never got there in the first place. The Transaction
		// Status column says the document was cancelled; only this pill can say
		// which of the two operations was the one that failed.
		//
		// Worded exactly as the invoice form words it (_render_taxjar_sync_status_pill
		// in taxjar_utils.js), so one state is not called two things on two screens.
		const cancelled = row.docstatus === 2;
		const label = cancelled && status === "Failed" ? __("Failed to Cancel") : __(status);

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

		// Excluded may still have nothing to say - a row written before the
		// reason was recorded, for a company whose configuration no longer
		// explains it - and an icon promising a detail that does not exist is
		// worse than no icon, so the pill goes out on its own.
		let info_text = "";
		// The link the reason leaves the reader wanting, where the reason has
		// one. It travels on the button rather than inside data-info, because
		// the popover writes the sentence as text.
		let info_action = null;
		if (status === "Failed") {
			info_text = row.taxjar_sync_error || __("Unknown error");
		} else if (status === "Excluded") {
			info_text = taxjar_integration.exclusion_reason_text(
				row.taxjar_exclusion_reason,
				row.taxjar_exclusion_reason_is_current
			);
			info_action = taxjar_integration.exclusion_reason_action(row.taxjar_exclusion_reason);
		}
		if (!info_text) return pill;

		const action_attrs = info_action
			? ` data-info-href="${frappe.utils.escape_html(
					info_action.href
			  )}" data-info-link="${frappe.utils.escape_html(info_action.label)}"`
			: "";
		const icon = `<button type="button" class="taxjar-sync-icon taxjar-sync-trigger" data-info="${frappe.utils.escape_html(
			info_text
		)}"${action_attrs}>${frappe.utils.icon("info", "sm")}</button>`;
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
		// A grace period rather than an immediate hide: the popover can hold a
		// link, and the pointer has to cross the gap from the icon to reach it.
		// The popover cancels the timer once the pointer arrives on it.
		$wrapper.on("mouseleave", ".taxjar-sync-trigger", () =>
			this._hide_sync_popover(POPOVER_GRACE_MS)
		);
		$wrapper.on("click", ".taxjar-sync-trigger", (e) => {
			e.stopPropagation();
			this._show_sync_popover($(e.currentTarget));
		});
	}

	_show_sync_popover($trigger) {
		this._hide_sync_popover();
		const text = $trigger.attr("data-info") || "";
		const href = $trigger.attr("data-info-href");
		const action = href ? { href, label: $trigger.attr("data-info-link") } : null;
		const $pop = taxjar_integration
			.sync_info_body(text, action)
			.addClass("taxjar-sync-pop")
			.appendTo("body");
		$pop.on("mouseenter", () => clearTimeout(this._pop_timer));
		$pop.on("mouseleave", () => this._hide_sync_popover());
		// A click inside goes to the link, not to the document handler below
		// that closes the popover. The hide waits for the next tick, because a
		// browser acts on a link after the click event finishes and an anchor
		// pulled out of the document during it may never be followed.
		$pop.on("click", (e) => {
			e.stopPropagation();
			setTimeout(() => this._hide_sync_popover());
		});
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

	// A delay only ever postpones the hide. Every other caller wants the
	// popover gone now, and _show_sync_popover leads with one, so a pending
	// timer never outlives the popover it was started for.
	_hide_sync_popover(delay) {
		clearTimeout(this._pop_timer);
		if (delay) {
			this._pop_timer = setTimeout(() => this._hide_sync_popover(), delay);
			return;
		}
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

	// Every row on the Failed tab is retryable, so the tab itself is the
	// eligibility filter. All Transactions is the union of all five, so a
	// selection there can hold rows that Resync cannot touch - Synced, Queued,
	// Draft, Excluded. bulk_retry() on the server skips those anyway, but an
	// action that silently does nothing to three of the five rows a reader
	// ticked is a report they only get afterwards. So the count of rows ticked
	// and the count the action can act on are stated apart, before the press:
	// the caption counts the selection, the menu item counts what it will do.
	//
	// With nothing eligible there is no menu item, which leaves the button
	// disabled and explaining itself - see BulkActionButton.
	update_bulk_state() {
		if (!this.tab_offers_selection()) {
			// Only the selection's own controls go - the row itself stays, since
			// Export sits in it on every tab.
			this.$selection_actions.hide();
			return;
		}
		this.$selection_actions.show();

		const checked = this.get_checked();
		const retryable = checked.filter((row) => row.taxjar_sync_status === "Failed");

		this.$selection_count.text(checked.length ? __("{0} selected", [checked.length]) : "");

		// The title first, then the disabled state that reads it - the other
		// order shows the previous update's title for one update.
		this.bulk_action.disabled_title = checked.length
			? __("None of the selected transactions can be resynced")
			: __("Select one or more records to run an action");
		this.bulk_action.set_action(() => this.confirm_bulk_retry(retryable));
		this.bulk_action.toggle_disabled(!retryable.length);
	}

	tab_offers_selection() {
		return this.active_tab === FAILED_TAB || this.active_tab === ALL_TAB;
	}

	// Ticking five rows of which three failed has to say three somewhere before
	// anything is sent. The caption counts the selection and the button carries
	// a plain verb, so the dialog is where the reader meets the number the
	// action will act on - on All Transactions, where the two can differ.
	confirm_bulk_retry(rows) {
		const message =
			rows.length === 1
				? __("Resync 1 record with TaxJar?")
				: __("Resync {0} records with TaxJar?", [rows.length]);

		frappe.confirm(message, () => this.bulk_retry(rows));
	}

	bulk_retry(rows) {
		frappe
			.xcall(
				"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.bulk_retry",
				{ invoices: rows.map((row) => row.name) }
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
