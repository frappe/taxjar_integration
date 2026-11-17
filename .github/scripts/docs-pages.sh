#!/usr/bin/env bash
# Publishes the docs to the gh-pages branch. GitHub Pages serves that branch.
#
#   docs-pages.sh deploy-root <build folder>           the public docs
#   docs-pages.sh deploy-preview <build folder> <PR>   the preview of a pull request
#   docs-pages.sh remove-preview <PR>                  delete that preview
#
# DOCS_URL is the public address of the docs, for example
# https://regional.frappe.io/usa/sales-tax. The domain goes into the CNAME file,
# and the path is the folder of the docs on the branch:
#
#   usa/sales-tax/                   the public docs
#   usa/sales-tax/pr-preview/pr-7/   the preview of pull request 7
#
# Each command changes only its own folder, so the public docs and the previews
# do not delete each other. Run it from a checkout of the repository that can
# push to origin.
set -euo pipefail

BRANCH="gh-pages"

: "${DOCS_URL:?Set DOCS_URL, for example https://regional.frappe.io/usa/sales-tax}"
address="${DOCS_URL#*://}"
address="${address%/}"
DOMAIN="${address%%/*}"
DOCS_PATH="${address#*/}"
if [ "$DOCS_PATH" = "$address" ] || [ -z "$DOCS_PATH" ]; then
	echo "DOCS_URL must have a path, for example /usa/sales-tax." >&2
	exit 1
fi

usage() {
	sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//' >&2
	exit 1
}

need_build() {
	if [ ! -f "$1/index.html" ]; then
		echo "$1 is not a docs build: it has no index.html." >&2
		exit 1
	fi
}

need_number() {
	if ! [[ "$1" =~ ^[0-9]+$ ]]; then
		echo "The pull request must be a number, not '$1'." >&2
		exit 1
	fi
}

site="$(mktemp -d)"

# Checks out the newest gh-pages into $site. The first deploy has no branch
# yet, so it starts an empty one.
open_site() {
	if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
		git fetch --quiet --depth 1 origin "$BRANCH"
		git worktree add --quiet --force -B "$BRANCH" "$site" FETCH_HEAD
	else
		git worktree add --quiet --detach "$site"
		git -C "$site" checkout --quiet --orphan "$BRANCH"
		git -C "$site" rm -rf --quiet .
	fi
}

close_site() {
	git worktree remove --force "$site"
	git branch --quiet -D "$BRANCH" 2>/dev/null || true
}

put_root() {
	mkdir -p "$site/$DOCS_PATH"
	# --delete removes the pages that the docs no longer have. The previews
	# are in the same folder, so they are excluded.
	rsync -a --delete --exclude '/pr-preview/' "$build/" "$site/$DOCS_PATH/"
	# The root of the domain gets only what a browser or a search engine asks
	# the root for: a redirect to the docs, the 404 page and robots.txt.
	cp "$build/404.html" "$site/404.html"
	cp "$build/robots.txt" "$site/robots.txt"
	cat > "$site/index.html" <<HTML
<!doctype html>
<meta charset="utf-8">
<title>Frappe Regional</title>
<link rel="canonical" href="https://$DOMAIN/$DOCS_PATH/">
<meta http-equiv="refresh" content="0; url=/$DOCS_PATH/">
<a href="/$DOCS_PATH/">US sales tax for ERPNext</a>
HTML
}

put_preview() {
	mkdir -p "$site/$DOCS_PATH/pr-preview/pr-$number"
	rsync -a --delete "$build/" "$site/$DOCS_PATH/pr-preview/pr-$number/"
}

drop_preview() {
	rm -rf "$site/$DOCS_PATH/pr-preview/pr-$number"
}

# Makes the change on the newest gh-pages and pushes it. Two deploys can push
# at the same time, for example two previews. The second push fails, and it
# makes its change again on the new branch.
publish() {
	local message="$1" change="$2" attempt
	for attempt in 1 2 3 4 5; do
		open_site
		"$change"
		# .nojekyll: Pages must serve the files as they are. CNAME: the domain.
		touch "$site/.nojekyll"
		echo "$DOMAIN" > "$site/CNAME"
		git -C "$site" add --all
		if git -C "$site" diff --cached --quiet; then
			echo "Nothing to publish."
			close_site
			return 0
		fi
		git -C "$site" -c user.name="github-actions[bot]" \
			-c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
			commit --quiet -m "$message"
		if git -C "$site" push --quiet origin "HEAD:refs/heads/$BRANCH"; then
			close_site
			return 0
		fi
		echo "A different deploy pushed first. Attempt $attempt of 5 failed."
		close_site
		sleep $((attempt * 3))
	done
	echo "Could not push to $BRANCH." >&2
	return 1
}

case "${1:-}" in
	deploy-root)
		[ $# -eq 2 ] || usage
		build="$2"
		need_build "$build"
		publish "docs: deploy ${GITHUB_SHA:-a local build}" put_root
		;;
	deploy-preview)
		[ $# -eq 3 ] || usage
		build="$2" number="$3"
		need_build "$build"
		need_number "$number"
		publish "docs: preview of pull request $number" put_preview
		;;
	remove-preview)
		[ $# -eq 2 ] || usage
		number="$2"
		need_number "$number"
		publish "docs: remove the preview of pull request $number" drop_preview
		;;
	*)
		usage
		;;
esac
