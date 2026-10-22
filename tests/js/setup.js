// jQuery is a global on the desk, not an import. The scripts under test call
// `$(document)` to reach the form sidebar, so it has to be a global here too,
// and it has to be the real library: the sidebar code inserts markup with
// `.after()` and then the tests read it back with `.find()`.
import jquery from "jquery";

globalThis.$ = jquery;
globalThis.jQuery = jquery;
window.$ = jquery;
window.jQuery = jquery;
