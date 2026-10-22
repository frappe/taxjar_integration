frappe.provide("taxjar_integration");

// Pagination for the TaxJar desk pages.
//
// The tables render at their natural height with no inner scrollbar, so the
// page size is what keeps a page to roughly a screenful - hence the size
// picker sitting beside the steps rather than buried in a menu.
//
// One row: the page size on the left, then "Page 2 of 7" and the two steps on
// the right. The control is the same width at 3 pages and at 300, because the
// count lives in the words rather than in a row of numbered buttons.
taxjar_integration.Paginator = class Paginator {
	constructor(options) {
		Object.assign(this, options);
		this.page_sizes = this.page_sizes || [20, 50, 100];
		this.$wrapper.addClass("taxjar-paginator");
	}

	// state: { page, total_pages, page_size }
	//
	// Both steps are always rendered, disabled at the ends rather than removed
	// - controls that come and go make the row jump and leave you unsure
	// whether there is more to see or the button simply vanished.
	render(state) {
		this.$wrapper.empty();
		if (!state) return;

		this.render_size_picker(state);

		const total_pages = Math.max(state.total_pages || 1, 1);

		// "Page 2 of 7" sits on the same line as the steps, ahead of them:
		// where you are, then the means of moving. The words carry the count,
		// so the steps say only which way they go.
		const $nav = $('<div class="taxjar-paginator-nav"></div>').appendTo(this.$wrapper);
		$('<div class="taxjar-paginator-status"></div>')
			.text(__("Page {0} of {1}", [state.page, total_pages]))
			.appendTo($nav);

		const $pages = $('<div class="taxjar-paginator-pages"></div>').appendTo($nav);

		this.add_step($pages, "chevron-left", __("Previous page"), state.page - 1, state.page <= 1);
		this.add_step(
			$pages,
			"chevron-right",
			__("Next page"),
			state.page + 1,
			state.page >= total_pages
		);
	}

	// A segmented group, because the sizes are few and worth comparing at a
	// glance, which a collapsed select hides.
	//
	// frappe.ui.TabButtons, the desk's own component for this - its own
	// documentation names a page size picker as the case it is for. It was a
	// bootstrap .btn-group copied out of the list view, with rules in the scss
	// to make it look like the desk around it; the component carries its rail,
	// its pill and its dark theme itself.
	//
	// It is a radio group: arrow keys move the choice, and the whole group
	// takes one tab stop. Picking the size that is already on does nothing,
	// because TabButtons calls on_change only when the value changes - so the
	// current size no longer has to be disabled to say the same thing.
	render_size_picker(state) {
		const picker = new frappe.ui.TabButtons({
			// Not visible. It is the name a screen reader reads when focus
			// enters the group, which would otherwise be "radio group" alone.
			label: __("Rows per page"),
			options: this.page_sizes.map((size) => ({ label: String(size), value: size })),
			value: state.page_size,
			css_class: "taxjar-paginator-size",
			// Changing the size reshuffles every boundary, so the old page
			// number is meaningless - the caller resets to 1.
			on_change: (size) => this.on_page_size(size),
		});

		picker.$el.appendTo(this.$wrapper);
	}

	// One step, as an arrow alone. The button carries no text, so `tooltip` is
	// both the bubble on hover and the name a screen reader reads.
	add_step($pages, icon, tooltip, page, disabled) {
		$pages.append(
			frappe.ui.button({
				icon,
				tooltip,
				variant: "subtle",
				disabled,
				onclick: () => this.on_page(page),
			})
		);
	}
};
