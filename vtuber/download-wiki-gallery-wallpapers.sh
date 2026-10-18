#!/usr/bin/env bash

set -euo pipefail

readonly TARGET_DIR="$(dirname "${BASH_SOURCE[0]}")"
readonly PROFILE_FILE="$TARGET_DIR/wiki-profiles.tsv"
readonly COMPLETED_FILE="$TARGET_DIR/downloaded-creators.txt"
readonly WIKI_API_URL="https://virtualyoutuber.fandom.com/api.php"
readonly USER_AGENT="Mozilla/5.0"
readonly DEFAULT_COUNT=20

count="${1:-$DEFAULT_COUNT}"
if ! [[ "$count" =~ ^[1-9][0-9]*$ ]]; then
    printf 'Usage: %s [positive image count]\n' "${0##*/}" >&2
    exit 2
fi

for command in curl file identify jq mktemp shuf; do
    if ! command -v "$command" >/dev/null; then
        printf 'Missing required command: %s\n' "$command" >&2
        exit 1
    fi
done

declare -A completed_creators
while IFS= read -r creator || [[ -n "$creator" ]]; do
    [[ -z "$creator" || "${creator:0:1}" == '#' ]] && continue
    completed_creators["$creator"]=1
done < "$COMPLETED_FILE"

downloaded=0
while IFS=$'\t' read -r creator profile || [[ -n "$creator" ]]; do
    [[ -z "$creator" || "${creator:0:1}" == '#' ]] && continue
    ((downloaded < count)) || break
    [[ -z "${completed_creators[$creator]+present}" ]] || continue

    response="$(curl --fail --silent --show-error --location --get "$WIKI_API_URL" \
        --user-agent "$USER_AGENT" \
        --data-urlencode 'action=query' \
        --data-urlencode 'generator=images' \
        --data-urlencode "titles=$profile/Gallery" \
        --data-urlencode 'prop=imageinfo' \
        --data-urlencode 'iiprop=url|size' \
        --data-urlencode 'gimlimit=max' \
        --data-urlencode 'format=json')" || continue

    entries="$(jq -r '.query.pages[]? | select(.imageinfo[0]? != null) | select(.imageinfo[0].width >= 1920 and .imageinfo[0].height >= 1080 and .imageinfo[0].width * 9 == .imageinfo[0].height * 16) | [(.pageid | tostring), .imageinfo[0].url, (.title | sub("^File:"; ""))] | @tsv' <<<"$response" | shuf)"
    while IFS=$'\t' read -r id url filename; do
        [[ -n "$id" ]] || continue

        extension="${filename##*.}"
        destination="$TARGET_DIR/vtwiki-$id.$extension"
        [[ -e "$destination" ]] && continue

        temporary="$(mktemp "$TARGET_DIR/.vtwiki-$id.XXXXXX")"
        if ! curl --fail --silent --show-error --location --user-agent "$USER_AGENT" \
            --referer "https://virtualyoutuber.fandom.com/wiki/${profile// /_}/Gallery" \
            --output "$temporary" "$url"; then
            rm -f "$temporary"
            continue
        fi

        mime_type="$(file --brief --mime-type "$temporary")"
        dimensions="$(identify -format '%w %h' "$temporary" 2>/dev/null || true)"
        read -r width height <<<"$dimensions"
        if [[ "$mime_type" != image/* ]] || [[ ! "$width" =~ ^[0-9]+$ ]] ||
            [[ ! "$height" =~ ^[0-9]+$ ]] || ((width < 1920 || height < 1080)) ||
            ((width * 9 != height * 16)); then
            rm -f "$temporary"
            continue
        fi

        mv "$temporary" "$destination"
        printf '%s\n' "$creator" >> "$COMPLETED_FILE"
        completed_creators["$creator"]=1
        printf 'Downloaded %s for %s (%sx%s)\n' \
            "${destination##*/}" "$creator" "$width" "$height"
        ((downloaded += 1))
        break
    done <<<"$entries"
done < "$PROFILE_FILE"

printf 'Complete: %d downloaded, directory: %s\n' "$downloaded" "$TARGET_DIR"
