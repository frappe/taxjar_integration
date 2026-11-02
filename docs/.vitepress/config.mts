import { defineConfig } from 'vitepress'
import { tabsMarkdownPlugin } from 'vitepress-plugin-tabs'
import { withMermaid } from 'vitepress-plugin-mermaid'
import { base, pageHead, siteUrl, writeDiscoveryFiles } from './seo'

const description = 'US sales tax for ERPNext, calculated by TaxJar and filed with AutoFile.'

// The sidebar follows the reader's journey: start, setting up, sales tax, transaction sync, sales adjustments,
// tax exemptions, tax return filing, troubleshoot. Reference pages come last.
const sidebar = [
	{
		text: 'Getting Started',
		items: [
			{ text: 'Introduction', link: '/start/overview' },
			{ text: 'Walkthrough', link: '/start/walkthrough' },
			{ text: 'Installation', link: '/start/installation' },
		],
	},
	{
		text: 'Setting Up',
		items: [
			{ text: 'Guided Setup', link: '/setup/guided-setup' },
			{ text: 'Roles & Permissions', link: '/setup/access' },
			{ text: 'Updating your nexus', link: '/setup/nexus' },
			{ text: 'Address Validation', link: '/setup/address-validation' },
			{ text: 'Before you go live', link: '/setup/go-live' },
		],
	},
	{
		text: 'Sales Tax',
		items: [
			{ text: 'Tax Computation', link: '/sell/how-tax-is-calculated' },
			{ text: 'Verify Tax Applicability', link: '/sell/check-the-tax' },
			{ text: 'Additional Charges & Discounts', link: '/sell/extra-charges' },
			{ text: 'Print Format', link: '/sell/print' },
		],
	},
	{
		text: 'Transaction Sync',
		items: [
			{ text: 'Syncing to TaxJar', link: '/invoice/how-sync-works' },
			{ text: 'Resolve Failed Syncs', link: '/file/fix-failed-syncs' },
		],
	},
	{
		text: 'Sales Adjustments',
		items: [
			{ text: 'Credit & Debit Notes', link: '/invoice/credit-and-debit-notes' },
			{ text: 'Cancellations & Amendments', link: '/invoice/cancel-or-correct' },
		],
	},
	{
		text: 'Tax Exemptions',
		items: [
			{ text: 'Customer Tax Exemption', link: '/sell/exempt-customers' },
			{ text: 'Transaction Tax Exemption', link: '/sell/exempt-a-sale' },
			{ text: 'Item Tax Exemption', link: '/setup/product-tax-categories' },
		],
	},
	{
		text: 'Tax Return Filing',
		items: [
			{ text: 'Period Close & Filing', link: '/file/close-a-period' },
		],
	},
	{
		text: 'Troubleshoot',
		items: [
			{ text: 'No Sales Tax on a Document', link: '/help/no-sales-tax' },
			{ text: 'Messages & Errors', link: '/help/messages' },
			{ text: 'API Log', link: '/help/api-log' },
		],
	},
	{
		text: 'Reference',
		collapsed: true,
		items: [
			{ text: 'Scheduled Jobs', link: '/reference/scheduled-jobs' },
			{ text: 'TaxJar Pages & Settings', link: '/reference/screens' },
			{ text: 'Upgrade from Version 15', link: '/setup/upgrade-from-v15' },
			{ text: 'Usage Data & Feedback', link: '/reference/usage-data' },
			{ text: 'Glossary', link: '/reference/glossary' },
		],
	},
]

// withMermaid draws ```mermaid code blocks as diagrams.
export default withMermaid(defineConfig({
	srcDir: 'src',
	// Parts are included into pages. They are not pages.
	srcExclude: ['parts/**'],
	title: 'TaxJar Integration',
	// Search results show about 60 characters of a title. The suffix holds the two
	// words that people search with. scripts/lint.py reads it to check the length.
	titleTemplate: ':title | TaxJar for ERPNext',
	description,
	lang: 'en-US',
	base,
	cleanUrls: true,
	lastUpdated: false,
	// Search and discovery: see seo.ts. The sitemap needs the public address.
	sitemap: siteUrl ? { hostname: `${siteUrl}/` } : undefined,
	transformHead: ({ pageData }) => pageHead(pageData),
	buildEnd: (siteConfig) => writeDiscoveryFiles(siteConfig, sidebar, description),
	// Content tabs: :::tabs with == Live and == Sandbox.
	markdown: {
		config(md) {
			md.use(tabsMarkdownPlugin)
		},
	},
	head: [['link', { rel: 'icon', type: 'image/png', href: `${base}logo.png` }]],
	themeConfig: {
		logo: '/logo.png',
		nav: [
			{ text: 'Setting Up', link: '/setup/guided-setup' },
			{ text: 'Troubleshoot', link: '/help/messages' },
		],
		sidebar,
		outline: { level: [2, 3], label: 'On this page' },
		search: { provider: 'local' },
		docFooter: { prev: 'Previous', next: 'Next' },
		footer: {
			message: 'For the TaxJar Integration app for ERPNext version 16.',
		},
	},
	vite: {
		// Mermaid 11 uses fastdom, an old-style module. The Mermaid plugin does not
		// pre-bundle it, so the dev server cannot load it without this line.
		optimizeDeps: { include: ['mermaid > fastdom', 'mermaid > fastdom/extensions/fastdom-promised.js'] },
	},
}))
