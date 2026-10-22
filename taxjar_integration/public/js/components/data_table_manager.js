frappe.provide("taxjar_integration");

// Thin wrapper over frappe.DataTable (frappe/public/js/frappe/ui/datatable.js),
// giving the TaxJar desk pages the column/checkbox/inline-filter behaviour the
// desk uses elsewhere instead of hand-rolled <table> markup.
//
// checkboxColumn puts a select-all checkbox in the header - that is where the
// page's "Select All" button went. inlineFilters draws the per-column filter
// row under the header.
//
// Modelled on india_compliance's DataTableManager, deliberately copied rather
// than imported: india_compliance is present in this bench but installed on no
// site, so importing it would break at runtime. Everything it wraps is native
// frappe, so the copy costs nothing.
taxjar_integration.DataTableManager = class DataTableManager {
	constructor(options) {
		Object.assign(this, options);
		this.data = this.data || [];
		this.make();
	}

	make() {
		this.$wrapper.addClass("taxjar-datatable");
		this.render_datatable();
		this.setup_server_filters();
		this.suppress_native_tooltips();
		this.fit_height();

		this.columns_dict = {};
		for (const column of this.datatable.getColumns()) {
			this.columns_dict[column.field || column.id] = column;
		}
	}

	// The page paginates; the table must not scroll inside itself as well. The
	// library's stylesheet pins .dt-scrollable to 40vw, which is what produces
	// that inner scrollbar, so the container is resized to exactly the rows it
	// holds and there is never anything to scroll.
	//
	// The height cannot simply be dropped to auto: rows are drawn by HyperList,
	// a virtual scroller that takes the container's *computed* height as its
	// viewport (body-renderer.js:35-40). An auto height computes to 0px, the
	// viewport becomes zero rows tall, and the table renders empty. It needs a
	// real number - just the right one.
	//
	// Setting the height alone is not enough either, since HyperList has
	// already read the old value; the re-render is what makes it take effect.
	fit_height() {
		const $scrollable = this.$wrapper.find(".dt-scrollable");
		const el = $scrollable.get(0);
		if (!el) return;

		const cell_height = this.options?.cellHeight || 34;
		const rows = Math.max(this.data.length, 1);
		// A horizontal scrollbar takes vertical space inside the container, so
		// without an allowance for it the last row would be clipped. Same
		// correction the library makes for itself in style.js:346-351.
		const scrollbar = el.scrollWidth > el.clientWidth ? 16 : 0;

		const height = `${rows * cell_height + scrollbar + 2}px`;
		if ($scrollable.css("height") === height) return;

		$scrollable.css("height", height);
		this.datatable.bodyRenderer.render();
	}

	render_datatable() {
		const datatable_options = {
			dynamicRowHeight: true,
			checkboxColumn: true,
			inlineFilters: true,
			noDataMessage: __("No Matching Data Found!"),
			cellHeight: 34,
			// Columns share out the container width instead of leaving dead
			// space to the right of the last one.
			layout: "fluid",
			// On by default in the library. With pagination the number restarts
			// at 1 on every page, so it says nothing the rows don't already.
			serialNoColumn: false,
			// The library's own floating "N rows selected" toast
			// (rowmanager.js:138-142). The pages show that count beside the Bulk
			// Action button, where it belongs next to what acts on it, and the
			// toast overlaps the rows while you are trying to pick them.
			checkedRowStatus: false,
			// The library filters the rows it has in memory, which is one page.
			// Filtering happens on the server instead (setup_server_filters),
			// so this hands every row straight back unfiltered.
			filterRows: (rows) => rows.map((row) => row.meta.rowIndex),
			events: {
				onCheckRow: () => this.on_check_row && this.on_check_row(this.get_checked_items()),
			},
			...this.options,
			columns: this.get_dt_columns(),
			data: this.data,
		};

		this.datatable = new frappe.DataTable(this.$wrapper.get(0), datatable_options);
	}

	// The library stamps every cell with a title attribute holding that cell's
	// own text (cellmanager.js:939), so the browser raises its native tooltip
	// over content that is already fully readable - columns here are sized to
	// their widest cell, so nothing is truncated and the tooltip only ever
	// repeats what is on screen. Worse, on a status cell it lands on top of the
	// popover carrying the detail the reader actually hovered for.
	//
	// Stripped as the pointer arrives rather than after each render: the
	// browser reads the attribute only once its hover delay elapses, so
	// removing it on the way in is enough, and it keeps working through the
	// re-renders HyperList does on every scroll. Delegated on the wrapper, so
	// mouseover (which bubbles) rather than mouseenter (which does not). The
	// filter row's own title lives on the input, not the cell, and stays.
	suppress_native_tooltips() {
		this.$wrapper.on("mouseover", ".dt-cell__content[title]", (e) =>
			$(e.currentTarget).removeAttr("title")
		);
	}

	// The inline filter row looks like it filters the result set, so it has to
	// actually do that. Left to the library it would only narrow the page in
	// memory - with 20-row pages, searching a customer who is on page 3 would
	// silently report nothing found.
	setup_server_filters() {
		if (!this.on_filter_change) return;

		const push_filters = frappe.utils.debounce(() => {
			const filters = {};
			// Each filter input carries its own colIndex (columnmanager.js:395).
			this.$wrapper.find(".dt-filter").each((_, input) => {
				const value = input.value.trim();
				if (!value) return;
				const column = this.datatable.getColumn(input.dataset.colIndex);
				if (column?.field) filters[column.field] = value;
			});
			this.on_filter_change(filters);
		}, 400);

		this.$wrapper.on("input", ".dt-filter", push_filters);
	}

	// datatable.refresh() rebuilds the whole header (columnmanager.js:28-45),
	// filter row included, so the new inputs come back empty and the row comes
	// back hidden. The server filter still holds the old text, so the rows stay
	// filtered by a word the reader can no longer see. The filter row's state is
	// read before the rebuild and put back after it, focus and caret included,
	// because a refresh lands while the reader is still typing.
	refresh(data, columns) {
		this.data = data || [];
		const filter_state = this.get_filter_state();
		this.datatable.refresh(this.data, columns);
		this.restore_filter_state(filter_state);
		this.fit_height();
	}

	// Read off the DOM, not columnmanager.isFilterShown: nothing here sets that
	// flag, yet the row is on screen, so the flag cannot say whether it shows.
	get_filter_state() {
		const $row = this.$wrapper.find(".dt-row-filter");
		const values = {};
		this.$wrapper.find(".dt-filter").each((_, input) => {
			if (input.value) values[input.dataset.colIndex] = input.value;
		});

		const focused = document.activeElement;
		const has_focus = focused?.classList.contains("dt-filter") && this.$wrapper[0].contains(focused);

		return {
			shown: $row.length > 0 && $row.css("display") !== "none",
			values,
			focus: has_focus
				? {
						col_index: focused.dataset.colIndex,
						start: focused.selectionStart,
						end: focused.selectionEnd,
				  }
				: null,
		};
	}

	restore_filter_state({ shown, values, focus }) {
		if (!shown && !Object.keys(values).length) return;
		this.datatable.columnmanager.toggleFilter(true);

		this.$wrapper.find(".dt-filter").each((_, input) => {
			input.value = values[input.dataset.colIndex] || "";
			if (focus?.col_index !== input.dataset.colIndex) return;
			input.focus();
			input.setSelectionRange(focus.start, focus.end);
		});
	}

	get_dt_columns() {
		return (this.columns || []).map((column) => {
			const docfield = {
				options: column.options || column.doctype,
				fieldname: column.fieldname,
				fieldtype: column.fieldtype,
				precision: column.precision,
			};

			// _value rewrites the raw cell value before frappe.format; _html
			// replaces the formatted output entirely (pills, links, muted
			// placeholders). Both get the whole row, since most of our cells
			// depend on a sibling field.
			const format = (value, row, col, data) => {
				if (col._html) return col._html(value, data);
				if (col._value) value = col._value(value, data);
				return frappe.format(value, col, { always_show_decimals: true }, data);
			};

			return {
				id: column.fieldname,
				field: column.fieldname,
				name: column.label,
				content: column.label,
				editable: false,
				// No width fallback on purpose. A column left without one gets
				// column.naturalWidth - the widest rendered cell in it
				// (style.js:204-207) - so text is never cut off, and the fluid
				// layout then shares out whatever room is left rather than
				// leaving dead space to the right of the last column.
				format,
				docfield,
				...column,
			};
		});
	}

	get_checked_items() {
		return this.datatable.rowmanager.getCheckedRows().map((index) => this.data[index]);
	}

	clear_checked_items() {
		const { rowmanager } = this.datatable;
		rowmanager.getCheckedRows().map((rowIndex) => rowmanager.checkRow(rowIndex, false));
	}
};
