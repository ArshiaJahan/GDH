# Trailer craft

Read when writing the brief, the beat sheet, card copy or VO, and when judging a cut. Sources at the end.

## The order that works: Genre, HOOK, Anchors, Content
- Establish the **genre in 1–2 shots**, then the **hook** (what no other game in the genre does). The hook lands
  ideally within **10–15 s**, at the latest in the first third (and never after the first half). The harness rule:
  hook ≤ 10 s, hard fail > 15 s (`trailer_edl.py check --beats`).
- **Anchors** (features a genre fan expects: progression, bosses, builds) only after or interleaved with the hook.
- **Content** (breadth: biomes, enemies, items) last, as a fast montage. Never lead with content or with lore.

## Muted autoplay and the first seconds
- Steam's Discovery Queue gives a trailer **< 10 s** to make an impression, often **without sound**; social feeds
  autoplay muted. Every beat must read with the sound off (the Muted Scroller reviewer checks `first5.png`).
- **First frame = gameplay in motion**, from a section "after hours of play, not minutes". No studio logos, publisher
  idents, slow environment pans or full-screen ratings before the hook. A small rating bug on gameplay is fine
  (overlay), unless the rating board requires a full-screen card.
- Structure for a ~90 s general/social trailer: Thumbstopper 1–10 s (game loop, may end on title + CTA) → Intro
  10–15 s (basics, verbs) → Escalation ~40 s → Climax 20–30 s (breadth montage) → end slate.
- 30 s cutdowns are "a game loop or two" covering every key verb.

## Steam specifics
- Only the **first two trailers** show before screenshots. **Slot 1 = gameplay**, from the player's perspective, HUD
  visible is often good, gameplay-dense end to end: Steam's **microtrailer** is six 1-s clips auto-cut from the first
  trailer, so any second of it may be sampled. Slot 2 = story / feel / dev video.
- Trailers sell what screenshots can't: **game feel** (animation + SFX), story/voice, mood. Keep game SFX on.
- Custom poster = a **frame from the video**, 1920×1080, **avoid text** (`trailer_edl.py poster`).
- The game must be "consistent with your marketing materials" (Steam distribution agreement): **real gameplay only**.
  Never generated "footage". Generated music/VO/SFX are fine; list them in REPORT.md for the content survey.

## Templates
- **Simplest Steam trailer:** a gameplay montage — the loop, variety, clear shots, cut to music, end slate.
- **Tell, Show, Repeat:** genre shot → title card for a pillar → matching gameplay → repeat 3–5× → montage → slate.
  Easiest structure; the cards carry it, so write them about the **player fantasy** ("Show the dream, not the job"):
  "Every run rewrites the map" beats "PROCEDURAL LEVELS".

## Editing rules of thumb
- **Rule of threes:** three escalating shots per idea; the third is the payoff.
- **Waves of intensity:** build, release, build higher. The climax has the fastest cutting.
- **Cut on the music:** cuts on beats, big moments on downbeats (`beat_grid.py`, `check --grid`). One frame off is
  visible; the checker reports cuts more than `snap_tolerance_frames` off the grid.
- **Shot clarity:** one readable action per shot; the player character findable within 0.5 s; no cuts mid-motion
  that hide the result. Hold a shot until its payoff lands, not longer.
- **Freeze frames / speed ramps** (`freeze_end`, `speed`) for impact, sparingly. Slow-mo from the edit (speed 0.5)
  needs a 60 fps capture to stay smooth.
- **End slate 3–6 s** (social: last 2–3 s): logo + platform(s) + CTA ("Wishlist on Steam" / "Play the demo" /
  "Out now") + date if known.

## Card and on-screen text rules
- **≤ 7 words per card**, on screen **≥ 0.5 s + 0.33 s per word** (checked against beats.json).
- Big, high-contrast, in the game's own font (TrailerCards renders them with the project's TMP font asset).
- Cards don't open the trailer (a card first may last at most 1.0 s — EDL check).
- No feature-list bullets. Fantasy, verbs, stakes.

## Accessibility
- **Hand-made block captions** (not word-by-word), key SFX in brackets (`[explosion]`), ≤ 42 chars/line, ≤ 2 lines,
  1–6 s each (`trailer_edl.py srt`). Sidecar `.srt` for YouTube/X; burned-in on vertical cuts.
- On-screen text helps cognitive access; keep it on screen long enough to read twice.
- **No flashing**: no more than 3 large luma flashes per second (`qc` warns); seizure risk.

## Process
- Capture many takes; editing comes "in waves": rough cut to music → structure → polish → captions/mix.
- Keep a capture inventory (shots.json + report.json) so recaptures are one command.

## Sources
- Derek Lieu, hook: https://www.derek-lieu.com/blog/2022/10/24/how-to-hook-the-audience-and-how-quickly-to-do-it
- Derek Lieu, social: https://www.derek-lieu.com/blog/2023/2/12/how-to-optimize-a-game-trailer-for-social-media
- Derek Lieu, Steam: https://www.derek-lieu.com/blog/2023/5/8/how-to-optimize-your-steam-trailers-in-2023
- Derek Lieu, Tell Show Repeat: https://www.derek-lieu.com/blog/2023/4/9/tell-show-repeat-the-2nd-easiest-game-trailer-to-make
- Derek Lieu, creative brief: https://www.derek-lieu.com/blog/2024/9/2/how-to-make-a-creative-brief-for-a-game-trailer
- Derek Lieu, accessibility: https://www.derek-lieu.com/blog/2023/5/27/accessibility-considerations-for-game-trailers
- Derek Lieu, how-to index: https://www.derek-lieu.com/blog?category=How+to+Make+a+Trailer
- Steamworks trailers: https://partner.steamgames.com/doc/store/trailer
- Steam content survey: https://partner.steamgames.com/doc/gettingstarted/contentsurvey
