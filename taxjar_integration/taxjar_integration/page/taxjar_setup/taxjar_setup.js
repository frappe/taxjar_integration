// TaxJar guided setup — desk page shell.
//
// Layout: a single-step panel that swaps its entire content on Save & continue —
// only one step is ever shown at a time, rendered as plain page flow (no card/box
// around it) rather than a widget embedded in the desk. Each step's own header
// opens with the progress rail — frappe's own Espresso Progress component
// (intervals form), one segment per step — with a clickable caption per step
// underneath doubling as navigation (the one thing the stock component doesn't do).
//
// Every data field is a real Frappe control (frappe.ui.form.make_control), and
// every other piece of chrome — buttons, status badges, the Sandbox/Live toggle,
// the nexus banner, empty/loading states — is frappe's Espresso desk component
// library (frappe.ui.button/.badge/.tab_buttons/.alert/.empty_state/.skeleton,
// demoed live in Component Explorer, /app/component-explorer). A connection
// failure surfaces as the token field's own error text (df.invalid +
// set_description — frappe's native invalid-field primitive), not a popover.
// Only the card layout around all of this is custom CSS. Connect, Accounts and Features
// persist per step (Continue = collect -> save API -> reload state -> advance),
// so the guide is resumable; Nexus persists via its own Fetch action instead of
// a Continue save. See docs/guided-setup-plan.md.

const SETUP_MODULE = "taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup";

// State load lives in on_page_show, not the constructor - desk pages are cached
// in frappe.pages[name], so revisiting the route only un-hides the existing DOM
// and the wizard would keep showing whatever it read on first load. Safe for a
// multi-step wizard because _load_state() re-renders the *current* step and
// never touches this.cur/this.reached, so the user's position is preserved.
frappe.pages["taxjar-setup"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("TaxJar Setup"),
		single_column: true,
	});
	wrapper.taxjar_setup = new TaxJarSetup(page);
};

frappe.pages["taxjar-setup"].on_page_show = function (wrapper) {
	wrapper.taxjar_setup._load_state();
};

const AUTOFILE_DOC_URL = "https://support.taxjar.com/article/908-how-does-autofile-work";
const TAXJAR_NEXUS_URL = "https://app.taxjar.com/account#states";

const SETUP_STEPS = [
	// Nothing is actually saved on this step (no form fields), so its button
	// just says "Continue" rather than the misleading "Save & continue".
	{ key: "welcome", label: __("Pre-requisites"), title: __("Integrate TaxJar with ERPNext"), nextLabel: __("Continue") },
	{ key: "connect", label: __("Connect"), title: __("Connect your TaxJar account") },
	{ key: "accounts", label: __("Map Ledgers"), title: __("Map your accounting ledgers") },
	{ key: "features", label: __("Features"), title: __("Choose features to activate") },
	{ key: "nexus", label: __("Sync Nexus"), title: __("Sync your nexus regions") },
	{ key: "review", label: __("Review"), title: __("Review & activate") },
];

class TaxJarSetup {
	constructor(page) {
		this.page = page;
		this.cur = 0;
		this.reached = 0;
		this.state = null;
		this.controls = {};
		// API Credentials starts expanded - it's a required step, so hiding it
		// by default would just cost an extra click every single time.
		this._credsExpanded = true;
		this._build_shell();
	}

	_build_shell() {
		this.$root = $(`
			<div class="taxjar-setup">
				<section class="ts-panel">
					<header class="ts-head">
						<div class="ts-rail"></div>
						<ol class="ts-steps"></ol>
					</header>
					<h2 class="ts-title"></h2>
					<div class="ts-body"></div>
					<footer class="ts-foot">
						<div class="ts-back-mount"></div>
						<span class="ts-grow"></span>
						<div class="ts-next-mount"></div>
					</footer>
				</section>
			</div>
		`).appendTo(this.page.main);

		this.$steps = this.$root.find(".ts-steps");
		this.$body = this.$root.find(".ts-body");

		// The bar itself is frappe's own Espresso Progress (intervals form) —
		// .es-progress ships its own CSS already loaded on every desk page.
		// No label/hint here - the step captions below it already say which
		// step is current, so a "Features / Step 4 of 6" header on top would
		// just repeat that. The clickable captions are this wizard's own
		// addition, the one thing the stock component doesn't do.
		this.progress = new frappe.ui.Progress({
			intervals: true,
			interval_count: SETUP_STEPS.length,
		});
		this.$root.find(".ts-rail").append(this.progress.$el);

		this.$steps.html(SETUP_STEPS.map((s, i) => `
			<li><button type="button" class="ts-step-btn" data-i="${i}">${frappe.utils.escape_html(s.label)}</button></li>
		`).join(""));
		this.$steps.find(".ts-step-btn").on("click", (e) => {
			this._go(+$(e.currentTarget).data("i"));
		});

		this.$root.find(".ts-back-mount").append(frappe.ui.button({
			label: __("Back"), variant: "outline", css_class: "ts-back",
			onclick: () => this._go(this.cur - 1),
		}));
		this.$root.find(".ts-next-mount").append(frappe.ui.button({
			label: __("Continue"), variant: "solid", css_class: "ts-next",
			onclick: () => this._on_next(),
		}));
	}

	// ── server calls ────────────────────────────────────────────────
	_call(method, args) {
		return frappe.xcall(`${SETUP_MODULE}.${method}`, args);
	}

	_reload_state() {
		return this._call("get_setup_state", {}).then((state) => { this.state = state; });
	}

	_load_state() {
		this.$body.html(`<div class="ts-skeleton"></div>`);
		const $sk = this.$body.find(".ts-skeleton");
		$sk.append(frappe.ui.skeleton({ width: "45%", height: "14px" }));
		$sk.append(frappe.ui.skeleton({ width: "100%", height: "72px" }));
		$sk.append(frappe.ui.skeleton({ width: "100%", height: "72px" }));
		this._reload_state().then(() => this._render());
	}

	// ── navigation ───────────────────────────────────────────────────
	_go(i) {
		if (i < 0 || i >= SETUP_STEPS.length || i > this.reached) return;
		this.cur = i;
		this.reached = Math.max(this.reached, i);
		this._render();
	}

	_advance() {
		if (this.cur < SETUP_STEPS.length - 1) {
			this.reached = Math.max(this.reached, this.cur + 1);
			this._go(this.cur + 1);
		}
	}

	_on_next() {
		// Gated (e.g. Connect before anything's tested) stays a real, clickable
		// button rather than a native disabled one — a disabled button eats the
		// click silently, which just looks broken. Explain what's missing instead.
		if (this._nextGated) {
			frappe.show_alert({ message: this._nextGateMessage || __("Please complete this step first."), indicator: "orange" });
			return;
		}

		const step = SETUP_STEPS[this.cur];
		if (step.key === "review") return this._finish();

		// Steps with a save API collect -> save -> reload state -> advance;
		// steps without one (Welcome, Nexus — which persists via its own Fetch
		// action) just advance.
		const saver = this[`_save_${step.key}`];
		if (!saver) return this._advance();
		Promise.resolve(saver.call(this)).then((ok) => { if (ok) this._advance(); });
	}

	// Visually disabled but still clickable, so a click can explain why instead
	// of a native `disabled` button silently eating it.
	_set_next_gated(blocked, message) {
		this._nextGated = blocked;
		this._nextGateMessage = message;
		this.$root.find(".ts-next").toggleClass("ts-next-gated", blocked);
	}

	_finish() {
		const $btn = this.$root.find(".ts-next").prop("disabled", true);
		this._call("finish_setup", {})
			.then(() => {
				frappe.show_alert({ message: __("TaxJar setup complete."), indicator: "green" }, 5);
				frappe.set_route("Form", "TaxJar Settings");
			})
			.finally(() => $btn.prop("disabled", false));
	}

	// ── render ───────────────────────────────────────────────────────
	_render() {
		const step = SETUP_STEPS[this.cur];

		// Panel shows exactly one step's content, swapped in full on navigate.
		// Nexus renders its own title inline (beside "Synced ...") instead of
		// using the shared heading above the body.
		this.$root.find(".ts-title").toggleClass("hide", step.key === "nexus").text(step.title);
		this.$root.find(".ts-back").toggleClass("hide", this.cur === 0);
		const nextLabel = this.cur === SETUP_STEPS.length - 1
			? __("Activate")
			: (step.nextLabel || __("Save & continue"));
		this.$root.find(".ts-next .es-button__label").text(nextLabel);
		this.$root.find(".ts-next").prop("disabled", false);
		this._set_next_gated(false);

		// Bar fills up to and including the current step; the caption row
		// below is pure navigation, clickable once a step's been reached.
		this.progress.set_value(((this.cur + 1) / SETUP_STEPS.length) * 100);
		this.$steps.find(".ts-step-btn").each((i, el) => {
			const $el = $(el);
			$el.toggleClass("filled", i <= this.cur).toggleClass("active", i === this.cur);
			$el.prop("disabled", i > this.reached);
		});

		this.$body.empty();
		this[`_render_${step.key}`]();
	}

	// ── Step 1: Welcome ──────────────────────────────────────────────
	_render_welcome() {
		const icon = frappe.utils.icon("external-link", "xs");
		const chartOfAccountsUrl = `${frappe.urllib.get_base_url()}/app/account/view/tree`;

		this.$body.html(`
			<ul class="ts-check">
				<li>
					<a class="ts-check-link" href="https://app.taxjar.com/api_sign_up" target="_blank" rel="noopener noreferrer">
						<span class="ts-check-num">1</span>
						<span class="ts-check-text">${__("Sign Up for TaxJar")}${icon}</span>
					</a>
				</li>
				<li>
					<a class="ts-check-link" href="https://app.taxjar.com/account#api-access" target="_blank" rel="noopener noreferrer">
						<span class="ts-check-num">2</span>
						<span class="ts-check-text">${__("Get API Token from TaxJar")}${icon}</span>
					</a>
				</li>
				<li>
					<a class="ts-check-link" href="https://app.taxjar.com/account#states" target="_blank" rel="noopener noreferrer">
						<span class="ts-check-num">3</span>
						<span class="ts-check-text">${__("Configure Nexus in TaxJar")}${icon}</span>
					</a>
				</li>
				<li>
					<a class="ts-check-link" href="${chartOfAccountsUrl}" target="_blank" rel="noopener noreferrer">
						<span class="ts-check-num">4</span>
						<span class="ts-check-text">
							${__("Review Ledger Accounts")}${icon}
							<ul class="ts-check-sub">
								<li>${__("Sales Tax Payable")}</li>
								<li>${__("Shipping and Freight Income")}</li>
							</ul>
						</span>
					</a>
				</li>
			</ul>
		`);
	}

	// Sandbox/Live as a segmented single-select (frappe.ui.tab_buttons) rather
	// than a closed dropdown - it's a binary choice, worth showing both sides
	// of at once. Wrapped in the same get_value/set_value shape the rest of
	// this file already calls on this.controls.mode.
	_render_mode_toggle($parent, initial) {
		const $el = frappe.ui.tab_buttons({
			options: [
				{ label: __("Sandbox"), value: "Sandbox" },
				{ label: __("Live"), value: "Live" },
			],
			value: initial,
			on_change: () => this._on_mode_change(),
		}).appendTo($parent);

		const tabButtons = $el.data("es-tab-buttons");
		return {
			get_value: () => tabButtons.get_value(),
			set_value: (v) => tabButtons.set_value(v, { silent: true }),
		};
	}

	// ── Step 2: Connect ─────────────────────────────────────────
	_render_connect() {
		const s = this.state || {};
		const creds = (s.credentials && s.credentials.length) ? s.credentials : [{ company: null, token_last4: null }];

		this.$body.html(`
			<div class="ts-card">
				<div class="ts-card-b ts-mode-row">
					<div>
						<label class="control-label">${__("API Mode")} <span class="ts-reqd">*</span></label>
					</div>
					<div class="ts-field-mode"></div>
				</div>
			</div>

			<div class="ts-card" style="margin-top:20px">
				<div class="ts-card-h ts-cred-heading">
					<span class="ts-acc-chevron">${frappe.utils.icon("chevron-right", "sm")}</span>
					<b>${__("API Credentials")}</b>
				</div>
				<div class="ts-card-b ts-cred-rows"></div>
				<div class="ts-card-b ts-cred-add-row"></div>
			</div>

			<div class="ts-card ts-logtoggle" style="margin-top:20px">
				<div class="ts-card-b">
					<div class="ts-field-logging"></div>
				</div>
				<div class="ts-card-b ts-retention-row">
					<div>
						<label class="control-label">${__("Retention")}</label>
						<p class="ts-fieldnote ts-retention-note"></p>
					</div>
					<div class="ts-retention-wrap">
						<div class="ts-field-retention"></div>
						<span class="ts-retention-unit"></span>
					</div>
				</div>
			</div>
		`);

		// A two-option toggle, not a native Select - Sandbox/Live is a binary
		// choice worth showing both sides of at once rather than hiding one
		// behind a closed dropdown. Not a real frappe control, so it can't
		// get InfoCard for free the way Select did; the label+description
		// are hand-authored instead (same as Enable API logs' own reverted
		// plain-description treatment above).
		this.controls.mode = this._render_mode_toggle(this.$body.find(".ts-field-mode"), s.api_mode || "Live");

		// this.controls.mode.get_value() is safe to read synchronously here
		// (unlike a real frappe control's set_value(), the toggle above has no
		// frappe.run_serially step to resolve), but _modeIsLive stays its own
		// tracked flag regardless, since credential cards not yet built at
		// this point (see _add_credential_card below) need to read it too;
		// _on_mode_change() keeps it in sync from here on.
		this._modeIsLive = (s.api_mode || "Live") === "Live";

		this._connectCards = [];
		creds.forEach((cred) => this._add_credential_card(cred));
		// Reapplies whatever this instance's expand state already was (e.g. the
		// user collapsed it, then went Back and returned) rather than always
		// resetting to expanded on every re-render of this step.
		this._set_creds_expanded(this._credsExpanded);

		this.$body.find(".ts-cred-heading").on("click", () => this._set_creds_expanded(!this._credsExpanded));
		// Lives below the rows now (inside .ts-cred-add-row), not in the
		// clickable heading, so it's only ever visible/reachable while already
		// expanded - no need to force-expand or guard against also toggling
		// the heading's own collapse.
		this.$body.find(".ts-cred-add-row").append(frappe.ui.button({
			label: __("Add another company"), icon: "plus", variant: "outline", size: "sm",
			onclick: () => this._add_credential_card({ company: null, token_last4: null }),
		}));

		// fieldtype "Switch" (frappe.ui.form.ControlSwitch, controls/switch.js)
		// is a real pill toggle already shipped and styled in frappe core
		// (frappe/public/scss/common/controls.scss's .switch-control/
		// .switch-visual/.switch-thumb, already part of the desk CSS bundle)
		// - reachable from a plain script exactly like Check is, no Vue/
		// frappe-ui package involved. Replaces the hand-rolled CSS checkbox
		// (appearance:none + ::before track/thumb), which rendered as a
		// broken grey ring instead of a clean switch in practice. Its own
		// native label+description replace the hand-authored .ts-togtext.
		this.controls.enableLogging = frappe.ui.form.make_control({
			parent: this.$body.find(".ts-field-logging"),
			df: {
				fieldtype: "Switch", fieldname: "enable_taxjar_logging",
				label: __("Enable API Logs"),
				description: __("Records API requests, responses, and errors."),
			},
			render_input: true,
		});
		this.controls.enableLogging.set_value(s.enable_taxjar_logging ? 1 : 0);

		// only_input: the unit text to the right already says what this
		// number means, so a separate field label would be redundant.
		this.controls.logRetention = frappe.ui.form.make_control({
			parent: this.$body.find(".ts-field-retention"),
			df: { fieldtype: "Int", fieldname: "log_retention_days" },
			only_input: true,
			render_input: true,
		});
		this.controls.logRetention.set_value(s.log_retention_days != null ? s.log_retention_days : 15);

		const $retentionUnit = this.$body.find(".ts-retention-unit");
		const $retentionNote = this.$body.find(".ts-retention-note");
		// The unit beside the input and the description under the label turn on
		// the same singular/plural test, so one function writes both - two
		// listeners on the same input is how they end up disagreeing.
		//
		// Two whole sentences rather than one with the word interpolated in:
		// the languages frappe ships translations for don't all pluralise by
		// swapping a single word, and a translator handed "day"/"days" on its
		// own has no sentence to agree it with. The description lives here
		// rather than in the template for the same reason it changes at all -
		// it has no correct static form.
		const syncRetentionCopy = (days) => {
			const one = cint(days) === 1;
			$retentionUnit.text(one ? __("day") : __("days"));
			$retentionNote.text(one
				? __("Logs older than specified day are auto-purged.")
				: __("Logs older than specified days are auto-purged."));
		};
		// set_value() above resolves through frappe.run_serially, so reading
		// get_value() back synchronously right here would still see the
		// pre-set value on first render (same class of bug as _modeIsLive) -
		// seed from the already-known state/default instead, and only trust
		// get_value() from here on for the change event.
		syncRetentionCopy(s.log_retention_days != null ? s.log_retention_days : 15);
		this.controls.logRetention.$input.on("input", () => {
			syncRetentionCopy(this.controls.logRetention.get_value());
		});

		// Log Retention only means anything once logging is on — mirrors the
		// doctype field's own depends_on: eval: doc.enable_taxjar_logging.
		// Hides the whole row (label + description + input), not just the
		// input - "Retention / Logs older than specified days..." with no
		// way to see or edit the day count would read as broken, not off.
		const $retentionField = this.$body.find(".ts-retention-row");
		const syncRetentionVisibility = () => {
			$retentionField.toggle(!!this.controls.enableLogging.get_value());
		};
		// Same asynchronous-set_value gotcha as above - use the known state
		// value for the initial visibility check, not a synchronous read.
		$retentionField.toggle(!!s.enable_taxjar_logging);
		this.controls.enableLogging.$input.on("change", syncRetentionVisibility);

		this._sync_connect_gate();
	}

	_set_creds_expanded(expanded) {
		this._credsExpanded = expanded;
		this.$body.find(".ts-cred-rows, .ts-cred-add-row").css("display", expanded ? "flex" : "none");
		this.$body.find(".ts-cred-heading .ts-acc-chevron").toggleClass("ts-acc-chevron-open", expanded);
	}

	_add_credential_card(cred) {
		// No per-row header anymore - the Company field itself is always
		// visible in the row, so nothing else needs to identify which
		// company a row is for. Rows are separated with a divider instead
		// (see .ts-cred-row + .ts-cred-row in the CSS).
		// A company that already has a saved token still needs re-verifying
		// on every visit - the token could have been changed directly on the
		// TaxJar Settings form since this wizard last ran, and trusting a
		// stale "tested" flag showed a green Success pill for a token that
		// was never actually checked. See the auto-test call below.
		const alreadySaved = !!cred.token_last4;
		const $card = $(`
			<div class="ts-cred-row">
				<div class="ts-field-company"></div>
				<div class="ts-field-token"></div>
				<div class="ts-cred-tail">
					<div class="ts-cred-action"></div>
					<button class="ts-card-remove" title="${__("Remove")}">&times;</button>
				</div>
			</div>
		`).appendTo(this.$body.find(".ts-cred-rows"));

		const entry = { company: cred.company, tested: false, lastError: null, $card, controls: {} };
		this._connectCards.push(entry);

		const otherCompanies = () => this._connectCards
			.filter((c) => c !== entry)
			.map((c) => c.controls.company && c.controls.company.get_value())
			.filter(Boolean);

		const companyControl = frappe.ui.form.make_control({
			parent: $card.find(".ts-field-company"),
			df: {
				fieldtype: "Link", fieldname: "company", options: "Company", label: __("Company"), reqd: 1,
				get_query: () => ({ filters: { name: ["not in", otherCompanies()] } }),
			},
			render_input: true,
		});
		// set_value() below (restoring an existing credential's company) fires
		// df.onchange itself as part of setting the value - not just real user
		// input - so without this guard, populating an already-saved card
		// immediately re-fired onchange and reset entry.tested straight back to
		// false right after alreadySaved had just set it true, wiping the
		// "Success" pill the moment the card rendered.
		let restoringInitialCompany = !!cred.company;
		companyControl.df.onchange = () => {
			if (restoringInitialCompany) {
				restoringInitialCompany = false;
				return;
			}
			entry.company = companyControl.get_value();
			entry.tested = false;
			this._reset_cred_status(entry);
			this._sync_connect_gate();
		};
		if (cred.company) {
			companyControl.set_value(cred.company);
			// Company is the key save_connection upserts on — locked once a token is
			// already stored for it, so Continue can't silently orphan that row.
			companyControl.df.read_only = 1;
			companyControl.refresh();
		}
		entry.controls.company = companyControl;

		// ControlLink builds its own <input> and (unlike ControlData) never sets
		// autocomplete="off" on it - harmless on its own, but this field sits
		// right above the Password field below, which is exactly the "text input
		// immediately before a password input" shape Chrome's login-manager
		// heuristic looks for. Left alone, Chrome offers to autofill the site's
		// saved login here, dropping "Administrator" into Company and the saved
		// password into the token field, which then fails Link validation.
		companyControl.$input.attr("autocomplete", "off");

		const tokenControl = frappe.ui.form.make_control({
			parent: $card.find(".ts-field-token"),
			df: {
				fieldtype: "Password", fieldname: "token",
				label: this._modeIsLive ? __("Live token") : __("Sandbox token"),
				reqd: !cred.token_last4,
				placeholder: cred.token_last4 ? "••••••••••••" + cred.token_last4 : "",
			},
			render_input: true,
		});
		// Chrome tends to ignore autocomplete="off" (set by ControlData) on
		// password inputs specifically, but does respect "new-password" - the
		// standard way to tell it this isn't a login field to offer saved
		// credentials for.
		tokenControl.$input.attr("autocomplete", "new-password");
		// A TaxJar token isn't a password being created — the strength meter (and
		// the request it fires on every keystroke) makes no sense here and was the
		// source of a 500 in this environment; this control never needed it.
		tokenControl.disable_password_checks();
		entry.controls.token = tokenControl;

		// A saved connection starts "tested" (see alreadySaved above), but that only
		// holds while the stored token is still what's in effect. The moment the
		// user actually types into this field, the value in play changes and the
		// previous verification no longer applies — require a fresh Connect
		// before Continue is ungated again.
		tokenControl.$input.on("input", () => {
			if (!entry.tested) return;
			entry.tested = false;
			this._reset_cred_status(entry);
			this._sync_connect_gate();
		});

		this._render_cred_action(entry);
		$card.find(".ts-card-remove").on("click", () => this._remove_credential_card(entry, cred));
		this._sync_remove_buttons();

		// Re-verify a previously-saved token every time this step is opened,
		// rather than trusting that it's still the one that was last tested -
		// it may have been edited directly on the TaxJar Settings form since.
		// _test_connection sends no token for a restored row, so the server
		// falls back to whatever is currently stored (see test_connection's
		// own docstring) - this is a real check, not a re-display of the old
		// result.
		if (alreadySaved) {
			this._test_connection(entry);
		}
	}

	// At least one company/token row must always remain - the Connect step
	// can't be left with zero credentials to carry into the rest of the
	// wizard. Disabling the sole row's remove button (rather than hiding it,
	// which would shift the row's own layout) is cheaper than re-deriving
	// this from _connectCards.length at every call site that can change it.
	_sync_remove_buttons() {
		const onlyRow = this._connectCards.length <= 1;
		this.$body.find(".ts-card-remove").prop("disabled", onlyRow);
	}

	// The action slot cycles through three states: an idle "Connect" button,
	// a transient "testing…" state (see _test_connection), a green check
	// badge once verified (a status, so a badge - clicking it re-tests), and
	// a red Retry button on failure (an action, so a real button, unlike the
	// status it sits next to). The failure reason itself isn't shown here at
	// all — it lives as the token field's own error text (see
	// _set_token_error), frappe's native invalid-field primitive rather than
	// a bespoke popover. Centralised here since every entry point that can
	// invalidate a previous test (edit company, edit token, switch mode)
	// needs to fall back to the same idle button.
	_render_cred_action(entry) {
		const $action = entry.$card.find(".ts-cred-action").empty();
		this._set_token_error(entry, entry.lastError);
		if (entry.tested) {
			$action.append(this._build_status_badge(entry, {
				theme: "green", icon: "check", size: "lg", title: __("Verified. Click to test again."),
			}));
		} else if (entry.lastError) {
			$action.append(frappe.ui.button({
				icon: "refresh-cw", variant: "outline", theme: "red",
				tooltip: __("Retry"),
				onclick: () => this._test_connection(entry),
			}));
		} else {
			$action.append(frappe.ui.button({
				label: __("Connect"), variant: "outline",
				onclick: () => this._test_connection(entry),
			}));
		}
	}

	// An icon-only status badge doubling as a re-test trigger - frappe.ui.badge
	// itself is deliberately non-interactive markup, so the click/keyboard
	// wiring that makes it re-testable lives here instead. No visible label:
	// the title (and the aria-label badge.js derives from it on an icon-only
	// badge) carries the meaning instead of a "Verified" word. Only the
	// success state still uses this - a failure is an actionable Retry
	// button instead (see _render_cred_action), not a badge.
	_build_status_badge(entry, opts) {
		const $badge = frappe.ui.badge(opts);
		$badge.attr({ role: "button", tabindex: 0 }).css("cursor", "pointer");
		$badge.on("click", () => this._test_connection(entry));
		$badge.on("keydown", (e) => {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				this._test_connection(entry);
			}
		});
		return $badge;
	}

	// Failure reason as the token field's own error, not a separate popover -
	// df.invalid + set_invalid() is frappe's native invalid-field primitive
	// (the same one a required/malformed field uses; see base_input.js), and
	// set_description() is the same help-text slot every other field on this
	// page already uses - .taxjar-setup .has-error .help-box (see the CSS)
	// is what turns it red.
	_set_token_error(entry, message) {
		const tokenCtrl = entry.controls.token;
		tokenCtrl.df.invalid = !!message;
		tokenCtrl.set_invalid();
		tokenCtrl.set_description(message || "");
	}

	_remove_credential_card(entry, cred) {
		const drop = () => {
			this._connectCards = this._connectCards.filter((c) => c !== entry);
			entry.$card.remove();
			this._sync_connect_gate();
			this._sync_remove_buttons();
		};

		if (!cred.company) {
			// Never saved — nothing server-side to clean up.
			drop();
			return;
		}

		frappe.confirm(
			__("Remove {0} and its saved token? This also clears any accounts or features already configured for it.", [cred.company]),
			() => this._call("remove_company", { company: cred.company }).then(() => this._reload_state()).then(drop)
		);
	}

	_reset_cred_status(entry) {
		entry.lastError = null;
		this._render_cred_action(entry);
	}

	_on_mode_change() {
		// Real user-driven change event — the control's value is accurate to read
		// synchronously here, unlike the set_value() call in _render_connect().
		const live = this.controls.mode.get_value() === "Live";
		this._modeIsLive = live;
		this._connectCards.forEach((entry) => {
			const tokenCtrl = entry.controls.token;
			// The last-4 hint / placeholder was computed for the previous mode's
			// token — sandbox and live tokens are different values, so we can't
			// carry it over without another round trip. Re-entry is required.
			tokenCtrl.df.label = live ? __("Live token") : __("Sandbox token");
			tokenCtrl.df.placeholder = "";
			tokenCtrl.df.reqd = 1;
			tokenCtrl.refresh();
			entry.tested = false;
			this._reset_cred_status(entry);
		});
		this._sync_connect_gate();
	}

	_test_connection(entry) {
		// entry.company (kept in sync directly, not re-read off the control) -
		// same asynchronous-set_value gotcha _sync_connect_gate already guards
		// against. This runs synchronously right after set_value() for the
		// auto re-test on a restored card, before that promise has resolved,
		// so the control's own get_value() would still read blank here.
		const company = entry.company;
		if (!company) {
			frappe.show_alert({ message: __("Select a company first."), indicator: "orange" });
			return;
		}
		// Transient state, not routed through _render_cred_action - nothing
		// about entry.tested/lastError has changed yet, this is just what the
		// action slot looks like while the request is in flight. Espresso's
		// spinner (.es-spinner - the same primitive a button shows for its
		// own loading state) stands in on its own here rather than inside a
		// button, since there's no button label worth keeping around for the
		// half-second the request takes.
		entry.$card.find(".ts-cred-action").empty().append(
			$(`<span class="es-spinner" role="status"></span>`).attr("aria-label", __("Connecting…"))
		);

		this._call("test_connection", {
			company,
			token: entry.controls.token.get_value() || undefined,
			mode: this.controls.mode.get_value(),
		}).then((res) => {
			entry.tested = !!res.ok;
			entry.lastError = res.ok ? null : (res.message || __("Could not connect."));
			this._render_cred_action(entry);
			this._sync_connect_gate();
		}).catch(() => {
			entry.tested = false;
			entry.lastError = __("Something went wrong.");
			this._render_cred_action(entry);
		});
	}

	_sync_connect_gate() {
		// Reads c.company (kept in sync directly on the entry), deliberately
		// not the Company control's own get_value(). For a restored card, that
		// control is read-only and its value was just populated via
		// set_value(), which - like the mode label and retention-visibility
		// bugs - resolves asynchronously; reading it back from the control
		// synchronously right here (this runs immediately after every card is
		// added, on every render) could still see the pre-set value and
		// wrongly gate Continue on an already-saved, already-tested credential.
		//
		// Every company must test successfully, not just one - an untested or
		// failed credential left in the list here was reaching later steps
		// (Nexus fetch pulls nexus for every company in one request and used
		// to hard-crash with a raw 401 traceback the moment any one of them
		// had a bad token) with no way back to fix it. Naming the specific
		// company gives the user two concrete ways out: fix its token and
		// re-test, or remove it.
		const withCompany = this._connectCards.filter((c) => c.company);
		if (!withCompany.length) {
			this._set_next_gated(true, __("Add at least one company before continuing."));
			return;
		}
		const untested = withCompany.find((c) => !c.tested);
		this._set_next_gated(
			!!untested,
			untested ? __("Test the connection for {0} (or remove it) before continuing.", [untested.company]) : ""
		);
	}

	_save_connect() {
		const mode = this.controls.mode.get_value();
		const rows = this._connectCards
			.map((c) => ({ company: c.controls.company.get_value(), token: c.controls.token.get_value() }))
			.filter((r) => r.company);

		if (!rows.length) {
			frappe.show_alert({ message: __("Add at least one company."), indicator: "orange" });
			return false;
		}

		const $next = this.$root.find(".ts-next").prop("disabled", true);
		return this._call("save_connection", {
			mode,
			credentials: rows,
			enable_taxjar_logging: this.controls.enableLogging.get_value() ? 1 : 0,
			log_retention_days: this.controls.logRetention.get_value(),
		})
			.then(() => this._reload_state())
			.then(() => true)
			.catch(() => false)
			.finally(() => $next.prop("disabled", false));
	}

	// ── Step 3: Map Ledgers ────────────────────────────────────
	_render_accounts() {
		const s = this.state || {};
		const creds = s.credentials || [];

		if (!creds.length) {
			this.$body.append(frappe.ui.empty_state({
				icon: "inbox",
				title: __("No companies connected yet"),
				description: __("Add a company on the Connect step first."),
				actions: [{
					label: __("Go to Connect"), variant: "outline",
					onclick: () => this._go(SETUP_STEPS.findIndex((step) => step.key === "connect")),
				}],
			}));
			this._accountCards = [];
			return;
		}

		this.$body.html(`
			<p class="ts-fieldnote">${__("Sales Taxes & Charges Template is configured based on the ledgers selected below.")}</p>
			<div class="ts-cardgrid ts-account-cards"></div>
		`);

		const configByCompany = {};
		(s.companies || []).forEach((c) => { configByCompany[c.company] = c; });

		this._accountCards = [];
		creds.forEach((cred) => {
			const cfg = configByCompany[cred.company] || {};
			const $card = $(`
				<div class="ts-card">
					<div class="ts-card-h"><b>${frappe.utils.escape_html(cred.company)}</b></div>
					<div class="ts-card-b">
						<div class="ts-field-tax"></div>
						<div class="ts-field-ship"></div>
					</div>
				</div>
			`).appendTo(this.$body.find(".ts-account-cards"));

			const taxControl = frappe.ui.form.make_control({
				parent: $card.find(".ts-field-tax"),
				df: {
					fieldtype: "Link", fieldname: "tax_account_head", options: "Account",
					label: __("Sales Tax Ledger Account"), reqd: 1,
					show_description_on_click: 1,
					description: __("Sales Tax Liability towards government."),
					get_query: () => ({ filters: { company: cred.company, is_group: 0 } }),
				},
				render_input: true,
			});
			if (cfg.tax_account_head) taxControl.set_value(cfg.tax_account_head);

			const shipControl = frappe.ui.form.make_control({
				parent: $card.find(".ts-field-ship"),
				df: {
					fieldtype: "Link", fieldname: "shipping_account_head", options: "Account",
					label: __("Shipping Ledger Account"), reqd: 1,
					show_description_on_click: 1,
					description: __("Shipping & Handling fees charged to your customer. (Tax applicability as per state rules in TaxJar)"),
					get_query: () => ({ filters: { company: cred.company, is_group: 0 } }),
				},
				render_input: true,
			});
			if (cfg.shipping_account_head) shipControl.set_value(cfg.shipping_account_head);

			// Pre-fill whichever ledger is still blank from the standard US chart of
			// accounts (Sales Tax Payable / Shipping and Freight Income), so the admin
			// sees accounts already filled in and can still override before saving.
			if (!cfg.tax_account_head || !cfg.shipping_account_head) {
				this._call("get_default_ledgers", { company: cred.company }).then((defaults) => {
					defaults = defaults || {};
					if (!cfg.tax_account_head && defaults.tax_account_head) {
						taxControl.set_value(defaults.tax_account_head);
					}
					if (!cfg.shipping_account_head && defaults.shipping_account_head) {
						shipControl.set_value(defaults.shipping_account_head);
					}
				});
			}

			this._accountCards.push({ company: cred.company, controls: { tax: taxControl, ship: shipControl } });
		});
	}

	_save_accounts() {
		const rows = (this._accountCards || []).map((c) => ({
			company: c.company,
			tax_account_head: c.controls.tax.get_value(),
			shipping_account_head: c.controls.ship.get_value(),
		}));

		if (!rows.length || rows.some((r) => !r.tax_account_head || !r.shipping_account_head)) {
			frappe.show_alert({ message: __("Fill in both accounts for every company."), indicator: "orange" });
			return false;
		}

		const $next = this.$root.find(".ts-next").prop("disabled", true);
		return this._call("save_company_accounts", { rows })
			.then(() => this._reload_state())
			.then(() => true)
			.catch(() => false)
			.finally(() => $next.prop("disabled", false));
	}

	// ── Step 4: Features ────────────────────────────────────────────
	// No master switch here — taxjar_enabled is managed on the TaxJar Settings
	// doctype directly, not by this wizard. This step only ever touches the
	// per-company Calculate/File flags.
	_render_features() {
		const s = this.state || {};
		const companies = s.companies || [];

		this._featureCards = [];
		if (!companies.length) {
			this.$body.append(frappe.ui.empty_state({
				icon: "settings",
				title: __("No company accounts yet"),
				description: __("Add company accounts first."),
				actions: [{
					label: __("Go to Map Ledgers"), variant: "outline",
					onclick: () => this._go(SETUP_STEPS.findIndex((step) => step.key === "accounts")),
				}],
			}));
			return;
		}

		this.$body.html(`<div class="ts-cardgrid ts-feature-cards"></div>`);
		companies.forEach((c) => this._add_feature_card(c));
	}

	_add_feature_card(c) {
		const $card = $(`
			<div class="ts-card">
				<div class="ts-card-h"><b>${frappe.utils.escape_html(c.company)}</b></div>
				<div class="ts-card-b ts-cotog">
					<div class="ts-togrow">
						<div class="ts-field-calc"></div>
						<div class="ts-togtext"><b>${__("Compute Taxes on Sales")}</b><p>${__("Nexus based accurate tax calculation")}</p></div>
					</div>
					<div class="ts-togrow">
						<div class="ts-field-file"></div>
						<div class="ts-togtext"><b>${__("Sync Transactions to TaxJar")}</b><p>${__("File your sales tax return with {0}", [`<a href="${AUTOFILE_DOC_URL}" target="_blank" rel="noopener noreferrer">${__("TaxJar AutoFile")}</a>`])}</p></div>
					</div>
				</div>
			</div>
		`).appendTo(this.$body.find(".ts-feature-cards"));

		const calc = frappe.ui.form.make_control({
			parent: $card.find(".ts-field-calc"), df: { fieldtype: "Check", fieldname: "calculate" }, render_input: true,
		});
		calc.set_value(c.calculate ? 1 : 0);

		const file = frappe.ui.form.make_control({
			parent: $card.find(".ts-field-file"), df: { fieldtype: "Check", fieldname: "file" }, render_input: true,
		});
		file.set_value(c.file ? 1 : 0);

		this._featureCards.push({ company: c.company, controls: { calc, file } });
	}

	_save_features() {
		// NOT sent as "flags" - frappe.call()'s get_newargs() unconditionally
		// strips any kwarg literally named "flags" from every whitelisted API
		// call (a security measure, unrelated to this doctype), so the server
		// param is company_flags instead. See save_features()'s docstring.
		const company_flags = (this._featureCards || []).map((c) => ({
			company: c.company,
			calculate: c.controls.calc.get_value() ? 1 : 0,
			file: c.controls.file.get_value() ? 1 : 0,
		}));

		const $next = this.$root.find(".ts-next").prop("disabled", true);
		return this._call("save_features", { company_flags })
			.then(() => this._reload_state())
			.then(() => true)
			.catch(() => false)
			.finally(() => $next.prop("disabled", false));
	}

	// ── Step 5: Sync Nexus ───────────────────────────────────────────────
	_render_nexus() {
		const s = this.state || {};
		const nexusByCompany = s.nexus_by_company || {};

		this.$body.html(`
			<div class="ts-nexusnote-mount"></div>
			<div class="ts-nexusaction">
				<h2 class="ts-nexustitle">${frappe.utils.escape_html(SETUP_STEPS[this.cur].title)}</h2>
				<span class="ts-fetchstatus"></span>
				<span class="ts-lastsync"></span>
				<div class="ts-fetch-mount"></div>
			</div>
			<div class="ts-cardgrid ts-nexusresult"></div>
		`);

		this.$body.find(".ts-nexusnote-mount").append(frappe.ui.alert({
			theme: "blue",
			title: __("Nexus regions are fetched daily at midnight from TaxJar"),
			footer: () => frappe.ui.button({
				label: __("Manage TaxJar Nexus"), variant: "outline", size: "xs", icon_right: "external-link",
				onclick: () => window.open(TAXJAR_NEXUS_URL, "_blank", "noopener,noreferrer"),
			}),
		}));

		this.$body.find(".ts-fetch-mount").append(frappe.ui.button({
			icon: "refresh-cw", variant: "outline",
			title: __("Fetch from TaxJar"),
			onclick: () => this._fetch_nexus(),
		}));
		this.$body.find(".ts-fetchstatus").append(frappe.ui.badge({ label: __("Not fetched yet") }));

		this._render_nexus_groups(nexusByCompany);
		this._render_last_sync(s.nexus_last_synced);

		// Opening this step always pulls the latest — no need to remember to
		// click Fetch just to see current nexus. The status badge above is
		// overwritten immediately by _fetch_nexus()'s own in-progress state.
		this._fetch_nexus();
	}

	_render_nexus_groups(nexusByCompany) {
		const $result = this.$body.find(".ts-nexusresult");
		const companies = Object.keys(nexusByCompany).filter((c) => nexusByCompany[c].length);
		if (!companies.length) { $result.empty(); return; }

		$result.html(companies.map((company) => {
			const regions = nexusByCompany[company];
			const pills = regions.map((r) => `
				<span class="ts-pill">${frappe.utils.escape_html(r.region || r.region_code)}
					<span class="ts-pillcode">${frappe.utils.escape_html(r.region_code)}</span></span>
			`).join("");
			return `
				<div class="ts-card">
					<div class="ts-card-h"><b>${frappe.utils.escape_html(company)}</b></div>
					<div class="ts-card-b"><div class="ts-pills">${pills}</div></div>
				</div>
			`;
		}).join(""));
	}

	// Blank until a sync has actually happened - "Synced never" is noise on
	// a first run, and the status badge beside it already says "Not fetched yet".
	_render_last_sync(when) {
		this.$body.find(".ts-lastsync").html(
			when ? __("Synced {0}", [frappe.datetime.comment_when(when)]) : ""
		);
	}

	_fetch_nexus() {
		const $status = this.$body.find(".ts-fetchstatus").empty();
		const $btn = this.$body.find(".ts-fetch-mount .es-button").attr("aria-busy", "true");

		this._call("fetch_nexus", {}).then((res) => {
			this.state.nexus_by_company = res.nexus_by_company;
			this._render_nexus_groups(res.nexus_by_company);
			this.state.nexus_last_synced = res.nexus_last_synced;
			this._render_last_sync(res.nexus_last_synced);
		}).catch(() => {
			$status.append(frappe.ui.badge({ label: __("Could not fetch nexus."), theme: "red" }));
		}).finally(() => $btn.removeAttr("aria-busy"));
	}

	// ── Step 6: Review ──────────────────────────────────────────────
	_render_review() {
		const s = this.state || {};
		const companies = s.companies || [];
		const nexusByCompany = s.nexus_by_company || {};
		const totalNexus = Object.values(nexusByCompany).reduce((n, arr) => n + arr.length, 0);
		const nexusCompaniesN = Object.keys(nexusByCompany).length;

		// Company name and its accounts stack on their own lines — a company
		// name and "Tax head · Shipping head" side by side wraps unevenly and
		// never lines up cleanly in a two-column row. Tax Ledger / Shipping
		// Ledger get their own line each too, rather than being crammed
		// together on one line with no indication of which was which.
		const accountRows = companies.map((c) => `
			<div class="ts-accrow">
				<div class="ts-acc-company">${frappe.utils.escape_html(c.company)}</div>
				<div class="ts-acc-detail">${__("Tax Ledger")}: ${frappe.utils.escape_html(c.tax_account_head || "—")}</div>
				<div class="ts-acc-detail">${__("Shipping Ledger")}: ${frappe.utils.escape_html(c.shipping_account_head || "—")}</div>
			</div>
		`).join("") || `<div class="text-muted small">${__("No accounts configured yet.")}</div>`;

		const featureRows = companies.map((c) => `
			<div class="ts-kv ts-kv-company"><span>${frappe.utils.escape_html(c.company)}</span>
				<span>${c.calculate && c.file ? __("Sales Tax · Transactions Sync") : c.calculate ? __("Compute Sales Tax") : c.file ? __("Sync Transactions") : __("Off")}</span></div>
		`).join("") || `<div class="text-muted small">${__("No companies configured yet.")}</div>`;

		const mode = s.api_mode || "—";
		const modeDisplay = mode === "Live"
			? `<span class="indicator-pill green no-indicator-dot">${__("Live")}</span>`
			: frappe.utils.escape_html(mode);

		const retentionDays = s.log_retention_days;
		const logsDisplay = s.enable_taxjar_logging
			? __("Enabled · {0} {1} retention", [retentionDays, retentionDays === 1 ? __("day") : __("days")])
			: __("Off");

		this.$body.html(`
			<div class="ts-cardgrid">
				<div class="ts-card"><div class="ts-card-h"><b>${__("Connection")}</b></div>
					<div class="ts-card-b" style="gap:0">
						<div class="ts-kv"><span>${__("Mode")}</span><span>${modeDisplay}</span></div>
						<div class="ts-kv"><span>${__("API Logs")}</span><span class="ts-kv-plain">${logsDisplay}</span></div>
					</div></div>
				<div class="ts-card"><div class="ts-card-h"><b>${__("Nexus")}</b></div>
					<div class="ts-card-b" style="gap:0">
						<div class="ts-kv"><span>${__("Regions")}</span><span class="ts-kv-plain">${__("{0} across {1} {2}", [totalNexus, nexusCompaniesN, nexusCompaniesN === 1 ? __("company") : __("companies")])}</span></div>
						<div class="ts-kv"><span>${__("Auto-Refresh")}</span><span class="ts-kv-plain">${__("Daily at midnight")}</span></div>
					</div></div>
				<div class="ts-card"><div class="ts-card-h"><b>${__("Accounts")}</b></div>
					<div class="ts-card-b" style="gap:0">${accountRows}</div></div>
				<div class="ts-card"><div class="ts-card-h"><b>${__("Features")}</b></div>
					<div class="ts-card-b" style="gap:0">${featureRows}</div></div>
			</div>
		`);
	}
}
