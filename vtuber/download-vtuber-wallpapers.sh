#!/usr/bin/env bash

set -euo pipefail

readonly TARGET_DIR="$(dirname "${BASH_SOURCE[0]}")"
readonly CREATOR_FILE="$TARGET_DIR/creators.txt"
readonly COMPLETED_FILE="$TARGET_DIR/downloaded-creators.txt"
readonly SAFEBOORU_API_URL="https://safebooru.org/index.php"
readonly DANBOORU_API_URL="https://danbooru.donmai.us/posts.json"
readonly USER_AGENT="vtuber-wallpaper-downloader/1.0"
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

mkdir -p "$TARGET_DIR"
creators=()
while IFS= read -r creator || [[ -n "$creator" ]]; do
    [[ -z "$creator" || "${creator:0:1}" == '#' ]] && continue
    creators+=("$creator")
done < "$CREATOR_FILE"

if ((${#creators[@]} == 0)); then
    printf 'No creator queries found in %s\n' "$CREATOR_FILE" >&2
    exit 1
fi

declare -A completed_creators
if [[ -f "$COMPLETED_FILE" ]]; then
    while IFS= read -r creator || [[ -n "$creator" ]]; do
        [[ -z "$creator" || "${creator:0:1}" == '#' ]] && continue
        completed_creators["$creator"]=1
    done < "$COMPLETED_FILE"
fi

if ((count > ${#creators[@]})); then
    printf 'Limiting this run to %d creators to avoid duplicates.\n' "${#creators[@]}"
    count="${#creators[@]}"
fi

downloaded=0
skipped=0

while ((downloaded < count)); do
    round_downloaded=0
    while IFS= read -r creator; do
        ((downloaded < count)) || break
        [[ -z "${completed_creators[$creator]+present}" ]] || continue

        entries=""
        if response="$(curl --fail --silent --show-error --location --get "$SAFEBOORU_API_URL" \
            --user-agent "$USER_AGENT" \
            --data-urlencode 'page=dapi' \
            --data-urlencode 's=post' \
            --data-urlencode 'q=index' \
            --data-urlencode 'json=1' \
            --data-urlencode 'limit=20' \
            --data-urlencode "tags=$creator")"; then
            entries="$(jq -r '.[]? | select(.file_url != null) | select(.width >= 1920 and .height >= 1080 and .width * 9 == .height * 16) | select(((.tags // "") | test("(^| )(1boy|2boys|3boys|multiple_boys)( |$)")) | not) | ["safebooru", (.id | tostring), .file_url] | @tsv' <<<"$response" | shuf)"
        fi

        if [[ -z "$entries" ]] && response="$(curl --fail --silent --show-error --location --get "$DANBOORU_API_URL" \
            --user-agent "$USER_AGENT" \
            --data-urlencode "tags=$creator ratio:16:9 width:>=1920 height:>=1080 order:random" \
            --data-urlencode 'limit=20')"; then
            entries="$(jq -r '.[]? | select(.file_url != null) | select((.tag_string_general | test("(^| )(1boy|2boys|3boys|multiple_boys)( |$)")) | not) | ["danbooru", (.id | tostring), .file_url] | @tsv' <<<"$response" | shuf)"
        fi

        while IFS=$'\t' read -r source id url; do
            [[ -n "$id" ]] || continue

            extension="${url%%\?*}"
            extension="${extension##*.}"
            destination="$TARGET_DIR/$source-$id.$extension"
            if [[ -e "$destination" ]]; then
                ((skipped += 1))
                continue
            fi

            temporary="$(mktemp "$TARGET_DIR/.$source-$id.XXXXXX")"
            if ! curl --fail --silent --show-error --location --user-agent "$USER_AGENT" \
                --output "$temporary" "$url"; then
                rm -f "$temporary"
                printf 'Could not download %s\n' "$url" >&2
                continue
            fi

            mime_type="$(file --brief --mime-type "$temporary")"
            dimensions="$(identify -format '%w %h' "$temporary" 2>/dev/null || true)"
            read -r width height <<<"$dimensions"
            if [[ "$mime_type" != image/* ]] || [[ ! "$width" =~ ^[0-9]+$ ]] ||
                [[ ! "$height" =~ ^[0-9]+$ ]] || ((width < 1920 || height < 1080)) ||
                ((width * 9 != height * 16)); then
                rm -f "$temporary"
                printf 'Rejected invalid or undersized image: %s\n' "$url" >&2
                continue
            fi

            mv "$temporary" "$destination"
            printf 'Downloaded %s for %s (%sx%s)\n' \
                "${destination##*/}" "$creator" "$width" "$height"
            printf '%s\n' "$creator" >> "$COMPLETED_FILE"
            completed_creators["$creator"]=1
            ((downloaded += 1))
            ((round_downloaded += 1))
            break
        done <<<"$entries"
    done < <(printf '%s\n' "${creators[@]}" | shuf)

    # A batch has at most one wallpaper per configured creator.
    break
done

printf 'Complete: %d downloaded, %d already present, directory: %s\n' \
    "$downloaded" "$skipped" "$TARGET_DIR"
