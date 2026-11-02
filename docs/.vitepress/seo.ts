import fs from 'node:fs'
import path from 'node:path'
import type { HeadConfig, PageData, SiteConfig } from 'vitepress'

// DOCS_URL is the public address of the docs, with its path, for example
// https://docs.frappe.io/regional/usa. A build with DOCS_URL is the public site:
// search engines may index it, and it has a sitemap and canonical URLs. A build
// without DOCS_URL is a preview, and every page asks search engines not to index it.
export const siteUrl = (process.env.DOCS_URL || '').replace(/\/+$/, '')
export const base = siteUrl ? new URL(siteUrl).pathname.replace(/\/?$/, '/') : '/'

const siteName = 'TaxJar Integration for ERPNext'
const socialImage = 'social-card.png'

type SidebarGroup = { text: string; items: { text: string; link: string }[] }

// start/overview.md -> start/overview, index.md -> ''
function pagePath(relativePath: string) {
	return relativePath.replace(/(^|\/)index\.md$/, '$1').replace(/\.md$/, '')
}

function absolute(urlPath: string) {
	return `${siteUrl}/${urlPath.replace(/^\//, '')}`
}

export function pageHead(pageData: PageData): HeadConfig[] {
	if (!siteUrl) return [['meta', { name: 'robots', content: 'noindex, nofollow' }]]

	const url = absolute(pagePath(pageData.relativePath))
	const title = pageData.frontmatter.title || pageData.title
	const description = pageData.frontmatter.description || pageData.description
	const isHome = pageData.frontmatter.layout === 'home'

	const publisher = { '@type': 'Organization', name: 'Frappe', url: 'https://frappe.io' }
	const app = {
		'@type': 'SoftwareApplication',
		name: siteName,
		applicationCategory: 'BusinessApplication',
		operatingSystem: 'Web',
		description: 'US sales tax for ERPNext, calculated by TaxJar and filed with AutoFile.',
	}
	// Search engines read the page type from JSON-LD: the home page describes the
	// site and the app, and each other page is an article about the app.
	const data = isHome
		? [{ '@type': 'WebSite', name: siteName, url: absolute(''), description, publisher, inLanguage: 'en-US' }, app]
		: [
				{
					'@type': 'TechArticle',
					headline: title,
					description,
					url,
					inLanguage: 'en-US',
					publisher,
					isPartOf: { '@type': 'WebSite', name: siteName, url: absolute('') },
					about: app,
				},
			]

	return [
		['link', { rel: 'canonical', href: url }],
		['meta', { property: 'og:type', content: isHome ? 'website' : 'article' }],
		['meta', { property: 'og:site_name', content: siteName }],
		['meta', { property: 'og:title', content: title }],
		['meta', { property: 'og:description', content: description }],
		['meta', { property: 'og:url', content: url }],
		['meta', { property: 'og:image', content: absolute(socialImage) }],
		['meta', { property: 'og:image:width', content: '1200' }],
		['meta', { property: 'og:image:height', content: '630' }],
		['meta', { name: 'twitter:card', content: 'summary_large_image' }],
		['script', { type: 'application/ld+json' }, JSON.stringify({ '@context': 'https://schema.org', '@graph': data })],
	]
}

// The Markdown of a page for AI agents: the title and the description, then the
// body. A video becomes a link, because the agent cannot play it.
function pageMarkdown(file: string) {
	const source = fs.readFileSync(file, 'utf8')
	const match = source.match(/^---\n([\s\S]*?)\n---\n/)
	const field = (name: string) => match?.[1].match(new RegExp(`^${name}: *"?(.*?)"?$`, 'm'))?.[1] ?? ''
	const body = (match ? source.slice(match[0].length) : source)
		.replace(/<YouTubeVideo\s([^>]*?)\/>/g, (_, attrs: string) => {
			const id = attrs.match(/\bid="([^"]+)"/)?.[1]
			const title = attrs.match(/\btitle="([^"]+)"/)?.[1] ?? 'Video'
			const start = attrs.match(/:start="(\d+)"/)?.[1]
			return `[Video: ${title}](https://www.youtube.com/watch?v=${id}${start ? `&t=${start}` : ''})`
		})
		.replace(/\]\(\/(?!\/)/g, `](${siteUrl}/`)
		.trim()
	return { description: field('description'), body }
}

// robots.txt, llms.txt, llms-full.txt and a .md copy of each page, in the
// sidebar order. llms.txt is the index that AI agents read first
// (https://llmstxt.org). llms-full.txt holds all the pages in one file.
export function writeDiscoveryFiles(siteConfig: SiteConfig, sidebar: SidebarGroup[], description: string) {
	const { outDir, srcDir } = siteConfig

	fs.writeFileSync(
		path.join(outDir, 'robots.txt'),
		siteUrl
			? `User-agent: *\nAllow: /\n\nSitemap: ${absolute('sitemap.xml')}\n`
			: 'User-agent: *\nDisallow: /\n',
	)

	const index = [`# ${siteName}`, '', `> ${description}`, '']
	const full = [`# ${siteName}`, '', `> ${description}`, '']
	for (const group of sidebar) {
		index.push(`## ${group.text}`, '')
		for (const item of group.items) {
			const page = pageMarkdown(path.join(srcDir, `${item.link}.md`))
			const copy = `${item.link.replace(/^\//, '')}.md`
			fs.mkdirSync(path.dirname(path.join(outDir, copy)), { recursive: true })
			fs.writeFileSync(path.join(outDir, copy), `> ${page.description}\n\n${page.body}\n`)
			index.push(`- [${item.text}](${siteUrl ? absolute(copy) : copy}): ${page.description}`)
			full.push('---', '', `Source: ${siteUrl ? absolute(item.link) : item.link}`, '', page.body, '')
		}
		index.push('')
	}
	fs.writeFileSync(path.join(outDir, 'llms.txt'), index.join('\n'))
	fs.writeFileSync(path.join(outDir, 'llms-full.txt'), full.join('\n'))
}
