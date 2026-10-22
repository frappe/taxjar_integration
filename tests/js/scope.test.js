// taxjar_integration.scope() and when_scoped() - the two functions every client
// gate is built on. Design doc §3.4.

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
	IN_CO,
	SCOPE_METHOD,
	US_CALC,
	US_OFF,
	US_UNCONFIGURED,
	answer_scope,
	install_desk,
	load_taxjar_utils,
	make_frm,
} from "./helpers/desk.js";

describe("taxjar_integration.scope", () => {
	let frappe;
	let taxjar;

	beforeEach(() => {
		frappe = install_desk();
		taxjar = load_taxjar_utils();
	});

	it("answers null for no company, without asking the server", async () => {
		answer_scope(frappe, US_CALC);

		await expect(taxjar.scope(undefined)).resolves.toBeNull();
		await expect(taxjar.scope("")).resolves.toBeNull();

		expect(frappe.xcall).not.toHaveBeenCalled();
	});

	it("asks the server once for a company, and answers the rest from memory", async () => {
		answer_scope(frappe, US_CALC);

		const first = await taxjar.scope(US_CALC.company);
		const second = await taxjar.scope(US_CALC.company);

		expect(first).toEqual(US_CALC);
		expect(second).toEqual(US_CALC);
		expect(frappe.xcall).toHaveBeenCalledTimes(1);
		expect(frappe.xcall).toHaveBeenCalledWith(SCOPE_METHOD, { company: US_CALC.company });
	});

	// The memo lasts as long as the page, and desk routing never reloads the
	// page. So a configuration change has to say so, or every form opened
	// afterwards paints an answer from before the change - which is what made a
	// hard refresh the only way to see a switch take effect.
	it("asks again once the cache is cleared", async () => {
		const answers = [US_CALC, US_OFF];
		frappe.xcall.mockImplementation(() => Promise.resolve(answers.shift()));

		await expect(taxjar.scope(US_CALC.company)).resolves.toEqual(US_CALC);

		taxjar.clear_scope_cache();

		await expect(taxjar.scope(US_CALC.company)).resolves.toEqual(US_OFF);
		expect(frappe.xcall).toHaveBeenCalledTimes(2);
	});

	it("forgets every company, not only the one that changed", async () => {
		const by_company = { [US_CALC.company]: US_CALC, [US_OFF.company]: US_OFF };
		frappe.xcall.mockImplementation((method, args) =>
			Promise.resolve(by_company[args.company])
		);

		await taxjar.scope(US_CALC.company);
		await taxjar.scope(US_OFF.company);
		expect(frappe.xcall).toHaveBeenCalledTimes(2);

		// One save rewrites the whole TaxJar Settings record, company_config
		// child rows included, so no single company owns the change.
		taxjar.clear_scope_cache();

		await taxjar.scope(US_CALC.company);
		await taxjar.scope(US_OFF.company);
		expect(frappe.xcall).toHaveBeenCalledTimes(4);
	});

	// The memo is on the promise, not on its result. Four callers that start
	// together on one form refresh have no result to share yet, so a memo on the
	// result would let all four race to the server.
	it("shares one request between callers that start together", async () => {
		let settle;
		frappe.xcall.mockImplementation(
			() => new Promise((resolve) => {
				settle = resolve;
			})
		);

		const waiting = [
			taxjar.scope(US_CALC.company),
			taxjar.scope(US_CALC.company),
			taxjar.scope(US_CALC.company),
			taxjar.scope(US_CALC.company),
		];

		expect(frappe.xcall).toHaveBeenCalledTimes(1);

		settle(US_CALC);
		const answers = await Promise.all(waiting);

		expect(answers).toEqual([US_CALC, US_CALC, US_CALC, US_CALC]);
		expect(frappe.xcall).toHaveBeenCalledTimes(1);
	});

	it("keeps one answer per company", async () => {
		const by_company = { [US_CALC.company]: US_CALC, [IN_CO.company]: IN_CO };
		frappe.xcall.mockImplementation((method, args) => Promise.resolve(by_company[args.company]));

		await expect(taxjar.scope(US_CALC.company)).resolves.toEqual(US_CALC);
		await expect(taxjar.scope(IN_CO.company)).resolves.toEqual(IN_CO);

		expect(frappe.xcall).toHaveBeenCalledTimes(2);
	});

	// A failed read must not leave the form asserting anything about a company it
	// could not resolve, and must not leave a poisoned entry behind either.
	it("answers null on a failed read, and asks again next time", async () => {
		frappe.xcall.mockRejectedValueOnce(new Error("network"));

		await expect(taxjar.scope(US_CALC.company)).resolves.toBeNull();

		frappe.xcall.mockResolvedValueOnce(US_CALC);
		await expect(taxjar.scope(US_CALC.company)).resolves.toEqual(US_CALC);

		expect(frappe.xcall).toHaveBeenCalledTimes(2);
	});
});

describe("taxjar_integration.when_scoped", () => {
	let frappe;
	let taxjar;
	let body;

	beforeEach(() => {
		frappe = install_desk();
		taxjar = load_taxjar_utils();
		body = vi.fn();
	});

	const run = (profile, predicate) => {
		answer_scope(frappe, profile);
		const frm = make_frm({ company: profile.company });
		return taxjar.when_scoped(frm, predicate, body);
	};

	it("runs the body for a company in scope whose predicate holds", async () => {
		await run(US_CALC, (scope) => scope.calculates);

		expect(body).toHaveBeenCalledTimes(1);
		expect(body).toHaveBeenCalledWith(US_CALC);
	});

	it("does not run the body for a company out of scope", async () => {
		await run(IN_CO, () => true);
		await run(US_UNCONFIGURED, () => true);

		expect(body).not.toHaveBeenCalled();
	});

	it("does not run the body when the predicate fails", async () => {
		await run(US_OFF, (scope) => scope.calculates);

		expect(body).not.toHaveBeenCalled();
	});

	it("does not run the body when the scope could not be read", async () => {
		frappe.xcall.mockRejectedValue(new Error("network"));
		const frm = make_frm({ company: US_CALC.company });

		await taxjar.when_scoped(frm, () => true, body);

		expect(body).not.toHaveBeenCalled();
	});

	// The company is read off the form on every call rather than captured, so
	// changing it on a draft changes the answer.
	it("reads the company off the form each time it is called", async () => {
		const by_company = { [US_CALC.company]: US_CALC, [IN_CO.company]: IN_CO };
		frappe.xcall.mockImplementation((method, args) => Promise.resolve(by_company[args.company]));

		const frm = make_frm({ company: US_CALC.company });
		await taxjar.when_scoped(frm, () => true, body);
		expect(body).toHaveBeenCalledTimes(1);

		frm.doc.company = IN_CO.company;
		await taxjar.when_scoped(frm, () => true, body);
		expect(body).toHaveBeenCalledTimes(1);
	});
});
