// The CSAT survey card in the TaxJar sidebar, and the dialog that it opens.
//
// The server decides when to ask, keeps the survey state, and sends the answer
// to Pulse (taxjar_integration/taxjar_integration/csat.py). This file only shows
// the card and the dialog. It keeps no state in localStorage.
if (!window.taxjar_integration) {
	window.taxjar_integration = {};
}

const CSAT_METHOD = "taxjar_integration.taxjar_integration.csat";
const CSAT_CARD_CLASS = "taxjar-csat-card";

class TaxJarCsat {
	constructor() {
		this.prompt = null;
		this.loading = null;
		this.shown_sent = false;
	}

	/** Add the card when the sidebar of this app shows and the survey is due. */
	render(sidebar) {
		// With telemetry off the server never asks, so skip the request.
		if (!frappe.boot.enable_telemetry || !taxjar_integration.is_taxjar_sidebar(sidebar)) return;

		this.load().then(() => {
			if (this.prompt && this.prompt.show) this.add_card(sidebar);
		});
	}

	load() {
		if (!this.loading) {
			this.loading = frappe
				.xcall(`${CSAT_METHOD}.get_csat_prompt`)
				.then((prompt) => (this.prompt = prompt))
				// The survey is optional: a failure shows no card and no error.
				.catch(() => (this.prompt = null));
		}
		return this.loading;
	}

	add_card(sidebar) {
		const parent = sidebar.wrapper.find(".body-sidebar-cards");
		if (!parent.length || parent.find(`.${CSAT_CARD_CLASS}`).length) return;

		this.card = new frappe.ui.SidebarCard({
			parent,
			icon: "face-slightly-smiling",
			title: __("Rate the TaxJar app"),
			message: "",
			// Outline drops the template's px-2 py-2, which beat the card's own padding.
			outline: true,
			close_button: true,
			primary_action_label: __("Give feedback"),
			primary_button_width: true,
			primary_action: () => this.open_dialog(),
		});
		this.card.card.addClass(CSAT_CARD_CLASS);
		// The card hides itself on close. The server must also know, so the
		// card does not come back on the next page.
		this.card.card.find(".close-button").on("click", () => this.finish("dismissed"));

		if (!this.shown_sent) {
			this.shown_sent = true;
			this.record("shown");
		}
	}

	open_dialog() {
		const question = __("How satisfied are you with the TaxJar integration?");
		const dialog = new frappe.ui.Dialog({
			title: __("Rate the TaxJar app"),
			fields: [
				{ fieldtype: "HTML", fieldname: "score_scale" },
				{
					// The scale writes the score here. The hidden field gives the
					// required check.
					fieldtype: "Data",
					fieldname: "score",
					label: question,
					hidden: 1,
					reqd: 1,
				},
				{
					fieldtype: "Small Text",
					fieldname: "comment",
					label: __("Comments (if any)"),
					// The privacy notice. Escaped: the desk shows a description as HTML,
					// and a translation must not add markup to it.
					description: frappe.utils.escape_html(
						__(
							"Feedback shared is anonymous, don't include any personal information."
						)
					),
				},
			],
			primary_action_label: __("Send"),
			primary_action: (values) => this.submit(dialog, values),
			secondary_action_label: __("Do not ask me again"),
			secondary_action: () => {
				dialog.hide();
				this.finish("opted_out");
			},
		});
		new FeedbackScale(dialog.fields_dict.score_scale.$wrapper, question, (score) =>
			dialog.set_value("score", String(score))
		);
		dialog.show();
	}

	submit(dialog, values) {
		const answer = { score: Number(values.score) };
		// The server cleans the text; this only skips a comment of spaces.
		const comment = (values.comment || "").trim();
		if (comment) answer.comment = comment;
		dialog.hide();
		this.finish("submitted", answer).then(() => {
			frappe.show_alert({ message: __("Thank you for your feedback."), indicator: "green" });
		});
	}

	/** End the survey for this cycle: hide the card and tell the server. */
	finish(action, answer = {}) {
		this.prompt = { show: false };
		if (this.card) this.card.hide();
		return this.record(action, answer);
	}

	record(action, answer = {}) {
		return frappe.xcall(`${CSAT_METHOD}.record_csat`, { action, ...answer });
	}
}

/**
 * A segmented bar of five score buttons, 1 to 5, in place of the star Rating
 * field. It is the desk TabButtons (frappe.ui.TabButtons), which gives the
 * gray bar, the radio group, and the arrow keys.
 *
 * Each button shows the color of its score (the SCSS reads data-score) on
 * hover and when picked. The line below names the two ends of the scale.
 */
class FeedbackScale {
	constructor($parent, question, on_pick) {
		// Translate here, not at load: the bundle can load before the translations.
		const labels = [
			__("Very dissatisfied"),
			__("Dissatisfied"),
			__("Neutral"),
			__("Satisfied"),
			__("Very satisfied"),
		];
		this.buttons = new frappe.ui.TabButtons({
			label: question,
			size: "md",
			options: labels.map((label, i) => ({ label: String(i + 1), value: i + 1 })),
			on_change: on_pick,
		});
		this.buttons.pills.forEach((pill, i) => {
			pill.el.dataset.score = i + 1;
			pill.el.setAttribute("aria-label", `${i + 1}, ${labels[i]}`);
		});
		this.clear();

		$(`
			<div class="taxjar-feedback-scale">
				<div class="control-label reqd" aria-hidden="true">${frappe.utils.escape_html(question)}</div>
				<div class="taxjar-feedback-scale-ends" aria-hidden="true">
					<span>${frappe.utils.escape_html(labels[0])}</span>
					<span>${frappe.utils.escape_html(labels[labels.length - 1])}</span>
				</div>
			</div>
		`)
			.appendTo($parent)
			.find(".control-label")
			.after(this.buttons.$el);
	}

	/**
	 * Start with no score. TabButtons always selects its first option, and a
	 * survey that starts at 1 pushes the user to that score.
	 */
	clear() {
		this.buttons.selected = null;
		this.buttons.pills.forEach((pill, i) => {
			pill.el.setAttribute("data-state", "inactive");
			pill.el.setAttribute("aria-checked", "false");
			// One tab stop, as TabButtons gives the selected button.
			pill.el.tabIndex = i ? -1 : 0;
		});
	}
}

taxjar_integration.csat = new TaxJarCsat();

/**
 * Add the card after each render of the sidebar cards.
 *
 * The desk empties the card slot in add_sidebar_cards() on each sidebar setup,
 * so a card added before that is lost. Wrap the method once, on the prototype.
 */
function patch_sidebar_cards() {
	const sidebar_class = window.frappe && frappe.ui && frappe.ui.Sidebar;
	if (!sidebar_class || sidebar_class.prototype.taxjar_csat_patched) return;

	const add_sidebar_cards = sidebar_class.prototype.add_sidebar_cards;
	sidebar_class.prototype.add_sidebar_cards = function () {
		add_sidebar_cards.apply(this, arguments);
		try {
			taxjar_integration.csat.render(this);
		} catch (error) {
			// The survey must never break the sidebar.
			console.error(error);
		}
	};
	sidebar_class.prototype.taxjar_csat_patched = true;
}

patch_sidebar_cards();
$(document).on("sidebar_setup", patch_sidebar_cards);
