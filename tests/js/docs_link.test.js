// The "Read documentation" link in a permission refusal opens in a new tab.
//
// Frappe cleans the HTML of every message it shows, and the cleaning keeps
// href on a link but drops target. So taxjar_utils.js opens this one link in a
// new tab itself, and leaves every other link to the desk.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { install_desk, load_taxjar_utils } from "./helpers/desk.js";

let taxjar;

beforeEach(() => {
	install_desk();
	taxjar = load_taxjar_utils();
	window.open = vi.fn();
});

afterEach(() => {
	document.body.innerHTML = "";
});

function click_link(href) {
	const link = $(`<a href="${href}">Read documentation &rarr;</a>`).appendTo(document.body)[0];
	const event = new MouseEvent("click", { bubbles: true, cancelable: true });
	link.dispatchEvent(event);
	return event;
}

describe("the roles documentation link", () => {
	it("opens in a new tab", () => {
		const href = `${taxjar.ROLES_DOCS_URL}#taxjar-tasks-and-the-rights-they-need`;
		const event = click_link(href);

		expect(window.open).toHaveBeenCalledWith(href, "_blank", "noopener,noreferrer");
		expect(event.defaultPrevented).toBe(true);
	});

	it("leaves every other link to the desk", () => {
		const event = click_link("https://example.org/somewhere-else");

		expect(window.open).not.toHaveBeenCalled();
		expect(event.defaultPrevented).toBe(false);
	});

	it("opens once, however often the file is loaded", () => {
		load_taxjar_utils();
		click_link(taxjar.ROLES_DOCS_URL);

		expect(window.open).toHaveBeenCalledTimes(1);
	});
});
