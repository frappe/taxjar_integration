import fs from 'node:fs'
import path from 'node:path'
import type { MarkdownRenderer } from 'vitepress'

// A page shows its text before its screenshots arrive. Two things made the
// screenshots look late:
//
// - The <img> tag had no size. The browser kept no space for the image, so
//   the text below it moved down when the image arrived.
// - All the screenshots of a page loaded at the same time. The one on the
//   screen waited with those far below it.
//
// This plugin adds attributes to each <img> tag. It does not change an image
// file. The width and the height come from the file, so the browser keeps the
// space. The first image of a page loads with high priority, and the others
// load when the reader comes near them.
const publicDir = path.resolve(import.meta.dirname, '../src/public')

// The size of a WebP or PNG image, from the start of the file.
function readSize(file: string): { width: number; height: number } | null {
	const bytes = Buffer.alloc(32)
	let length = 0
	try {
		const handle = fs.openSync(file, 'r')
		length = fs.readSync(handle, bytes, 0, 32, 0)
		fs.closeSync(handle)
	} catch {
		return null
	}
	if (length < 30) return null

	if (bytes.toString('latin1', 1, 4) === 'PNG') {
		return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) }
	}
	if (bytes.toString('latin1', 0, 4) !== 'RIFF' || bytes.toString('latin1', 8, 12) !== 'WEBP') return null

	// WebP has three kinds of image data, and each one stores the size differently.
	const kind = bytes.toString('latin1', 12, 16)
	if (kind === 'VP8 ') {
		return { width: bytes.readUInt16LE(26) & 0x3fff, height: bytes.readUInt16LE(28) & 0x3fff }
	}
	if (kind === 'VP8L') {
		const bits = bytes.readUInt32LE(21)
		return { width: (bits & 0x3fff) + 1, height: ((bits >>> 14) & 0x3fff) + 1 }
	}
	if (kind === 'VP8X') {
		return { width: bytes.readUIntLE(24, 3) + 1, height: bytes.readUIntLE(27, 3) + 1 }
	}
	return null
}

const sizes = new Map<string, ReturnType<typeof readSize>>()

export function imageLoading(md: MarkdownRenderer) {
	const render = md.renderer.rules.image!

	md.renderer.rules.image = (tokens, index, options, env, self) => {
		const token = tokens[index]
		const src = token.attrGet('src') || ''

		// An image of the docs is in src/public, and its address starts with "/".
		if (src.startsWith('/') && !src.startsWith('//')) {
			const file = path.join(publicDir, decodeURI(src.split(/[?#]/)[0]))
			if (!sizes.has(file)) sizes.set(file, readSize(file))
			const size = sizes.get(file)
			if (size) {
				token.attrSet('width', String(size.width))
				token.attrSet('height', String(size.height))
			}
		}

		// env is the same object for all the images of one page.
		env.imageCount = (env.imageCount || 0) + 1
		if (env.imageCount === 1) {
			token.attrSet('fetchpriority', 'high')
		} else {
			token.attrSet('loading', 'lazy')
			token.attrSet('decoding', 'async')
		}

		return render(tokens, index, options, env, self)
	}
}
