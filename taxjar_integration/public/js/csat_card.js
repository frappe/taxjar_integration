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
		if (!taxjar_integration.is_taxjar_sidebar(sidebar)) return;

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
 * A row of five score buttons, 1 to 5, in place of the star Rating field.
 *
 * Each button has the color of its score (the SCSS reads data-score). The row
 * is a radio group: the arrow keys move the pick, and Tab enters and leaves the
 * row as one stop. The line below the row names the score under the pointer,
 * or the picked score. The line is empty until then.
 */
class FeedbackScale {
	constructor($parent, question, on_pick) {
		this.score = 0;
		this.on_pick = on_pick;
		// Translate here, not at load: the bundle can load before the translations.
		this.labels = [
			__("Very dissatisfied"),
			__("Dissatisfied"),
			__("Neutral"),
			__("Satisfied"),
			__("Very satisfied"),
		];
		this.make($parent, question);
	}

	make($parent, question) {
		const label_id = frappe.utils.get_random(8);
		const buttons = this.labels.map(
			(label, i) =>
				`<button type="button" class="taxjar-feedback-scale-option" role="radio"
					data-score="${i + 1}" aria-checked="false" tabindex="${i ? -1 : 0}"
					aria-label="${frappe.utils.escape_html(`${i + 1}, ${label}`)}">${i + 1}</button>`
		).join("");

		this.$wrapper = $(`
			<div class="taxjar-feedback-scale">
				<div class="control-label reqd" id="${label_id}">${frappe.utils.escape_html(question)}</div>
				<div class="taxjar-feedback-scale-options" role="radiogroup" aria-labelledby="${label_id}">
					${buttons}
				</div>
				<div class="taxjar-feedback-scale-label" aria-hidden="true"></div>
			</div>
		`).appendTo($parent);
		this.$options = this.$wrapper.find(".taxjar-feedback-scale-option");
		this.$label = this.$wrapper.find(".taxjar-feedback-scale-label");
		this.show_label(0);

		this.$options
			.on("click", (e) => this.pick(Number(e.currentTarget.dataset.score)))
			.on("mouseenter", (e) => this.show_label(Number(e.currentTarget.dataset.score)))
			.on("mouseleave", () => this.show_label(this.score))
			.on("keydown", (e) => this.on_key(e));
	}

	pick(score) {
		this.score = score;
		this.$options.each((i, button) => {
			const on = i + 1 === score;
			button.setAttribute("aria-checked", on ? "true" : "false");
			button.tabIndex = on ? 0 : -1;
		});
		this.$wrapper.addClass("has-score");
		this.show_label(score);
		this.on_pick(score);
	}

	on_key(e) {
		const current = this.score || 1;
		const next = {
			ArrowRight: current + 1,
			ArrowDown: current + 1,
			ArrowLeft: current - 1,
			ArrowUp: current - 1,
			Home: 1,
			End: this.labels.length,
		}[e.key];
		if (!next) return;

		e.preventDefault();
		// Wrap around at each end, as a radio group does.
		const count = this.labels.length;
		const score = ((next - 1 + count) % count) + 1;
		this.pick(score);
		this.$options.get(score - 1).focus();
	}

	show_label(score) {
		this.$label.text(score ? this.labels[score - 1] : "");
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
