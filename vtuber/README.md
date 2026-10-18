# VTuber Wallpapers

This directory is populated by `download-vtuber-wallpapers.sh`. Its balanced
creator roster is in `creators.txt`.

The script queries Safebooru first and falls back to Danbooru for the configured
female creator tags. It excludes common male-character tags, requires 16:9
images at a minimum resolution of 1920x1080, and downloads full image URLs from
the public APIs. It accepts native 16:9 images only and validates the image
format and dimensions before keeping each file.
Each round shuffles the roster and downloads at most one image per creator,
which avoids a single popular agency dominating the collection. A run is capped
at the roster size so it never cycles through creators to satisfy a larger count.
`downloaded-creators.txt` keeps that one-per-creator rule across reruns and
across both image sources.

`download-wiki-gallery-wallpapers.sh` checks native 16:9 originals from the
Virtual YouTuber Wiki galleries listed in `wiki-profiles.tsv`.

Run from this directory:

```bash
./download-vtuber-wallpapers.sh
```

Pass a count to download more images, for example:

```bash
./download-vtuber-wallpapers.sh 40
```

Rerunning it does not replace files already present. Image filenames include the
source and post ID. Visit `https://safebooru.org/index.php?page=post&s=view&id=<id>`
or `https://danbooru.donmai.us/posts/<id>` for attribution where available.

Add or remove lines in `creators.txt` to tune the collection. Blank
lines and lines beginning with `#` are ignored.
