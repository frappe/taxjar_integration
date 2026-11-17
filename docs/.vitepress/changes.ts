import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import type { MarkdownRenderer } from 'vitepress'

// The preview of a pull request shows what the pull request changed. A changed
// block gets the class "docs-changed", and a changed page gets a banner with a
// link to the same page of the live docs. See custom.css for the look.
//
// DOCS_DIFF_BASE is the git ref of the base branch. The PR run sets it for a
// preview build. A build without it, such as the public site, has no marks.
// DOCS_LIVE_URL is the address of the live docs, for the link in the banner.
const baseRef = process.env.DOCS_DIFF_BASE || ''
const liveUrl = (process.env.DOCS_LIVE_URL || '').replace(/\/+$/, '')

const srcDir = path.resolve(import.meta.dirname, '../src')
const repoRoot = baseRef ? git(['rev-parse', '--show-toplevel'], srcDir) : ''
const srcInRepo = repoRoot ? path.relative(repoRoot, srcDir).split(path.sep).join('/') : ''

function git(args: string[], cwd = repoRoot) {
	try {
		return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trimEnd()
	} catch {
		return ''
	}
}

// The commit where the pull request left the base branch. A change that the
// base branch got later is not a change of this pull request.
const base = baseRef ? git(['merge-base', baseRef, 'HEAD']) || baseRef : ''

// The lines of a text that say something: no empty lines, no space at the ends.
function lines(text: string) {
	return text
		.split('\n')
		.map((line) => line.trim())
		.filter(Boolean)
}

// A page can include a part (src/parts). The text of a part is then in the
// page, so the lines of all parts count as lines of each page.
function partLines(read: (file: string) => string, files: string[]) {
	return files.filter((file) => file.startsWith('parts/')).flatMap((file) => lines(read(file)))
}

const baseFile = (file: string) => git(['show', `${base}:${srcInRepo}/${file}`])
const headFile = (file: string) => {
	try {
		return fs.readFileSync(path.join(srcDir, file), 'utf8')
	} catch {
		return ''
	}
}
const baseParts = base
	? partLines(
			baseFile,
			git(['ls-tree', '-r', '--name-only', base, '--', `${srcInRepo}/parts`])
				.split('\n')
				.filter(Boolean)
				.map((file) => file.slice(srcInRepo.length + 1)),
		)
	: []
const headParts = base
	? partLines(
			headFile,
			fs.existsSync(path.join(srcDir, 'parts'))
				? (fs.readdirSync(path.join(srcDir, 'parts'), { recursive: true }) as string[]).map((file) => `parts/${file}`)
				: [],
		)
	: []

// The blocks that can get a mark. A table gets its marks on the rows.
const MARKED = new Set(['paragraph_open', 'heading_open', 'tr_open', 'fence', 'code_block'])

export function markChanges(md: MarkdownRenderer) {
	if (!base) return

	md.core.ruler.push('docs_changes', (state) => {
		const file: string = state.env?.relativePath || ''
		if (!file || file.startsWith('parts/')) return

		const before = baseFile(file)
		const isNew = !before
		const known = new Set([...lines(before), ...baseParts])
		let changed = 0

		if (!isNew) {
			const source = state.src.split('\n')
			const out: typeof state.tokens = []
			for (const [index, token] of state.tokens.entries()) {
				const isChanged =
					MARKED.has(token.type) &&
					token.map &&
					lines(source.slice(token.map[0], token.map[1]).join('\n')).some((line) => !known.has(line))
				if (!isChanged) {
					out.push(token)
					continue
				}
				changed += 1
				if (token.type === 'fence' || token.type === 'code_block') {
					// The code block renderer does not keep a class, so a wrapper holds it.
					const open = new state.Token('html_block', '', 0)
					open.content = '<div class="docs-changed">\n'
					const close = new state.Token('html_block', '', 0)
					close.content = '</div>\n'
					out.push(open, token, close)
					continue
				}
				// The paragraph of a short list item has no <p> in the page. The
				// mark then goes on the list item.
				let target = token
				if (token.hidden) {
					for (let parent = index - 1; parent >= 0; parent -= 1) {
						const candidate = state.tokens[parent]
						if (candidate.nesting === 1 && candidate.level < token.level) {
							target = candidate
							break
						}
					}
				}
				if (!(target.attrGet('class') || '').split(' ').includes('docs-changed')) {
					target.attrJoin('class', 'docs-changed')
				}
				out.push(token)
			}
			state.tokens = out
		}

		// Text that the pull request removed is not in the page, so it cannot
		// get a mark. The banner gives the number of the lines that are gone:
		// the removed lines, and the old text of the changed lines.
		const now = new Set([...lines(headFile(file)), ...headParts])
		const removed = isNew ? 0 : lines(before).filter((line) => !now.has(line)).length
		if (!isNew && !changed && !removed) return

		const facts = isNew
			? ['This page is new in this pull request.']
			: [
					'This pull request changes this page.',
					changed ? `Changed or new blocks have a mark: ${changed}.` : '',
					removed ? `Removed or replaced lines: ${removed}.` : '',
				].filter(Boolean)
		const route = file.replace(/(^|\/)index\.md$/, '$1').replace(/\.md$/, '')
		const link =
			liveUrl && !isNew ? ` <a href="${liveUrl}/${route}" target="_blank" rel="noopener">Open the live page</a>` : ''
		const banner = new state.Token('html_block', '', 0)
		banner.content = `<div class="docs-changes-banner" v-pre>${facts.join(' ')}${link}</div>\n`
		// After the frontmatter token, if the page has one.
		const first = state.tokens.findIndex((token) => token.type !== 'front_matter')
		state.tokens.splice(first < 0 ? 0 : first, 0, banner)
	})
}
