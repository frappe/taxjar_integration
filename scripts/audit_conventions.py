#!/usr/bin/env python3
"""Static convention checks for this app, run in CI beside semgrep.

Three conventions that a one-time sweep fixes and then quietly loses:

1. mock-target inertness - every patch("module.symbol") in the test suite names
   a symbol the module under test still defines *and* still uses. A patch whose
   target has been renamed or refactored off the code path keeps passing while
   testing nothing, which is the failure mode a large refactor is most likely to
   introduce and the least likely to notice.

2. throw titles - every frappe.throw() passes title=. Without one frappe renders
   the dialog under the generic heading "Message", which is neither specific nor
   searchable, and reads to the user as a core ERPNext failure rather than a
   TaxJar one.

3. enqueue-after-commit - every frappe.enqueue() passes enqueue_after_commit, or
   carries an inline justification. A job enqueued before its transaction commits
   can start against the pre-commit row.

AST-based rather than grep: a docstring that merely mentions frappe.throw() is
not a call, and a regex cannot tell the difference.

Usage:  python scripts/audit_conventions.py [--quiet]
Exit:   0 clean, 1 violations found.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "taxjar_integration"
ROOT = APP.parent

# --- exemptions ---------------------------------------------------------------
#
# Empty, and meant to stay that way. It briefly held the throws in get_state_code(),
# get_iso_3166_2_state_code() and validate_address() while those were being
# rewritten - the first two no longer throw at all, and validate_address()'s
# remaining messages carry titles.
THROW_TITLE_EXEMPT: set[tuple[str, str]] = set()

# frappe.enqueue calls that deliberately do not defer to commit, with the reason.
ENQUEUE_EXEMPT: dict[tuple[str, int], str] = {}

SKIP_DIRS = {"dist", "node_modules", "__pycache__", ".git"}


def _py_files(root: Path):
	for path in sorted(root.rglob("*.py")):
		if not any(part in SKIP_DIRS for part in path.parts):
			yield path


def _rel(path: Path) -> str:
	return str(path.relative_to(ROOT))


def _attr_path(node: ast.AST) -> str:
	"""Dotted source text of an attribute chain, e.g. frappe.db.get_value."""
	parts = []
	while isinstance(node, ast.Attribute):
		parts.append(node.attr)
		node = node.value
	if isinstance(node, ast.Name):
		parts.append(node.id)
	return ".".join(reversed(parts))


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
	"""Map every line number to the innermost function that contains it."""
	owner: dict[int, str] = {}
	for node in ast.walk(tree):
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
			for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
				owner[line] = node.name
	return owner


# --- check 2: throw titles ----------------------------------------------------

def check_throw_titles() -> list[str]:
	problems = []
	for path in _py_files(APP):
		if "/test_" in _rel(path):
			continue
		tree = ast.parse(path.read_text(), filename=str(path))
		owner = _enclosing_functions(tree)
		for node in ast.walk(tree):
			if not isinstance(node, ast.Call):
				continue
			if _attr_path(node.func) != "frappe.throw":
				continue
			if any(kw.arg == "title" for kw in node.keywords):
				continue
			fn = owner.get(node.lineno, "<module>")
			if (_rel(path), fn) in THROW_TITLE_EXEMPT:
				continue
			problems.append(f"{_rel(path)}:{node.lineno}  frappe.throw() in {fn}() has no title=")
	return problems


# --- check 3: enqueue after commit --------------------------------------------

def check_enqueue_after_commit() -> list[str]:
	problems = []
	for path in _py_files(APP):
		if "/test_" in _rel(path):
			continue
		source = path.read_text()
		lines = source.splitlines()
		tree = ast.parse(source, filename=str(path))
		for node in ast.walk(tree):
			if not isinstance(node, ast.Call):
				continue
			if _attr_path(node.func) != "frappe.enqueue":
				continue
			if any(kw.arg == "enqueue_after_commit" for kw in node.keywords):
				continue
			if (_rel(path), node.lineno) in ENQUEUE_EXEMPT:
				continue
			# An inline justification on the call's own line, or the one above it.
			window = "\n".join(lines[max(0, node.lineno - 2):node.lineno])
			if "no-after-commit:" in window:
				continue
			problems.append(
				f"{_rel(path)}:{node.lineno}  frappe.enqueue() without enqueue_after_commit "
				f"(add it, or justify with a '# no-after-commit: <reason>' comment)"
			)
	return problems


# --- check 1: mock-target inertness -------------------------------------------

def _module_file(dotted: str) -> Path | None:
	candidate = ROOT / (dotted.replace(".", "/") + ".py")
	return candidate if candidate.is_file() else None


def _resolve_target(target: str) -> tuple[Path, str] | None:
	"""Split "a.b.c.symbol" into the deepest importable module and the symbol.

	Walks right-to-left so "pkg.mod.frappe.db.get_value" resolves to pkg/mod.py
	with symbol "frappe" - the name the module must actually hold.
	"""
	parts = target.split(".")
	for cut in range(len(parts) - 1, 0, -1):
		path = _module_file(".".join(parts[:cut]))
		if path:
			return path, parts[cut]
	return None


def check_mock_targets() -> list[str]:
	problems = []
	seen: set[str] = set()
	for path in _py_files(APP):
		if "/test_" not in _rel(path):
			continue
		tree = ast.parse(path.read_text(), filename=str(path))
		for node in ast.walk(tree):
			if not isinstance(node, ast.Call):
				continue
			if _attr_path(node.func).split(".")[-1] != "patch":
				continue
			if not node.args or not isinstance(node.args[0], ast.Constant):
				continue
			target = node.args[0].value
			if not isinstance(target, str) or target in seen:
				continue
			seen.add(target)

			resolved = _resolve_target(target)
			if resolved is None:
				continue  # third-party or stdlib target - not ours to police
			module_path, symbol = resolved
			module_src = module_path.read_text()
			module_tree = ast.parse(module_src, filename=str(module_path))

			bound = False
			for n in ast.walk(module_tree):
				if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == symbol:
					bound = True
				elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == symbol:
					bound = True
				elif isinstance(n, ast.alias) and (n.asname or n.name.split(".")[0]) == symbol:
					bound = True
			if not bound:
				problems.append(
					f"{_rel(path)}  patch(\"{target}\") - {_rel(module_path)} no longer defines "
					f"or imports '{symbol}'; this mock controls nothing"
				)
				continue

			# Bound but never used is just as inert: the module imports it and
			# the code path has moved on to something else.
			uses = sum(
				1 for n in ast.walk(module_tree)
				if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id == symbol
			) + sum(
				1 for n in ast.walk(module_tree)
				if isinstance(n, ast.Attribute) and _attr_path(n).split(".")[0] == symbol
			)
			if uses == 0:
				problems.append(
					f"{_rel(path)}  patch(\"{target}\") - {_rel(module_path)} binds '{symbol}' "
					f"but never uses it; this mock controls nothing"
				)
	return problems


# Endpoints that write to a Customer. A test that hands one of these a name it
# read from the site is mutating whatever that site happens to hold.
_CUSTOMER_WRITE_ENDPOINTS = (
	"configure_exemption",
	"bulk_clear_exemption",
	"bulk_sync_to_taxjar",
)


def check_tests_do_not_write_to_site_records():
	"""No test may feed a site read into a Customer write endpoint.

	The suite runs against a real site - the app's own docs name
	usa-final.localhost - and a Customer written by a test is a Customer the
	person using that site owns. TestCustomerConfigPageAPI used to read every
	customer with get_customers() and pass the names to these endpoints. It
	restored the exemption type afterwards, but bulk_sync_to_taxjar writes
	"Queued" and there is nothing to restore that from, so every run left real
	customers queued for a job that never existed - which is exactly the bug
	people then reported against the app.

	A test that needs a Customer creates its own and deletes it.
	"""
	problems = []
	for path in _py_files(ROOT):
		if not path.name.startswith("test_"):
			continue
		source = path.read_text(encoding="utf-8")
		lines = source.splitlines()
		for i, line in enumerate(lines):
			if 'get_customers()["customers"]' not in line:
				continue
			# Look ahead to the end of this test for a write endpoint call.
			for follow in lines[i : i + 40]:
				if follow.lstrip().startswith("def test_") and follow is not lines[i]:
					break
				for endpoint in _CUSTOMER_WRITE_ENDPOINTS:
					if f"{endpoint}(" in follow and "def " not in follow:
						problems.append(
							f"{_rel(path)}:{i + 1}  a name read from the site is passed to "
							f"{endpoint}(); create a Customer for the test instead"
						)
						break
				else:
					continue
				break
	return problems


CHECKS = (
	("mock targets still on the code path", check_mock_targets),
	("frappe.throw() titles", check_throw_titles),
	("frappe.enqueue() after commit", check_enqueue_after_commit),
	("tests do not write to site records", check_tests_do_not_write_to_site_records),
)


def main() -> int:
	quiet = "--quiet" in sys.argv
	failed = 0
	for name, check in CHECKS:
		problems = check()
		failed += len(problems)
		if problems:
			print(f"\n✗ {name} - {len(problems)} violation(s)")
			for problem in problems:
				print(f"    {problem}")
		elif not quiet:
			print(f"✓ {name}")
	if failed:
		print(f"\n{failed} violation(s). See scripts/audit_conventions.py for what each check is for.")
		return 1
	if not quiet:
		print("\nAll convention checks clean.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
