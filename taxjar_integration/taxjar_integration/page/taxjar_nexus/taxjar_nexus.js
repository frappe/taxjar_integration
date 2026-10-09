// The Nexus & Product Category page (/app/taxjar-nexus) - the same two
// summaries the TaxJar Settings form's "Nexus & Product Category" tab shows,
// on a page of their own, because both are read far more often than the
// credentials they sit behind.
//
// This page draws its own cards instead of the shared table renderers in
// public/js/taxjar_utils.js. Every section here carries its own title,
// description, "Synced ..." caption and refresh control, and the settings form
// already supplies all four from its section headers and its labelled buttons.
// The form keeps the shared table renderers, so it is unchanged.
//
// The page is one centred column, under a heading of its own:
//   State Nexus           - one card per company, two cards to a row.
//   Product Tax Category  - the count, in a card the width of the column.
// A company with a long list of regions shows the first few and opens the rest
// in place - see _render_chips.
//
// Boxes come from the desk component library (frappe.ui.badge, .button,
// .empty_state) and the shared utility classes in
// frappe/public/scss/common/utilities.scss, so every colour, size and radius
// is a desk token and the page follows the dark theme. taxjar_nexus.css holds
// only what neither of those can express - see the note at the top of it.
//
// Data fetch lives in on_page_show, not the constructor - see the comment at
// the top of taxjar_transactions.js for why (cached desk pages, and the first
// on_page_show firing straight after on_page_load).
frappe.pages["taxjar-nexus"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Nexus & Product Category"),
		single_column: true,
	});

	wrapper.taxjar_nexus = new TaxJarNexusSummary(page);
};

frappe.pages["taxjar-nexus"].on_page_show = function (wrapper) {
	wrapper.taxjar_nexus.refresh();
};

const API = "taxjar_integration.taxjar_integration.page.taxjar_nexus.taxjar_nexus";

// How many region chips a country shows before the rest go behind one control.
// Two rows in a card at half the column width.
const REGIONS_SHOWN = 6;

class TaxJarNexusSummary {
	constructor(page) {
		this.page = page;
		this.$body = $('<div class="taxjar-nexus-page"></div>').appendTo(page.main);
	}

	// frappe.xcall, not frappe.call: the latter hands back a jQuery jqXHR, and a
	// jQuery 3 Deferred has .always() but no .finally() - so the sync() chain
	// below threw on it and left the button spinning forever. xcall wraps the
	// same request in a native Promise (and resolves to r.message), which is
	// what every other page in this app already calls.
	refresh() {
		frappe.xcall(`${API}.get_summary`).then((summary) => this.render(summary));
	}

	// The body is rebuilt on every render rather than patched in place, so the
	// refresh controls are wired again here.
	render(summary) {
		summary = summary || {};
		// A TaxJar User reads this page; only a TaxJar Manager syncs it. The
		// server's check is what refuses a sync - this only keeps the reader
		// from being offered a button that would.
		this.can_sync = !!summary.can_sync;

		this.$body.empty();
		const $column = $('<div class="taxjar-nexus-column flex flex-col gap-8"></div>').appendTo(
			this.$body
		);

		this._render_page_head($column);
		// A rule between the page head and the sections under it. Both section
		// heads are the same shape as the page head at a smaller step, so
		// without the rule the page head reads as the first section's own
		// heading rather than as the heading for both. The column's own gap
		// sets the space on each side of it.
		$('<div class="border-t border-outline-gray-1"></div>').appendTo($column);
		this._render_nexus_section(
			$column,
			this._group_by_company(summary.nexus || []),
			summary.nexus_last_synced
		);
		this._render_category_section($column, summary.product_tax_categories || {});
	}

	// ── data ──

	// The TaxJar Settings nexus child table, as one entry per company holding
	// that company's regions grouped by country. Insertion order is kept, so the
	// page lists companies and countries in the order the server returned them.
	_group_by_company(rows) {
		const companies = [];

		for (const row of rows) {
			const name = row.company || __("(No Company)");
			let company = companies.find((c) => c.name === name);
			if (!company) {
				company = { name, countries: [] };
				companies.push(company);
			}

			const country = row.country || __("Unknown");
			let group = company.countries.find((g) => g.country === country);
			if (!group) {
				group = { country, regions: [] };
				company.countries.push(group);
			}
			group.regions.push(row);
		}

		return companies;
	}

	// ── sections ──

	// The page's own heading, above both sections. It is what lets the section
	// titles below it sit at a smaller step without reading as body text.
	//
	// It does not repeat the desk title bar above it, which names the page.
	// This says what the page is for.
	_render_page_head($parent) {
		const $head = $('<div class="flex flex-col gap-1"></div>').appendTo($parent);

		$('<div class="text-4xl-semibold text-ink-gray-8"></div>')
			.text(__("Manage nexus & product category"))
			.appendTo($head);
		$('<div class="text-p-sm text-ink-gray-5"></div>')
			.text(
				__(
					"Review the nexus for your company & product tax category list fetched from TaxJar."
				)
			)
			.appendTo($head);
	}

	_render_nexus_section($parent, companies, last_synced) {
		const $section = this._section($parent);
		const $head = this._render_head($section, {
			title: __("State Nexus"),
			subtitle: __("Auto-updated at midnight"),
			tooltip: __("Fetch nexus regions from TaxJar"),
			onclick: () => this._sync_nexus($section),
		});
		this._render_synced($head, last_synced);

		const $grid = $('<div class="taxjar-nexus-grid"></div>').appendTo($section);

		if (!companies.length) {
			$('<div class="taxjar-nexus-wide"></div>')
				.append(this._nexus_empty_state())
				.appendTo($grid);
			return;
		}

		for (const company of companies) {
			// A lone card takes the whole row: half a row with nothing beside it
			// reads as a card that failed to load, and its right edge would stop
			// short of the refresh control that acts on it.
			const $card = this._card()
				.toggleClass("taxjar-nexus-wide", companies.length === 1)
				.appendTo($grid);

			// The head is filled, the way the guided setup wizard fills its own
			// card heads (.ts-card-h in taxjar_setup.css): --subtle-fg there is
			// an alias of --surface-gray-2, so one token serves both pages and
			// both themes.
			//
			// The head rounds its own two top corners because the card draws no
			// overflow: hidden - a square fill would otherwise sit outside the
			// card's rounded corners. Logical corner names (ss/se), so the fill
			// stays tucked into the card when the layout flips.
			$(
				'<div class="text-base-medium text-ink-gray-8 truncate px-4 py-3 bg-surface-gray-2 rounded-ss-lg rounded-se-lg"></div>'
			)
				.text(company.name)
				.appendTo($card);

			const $card_body = $(
				'<div class="border-t border-outline-gray-1 p-4 flex flex-col gap-4"></div>'
			).appendTo($card);
			this._render_countries($card_body, company.countries);
		}
	}

	// The category list is not company scoped, so the count is the whole summary
	// and it sits in one card the width of the column.
	_render_category_section($parent, categories) {
		const $section = this._section($parent);
		const $head = this._render_head($section, {
			title: __("Product Tax Category"),
			subtitle: __("Updates are fetched automatically every week"),
			tooltip: __("Fetch product tax categories from TaxJar"),
			onclick: () => this._sync_categories($section),
		});
		this._render_synced($head, categories.last_updated);

		const $card = this._card().addClass("p-5").appendTo($section);

		if (!categories.count) {
			$card.append(this._category_empty_state());
			return;
		}

		this._render_count($card, categories.count);
	}

	// ── pieces ──

	// A section is a head and the cards under it. Both run the width of the
	// centred column, so every right edge on the page lines up and each refresh
	// control sits at the edge of what it acts on.
	_section($parent) {
		return $('<div class="flex flex-col gap-4"></div>').appendTo($parent);
	}

	_card() {
		return $(
			'<div class="bg-surface-elevation-1 border border-outline-gray-1 rounded-lg shadow-sm"></div>'
		);
	}

	// The title with its description under it on the left, the "Synced ..."
	// caption and the icon only refresh control on the right.
	//
	// The row does not wrap. Wrapping dropped the control below the title and
	// hard against the left edge, which reads as a control for whatever comes
	// next. The title block carries min-w-0 instead, so a long description
	// takes a second line of its own and the control stays on the right.
	_render_head($parent, opts) {
		const $head = $(`
			<div class="flex items-center justify-between gap-4">
				<div class="flex flex-col gap-0.5 min-w-0">
					<div class="text-lg-semibold text-ink-gray-8" data-head="title"></div>
					<div class="text-p-sm text-ink-gray-5" data-head="subtitle"></div>
				</div>
			</div>
		`).appendTo($parent);

		$head.find('[data-head="title"]').text(opts.title);
		$head.find('[data-head="subtitle"]').text(opts.subtitle);
		this._render_sync_controls($head, opts);

		return $head;
	}

	// The right hand end of every head: the "Synced ..." caption, then the
	// refresh control.
	_render_sync_controls($parent, opts) {
		const $controls = $('<div class="flex items-center gap-2 shrink-0"></div>').appendTo(
			$parent
		);

		$(
			'<span class="text-p-xs text-ink-gray-5 whitespace-nowrap taxjar-nexus-synced"></span>'
		).appendTo($controls);

		if (!this.can_sync) return $controls;

		$('<span class="taxjar-nexus-sync-mount"></span>')
			.append(
				frappe.ui.button({
					icon: "refresh-cw",
					variant: "outline",
					tooltip: opts.tooltip,
					onclick: opts.onclick,
				})
			)
			.appendTo($controls);

		return $controls;
	}

	// "868 categories configured" is one phrase, so the whole phrase is the link
	// into the list it counts. Underlining the number alone read as a mistake.
	//
	// Inline, not a flex row: a flex item is blockified, and a text decoration
	// on the container does not reliably reach one - the underline broke into
	// two pieces with a gap between them. Inline boxes of two sizes share a
	// baseline on their own, which is what the flex row was there for.
	_render_count($parent, count) {
		const $link = $(
			'<a class="taxjar-nexus-count" href="/app/product-tax-category"></a>'
		).appendTo($parent);

		$('<span class="text-5xl-semibold text-ink-gray-8"></span>').text(count).appendTo($link);
		$link.append(" ");
		$('<span class="text-p-base text-ink-gray-6"></span>')
			.text(__("categories configured"))
			.appendTo($link);

		return $link;
	}

	_render_countries($parent, countries) {
		for (const group of countries) {
			const $group = $('<div class="flex flex-col gap-2"></div>').appendTo($parent);

			$('<div class="text-xs-medium text-ink-gray-6 whitespace-nowrap"></div>')
				.text(group.country)
				.appendTo($group);

			this._render_chips(
				$('<div class="flex flex-wrap gap-2"></div>').appendTo($group),
				group.regions
			);
		}
	}

	// A long list opens in place: the same chips, in the same row, so the only
	// thing the control changes is how many of them there are. The alternative
	// was a panel on hover, which is closed to a keyboard and to touch, and
	// which drew the hidden regions in a second style in a second place.
	//
	// The cap is per country, so a company holding regions in two countries
	// opens one country without the other. Every render starts closed: the page
	// rebuilds its whole body on each sync, so there is no open card to carry.
	_render_chips($chips, regions, open) {
		$chips.empty();

		const hidden = open ? 0 : Math.max(regions.length - REGIONS_SHOWN, 0);
		const shown = hidden ? regions.slice(0, REGIONS_SHOWN) : regions;
		shown.forEach((row) => this._region_chip(row).appendTo($chips));

		if (!hidden && !open) return;

		// On a line of its own, under the chips, whether or not the last chip
		// row had room for it. Sharing a row, it sat one gap past a pill and
		// read as a region that had lost its own pill; on its own line it reads
		// as the end of the list. The line is a full-width flex item, so the
		// row breaks before it and the control keeps its own width inside it.
		$('<div class="taxjar-nexus-more-line"></div>').appendTo($chips).append(
			frappe.ui.button({
				// The same words the Customer form's own region list uses, so
				// the two say one thing. "more" also reads at a count of one,
				// which "+1 regions" did not.
				label: hidden ? __("+{0} more", [hidden]) : __("Show fewer"),
				// The chips are the data. This is the one action in the row, so
				// it carries no pill and no icon of its own - grey words with
				// a rule under them, from the espresso button stripped to its
				// text (see .taxjar-nexus-more in the css). A pill here read
				// as one more region, and a chevron beside two words said what
				// the words say.
				//
				// It stays a button, not a link: it opens the rest of the list
				// in place and goes nowhere, and the button brings the
				// keyboard, the focus ring and the hover with it.
				variant: "ghost",
				size: "xs",
				// text-sm is the desk's own 13px step, the step the chips are
				// set in. The page names no size of its own anywhere.
				css_class: "taxjar-nexus-more text-sm",
				onclick: () => this._render_chips($chips, regions, !open),
			})
		);
	}

	// The region name as a pill, with its region code beside the name inside the
	// same pill - the pill the guided setup wizard's Sync Nexus step already
	// draws (.ts-pill in taxjar_setup.css). The two show the same regions, so
	// they look the same.
	//
	// frappe.ui.badge escapes its label, so the code is appended to the finished
	// pill rather than passed through as markup.
	//
	// The country code is not shown: the country name already labels the group
	// this pill sits in. It stays on the raw Nexus table on the settings form.
	_region_chip(row) {
		const $chip = frappe.ui.badge({
			label: row.region || "—",
			variant: "outline",
			// lg is the badge's own 13px step. The page names no size of its
			// own anywhere - every size on it comes from a component, from a
			// desk typography class, or from a desk token.
			size: "lg",
			css_class: "taxjar-nexus-chip",
		});

		if (row.region_code) {
			$('<span class="text-xs-medium taxjar-nexus-code text-ink-gray-5"></span>')
				.text(row.region_code)
				.appendTo($chip);
		}

		return $chip;
	}

	// Same wording as the shared renderer the settings form still uses, so the
	// two places say the same thing when neither has been fetched yet.
	_nexus_empty_state() {
		return frappe.ui.empty_state({
			icon: "map-pin",
			title: __("No nexus regions loaded"),
			description: this._empty_state_hint(),
			css_class: "my-2",
		});
	}

	// A reader has no button above, so the hint names who can fetch the list.
	_empty_state_hint() {
		return this.can_sync
			? __("Fetch them from TaxJar using the button above.")
			: __("A TaxJar Manager can fetch them from TaxJar.");
	}

	_category_empty_state() {
		return frappe.ui.empty_state({
			icon: "tag",
			title: __("No product tax categories loaded"),
			description: this._empty_state_hint(),
			css_class: "my-2",
		});
	}

	// Blank until a sync has actually happened - "Synced never" is noise next
	// to a card that already says nothing has been fetched yet.
	//
	// prettyDate returns "" for a timestamp on a later day than the browser's
	// (pretty_date.js:21) - which is what a just-written row looks like once the
	// site's System Settings timezone has passed midnight and the browser has
	// not. The absolute date is the fallback rather than a blank.
	//
	// prettyDate is asked first, not comment_when(): comment_when() wraps the
	// empty string in a <span>, so its result is never falsy.
	//
	// html(), not text(): comment_when() hands back a whole
	// <span class="frappe-timestamp" title="<absolute date>"> element, not a
	// bare string, so as text it renders as visible markup.
	_render_synced($head, when) {
		let relative = "";
		if (when) {
			relative = frappe.datetime.prettyDate(when)
				? frappe.datetime.comment_when(when)
				: taxjar_integration.format_last_synced(when);
		}
		const $caption = $head.find(".taxjar-nexus-synced");
		$caption.html(relative ? __("Synced {0}", [relative]) : "");
		taxjar_integration.timestamp_tooltips($caption);
	}

	// ── syncs ──

	_sync_nexus($section) {
		this.sync($section, "update_nexus_list", __("Nexus regions fetched and updated."));
	}

	_sync_categories($section) {
		this.sync(
			$section,
			"refresh_product_tax_categories",
			__("Product tax categories fetched and updated.")
		);
	}

	// Both syncs are a TaxJar round trip per company. The button carries the
	// progress itself (same as the wizard's Sync Nexus step) rather than
	// freezing the whole desk behind a dialog.
	sync($section, method, success_message) {
		const $button = $section
			.find(".taxjar-nexus-sync-mount .es-button")
			.attr("aria-busy", "true")
			.prop("disabled", true);

		frappe
			.xcall(`${API}.${method}`)
			.then((summary) => {
				this.render(summary);
				frappe.show_alert({ message: success_message, indicator: "green" }, 5);
			})
			.catch(() => {
				// frappe.call's own error handler has already shown the server's
				// message; this is only here so the button below still resets.
			})
			.finally(() => {
				// A successful sync has already replaced this button along with the
				// rest of the body. Resetting a detached element does nothing, which
				// is what a failed sync needs it to do on the button still on screen.
				$button.removeAttr("aria-busy").prop("disabled", false);
			});
	}
}
