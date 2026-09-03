frappe.provide("taxjar_integration");

// The strip of numbers above the tabs, built from frappe's own summary items
// (frappe.utils.build_summary_item) so it matches the desk's report summaries.
//
// Two things on top of the frappe primitive:
//
//   * groups - cards are rendered under a caption with a full-height rule
//     between groups, so "All Transactions" and "Draft" read as separate
//     totals rather than one long row of unrelated numbers;
//   * cards are actionable - clicking one drills the table down to what it
//     counts, keeping whatever company/date filters are already set. Clicking
//     the active card clears it again.
//
// Usage:
//   new taxjar_integration.SummaryStrip({
//       $wrapper,
//       on_select: (card) => { ... },   // card.value_key, or null when cleared
//       groups: [{ label: __("Draft"), cards: [{ label, value, value_key }] }],
//   });
taxjar_integration.SummaryStrip = class SummaryStrip {
	constructor(options) {
		Object.assign(this, options);
		this.groups = this.groups || [];
		this.active_key = null;
		this.render();
	}

	render() {
		this.$wrapper.empty().addClass("taxjar-summary-strip");

		this.groups.forEach((group) => {
			const $group = $('<div class="taxjar-summary-group"></div>').appendTo(this.$wrapper);

			// Groups grow in proportion to how many numbers they actually hold.
			// Left to CSS they would each grow by the same amount, so a group of
			// one - Draft - would end up as wide as a group of five and the
			// crowded side would stay crowded. Operators are punctuation and do
			// not count towards the weight.
			const weight = group.cards.filter((card) => !card.operator && !card.divider).length || 1;
			$group.css("flex-grow", weight);
			$(`<div class="taxjar-summary-group-label">${frappe.utils.escape_html(group.label)}</div>`).appendTo(
				$group
			);

			const $cards = $('<div class="report-summary"></div>').appendTo($group);

			group.cards.forEach((card) => {
				// An operator between cards, so a group of counts reads as the
				// arithmetic it actually is: total = a + b + c. Built from the
				// same label/value pair as a real card so the glyph lands on the
				// numbers' own line rather than being nudged there by hand.
				if (card.operator) {
					$(`
						<div class="summary-item taxjar-summary-operator">
							<span class="summary-label">&nbsp;</span>
							<div class="summary-value">${frappe.utils.escape_html(card.operator)}</div>
						</div>
					`).appendTo($cards);
					return;
				}

				// A plain rule, for a group whose counts do not add up to its
				// total and so must not claim to.
				if (card.divider) {
					$('<div class="taxjar-summary-divider"></div>').appendTo($cards);
					return;
				}

				const $card = frappe.utils
					.build_summary_item({
						// A card with nothing useful to call itself still needs
						// the label element, or its number sits higher than the
						// labelled ones beside it.
						label: card.label || " ",
						value: card.value,
						datatype: card.datatype || "Int",
						indicator: card.indicator,
					})
					.appendTo($cards);

				// Only a missing key means "not clickable". An empty string is a
				// real key - it is how a Total says "no filter, show all of it"
				// - and a truthiness check here would silently swallow it.
				if (card.value_key == null) return;

				// The whole card is the target, and the pointer cursor is what
				// says so. Anything smaller would leave most of the card showing
				// a clickable cursor over dead space. No title attribute: a
				// native tooltip on every card fires on hover across a whole row
				// of them, and the cursor plus the active underline already say
				// what a click does. card.title went with it - nothing set it.
				$card
					.addClass("taxjar-summary-clickable")
					.attr("role", "button")
					.attr("tabindex", 0)
					.attr("data-value-key", card.value_key);

				const activate = () => this.select(card);
				$card.on("click", activate);
				$card.on("keydown", (e) => {
					if (e.key === "Enter" || e.key === " ") {
						e.preventDefault();
						activate();
					}
				});
			});
		});

		this.paint_active();
	}

	// Re-selecting the active card clears it, so a card is a toggle rather than
	// a one-way trip that leaves the user hunting for how to get back.
	//
	// "cleared" is tracked rather than inferred from the key's truthiness: a
	// Total card's key is the empty string, so testing the key would report
	// every Total click as a clear and hand the caller null for a card that was
	// really selected.
	select(card) {
		const cleared = this.active_key === card.value_key;

		this.set_active(cleared ? null : card.value_key);
		this.on_select && this.on_select(cleared ? null : card);
	}

	set_active(value_key) {
		this.active_key = value_key;
		this.paint_active();
	}

	paint_active() {
		this.$wrapper.find(".taxjar-summary-clickable").each((_, el) => {
			const $el = $(el);
			$el.attr("aria-pressed", $el.attr("data-value-key") === this.active_key);
		});
	}

	// Values change on every refresh; the groups themselves do not.
	update(groups) {
		this.groups = groups;
		this.render();
	}
};
