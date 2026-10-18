# VTuber Wallpapers

Run this from the folder:

```fish
./download-vtuber-wallpapers.py
```

It downloads up to 20 high-resolution, near-16:9 wallpapers from Danbooru into this directory. General, sensitive, and questionable posts are allowed; explicit posts are excluded. To choose a different limit:

```fish
./download-vtuber-wallpapers.py 50
```

The creator searches are the non-comment lines in `creators.txt`. Edit that file to add or remove creators.

`creators.txt` is also your rotation control. Comment out or remove a creator, then run the script: its wallpaper is renamed from (for example) `filian--danbooru-123.jpg` to `filian--danbooru-123.jpg.disabled`, which wallpaper tools will not treat as an image. Re-enable the creator and run the script again to download a fresh wallpaper; the disabled file remains as an archive. Each active creator has at most one image-extension wallpaper.

For active creators, each run checks for a newer qualifying Danbooru post. A newer image is downloaded and validated before the previous wallpaper is renamed to `.disabled`.

Files are named `<creator-tag>--danbooru-<post-id>.<extension>`, for example `sansin_jin--danbooru-12406344.png`, so they sort by creator. Existing files are never replaced. `.vtwall.sqlite3` records completed and failed downloads so rerunning is safe. The script uses Python's standard library only and needs Python 3.12 or newer.

To rename older `danbooru-<post-id>.<extension>` files once, using their Danbooru tags and `creators.txt`:

```fish
./download-vtuber-wallpapers.py --rename-existing
```

Optional Danbooru login, if you have one:

```fish
set -Ux DANBOORU_LOGIN your_login
set -Ux DANBOORU_API_KEY your_api_key
```

Downloads are for a personal collection; respect the artists' rights and Danbooru's API limits.
