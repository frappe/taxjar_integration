<script setup lang="ts">
// A facade, as in the TaxJar Setup page: one thumbnail from i.ytimg.com, and
// nothing from YouTube loads until the reader clicks play. Then the player
// loads from youtube-nocookie.com.
import { ref } from 'vue'
import { withBase } from 'vitepress'

// start and end: the seconds to play from and to, to show one part of a
// longer video. thumbnail: a site image for that part, because YouTube has
// one thumbnail for the whole video.
const props = defineProps<{ id: string; title: string; start?: number; end?: number; thumbnail?: string }>()

const playing = ref(false)
// maxresdefault exists only for videos uploaded above 720p. hqdefault exists
// for every video.
const thumb = ref(props.thumbnail ? withBase(props.thumbnail) : `https://i.ytimg.com/vi/${encodeURIComponent(props.id)}/maxresdefault.jpg`)

function useFallbackThumb() {
	thumb.value = `https://i.ytimg.com/vi/${encodeURIComponent(props.id)}/hqdefault.jpg`
}

const src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(props.id)}?autoplay=1&rel=0&cc_load_policy=1${props.start ? `&start=${Math.floor(props.start)}` : ''}${props.end ? `&end=${Math.ceil(props.end)}` : ''}`
</script>

<template>
	<figure class="yt">
		<div class="yt-frame">
			<iframe
				v-if="playing"
				:src="src"
				:title="title"
				allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
				referrerpolicy="strict-origin-when-cross-origin"
				allowfullscreen
			/>
			<button v-else type="button" class="yt-play" :aria-label="`Play the video: ${title}`" @click="playing = true">
				<img :src="thumb" alt="" loading="lazy" @error="useFallbackThumb" />
				<span class="yt-mark" aria-hidden="true">
					<svg viewBox="0 0 68 48"><path d="M66.5 7.7A8.5 8.5 0 0 0 60.5 1.7C55.2.3 34 .3 34 .3s-21.2 0-26.5 1.4A8.5 8.5 0 0 0 1.5 7.7C.1 13 .1 24 .1 24s0 11 1.4 16.3a8.5 8.5 0 0 0 6 6c5.3 1.4 26.5 1.4 26.5 1.4s21.2 0 26.5-1.4a8.5 8.5 0 0 0 6-6C67.9 35 67.9 24 67.9 24s0-11-1.4-16.3Z" fill="#f00"/><path d="M45 24 27 14v20z" fill="#fff"/></svg>
				</span>
			</button>
		</div>
	</figure>
</template>

<style scoped>
.yt {
	margin: 16px 0 24px;
}
.yt-frame {
	position: relative;
	aspect-ratio: 16 / 9;
	border: 1px solid var(--vp-c-divider);
	border-radius: 8px;
	overflow: hidden;
	background: var(--vp-c-bg-soft);
}
.yt-frame iframe,
.yt-play {
	position: absolute;
	inset: 0;
	width: 100%;
	height: 100%;
	border: 0;
	padding: 0;
	cursor: pointer;
	background: none;
}
.vp-doc .yt-play img {
	width: 100%;
	height: 100%;
	object-fit: cover;
	margin: 0;
	border: 0;
	border-radius: 0;
}
/* In a corner, not the center: the video thumbnails put their title in the
   center. */
.yt-mark {
	position: absolute;
	left: 16px;
	bottom: 16px;
	width: 68px;
	height: 48px;
	transition: transform 0.15s;
}
.yt-play:hover .yt-mark,
.yt-play:focus-visible .yt-mark {
	transform: scale(1.1);
}
.yt-play:focus-visible {
	outline: 2px solid var(--vp-c-brand-1);
	outline-offset: -2px;
}
</style>
