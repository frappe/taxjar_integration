"""Check the docs: frontmatter, headings, alt text, images, links, anchors, sidebar."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def slug(text):
	# VitePress slugify: lower case, drop punctuation, spaces to hyphens.
	text = re.sub(r"[*`]", "", text).strip().lower()
	text = re.sub(r"[^\w\s-]", "", text)
	return re.sub(r"[\s]+", "-", text).strip("-")


pages, anchors = {}, {}
for p in SRC.rglob("*.md"):
	if "parts" in p.relative_to(SRC).parts:
		continue
	route = "/" + str(p.relative_to(SRC))[:-3]
	route = "/" if route == "/index" else route
	text = p.read_text()
	pages[route] = (p, text)
	anchors[route] = {slug(h) for h in re.findall(r"^#{1,6} (.+)$", text, re.M)}
	# HTML ids, for example <li id="step-2-connect">.
	anchors[route] |= set(re.findall(r'\bid="([\w-]+)"', text))

# The full title is the frontmatter title and this suffix, unless the page sets
# titleTemplate: false. Search results show about 60 characters.
suffix = re.search(r"titleTemplate: ':title(.*)'", (ROOT / ".vitepress/config.mts").read_text()).group(1)

errors = []
for route, (p, text) in pages.items():
	fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
	if not fm:
		errors.append(f"{p}: no frontmatter")
		continue
	for key in ("title", "description"):
		if not re.search(rf"^{key}: \".+\"$", fm.group(1), re.M):
			errors.append(f"{p}: {key} missing or unquoted")
	title = re.search(r'^title: "(.+)"$', fm.group(1), re.M)
	if title:
		full = title.group(1) + ("" if re.search(r"^titleTemplate: false$", fm.group(1), re.M) else suffix)
		if len(full) > 60:
			errors.append(f"{p}: title with suffix is {len(full)} characters, more than 60: {full}")
	body = text[fm.end():]
	last = 0
	in_code = False
	for i, line in enumerate(body.splitlines(), 1):
		if line.startswith("```"):
			in_code = not in_code
		if in_code:
			continue
		h = re.match(r"^(#+) ", line)
		if h:
			if last and len(h.group(1)) > last + 1:
				errors.append(f"{p}: heading jumps to h{len(h.group(1))}: {line}")
			last = len(h.group(1))
		for alt, src in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", line):
			if not alt.strip():
				errors.append(f"{p}: empty alt text")
			if not (SRC / "public" / src.lstrip("/")).exists():
				errors.append(f"{p}: missing image {src}")
		for target in re.findall(r"\]\((/[^)\s]*)\)", line):
			if target.startswith("/images/"):
				continue
			path, _, anchor = target.partition("#")
			if path not in pages:
				errors.append(f"{p}: broken link {target}")
			elif anchor and anchor not in anchors[path]:
				errors.append(f"{p}: broken anchor {target}")
		if "{{" in line:
			errors.append(f"{p}: template syntax")
		if re.search(r"\]\((?:click )?here\)", line, re.I):
			errors.append(f"{p}: vague link text")

config = (ROOT / ".vitepress/config.mts").read_text()
linked = set(re.findall(r"link: '([^']+)'", config))
for link in linked:
	path, _, anchor = link.partition("#")
	if path not in pages:
		errors.append(f"sidebar: no page for {link}")
	elif anchor and anchor not in anchors[path]:
		errors.append(f"sidebar: broken anchor {link}")
for route in pages:
	if route != "/" and route not in linked:
		errors.append(f"sidebar: no link for {route}")

print("\n".join(errors) or "lint: no errors")
sys.exit(1 if errors else 0)
