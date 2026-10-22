import { defineConfig } from "vitest/config";

// The desk scripts are plain browser scripts that hang off a global, not ES
// modules, so they are loaded by `tests/js/helpers/desk.js` rather than
// imported. jsdom supplies the `window` and `document` they expect.
export default defineConfig({
	test: {
		environment: "jsdom",
		include: ["tests/js/**/*.test.js"],
		setupFiles: ["tests/js/setup.js"],
		restoreMocks: true,
	},
});
