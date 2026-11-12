# Platform specs and export presets

Read when choosing deliverables, before `export`, and when `qc` fails. Platform rules change; the sources are listed
per row. Defaults for this harness: **Steam master 1080p + YouTube + vertical 9:16 (Shorts/TikTok)**; X on request.

| Target | Frame | FPS | Video | Audio | Length / limits | Source |
|---|---|---|---|---|---|---|
| Steam store | 1920×1080 16:9 (4:3 accepted) | 30 or 60 | H.264, ≥ 5 Mbps (Adobe preset 20 Mbps), .mp4/.mov | AAC 192k, 44.1/48 kHz stereo | no cap; aim 45–90 s; poster 1920×1080 frame, no text | https://partner.steamgames.com/doc/store/trailer |
| YouTube | 1920×1080 (or 2160p) | as recorded | MP4, H.264 High, 2 B-frames, closed GOP = fps/2, CABAC, 4:2:0, faststart, BT.709; 1080p60 ≈ 12 Mbps | AAC-LC 48 kHz stereo 384k | — | https://support.google.com/youtube/answer/1722171 |
| YouTube Shorts | 9:16 or 1:1 | as recorded | same | same | ≤ 3 min (vertical/square is classified as a Short) | https://support.google.com/youtube/answer/15424877 |
| X | 1280×720 (1920×1080 for subscribed accounts), 720×1280 portrait | ≤ 60 | H.264 High, yuv420p, ≥ 5,000 kbps, no open GOP, progressive, aspect 1:3–3:1 | AAC-LC (not HE), mono/stereo, ≥ 128k | 0.5 s–20 min (default accounts) | https://docs.x.com/x-api/media/quickstart/best-practices |
| TikTok (ads spec; organic similar) | 9:16 ≥ 540×960 (1080×1920 used here), 16:9, 1:1 | — | .mp4/.mov, ≥ 516 kbps, ≤ 500 MB | — | ≤ 10 min; respect UI safe zones | https://ads.tiktok.com/help/article/video-ads-specifications |
| itch.io | — | — | embed a YouTube/Vimeo URL (no upload) | — | adds "Watch trailer" to the grid pop-over | https://itch.io/docs/creators/design |

House defaults (not platform rules): master loudness **−14 LUFS integrated, −1 dBTP**, LRA 11, for every target.
Captions: sidecar `.srt` where accepted (YouTube, X); burned in only on vertical cuts.

## What `trailer_edl.py export` runs
All exports start from `build/master.mov` (ProRes 422 HQ + PCM 48 kHz, already loudness-normalized). Common flags:
```
-vf scale=W:H:flags=lanczos,setsar=1,format=yuv420p      (neighbor when the EDL says scale_filter=neighbor)
-c:v libx264 -profile:v high -preset slow -crf C -maxrate M -bufsize B -pix_fmt yuv420p
-g <fps/2> -bf 2 -flags +cgop -colorspace bt709 -color_primaries bt709 -color_trc bt709
-c:a aac -b:a A -ar 48000 -ac 2 -movflags +faststart
```
| `--platform` | Output | W×H | C (crf) | M / B | A | Extras |
|---|---|---|---|---|---|---|
| `steam` | `exports/<id>-steam.mp4` | 1920×1080 | 16 | 24M / 48M | 192k | `exports/poster.png` (frame at `poster_at`) |
| `youtube` | `exports/<id>-youtube.mp4` | 1920×1080 | 16 | 16M / 32M | 384k | `exports/<id>.srt` (copy of captions.srt) |
| `x` | `exports/<id>-x.mp4` | 1920×1080 (1280×720 with `--x-720`) | 18 | 12M / 24M | 128k | `.srt`; fps capped at 60 |
| `shorts`, `tiktok` | `exports/<id>-<p>.mp4` | 1080×1920 | 18 | 16M / 32M | 192k | timeline re-rendered on a 9:16 canvas (not a crop of the master), captions burned |
| `loop` | `exports/<id>-loop.webm` + `.gif` | 640 / 480 wide | VP9 crf 34 | — | none | 8 s from `poster_at`, for press kits / store descriptions |

- `--encoder videotoolbox` swaps libx264 for `h264_videotoolbox -b:v <20M|16M|12M>` (faster, slightly larger files).
- `--x-720` exports `x` at 1280×720, the frame X lists for accounts without a subscription (`qc` accepts both sizes).
- Vertical cuts longer than `vertical.max_s` (default 60 s) are refused; pass `--max 180` or cut a `social` EDL.
- Vertical layout per clip: `vcrop: {"x": 0..1}` crops the 16:9 source around that horizontal focus (layout `crop`);
  otherwise `blurpad` (blurred, filled background + the whole 16:9 frame in the middle). Cards are fitted on their
  `bg`. Keep text out of the reserved areas: top 10 %, bottom 20 %, right 12 %.

## What `trailer_edl.py qc` checks (writes `review/qc.json`)
| Check | Fail | Warn |
|---|---|---|
| dimensions | not the platform's size | — |
| fps | > 60, ≠ EDL fps, Steam not 30/60 | — |
| codec / profile | not H.264 | not High |
| pix_fmt | not yuv420p | — |
| duration | > 1 frame off the EDL | — |
| audio | not AAC-LC 48 kHz stereo | — |
| faststart | moov after mdat | — |
| loudness | integrated more than 1 LU from the target | — |
| true peak | > target + 0.5 dB | > target (AAC overshoot) |
| black start | black in the first 2 s | — |
| freeze | — | picture frozen ≥ 2 s (end slates trigger it; judge) |
| flashes | — | > 3 large luma flashes in 1 s |
| hook rule (with `--edl`, `--beats`) | card first > 1 s, hook after 15 s | hook after 10 s |
