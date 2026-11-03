import DefaultTheme from 'vitepress/theme'
import { getScrollOffset, type Theme } from 'vitepress'
import { enhanceAppWithTabs } from 'vitepress-plugin-tabs/client'
import YouTubeVideo from './YouTubeVideo.vue'
import './custom.css'

// A link to a step of a collapsible {.steps} rail opens that step. The id is
// on the step heading inside the row.
function openStep(id: string) {
	document.getElementById(id)?.closest('ol.steps details')?.setAttribute('open', '')
}

// VitePress scrolls to the #section before the screenshots above it load.
// They have no fixed size, so they push the section down. Scroll again after
// they load. Lazy images load only when visible, so they are not waited for.
function scrollToHashAfterImages() {
	const id = decodeURIComponent(location.hash.slice(1))
	if (!id) return
	openStep(id)
	const pending = [...document.querySelectorAll<HTMLImageElement>('.vp-doc img')].filter(
		(img) => !img.complete && img.loading !== 'lazy',
	)
	const loaded = pending.map(
		(img) =>
			new Promise((resolve) => {
				img.addEventListener('load', resolve, { once: true })
				img.addEventListener('error', resolve, { once: true })
			}),
	)
	Promise.all(loaded).then(() => {
		const target = document.getElementById(id)
		if (!target) return
		// The same position as VitePress: below the top bar.
		const padding = parseInt(getComputedStyle(target).paddingTop, 10)
		const top = window.scrollY + target.getBoundingClientRect().top - getScrollOffset() + padding
		window.scrollTo(0, top)
	})
}

export default {
	extends: DefaultTheme,
	enhanceApp({ app, router }) {
		app.component('YouTubeVideo', YouTubeVideo)
		enhanceAppWithTabs(app)
		if (typeof window !== 'undefined') {
			router.onAfterRouteChange = () => requestAnimationFrame(scrollToHashAfterImages)
			// A click on a link on the same page, for example in the outline, does not
			// change the route. Open the step after VitePress updates the address.
			document.addEventListener('click', (event) => {
				if (!(event.target as Element).closest?.('a[href*="#"]')) return
				setTimeout(() => openStep(decodeURIComponent(location.hash.slice(1))))
			})
		}
	},
} satisfies Theme
