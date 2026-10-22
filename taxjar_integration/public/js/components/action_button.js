frappe.provide("taxjar_integration");

// One bulk action as its own button, for a tab that offers exactly one. The
// label names that action, so a menu of one would only repeat its trigger.
//
// It is always rendered, never hidden - a control that disappears teaches the
// reader nothing about why. Disabled it explains itself instead: hovering or
// focusing it says why the press would do nothing.
//
// Disabled state is data-disabled + an Espresso tooltip, NOT the button's
// native disabled attribute - the latter would also drop it out of the
// keyboard tab order, and a disabled button never fires the pointer events the
// tooltip listens on. Same reasoning, and the same capture-phase click guard,
// as BulkActionButton.
taxjar_integration.ActionButton = class ActionButton {
	// options: $wrapper, label, icon, action (run on click), disabled_title.
	constructor(options) {
		Object.assign(this, options);
		this.disabled_title = this.disabled_title || __("Select one or more records to run an action");
		this.render();
	}

	render() {
		this.$button = frappe.ui
			.button({
				label: this.label,
				// The row's other control, Export, carries one. Two buttons of
				// the same size and variant, one with an icon and one without,
				// read as two kinds of control rather than as a pair.
				icon: this.icon,
				variant: "outline",
				css_class: "taxjar-bulk-action",
				onclick: () => this.action?.(),
			})
			.appendTo(this.$wrapper);

		// The dark Espresso bubble, not the browser's native title: it reads in
		// the desk's own type, it shows on keyboard focus as well as hover, and
		// it names the button through aria-describedby while it is open. An
		// empty text shows nothing, which is the enabled state - see
		// toggle_disabled(). Looked up at run time, as frappe.ui.button does
		// with the same component: a bundle without it still gets a button.
		if (frappe.ui.Tooltip) {
			this.tooltip = new frappe.ui.Tooltip(this.$button[0], { text: "" });
		}

		// Runs before the click handler frappe.ui.button binds, which only fires
		// in the bubble phase - a capture-phase listener on the same element
		// always runs first.
		this.$button[0].addEventListener("click", (e) => {
			if (!this.is_disabled()) return;
			e.preventDefault();
			e.stopImmediatePropagation();
			// The press is the moment the reader most needs the reason, and it
			// is the moment the tooltip hides itself: the component treats a
			// press as the label having done its job, and a press inside the
			// 500ms hover delay cancels the bubble before it ever shows. So
			// show it here, after that hide, rather than leave a dead press
			// explaining nothing.
			this.tooltip?.show();
		}, true);

		// Nothing is ticked yet, so there is nothing to act on.
		this.toggle_disabled(true);
	}

	// The rows change with the selection, so the action does too.
	set_action(action) {
		this.action = action;
	}

	is_disabled() {
		return this.$button.is("[data-disabled]");
	}

	// Set disabled_title before this call, not after: the text is read here.
	toggle_disabled(disabled) {
		this.tooltip?.set_text(disabled ? this.disabled_title : "");
		if (disabled) {
			this.$button.attr({ "data-disabled": "", "aria-disabled": "true" });
		} else {
			this.$button.removeAttr("data-disabled").removeAttr("aria-disabled");
		}
	}
};
