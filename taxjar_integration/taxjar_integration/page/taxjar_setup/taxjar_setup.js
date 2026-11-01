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
// failure surfaces as a message line under the token field, beside a Retry
// button, not a popover and not a red field.
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
	// Leaving the route only hides this cached page, so a playing walkthrough
	// keeps its sound with nothing on screen. frappe fires "hide" on the
	// wrapper when another route takes its place.
	$(wrapper).on("hide", () => wrapper.taxjar_setup._stop_setup_video());
};

frappe.pages["taxjar-setup"].on_page_show = function (wrapper) {
	wrapper.taxjar_setup._on_arrive();
};

const AUTOFILE_DOC_URL = "https://support.taxjar.com/article/908-how-does-autofile-work";

// The two videos the page plays. Each is a bare video id, not a watch URL,
// because the page embeds it rather than linking out - the id is the only part
// of a YouTube URL an embed needs, and swapping a video is then a one-token
// edit. An empty string drops that player row rather than shipping a play
// button that opens nothing.
//
// SETUP_VIDEO_ID is the setup walkthrough on the first wizard screen.
// WALKTHROUGH_VIDEO_ID is the features walkthrough on the "TaxJar is configured"
// screen.
const SETUP_VIDEO_ID = "2RnyQMNnjME";
const WALKTHROUGH_VIDEO_ID = "Y-ppuE5RsLg";

// The name the analytics give each video (SETUP_VIDEOS in telemetry/events.py).
// A video that is not here sends no play event, so a new id cannot send a wrong name.
const VIDEO_NAMES = { [SETUP_VIDEO_ID]: "setup", [WALKTHROUGH_VIDEO_ID]: "features" };

// The video's own thumbnail host. maxresdefault only exists for videos uploaded
// above 720p, so it 404s on plenty of them; hqdefault is generated for every
// video and is the fallback (see the error handler on .ts-video-thumb).
function video_poster(video_id) {
	return `https://i.ytimg.com/vi/${encodeURIComponent(video_id)}`;
}
// Same URL as taxjar_integration.TAXJAR_NEXUS_URL in the app bundle. Kept as
// its own literal rather than read from there: this runs at module scope, and
// a page script that throws on load takes the whole page with it.
const TAXJAR_NEXUS_URL = "https://app.taxjar.com/account#api-access:~:text=Nexus%20Address%20Configuration";

// verify_company_address's {"checked": false} outcomes. The call did not happen,
// so none of these is a verdict about the address - each reads as a muted note
// beside an idle Verify button, never as a rejection and never as a gate.
const ADDRESS_NOT_CHECKED_REASONS = {
	unreachable: __("Could not reach TaxJar."),
	unsupported_country: __("TaxJar only verifies United States addresses."),
	no_credential: __("No TaxJar token for this company yet."),
	out_of_scope: __("TaxJar is not enabled for this company yet."),
	error: __("Could not check this address right now."),
};

// Named for the reader, not for the fieldname - "Missing taxjar_state_code" is
// not a sentence anyone can act on. Keyed by _REQUIRED_ADDRESS_FIELDS.
const ADDRESS_FIELD_LABELS = {
	address_line1: __("Street"),
	city: __("City"),
	taxjar_state_code: __("State Code"),
	pincode: __("Postal Code"),
};

const SETUP_STEPS = [
	// Nothing is actually saved on this step (no form fields), so its button
	// just says "Continue" rather than the misleading "Save & continue".
	{ key: "welcome", label: __("Pre-requisites"), title: __("Integrate TaxJar with ERPNext"), nextLabel: __("Continue") },
	{ key: "connect", label: __("Connect"), title: __("Connect your TaxJar account") },
	{ key: "accounts", label: __("Map Ledgers"), title: __("Map your accounting ledgers") },
	{ key: "address", label: __("Address"), title: __("Add your company address") },
	{ key: "features", label: __("Features"), title: __("Choose features to activate") },
	{ key: "nexus", label: __("Sync Nexus"), title: __("Sync your nexus regions") },
	// The summary, not a step the user walks to. Activate on the last wizard
	// step lands here, and a finished setup opens here. It carries no rail
	// caption and no footer, because there is nothing left to press.
	{ key: "review", title: __("Review & activate") },
];

// The summary is the last entry above; the wizard is everything before it. The
// split is here so the rail, the progress bar and the Activate button all count
// the same steps - the ones the user actually walks.
const SUMMARY_STEP = SETUP_STEPS.length - 1;
const WIZARD_STEPS = SETUP_STEPS.slice(0, SUMMARY_STEP);
const LAST_WIZARD_STEP = WIZARD_STEPS.length - 1;

// The steps the summary shows as editable cards, in wizard order. Titles are
// their own, not the rail's: "Map Ledgers" and "Sync Nexus" tell a first-time
// user what to do next, while this stack describes what is already configured.
// The summary page's cards. Four, not one per wizard step: Ledgers and Features
// describe the same company from two sides, and nothing maps to a step any more
// now that editing re-walks the whole wizard (see _start_edit).
// The parts of the configuration record a `focus` link can name. "connect" is
// the Connection card. The others are a section inside every company card.
const FOCUS_KEYS = ["connect", "nexus", "ledgers", "features", "address"];

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
		// The card a remedial link asked to point at, read off the route on
		// arrival. The review page opens every card, so this marks and scrolls
		// to one rather than opening it.
		this._focus = null;
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
			interval_count: WIZARD_STEPS.length,
		});
		this.$root.find(".ts-rail").append(this.progress.$el);

		this.$steps.html(WIZARD_STEPS.map((s, i) => `
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
		// Cleared on every call, not only on the saving ones. This page exists to
		// change the configuration the transaction forms memoise per company (see
		// taxjar_integration.scope), several steps here write it, and clearing a
		// client-side memo costs nothing - so one line here beats a list of
		// method names to keep in step with the savers below.
		taxjar_integration.clear_scope_cache();
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
		this._reload_state().then(() => {
			if (this._arriving) {
				this._arriving = false;
				this._land();
			}
			this._render();
		});
	}

	// Every arrival re-reads the route. The desk caches this page in
	// frappe.pages[], so a second visit only un-hides the DOM that is already
	// there. `focus` names the card the link wants opened: the invoice sidebar
	// and the transaction tax panel appear because one specific thing is off,
	// and they say which one.
	_on_arrive() {
		let focus = null;
		try {
			focus = new URLSearchParams(window.location.search).get("focus");
		} catch (e) {
			focus = null;
		}
		this._focus = FOCUS_KEYS.includes(focus) ? focus : null;
		this._arriving = true;
		this._load_state();
	}

	// Where a fresh arrival lands. A finished setup opens on the summary, with
	// every step reachable so the rail reads as navigation rather than a gate.
	// An unfinished one keeps the position the user had, which is what makes
	// the guide resumable.
	//
	// Gated on arrival rather than run from every _render(): _load_state() also
	// runs mid-edit, and moving the user then would throw away the step they
	// opened.
	_land() {
		if (!this.state || !this.state.setup_complete) return;
		this.reached = LAST_WIZARD_STEP;
		this.cur = SUMMARY_STEP;
	}

	// ── navigation ───────────────────────────────────────────────────
	_go(i) {
		if (i < 0 || i >= WIZARD_STEPS.length || i > this.reached) return;
		this.cur = i;
		this.reached = Math.max(this.reached, i);
		this._render();
	}

	_advance() {
		if (this.cur < LAST_WIZARD_STEP) {
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

		// One press at a time. The wait below lasts as long as a nexus fetch
		// does, and a second press inside it would send a second save.
		if (this._nextBusy) return;
		this._nextBusy = true;

		// Steps with a save API collect -> save -> reload state -> advance;
		// steps without one (Welcome, Nexus — which persists via its own Fetch
		// action) just advance. The last step activates rather than advances:
		// there is no Review step in between any more (see _finish).
		const step = SETUP_STEPS[this.cur];
		const done = () => (this.cur === LAST_WIZARD_STEP ? this._finish() : this._advance());
		const saver = this[`_save_${step.key}`];

		// Then wait for a running nexus fetch before sending anything. The
		// fetch and every saver here write the same TaxJar Settings record, and
		// the database answers the second writer with "Deadlock Occurred"
		// rather than queueing it. The two meet on the Nexus step, which starts
		// a fetch as it opens and carries the Activate button: a user who
		// presses Activate straight away used to get that error instead of an
		// activated setup.
		const $btn = this.$root.find(".ts-next");
		if (this._nexus_fetching) $btn.attr("aria-busy", "true");

		Promise.resolve(this._nexus_fetch).then(() => {
			$btn.removeAttr("aria-busy");
			if (!saver) return done();
			return Promise.resolve(saver.call(this)).then(
				(ok) => (ok ? done() : this._track_step_failed(step.key)),
				(error) => {
					this._track_step_failed(step.key);
					throw error;
				}
			);
		}).finally(() => { this._nextBusy = false; });
	}

	// ── editing ──────────────────────────────────────────────────────
	// The one way to change anything. It starts the wizard at Connect - the
	// first step that holds configuration, since Pre-requisites is a checklist
	// of links to TaxJar with nothing on it to edit - and the user walks
	// forward from there.
	//
	// There is no per-step edit and no way back to the summary except through
	// the wizard. Rotating one token therefore costs the remaining screens and
	// one Activate, which is the price of having exactly one path: a
	// configuration re-confirmed end to end cannot be left half valid.
	//
	// Every step stays reachable from the rail on the way through. The data
	// behind each one is already valid, so the rail is navigation here rather
	// than a gate.
	_start_edit() {
		this.reached = LAST_WIZARD_STEP;
		this.cur = SETUP_STEPS.findIndex((step) => step.key === "connect");
		this._focus = null;
		this._render();
	}

	// Visually disabled but still clickable, so a click can explain why instead
	// of a native `disabled` button silently eating it.
	_set_next_gated(blocked, message) {
		this._nextGated = blocked;
		this._nextGateMessage = message;
		this.$root.find(".ts-next").toggleClass("ts-next-gated", blocked);
	}

	// Activation stays on this page rather than routing to TaxJar Settings: the
	// form is one of several places the user might want to go next, and picking
	// one for them lands most of them somewhere they did not ask to be. No
	// toast either - the screen itself is the confirmation.
	//
	// It re-reads state instead of drawing the sealed screen directly, because
	// setup_complete is what every part of this page now branches on. One read
	// after the write keeps the screen and the flag telling the same story.
	//
	// The move to the summary waits on that read. If the flag did not land, the
	// user stays on the last step with the Activate button, rather than sitting
	// on a summary that claims a setup the server has not recorded.
	_finish() {
		const $btn = this.$root.find(".ts-next").prop("disabled", true);
		this._call("finish_setup", {})
			.then(() => this._reload_state())
			.then(() => {
				if (this.state && this.state.setup_complete) {
					this.reached = LAST_WIZARD_STEP;
					this.cur = SUMMARY_STEP;
				}
				this._render();
			})
			.finally(() => $btn.prop("disabled", false));
	}

	// ── render ───────────────────────────────────────────────────────
	_render() {
		const step = SETUP_STEPS[this.cur];

		// Panel shows exactly one step's content, swapped in full on navigate.
		// Nexus renders its own title inline (beside "Synced ...") instead of
		// using the shared heading above the body.
		//
		// Two chrome states. The wizard shows the rail and the footer, whether
		// this is a first run or a re-walk - they are the same walk. The sealed
		// summary hides both; its one action sits beside the title instead,
		// where the design puts it, rather than in the desk's own action slot.
		const sealed = this._is_sealed();
		this.$root.find(".ts-head").toggleClass("hide", sealed);
		this.$root.find(".ts-foot").toggleClass("hide", sealed);

		this.$root.find(".ts-title")
			.toggleClass("hide", step.key === "nexus" || sealed)
			.text(step.title);

		this.$root.find(".ts-back").toggleClass("hide", this.cur === 0);

		const nextLabel = this.cur === LAST_WIZARD_STEP
			? __("Activate")
			: (step.nextLabel || __("Save & continue"));
		this.$root.find(".ts-next .es-button__label").text(nextLabel);
		this.$root.find(".ts-next").prop("disabled", false);
		this._set_next_gated(false);

		// Bar fills up to and including the current step; the caption row
		// below is pure navigation, clickable once a step's been reached.
		this.progress.set_value((Math.min(this.cur + 1, WIZARD_STEPS.length) / WIZARD_STEPS.length) * 100);
		this.$steps.find(".ts-step-btn").each((i, el) => {
			const $el = $(el);
			$el.toggleClass("filled", i <= this.cur).toggleClass("active", i === this.cur);
			$el.prop("disabled", i > this.reached);
		});

		this.$body.empty();
		this[`_render_${step.key}`]();
		this._track_step_view(step.key);
	}

	// Analytics for the setup funnel. A view counts once per step change, and
	// only while setup is not finished: a finished setup opens on the summary
	// each time, which is not a step of the funnel.
	_track_step_view(key) {
		if (this.state?.setup_complete || this._viewed_step === key) return;
		this._viewed_step = key;
		taxjar_integration.track("taxjar_setup_step_viewed", { step: key });
	}

	// A step that did not save: the user stays on it and sees why.
	_track_step_failed(key) {
		taxjar_integration.track("taxjar_setup_step_failed", { step: key });
	}

	// Sealed once setup is complete and the user is standing on the summary.
	// Both ways in check the flag first - _land() on arrival and _finish() after
	// activation - so the two always agree.
	_is_sealed() {
		return (
			this.cur === SUMMARY_STEP
			&& !!(this.state && this.state.setup_complete)
		);
	}

	// ── Step 1: Welcome ──────────────────────────────────────────────
	// The walkthrough sits above the checklist, under the step's own title:
	// somebody who has never set this up is deciding whether to read four links
	// or watch the thing being done, and the video has to be visible for that
	// to be a choice. It repeats on the activated screen, which is a different
	// reader on a different day.
	_render_welcome() {
		const icon = frappe.utils.icon("external-link", "xs");
		const chartOfAccountsUrl = `${frappe.urllib.get_base_url()}/app/account/view/tree`;

		this.$body.html(`
			${this._video_card({
				video_id: SETUP_VIDEO_ID,
				title: __("Setup TaxJar"),
				description: __("Quick walkthrough to get your API keys & configure nexus."),
			})}
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
					<a class="ts-check-link" href="${TAXJAR_NEXUS_URL}" target="_blank" rel="noopener noreferrer">
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

		this._bind_setup_video();
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
					${frappe.ui.button.html({
						icon: "x", variant: "ghost", tooltip: __("Remove"), css_class: "ts-card-remove",
					})}
				</div>
				<div class="ts-cred-error"></div>
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
				// TaxJar calculates United States sales tax, so a company registered
				// anywhere else has nothing to configure here. Filtered rather than
				// rejected on save: the wizard should not offer a choice it will
				// then refuse. save_connection() checks it again regardless - a
				// client-side filter is a convenience, not the guard.
				get_query: () => ({
					filters: { name: ["not in", otherCompanies()], country: "United States" },
				}),
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
		// The markup form of frappe.ui.button only names the button from
		// `tooltip`; the bubble itself is bound on the element, here.
		const $remove = $card.find(".ts-card-remove");
		if (frappe.ui.tooltip) frappe.ui.tooltip($remove, { text: __("Remove") });
		$remove.on("click", () => this._remove_credential_card(entry, cred));
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

	// The action slot cycles through four states: an idle Connect button, a
	// transient Connecting… (see _test_connection), a green Connected status
	// once verified (not clickable), and a Retry
	// button on failure (an action, so a real button, unlike the status it
	// sits next to).
	//
	// Every one is the same outline button carrying an icon and a word, at its
	// own natural width. They are NOT stretched to the slot: .es-button centres
	// its contents, so a 92px "Connect" forced to 150px put ~29px of bare button
	// either side of the pair and read as the icon being flung away from the
	// word. The slot stays reserved - that is what stops Company and Token
	// resizing mid-request - and the buttons sit at its leading edge, so all
	// four start at the same x without any of them being padded out.
	//
	// The failure reason is not shown here at all. It lives on its own line
	// under the token field (see _set_token_error), next to the input the user
	// has to correct. Centralised here since every entry point that can
	// invalidate a previous test (edit company, edit token, switch mode) needs
	// to fall back to the same idle button.
	_render_cred_action(entry) {
		const $action = entry.$card.find(".ts-cred-action").empty();
		this._set_token_error(entry, entry.lastError);
		if (entry.tested) {
			// Button markup for the look only: it keeps the same height and
			// radius as the other states in the slot. It is a status, so it has
			// no handler. aria-disabled and tabindex -1 take it out of the
			// keyboard order, and the CSS rule blocks the mouse. To re-test,
			// the user edits the company or the token, which resets the slot.
			$action.append(frappe.ui.button({
				label: __("Connected"), icon: "circle-check", variant: "outline",
				css_class: "ts-cred-ok",
				attrs: { "aria-disabled": "true", tabindex: "-1" },
			}));
		} else if (entry.lastError) {
			$action.append(frappe.ui.button({
				label: __("Retry"), icon: "refresh-cw", variant: "outline", theme: "red",
				onclick: () => this._test_connection(entry),
			}));
		} else {
			// A plug that is not in yet. circle-check answers it above rather
			// than a plug-zap: the question this button settles is whether the
			// token works, and a tick says verified where a live plug says
			// powered.
			$action.append(frappe.ui.button({
				label: __("Connect"), icon: "plug", variant: "outline",
				onclick: () => this._test_connection(entry),
			}));
		}
	}

	// A status badge doubling as a re-check trigger - frappe.ui.badge itself is
	// deliberately non-interactive markup, so the click/keyboard wiring that
	// makes it re-checkable lives here instead. Only the success state uses it:
	// a failure is an actionable Retry button (see _render_cred_action), not a
	// status. The tooltip says clicking re-tests, which the word alone does not.
	// frappe.ui.badge has no tooltip option, only a native title, so the
	// tooltip is taken out of `opts` and bound here as the desk's own bubble.
	//
	// One caller left: the Address step's Valid badge (see
	// _render_address_action). The Connect step used this too until its verified
	// state became a real button, which needs none of the wiring below.
	// `onactivate` stays a parameter rather than a hardcoded call so the helper
	// does not name the one check it happens to serve.
	_build_status_badge(opts, onactivate) {
		const { tooltip, ...badge_opts } = opts;
		const $badge = frappe.ui.badge(badge_opts);
		$badge.attr({ role: "button", tabindex: 0 }).css("cursor", "pointer");
		if (tooltip && frappe.ui.tooltip) frappe.ui.tooltip($badge, { text: tooltip, delay: 0 });
		$badge.on("click", () => onactivate());
		$badge.on("keydown", (e) => {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				onactivate();
			}
		});
		return $badge;
	}

	// Failure reason on its own line under the token field, and nothing else.
	// The field is no longer marked invalid: df.invalid + set_invalid() put
	// frappe's red has-error border round the input, which tinted the password
	// control's eye button and made a failed row the loudest thing on the step -
	// louder than the Retry button that actually resolves it. The sentence and
	// the Retry button say what happened between them.
	//
	// The message is NOT set_description(), though: that renders into the
	// control's own .help-box, which made the token column taller than Company -
	// and since the action slot bottom-aligns to the row, the Retry button slid
	// down level with the error text instead of the input it retries. It can't
	// just be moved either; set_description() looks the .help-box up inside the
	// control wrapper. So the message gets its own line in the row
	// (.ts-cred-error), styled and placed as that help-box was.
	_set_token_error(entry, message) {
		// .text(), not .html() - the message is server-supplied (TaxJar's own
		// error text for a rejected token), and :empty is what hides the line.
		entry.$card.find(".ts-cred-error").text(message || "");
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
		// action slot looks like while the request is in flight.
		//
		// A real button in its own loading state, rather than a bare spinner:
		// frappe.ui.button renders Espresso's .es-spinner beside the loading
		// label, at the button's own height and width, and blocks clicks while
		// aria-busy is set. A lone spinner was the narrowest thing the slot ever
		// held, so the column stepped in on click and back out on the answer.
		entry.$card.find(".ts-cred-action").empty().append(frappe.ui.button({
			label: __("Connect"), loading_label: __("Connecting…"), loading: true,
			variant: "outline",
		}));

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
			untested ? __("Please validate API Key for {0}.", [untested.company]) : ""
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
					get_query: () => ({ filters: { company: cred.company, is_group: 0, root_type: "Liability" } }),
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
					get_query: () => ({
						filters: { company: cred.company, is_group: 0, root_type: ["in", ["Income", "Expense"]] },
					}),
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

	// ── Step 4: Address ─────────────────────────────────────────────
	// TaxJar prices a sale from the company's own address, which
	// get_company_address_details() resolves through
	// get_default_address("Company", company) - and that sorts on
	// is_primary_address, the field the Address doctype labels "Preferred
	// Billing Address". So the BILLING flag decides the tax origin, not the
	// shipping one.
	//
	// This step says so rather than quietly picking on the user's behalf: the
	// card marks the address TaxJar actually reads, the dialog offers the
	// doctype's own two checkboxes under its own labels, and Continue is what
	// moves the flag (save_company_address). A step that treated Preferred
	// Shipping as the origin would disagree with what get_tax_data() reads at
	// invoice time, which is worse than either rule on its own.
	_render_address() {
		const s = this.state || {};
		const creds = s.credentials || [];

		this._addressCards = [];
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
			this._set_next_gated(true, __("Add at least one company before continuing."));
			return;
		}

		this.$body.html(`
			<p class="ts-fieldnote">${__("Configure ship from address for accurate sales tax calculation, you can add additional addresses later.")}</p>
			<div class="ts-cardgrid ts-address-cards"></div>
		`);
		// Column count for the content-sized grid in the CSS: one card per
		// company, two to a row.
		this.$body.find(".ts-address-cards").css("--ts-addr-cols", Math.min(creds.length, 2));

		const byCompany = {};
		(s.addresses || []).forEach((a) => { byCompany[a.company] = a; });

		// One card per credential, in that list's order - the same list Map
		// Ledgers iterates, so a company that reached this step always has a
		// card. Order never changes across re-renders: floating the incomplete
		// ones to the top would move a card out from under the cursor at the
		// moment the user finishes with it.
		creds.forEach((cred) => {
			const $card = $(`
				<div class="ts-card">
					<div class="ts-card-h"><b>${frappe.utils.escape_html(cred.company)}</b></div>
					<div class="ts-card-b ts-addr-body"></div>
				</div>
			`).appendTo(this.$body.find(".ts-address-cards"));

			const entry = {
				company: cred.company,
				info: byCompany[cred.company] || { company: cred.company, address: null, missing: [], linked_count: 0 },
				$card,
				verified: false,
				verifyError: null,
				verifyNote: null,
			};
			this._addressCards.push(entry);
			this._render_address_card(entry);
		});

		this._sync_address_gate();
	}

	// Rebuilds one card in place. Cards re-render individually rather than
	// re-rendering the whole step, so editing one company's address doesn't
	// discard the Verify result the user has already spent a TaxJar call on for
	// every other card.
	_render_address_card(entry) {
		const info = entry.info || {};
		const $body = entry.$card.find(".ts-addr-body").empty();

		if (!info.address) {
			$body.append(`
				<p class="ts-addr-none">${__("No address on file for this company.")}</p>
				<div class="ts-addr-add"></div>
			`);
			// Outline, not solid. It is the only action on the card, but the
			// filled treatment is reserved for the page's own Continue - the
			// Connect step's action gave its ink up for exactly this reason, so
			// that one control reads as "the way forward" and nothing competes
			// with it. Being the card's only child is what makes this one
			// obvious; weight is not needed for that.
			//
			// And no Link field at all in this state: filtered to this company's
			// addresses, on a company with none, it opens to an empty dropdown,
			// a control that looks like a choice and offers nothing. It appears
			// once there is something to pick.
			$body.find(".ts-addr-add").append(frappe.ui.button({
				label: __("Add address"), icon: "plus", variant: "outline",
				onclick: () => this._open_address_dialog(entry, null),
			}));
			return;
		}

		$body.append(`
			<div class="ts-addr-pickrow">
				<div class="ts-field-address"></div>
				<div class="ts-addr-new"></div>
			</div>
			<div class="ts-addr-preview">
				<div class="ts-addr-top">
					<div class="ts-addr-lines"></div>
					<div class="ts-addr-tail">
						<div class="ts-addr-action"></div>
						<div class="ts-addr-edit"></div>
					</div>
				</div>
				<div class="ts-addr-verifynote"></div>
				<div class="ts-addr-flags"></div>
				<div class="ts-addr-note"></div>
			</div>
		`);

		const addressControl = frappe.ui.form.make_control({
			parent: $body.find(".ts-field-address"),
			df: {
				fieldtype: "Link", fieldname: "address", options: "Address",
				label: __("Company Address"), reqd: 1,
				// Drops the dropdown's own "Create a new Address" - the card
				// already carries a New address button, and two ways to create
				// the same thing, three lines apart, is one too many. The button
				// is also the better of the two: it opens this step's own dialog,
				// which asks for the four fields TaxJar needs and links the
				// address to the company, where frappe's own route would open a
				// blank Address form the user has to link by hand.
				//
				// only_select takes Advanced Search with it - frappe has no flag
				// for one without the other (see link.js) - and that is no loss
				// here: the list is already filtered to this company's own US
				// addresses, which is rarely more than two or three rows.
				only_select: 1,
				// address_query is frappe's own Dynamic Link-aware search; the
				// leftover `country` filter it doesn't consume becomes a plain
				// field filter on Address. Same reasoning as the Company link on
				// Connect: the wizard should not offer a choice it will refuse.
				get_query: () => ({
					query: "frappe.contacts.doctype.address.address.address_query",
					filters: {
						link_doctype: "Company",
						link_name: entry.company,
						country: "United States",
					},
				}),
			},
			render_input: true,
		});
		// set_value() below fires df.onchange itself as part of setting the
		// value, not just on real user input - the same trap the Connect step's
		// company control documents. Without this guard, restoring the current
		// address would immediately look like the user had picked a new one and
		// fire a reload on every render.
		let restoringInitialAddress = true;
		addressControl.df.onchange = () => {
			if (restoringInitialAddress) {
				restoringInitialAddress = false;
				return;
			}
			const picked = addressControl.get_value();
			if (!picked || picked === entry.info.address) return;
			// Previewed, not pinned - Continue is what writes the Preferred
			// Billing flag (save_company_address), the same way every other
			// step in this wizard defers its write to the same button.
			this._reload_address_card(entry, picked);
		};
		addressControl.set_value(info.address);
		// ControlLink leaves its <input> without autocomplete="off"; same
		// browser-autofill nuisance the Connect step's company field disables.
		addressControl.$input.attr("autocomplete", "off");

		$body.find(".ts-addr-new").append(frappe.ui.button({
			label: __("New address"), icon: "plus", variant: "outline", size: "sm",
			onclick: () => this._open_address_dialog(entry, null),
		}));

		const cityLine = [
			info.city,
			[info.taxjar_state_code, info.pincode].filter(Boolean).join(" "),
		].filter(Boolean).join(", ");
		const $lines = $body.find(".ts-addr-lines");
		[info.address_line1, info.address_line2, cityLine, info.country]
			.filter(Boolean)
			.forEach((line) => $lines.append($("<div></div>").text(line)));

		$body.find(".ts-addr-edit").append(frappe.ui.button({
			icon: "pencil", variant: "ghost", size: "sm",
			tooltip: __("Edit"),
			onclick: () => this._open_address_dialog(entry, info),
		}));

		this._render_address_flags(entry);
		this._render_address_note(entry);
		this._render_address_verify_note(entry);
		this._render_address_action(entry);

		// Verified on sight, not on click. Same as the Connect step re-testing
		// every saved token when it opens and the Nexus step re-fetching on
		// open: the answer is wanted the moment the step is looked at, and a
		// [ Verify ] button the user has to find first just delays the only
		// outcome they were ever going to ask for.
		//
		// Re-runs on every visit rather than remembering a verdict, and for the
		// same reason Connect re-tests rather than trusting a stale "tested"
		// flag: the address may have been edited on the Address form since, so
		// a remembered answer would be about a document that no longer exists
		// in that shape. The idle button stays as the way to ask again.
		if (this._address_is_verifiable(entry)) this._verify_address(entry);
	}

	// Nothing to verify without a complete address - TaxJar would be answering
	// about a street with no state or postal code.
	_address_is_complete(entry) {
		const info = entry.info || {};
		return !!info.address && !(info.missing || []).length;
	}

	// TaxJar's sandbox has no address endpoint, so in Sandbox mode the card
	// sends nothing and shows "Skipped" in place of a verdict.
	_address_is_verifiable(entry) {
		return this._address_is_complete(entry) && !this._is_sandbox_mode();
	}

	// The saved mode, not the Connect step's toggle: the server checks
	// against the saved one, and Continue on Connect reloads the state.
	_is_sandbox_mode() {
		return (this.state || {}).api_mode === "Sandbox";
	}

	// A restatement of the address's own two flags, not a second place to edit
	// them - the checkboxes live in the dialog, which is where they are written.
	// The Preferred Billing pill is the whole story: the dialog's own checkbox
	// already says that flag is what TaxJar calculates tax from, so repeating it
	// here as a caption said the same thing twice on one card.
	_render_address_flags(entry) {
		const info = entry.info || {};
		const $flags = entry.$card.find(".ts-addr-flags").empty();

		if (info.is_primary_address) $flags.append($(`<span class="ts-pill"></span>`).text(__("Billing")));
		if (info.is_shipping_address) $flags.append($(`<span class="ts-pill"></span>`).text(__("Shipping")));
	}

	// Several linked addresses and none of them pinned: `is_primary_address DESC`
	// is then sorting a column that is 0 for every candidate, so `limit 1`
	// returns whichever row the database hands back.
	//
	// Asks about the COMPANY, not about the address on screen. Reading
	// info.is_primary_address here answered "is the one I am looking at pinned",
	// which is false any time the user selects a company's other address - an
	// ordinary thing to do, and Continue pins it anyway - and then reported that
	// as "none marked Preferred Billing" to someone whose company was pinned
	// perfectly well.
	//
	// Deliberately not raised for a single address either: there is nothing
	// ambiguous about one candidate, and warning about it would be noise on the
	// most common setup there is.
	_address_is_ambiguous(info) {
		return info.linked_count > 1 && !info.company_has_preferred_billing;
	}

	// The state of the address itself, and only where something is actually
	// wrong with it: a missing field, or an origin nothing has pinned. A
	// correct, pinned address gets no note at all - saying so would be
	// narrating the happy path. Kept in its own slot from the verification note
	// above it, so a Verify failure never hides a missing ZIP.
	_render_address_note(entry) {
		const info = entry.info || {};
		const $note = entry.$card.find(".ts-addr-note").empty();

		if ((info.missing || []).length) {
			$note.append($(`<span class="ts-addr-warn"></span>`).text(this._missing_address_text(info.missing)));
			return;
		}
		if (this._address_is_ambiguous(info)) {
			$note.append($(`<span class="ts-addr-warn"></span>`).text(__(
				"{0} addresses, none marked Preferred Billing — TaxJar may not use this one. Continue marks it Preferred Billing.",
				[info.linked_count]
			)));
		}
	}

	_missing_address_text(missing) {
		const labels = missing.map((f) => ADDRESS_FIELD_LABELS[f] || f);
		// Two whole sentences rather than one with the pronoun swapped in: the
		// languages frappe ships translations for don't all agree a pronoun with
		// a list the same way, and a translator handed "it"/"them" alone has no
		// sentence to agree it with. Same reasoning as the log-retention copy on
		// the Connect step.
		return labels.length === 1
			? __("Missing {0} — TaxJar needs it to price this address.", [labels[0]])
			: __("Missing {0} — TaxJar needs them to price this address.", [frappe.utils.comma_and(labels)]);
	}

	_render_address_verify_note(entry) {
		const $note = entry.$card.find(".ts-addr-verifynote").empty();
		if (entry.verifyError) {
			$note.append($(`<span class="ts-addr-warn"></span>`).text(entry.verifyError));
		} else if (entry.verifyNote) {
			$note.append($(`<span class="ts-addr-muted"></span>`).text(entry.verifyNote));
		}
	}

	// Same three-state action slot the Connect step uses (idle button ->
	// spinner -> green badge or red Retry), pointed at the address check.
	_render_address_action(entry) {
		const $action = entry.$card.find(".ts-addr-action").empty();
		// A status, not a button: a click could only send the request the
		// sandbox cannot answer.
		if (this._address_is_complete(entry) && this._is_sandbox_mode()) {
			const $badge = frappe.ui.badge({
				label: __("Skipped"), theme: "gray", icon: "info", size: "lg",
			});
			if (frappe.ui.tooltip) frappe.ui.tooltip($badge, { text: __("Address validation is not supported in sandbox."), delay: 0 });
			$action.append($badge);
			return;
		}
		if (!this._address_is_verifiable(entry)) return;

		if (entry.verified) {
			// "Valid", not a bare tick. The card beside it already carries a
			// pencil, and two icon-only controls in one corner leave the reader
			// working out which is a status and which is an action.
			$action.append(this._build_status_badge({
				label: __("Valid"), theme: "green", icon: "circle-check", size: "lg",
				tooltip: __("Found by TaxJar. Click to check again."),
			}, () => this._verify_address(entry)));
		} else if (entry.verifyError) {
			$action.append(frappe.ui.button({
				icon: "refresh-cw", variant: "outline", theme: "red",
				tooltip: __("Retry"),
				onclick: () => this._verify_address(entry),
			}));
		} else {
			$action.append(frappe.ui.button({
				label: __("Verify"), variant: "outline", size: "sm",
				onclick: () => this._verify_address(entry),
			}));
		}
	}

	// A gate, by the product decision recorded in _sync_address_gate: an
	// address TaxJar rejects holds Continue until it is fixed.
	//
	// It was advisory before. TaxJar fails to match some addresses a user
	// entered correctly, which is why the TaxJar check left Address.validate -
	// so a rejected address that is in fact correct now stops this wizard, and
	// the way past it is to edit the address until TaxJar matches it.
	//
	// The three outcomes stay as they were. Only a checked-and-rejected one
	// sets verifyError, which is the single thing the gate reads.
	_verify_address(entry) {
		entry.$card.find(".ts-addr-action").empty().append(
			$(`<span class="es-spinner" role="status"></span>`).attr("aria-label", __("Verifying…"))
		);

		this._call("verify_company_address", { company: entry.company, address: entry.info.address })
			.then((res) => {
				res = res || {};
				if (!res.checked) {
					// The call did not happen, so this is not a verdict about
					// the address: idle button plus a muted reason, not a red
					// badge.
					entry.verified = false;
					entry.verifyError = null;
					entry.verifyNote = ADDRESS_NOT_CHECKED_REASONS[res.reason] || ADDRESS_NOT_CHECKED_REASONS.error;
				} else {
					entry.verified = !!res.valid;
					entry.verifyError = res.valid ? null : __("Invalid address as per TaxJar.");
					entry.verifyNote = null;
				}
				this._render_address_verify_note(entry);
				this._render_address_action(entry);
				// The verdict arrives after the card is drawn, so the gate is
				// set here rather than by whoever asked for the check.
				this._sync_address_gate();
			})
			.catch(() => {
				entry.verified = false;
				entry.verifyError = null;
				entry.verifyNote = ADDRESS_NOT_CHECKED_REASONS.error;
				this._render_address_verify_note(entry);
				this._render_address_action(entry);
				this._sync_address_gate();
			});
	}

	_reload_address_card(entry, address) {
		return this._call("get_company_address_state", { company: entry.company, address: address || undefined })
			.then((info) => {
				entry.info = info;
				// The address under the badge is not the one TaxJar was asked
				// about any more, so the previous verdict no longer applies.
				entry.verified = false;
				entry.verifyError = null;
				entry.verifyNote = null;
				this._render_address_card(entry);
				this._sync_address_gate();
			});
	}

	_open_address_dialog(entry, existing) {
		const isNew = !existing;
		const company = entry.company;

		const d = new frappe.ui.Dialog({
			title: isNew ? __("New address · {0}", [company]) : __("Edit address · {0}", [company]),
			fields: [
				{ fieldtype: "Data", fieldname: "address_title", label: __("Address Title"), reqd: 1 },
				{ fieldtype: "Data", fieldname: "address_line1", label: __("Address Line 1"), reqd: 1 },
				{ fieldtype: "Data", fieldname: "address_line2", label: __("Address Line 2") },
				{ fieldtype: "Section Break" },
				{ fieldtype: "Data", fieldname: "city", label: __("City"), reqd: 1 },
				{ fieldtype: "Column Break" },
				// The taxjar_state_code Select's own options, from the same
				// state map public/js/address.js uses - the server fills `state`
				// in from the code on save, so the pair cannot disagree.
				{
					fieldtype: "Select", fieldname: "taxjar_state_code",
					label: __("State Code"), options: this._state_code_options(), reqd: 1,
				},
				{ fieldtype: "Section Break" },
				{ fieldtype: "Data", fieldname: "pincode", label: __("Postal Code"), reqd: 1 },
				{ fieldtype: "Column Break" },
				// Read-only, not a Link: every company on this step is a US
				// company (company_scope refuses any other, and Connect's link
				// filter never offers one), so this is the only value that can
				// be correct. Shown so the address doesn't read as
				// country-less, not offered as a choice.
				{
					fieldtype: "Data", fieldname: "country", label: __("Country"),
					default: "United States", read_only: 1,
				},
				{ fieldtype: "Section Break" },
				// The Address doctype's own two flags, under its own labels
				// verbatim and with no gloss of the wizard's own. The same
				// checkboxes appear on the Address form the user will edit
				// later, so anything renamed or annotated here would only be
				// something to un-learn there. Preferred Billing is what
				// get_default_address() sorts on and therefore what decides the
				// tax origin (see the section comment above); that rule lives
				// in this file and in the design doc, not in a caption on the
				// form.
				{
					fieldtype: "Check", fieldname: "is_primary_address",
					label: __("Preferred Billing Address"),
				},
				{
					fieldtype: "Check", fieldname: "is_shipping_address",
					label: __("Preferred Shipping Address"),
				},
			],
			primary_action_label: __("Save address"),
			// cstr() on every text field, and not for tidiness: get_values()
			// drops any field whose value is blank (`if (!is_null(v))` in
			// field_group.js), so a field the user cleared arrives here as
			// undefined, JSON.stringify drops the key, and the server - which
			// writes only the keys it is sent - keeps the old value. Clearing
			// Address Line 2 then did nothing at all. cstr() turns the missing
			// key back into the empty string the user asked for.
			primary_action: (values) => {
				d.disable_primary_action();
				const payload = {
					address_title: cstr(values.address_title),
					address_line1: cstr(values.address_line1),
					address_line2: cstr(values.address_line2),
					city: cstr(values.city),
					taxjar_state_code: cstr(values.taxjar_state_code),
					pincode: cstr(values.pincode),
					is_primary_address: values.is_primary_address ? 1 : 0,
					is_shipping_address: values.is_shipping_address ? 1 : 0,
				};

				const saved = isNew
					? this._call("create_company_address", { company, values: payload })
					: this._call("update_company_address", { company, address: existing.address, values: payload });

				saved
					.then((res) => {
						d.hide();
						return this._reload_address_card(entry, res.address);
					})
					.catch(() => d.enable_primary_action());
			},
		});

		d.set_values(isNew
			? {
				address_title: company,
				country: "United States",
				// A new address is both, by default. It is the one the user
				// just went out of their way to enter, so having TaxJar
				// actually use it is the outcome they were after - and it
				// keeps a company from ending up with several addresses and
				// nothing pinned, which is the one state the origin is
				// arbitrary in (see _address_is_ambiguous). Untick either to
				// add an address without moving anything.
				is_primary_address: 1,
				is_shipping_address: 1,
			}
			: {
				address_title: existing.address_title,
				address_line1: existing.address_line1,
				address_line2: existing.address_line2,
				city: existing.city,
				taxjar_state_code: existing.taxjar_state_code,
				pincode: existing.pincode,
				country: "United States",
				is_primary_address: existing.is_primary_address ? 1 : 0,
				is_shipping_address: existing.is_shipping_address ? 1 : 0,
			});
		d.show();
	}

	_state_code_options() {
		// Read lazily rather than at module scope: us_state_code_options comes
		// from the app bundle, and a page script that throws while loading takes
		// the whole page with it (the same reason TAXJAR_NEXUS_URL is a literal
		// up top rather than read from there).
		if (!window.taxjar_integration) return [{ label: "", value: "" }];
		return taxjar_integration.us_state_code_options();
	}

	// Three things gate: no address at all, an incomplete one, and one TaxJar
	// has answered about and rejected. Not an ambiguous origin - that one is
	// resolved by the very button it would be blocking.
	//
	// The third is the address the user has just entered or just picked, since
	// the card verifies itself on sight (see _render_address_card) - so both
	// ways in reach this same check without the user pressing anything.
	//
	// It gates on a verdict, never on the absence of one: an address TaxJar
	// could not be asked about carries verifyNote instead of verifyError, and
	// an unreachable TaxJar must not hold up a setup.
	//
	// The first two name one company at a time, first in card order, with the
	// verb that matches its state; the message re-points itself as each is
	// fixed.
	_sync_address_gate() {
		const cards = this._addressCards || [];

		const noAddress = cards.find((c) => !c.info || !c.info.address);
		if (noAddress) {
			this._set_next_gated(true, __("Add an address for {0} before continuing.", [noAddress.company]));
			return;
		}

		const incomplete = cards.find((c) => (c.info.missing || []).length);
		if (incomplete) {
			this._set_next_gated(true, __("Complete the address for {0} before continuing.", [incomplete.company]));
			return;
		}

		// The only one of the three that names no company: the card carries
		// the same verdict under the address it is about, so the reader is
		// already looking at the one to review.
		const invalid = cards.find((c) => c.verifyError);
		this._set_next_gated(!!invalid, invalid ? __("Please review the address, its invalid as per TaxJar.") : "");
	}

	// Sends every card's current address, not just the changed ones -
	// _set_preferred_billing() skips any row whose flag already matches, so a
	// re-send is a no-op rather than a pointless save.
	_save_address() {
		const rows = (this._addressCards || [])
			.filter((c) => c.info && c.info.address)
			.map((c) => ({ company: c.company, address: c.info.address }));

		if (!rows.length) {
			frappe.show_alert({ message: __("Add an address for every company."), indicator: "orange" });
			return false;
		}

		const $next = this.$root.find(".ts-next").prop("disabled", true);
		return this._call("save_company_address", { rows })
			.then(() => this._reload_state())
			.then(() => true)
			.catch(() => false)
			.finally(() => $next.prop("disabled", false));
	}

	// ── Step 5: Features ────────────────────────────────────────────
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
						<div class="ts-togtext"><b>${__("Sync Transactions to TaxJar")}</b><p>${__("File your sales tax return with {0}", [`<a href="${AUTOFILE_DOC_URL}" target="_blank" rel="noopener noreferrer">${__("TaxJar AutoFile")}</a>`])}</p>
							<!-- Inside the File row's own text column, not beside it. This
							     narrows what that row sends rather than asking a third
							     question, and sitting here it lines up under the label above
							     by construction - with no indent measured against a checkbox
							     whose width this file does not own. -->
							<div class="ts-field-exports">
								<div class="ts-exports-pick"></div>
							</div>
						</div>
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

		// frappe.ui.TabButtons, the desk's segmented single-select, rather than a
		// switch. Both answers get named: a switch labelled "include exports"
		// says what turning it on does and leaves the reader to work out what
		// leaving it off does. Two pills say both, and the one that is pressed
		// is the sentence the card is making.
		//
		// The class rather than frappe.ui.tab_buttons(), because the card needs
		// the instance later for get_value() - the helper returns the element
		// and hides the instance on .data().
		//
		// Values are 0 and 1, the same pair the field stores. find_by_value()
		// compares with Object.is and value_of() tests "value" in option, so a
		// value of 0 selects its pill rather than falling back to the label.
		const exports = new frappe.ui.TabButtons({
			options: [
				{ label: __("Domestic + Export"), value: 1 },
				{ label: __("Domestic only"), value: 0 },
			],
			value: c.include_exports ? 1 : 0,
			size: "md",
			label: __("Transactions to send"),
		});
		$card.find(".ts-exports-pick").append(exports.$el);

		// Shown only while transactions are filed at all, because it decides
		// which of them are filed. A company that files nothing has no exports
		// to include, and the row would ask a question with no consequence.
		const toggle_exports = () =>
			$card.find(".ts-field-exports").toggleClass("hide", !file.get_value());
		file.df.change = toggle_exports;
		toggle_exports();

		this._featureCards.push({ company: c.company, controls: { calc, file, exports } });
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
			include_exports: c.controls.exports.get_value() ? 1 : 0,
		}));

		const $next = this.$root.find(".ts-next").prop("disabled", true);
		return this._call("save_features", { company_flags })
			.then(() => this._reload_state())
			.then(() => true)
			.catch(() => false)
			.finally(() => $next.prop("disabled", false));
	}

	// ── Step 6: Sync Nexus ───────────────────────────────────────────────
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
			title: __("State nexus is auto-fetched & updated daily at midnight"),
			footer: () => frappe.ui.button({
				label: __("Manage TaxJar Nexus"), variant: "outline", size: "xs", icon_right: "external-link",
				onclick: () => window.open(TAXJAR_NEXUS_URL, "_blank", "noopener,noreferrer"),
			}),
		}));

		this.$body.find(".ts-fetch-mount").append(frappe.ui.button({
			icon: "refresh-cw", variant: "outline",
			tooltip: __("Fetch from TaxJar"),
			onclick: () => this._fetch_nexus(),
		}));
		this._render_last_sync(s.nexus_last_synced);

		// Fetching with no company configured is a server-side throw ("add at
		// least one company's accounts first"), which would land as an error
		// dialog on merely opening this step. Say it here, where the way back
		// to fixing it is a click.
		if (!(s.companies || []).length) {
			// Nothing to fetch, so nothing to fetch it with, and nothing for the
			// banner's daily-sync promise to be about.
			this.$body.find(".ts-fetchstatus, .ts-fetch-mount").empty();
			this._toggle_nexus_note(false);
			this.$body.find(".ts-nexusresult").append(frappe.ui.empty_state({
				icon: "settings",
				css_class: "ts-nexusempty",
				title: __("No company accounts yet"),
				description: __("Nexus is fetched per company. Map a company's ledgers first."),
				actions: [{
					label: __("Go to Map Ledgers"), variant: "outline",
					onclick: () => this._go(SETUP_STEPS.findIndex((step) => step.key === "accounts")),
				}],
			}));
			return;
		}

		// Whatever is cached renders at once, but an empty cache is not yet an
		// answer — only the fetch below can tell "nothing fetched yet" apart
		// from "TaxJar has no nexus", and those two need very different screens.
		this._nexus_answered = false;
		this._render_nexus_groups(nexusByCompany);

		// Opening this step always pulls the latest — no need to remember to
		// click Fetch just to see current nexus.
		this._fetch_nexus();
	}

	// Driven by the configured companies rather than by the keys of
	// nexus_by_company, which only carries a company once TaxJar has returned at
	// least one region for it — a company with none would otherwise just be
	// missing from this step with nothing said about it.
	_render_nexus_groups(nexusByCompany) {
		const $result = this.$body.find(".ts-nexusresult").empty().removeAttr("aria-busy");
		const companies = ((this.state || {}).companies || []).map((c) => c.company).filter(Boolean);
		const total = companies.reduce((n, c) => n + (nexusByCompany[c] || []).length, 0);

		// The banner explains a list that is there. With no list it is one more
		// thing to read past on the way to the only message that matters, and
		// its own "Manage TaxJar Nexus" link duplicates that message's button.
		// While the first fetch runs the list is still the expected answer, so
		// the banner stays up rather than dropping in over the cards later.
		this._toggle_nexus_note(!!total || !this._nexus_answered);

		if (!total) {
			// Before the first fetch answers there is nothing to say: an empty
			// state here would read as "TaxJar has no nexus" while the request
			// that decides that is still in flight.
			if (this._nexus_answered) $result.append(this._nexus_empty_state());
			else this._render_nexus_placeholder($result, companies);
			return;
		}

		$result.html(companies.map((company) => {
			const regions = nexusByCompany[company] || [];
			const body = regions.length
				? `<div class="ts-pills">${regions.map((r) => `
					<span class="ts-pill">${frappe.utils.escape_html(r.region || r.region_code)}
						<span class="ts-pillcode">${frappe.utils.escape_html(r.region_code)}</span></span>
				`).join("")}</div>`
				: `<div class="ts-nonexus">${__("No nexus registered in TaxJar for this company.")}
					<a href="${TAXJAR_NEXUS_URL}" target="_blank" rel="noopener noreferrer">${__("Add it in TaxJar")}</a>
				</div>`;
			return `
				<div class="ts-card">
					<div class="ts-card-h"><b>${frappe.utils.escape_html(company)}</b></div>
					<div class="ts-card-b">${body}</div>
				</div>
			`;
		}).join(""));
	}

	// A first visit has nothing cached and the fetch takes a few seconds, so the
	// step would otherwise stand at its title with the whole grid blank. The
	// company names are known already and only their regions are not, so the
	// wait draws the answer's own shape: one card per company, with bars where
	// the region pills go.
	_render_nexus_placeholder($result, companies) {
		const widths = ["72px", "58px", "84px", "64px", "76px"];
		$result.attr("aria-busy", "true").html(companies.map((company) => `
			<div class="ts-card">
				<div class="ts-card-h"><b>${frappe.utils.escape_html(company)}</b></div>
				<div class="ts-card-b">
					<div class="ts-pills">${widths.map((width) => frappe.ui.skeleton.html({
						width, height: "26px", css_class: "ts-pillskel",
					})).join("")}</div>
				</div>
			</div>
		`).join(""));
	}

	_toggle_nexus_note(show) {
		this.$body.find(".ts-nexusnote-mount").toggleClass("hide", !show);
	}

	// Not an error and not a failed fetch: TaxJar answered, and the answer was
	// that this account has no nexus registered at all. Nothing in this wizard
	// can fix that — nexus is declared in TaxJar — so the whole screen is the
	// trip out to TaxJar and back.
	//
	// One action only: the retry is the refresh button already sitting beside
	// the title, and a second one here would be two controls for one job with
	// no way to tell which to press.
	_nexus_empty_state() {
		return frappe.ui.empty_state({
			icon: "map-pin",
			css_class: "ts-nexusempty",
			title: __("No nexus regions in your TaxJar account"),
			description: __("Please add state nexus in your TaxJar account and retry syncing."),
			// Outline, not solid: the filled treatment belongs to the page's
			// own Continue CTA.
			actions: [{
				label: __("Configure Nexus in TaxJar"), variant: "outline",
				icon: "external-link", href: TAXJAR_NEXUS_URL,
			}],
		});
	}

	// The one line that carries sync state, in the one place the user is already
	// reading it: "Syncing…" becomes "Synced just now" in place. A
	// separate in-progress pill beside it said the same thing twice, in two
	// shapes, with the settled answer arriving in neither of them.
	//
	// Blank until a sync has actually happened - "Synced never" is noise on a
	// first run, and the step fetches on open anyway, so the blank lasts as long
	// as it takes _fetch_nexus() to write "Syncing…" over it.
	//
	// The absolute date stands in when prettyDate has nothing to say: it
	// returns "" for a timestamp on a later day than the browser's, which a
	// just-written one is once the site's timezone has passed midnight and the
	// browser has not. comment_when() would wrap that "" in a span and leave
	// "Synced " with no time after it.
	_render_last_sync(when) {
		let relative = "";
		if (when) {
			relative = frappe.datetime.prettyDate(when)
				? frappe.datetime.comment_when(when)
				: taxjar_integration.format_last_synced(when);
		}
		const $caption = this.$body.find(".ts-lastsync");
		$caption.html(relative ? __("Synced {0}", [relative]) : "");
		taxjar_integration.timestamp_tooltips($caption);
	}

	_render_syncing() {
		this.$body.find(".ts-lastsync").text(__("Syncing…"));
	}

	// Returns the running fetch, so a press of Activate can wait for it rather
	// than send a second writer at the same record (see _on_next).
	_fetch_nexus() {
		// Every fetch clears and re-inserts the same nexus rows server-side, so
		// two of them in flight at once are two writers on the same table. The
		// server serialises them as well, but a second request that only ever
		// waits for the first one's answer is not worth sending.
		if (this._nexus_fetching) return this._nexus_fetch;
		this._nexus_fetching = true;

		const $status = this.$body.find(".ts-fetchstatus").empty();
		const $btn = this.$body.find(".ts-fetch-mount .es-button").attr("aria-busy", "true");
		this._render_syncing();

		// The stored chain ends after the catch below, so it settles rather
		// than rejects - a wait on it never turns one failed fetch into a
		// second unhandled error somewhere else.
		this._nexus_fetch = this._call("fetch_nexus", {}).then((res) => {
			this._nexus_answered = true;
			this.state.nexus_by_company = res.nexus_by_company;
			this._render_nexus_groups(res.nexus_by_company);
			this.state.nexus_last_synced = res.nexus_last_synced;
			this._render_last_sync(res.nexus_last_synced);
		}).catch(() => {
			// A failed fetch says nothing about whether nexus exists, so the
			// "no nexus in TaxJar" screen must not stand in for this. Put the
			// last-sync line back to whatever it said before this attempt -
			// leaving "Syncing…" up would claim one is still running.
			this._render_last_sync(this.state.nexus_last_synced);
			$status.append(frappe.ui.badge({ label: __("Could not fetch nexus."), theme: "red" }));
		}).finally(() => {
			this._nexus_fetching = false;
			$btn.removeAttr("aria-busy");
		});

		return this._nexus_fetch;
	}

	// ── Step 7: the configuration record ────────────────────────────
	// Review and the activated screen are one page in two states. Every card is
	// open and none of them carries a control: this is the configuration
	// written out, not a set of things to operate. One Edit configuration
	// button sits beside the title, and it restarts the wizard.
	//
	// The Connection card holds the site settings. Then each company has one
	// card with its ledgers, features, address and nexus, so the reader does
	// not match a company name across several cards. There are no
	// section headings. The Connection card has the same header band as a
	// company card, so the two kinds of card read alike.
	_render_review() {
		const s = this.state || {};
		const companies = this._review_companies(s);
		// Read by _bind_hover_cards, which finds a company by its card's index.
		this._review_company_list = companies;

		this.$body.html(`
			${s.setup_complete ? this._done_header() : ""}
			<div class="ts-card ts-conn${this._focus === "connect" ? " ts-cfg-focus" : ""}">
				<div class="ts-card-h ts-co-h">
					<b class="ts-co-name">${__("Connection")}</b>
				</div>
				<div class="ts-card-b ts-conn-b">
					${this._card_body_connect(s)}
				</div>
			</div>
			${companies.length
				? `<div class="ts-cogrid">${companies.map((c, i) => this._company_card(c, i)).join("")}</div>`
				: `<div class="text-muted small">${__("No companies configured yet.")}</div>`}
		`);

		if (s.setup_complete) {
			this.$body.find(".ts-done-action").append(frappe.ui.button({
				label: __("Edit configuration"),
				variant: "outline",
				icon: "pencil",
				onclick: () => this._start_edit(),
			}));
			this._bind_setup_video();
		}

		this._bind_hover_cards();

		// A remedial link named a part of the record. Every card is open, so
		// there is nothing to expand - mark it and bring it into view instead.
		if (this._focus) {
			const focused = this.$body.find(".ts-cfg-focus")[0];
			if (focused) focused.scrollIntoView({ block: "center", behavior: "smooth" });
		}
	}

	// One entry for each company, in company_config order. A company that has
	// only an address or only nexus rows still gets a card, after the others.
	_review_companies(s) {
		const byName = new Map();
		const entry = (name) => {
			if (!byName.has(name)) byName.set(name, { company: name, config: null, address: null, regions: [] });
			return byName.get(name);
		};
		(s.companies || []).forEach((c) => (entry(c.company).config = c));
		(s.addresses || []).forEach((a) => (entry(a.company).address = a));
		Object.entries(s.nexus_by_company || {}).forEach(([name, regions]) => (entry(name).regions = regions));
		return Array.from(byName.values()).filter((c) => c.company);
	}

	// frappe.ui.hover_card, the desk's own component, rather than a CSS-only
	// tooltip: it opens on keyboard focus as well as on hover, so the names
	// behind a hint are reachable without a pointer and on touch.
	//
	// Bound by index rather than by a name in a data attribute - a company name
	// round-tripping through an attribute has to be escaped on the way in and
	// unescaped on the way out, and one of those always gets forgotten.
	_bind_hover_cards() {
		const options = { side: "bottom", align: "end", open_delay: 200, close_delay: 150 };

		const companies = this._review_company_list || [];
		this.$body.find('.ts-hint[data-hover="regions"]').each((i, el) => {
			const regions = companies[$(el).data("i")]?.regions || [];
			frappe.ui.hover_card($(el), {
				content: () => taxjar_integration.region_hover_card(this._nexus_sections(regions)),
				...options,
			});
		});
	}

	// The same card the Customer Configuration page opens behind its own region
	// count: one section per country, the full names below it. TaxJar sends the
	// country name with each region, so a nexus outside the US and Canada gets a
	// heading of its own rather than dropping out of the card.
	//
	// No all_label here. That sentence answers "is this every state", a question
	// a list of exemptions raises and a list of registrations does not.
	//
	// Each heading has the country's flag before its name, as on the Customer
	// Configuration page. A country with no flag on file shows its name only.
	_nexus_sections(regions) {
		const byCountry = new Map();
		regions.forEach((r) => {
			const country = r.country || __("Unknown");
			if (!byCountry.has(country)) byCountry.set(country, { code: r.country_code, names: [] });
			byCountry.get(country).names.push(r.region || r.region_code || "—");
		});
		return Array.from(byCountry, ([country, { code, names }]) => ({
			heading: `${taxjar_integration.country_flag_html(code)}<span>${frappe.utils.escape_html(country)}</span>`,
			names,
			all_label: null,
		}));
	}

	// API mode leads and appears once. It is a site setting, not a per-company
	// one, so repeating it under every company would invite the reader to think
	// it could differ between them.
	//
	// No token here. Which key is stored for a company is the Connect step's
	// business, and this card answers the question the reader actually has:
	// which mode the API runs in, and is anything being logged.
	_card_body_connect(s) {
		const mode = s.api_mode || "—";
		// frappe.ui.badge, the Espresso component. .indicator-pill is deprecated
		// in favour of it, and the badge is what the feature chips below use, so
		// the two states on this page are drawn by one component.
		const modeDisplay = mode === "Live"
			? frappe.ui.badge.html({ label: __("Live"), theme: "green" })
			: frappe.utils.escape_html(mode);

		const retentionDays = s.log_retention_days;
		const logsDisplay = s.enable_taxjar_logging
			? __("Enabled · {0} {1} retention", [retentionDays, retentionDays === 1 ? __("day") : __("days")])
			: __("Off");

		return `
			<div class="ts-kv"><span>${__("API Mode")}</span><span>${modeDisplay}</span></div>
			<div class="ts-kv"><span>${__("API Logs")}</span><span class="ts-kv-plain">${logsDisplay}</span></div>
		`;
	}

	// One company: a header with its name and its region count,
	// then its ledgers, its features and its address.
	_company_card(c, index) {
		const name = frappe.utils.escape_html(c.company);
		const focus = (key) => (this._focus === key ? " ts-cfg-focus" : "");
		const value = (text) => frappe.utils.escape_html(text || "—");

		return `
			<div class="ts-card ts-co-card">
				<div class="ts-card-h ts-co-h">
					<b class="ts-co-name">${name}</b>
					<span class="ts-co-regions${focus("nexus")}">${this._region_count(c.regions, index)}</span>
				</div>
				<div class="ts-co-b">
					<dl class="ts-co-sec${focus("ledgers")}">
						<dt>${__("Tax Ledger")}</dt><dd>${value(c.config?.tax_account_head)}</dd>
						<dt>${__("Shipping Ledger")}</dt><dd>${value(c.config?.shipping_account_head)}</dd>
					</dl>
					<dl class="ts-co-sec${focus("features")}">
						<dt>${__("Features")}</dt><dd>${this._feature_chips(c.config)}</dd>
					</dl>
					<dl class="ts-co-sec${focus("address")}">
						<dt>${__("Address")}</dt><dd>${this._address_lines(c.address)}</dd>
					</dl>
				</div>
			</div>
		`;
	}

	// A count, not the whole list. A company with economic nexus everywhere
	// has up to 46 regions, and the list would make the card longer than the
	// rest of the page. The hover card names them, grouped by country.
	//
	// A company registered nowhere is a real answer, so it gets words, not a
	// blank space that looks like a card that did not render.
	_region_count(regions, index) {
		if (!regions.length) return `<span class="text-muted">${__("No regions")}</span>`;
		const label = regions.length === 1 ? __("1 region") : __("{0} regions", [regions.length]);
		return `<span class="ts-hint" data-hover="regions" data-i="${index}" tabindex="0">${label}</span>`;
	}

	// The enabled features only. A badge for a feature that is off made the
	// reader read each label to find which ones are on. With no feature on,
	// the row says so in words.
	//
	// frappe.ui.badge, the Espresso component: it brings its own theme, radius
	// and type size, and it inverts with the desk theme. Outline and green, so
	// "on" reads as on without a filled block of colour on the page.
	_feature_chips(config) {
		const on = [
			config?.calculate && __("Sales Tax"),
			config?.file && __("Transaction Sync"),
		].filter(Boolean);
		if (!on.length) return `<span class="text-muted">${__("None enabled")}</span>`;
		return `<div class="ts-flags">${on
			.map((label) => frappe.ui.badge.html({ label, theme: "green", variant: "outline" }))
			.join("")}</div>`;
	}

	// The street itself, not a yes/no. This is the only place the record says
	// which address TaxJar calculates tax from. The country is shown, because
	// the address is where the sale ships from.
	_address_lines(a) {
		const lines = a?.address
			? [
				a.address_line1,
				[a.city, [a.taxjar_state_code, a.pincode].filter(Boolean).join(" ")].filter(Boolean).join(", "),
				a.country,
			].filter(Boolean)
			: [];
		if (!lines.length) return `<span class="text-muted">${__("Not configured")}</span>`;
		return lines.map((line) => `<div>${frappe.utils.escape_html(line)}</div>`).join("");
	}

	// ── Activated header ────────────────────────────────────────────
	// A tick, the headline, and the one action, on a single row. Restrained on
	// purpose: this screen is read far more often than it is arrived at, and a
	// full-width celebration wears out the second time somebody opens it to
	// check a ledger.
	_done_header() {
		// A filled disc with a stock lucide tick inside it. Colour rides
		// --icon-stroke, the variable .icon already reads, rather than a stroke
		// attribute - .icon's own `stroke:` rule would win over one of those.
		const tick = `<span class="ts-done-tick">${frappe.utils.icon("check", "sm")}</span>`;

		return `
			<div class="ts-done">
				${tick}
				<h2 class="ts-done-title">${__("TaxJar is configured")}</h2>
				<span class="ts-done-spacer"></span>
				<div class="ts-done-action"></div>
			</div>
			${this._video_card({
				video_id: WALKTHROUGH_VIDEO_ID,
				title: __("Walkthrough"),
				description: __("See auto sales-tax computation and transaction syncing with TaxJar in action."),
			})}
		`;
	}

	// The walkthrough row. Two places show it, to two readers, and each hands
	// in its own two lines: the first step introduces a setup nobody has done
	// yet, and the activated screen offers the same video to somebody whose
	// setup already runs.
	//
	// The video and the words are all that differ. The markup, the facade, the
	// thumbnail fallback, the player and the rules stay here, so the rest cannot
	// drift. The row holds its own video id, and the player reads it from there.
	//
	// A facade, not an embed: one image from i.ytimg.com, and nothing from
	// youtube.com loads for somebody who never presses play. No duration in the
	// label - the video can be re-cut without this line going quietly wrong,
	// and a wrong duration is worse than none.
	//
	// An empty video id drops the row rather than shipping a play button that
	// opens nothing.
	_video_card({ video_id, title, description }) {
		if (!video_id) return "";

		const id = frappe.utils.escape_html(video_id);
		return `
			<div class="ts-video" data-video-id="${id}">
				<button type="button" class="ts-video-play" aria-label="${__("Play the TaxJar walkthrough")}">
					<img class="ts-video-thumb" src="${video_poster(video_id)}/maxresdefault.jpg" alt="">
					<span class="ts-video-mark">
						<svg viewBox="0 0 12 12" aria-hidden="true" focusable="false"><path d="M3 1.5 10 6l-7 4.5Z"/></svg>
					</span>
				</button>
				<div class="ts-video-text">
					<p class="ts-video-title">${frappe.utils.escape_html(title)}</p>
					<p class="ts-video-desc">${frappe.utils.escape_html(description)}</p>
				</div>
			</div>
		`;
	}

	// Both places play the video in the row itself.
	_bind_setup_video() {
		const page = this;
		this.$body.find(".ts-video-play").on("click", function () {
			page._play_setup_video_in_row($(this).closest(".ts-video"));
		});
		// Bound here rather than an inline onerror="" attribute, like every other
		// handler on this page. Safe to bind after inserting the <img>: the
		// browser cannot fire error before this synchronous block returns.
		//
		// maxresdefault only exists for videos uploaded above 720p, so it 404s on
		// plenty of them; hqdefault is generated for every video.
		this.$body.find(".ts-video-thumb").one("error", function () {
			this.src = `${video_poster($(this).closest(".ts-video").data("video-id"))}/hqdefault.jpg`;
		});
	}

	// The row becomes the player. A 168x96 frame is a thumbnail, not something
	// anybody can watch, so the card drops its side-by-side layout and gives the
	// video the width - the description has done its job once the video runs.
	//
	// The thumbnail is detached, not removed, so _stop_setup_video can put it
	// back with its click handler still bound.
	_play_setup_video_in_row($video) {
		$video.addClass("is-playing");
		const $play = $video.find(".ts-video-play");
		const video_id = String($video.data("video-id"));
		const src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(video_id)}?autoplay=1&rel=0`;
		$play.after(`
			<div class="ts-video-frame">
				<iframe
					src="${src}"
					title="${__("TaxJar walkthrough")}"
					allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
					referrerpolicy="strict-origin-when-cross-origin"
					allowfullscreen
				></iframe>
			</div>
		`);
		$video.data("ts-play", $play.detach());

		const video = VIDEO_NAMES[video_id];
		if (video) taxjar_integration.track("taxjar_setup_video_played", { video });
	}

	// Removing the iframe is the one way to stop it: a cross-origin player
	// takes no pause from this page. The row goes back to its thumbnail.
	_stop_setup_video() {
		this.$body.find(".ts-video.is-playing").each(function () {
			const $video = $(this);
			$video.find(".ts-video-frame").replaceWith($video.data("ts-play"));
			$video.removeClass("is-playing");
		});
	}
}
