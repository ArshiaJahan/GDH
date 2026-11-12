import { useRef, useState } from "react";
import { AudioPlayer, type AudioPlayerHandle } from "./AudioPlayer";

export type Word = { text: string; start: number; end: number; type?: string; speaker_id?: string | null };

/** 75.4 → "1:15"; an hour or more → "1:02:03". */
export function fmtStamp(s: number): string {
  const t = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = String(t % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

const PAUSE_S = 1.5;   // a silence this long starts a new segment
const MAX_WORDS = 60;  // long monologues split at the next sentence end after this many words

/** Segments: a new one on a speaker change, a long pause, or a sentence end in a long run. */
export function segments(words: Word[]): { speaker: string; start: number; words: Word[] }[] {
  const out: { speaker: string; start: number; words: Word[] }[] = [];
  let prev: Word | null = null;
  for (const w of words) {
    const sp = w.speaker_id ?? "";
    const cur = out.at(-1);
    const split = !cur || cur.speaker !== sp || (prev && w.start - prev.end >= PAUSE_S)
      || (cur.words.length >= MAX_WORDS && prev && /[.!?…]["')\]]?$/.test(prev.text.trim()));
    if (split) out.push({ speaker: sp, start: w.start, words: [] });
    out.at(-1)!.words.push(w);
    prev = w;
  }
  return out;
}

/** Speaker-labelled transcript with a mm:ss stamp per segment (and per word on hover).
 *  Clicking a stamp or a word seeks the player there; the word being spoken is highlighted. */
export function Transcript({ words, t, onSeek }: { words: Word[]; t: number; onSeek: (s: number) => void }) {
  return (
    <div className="rounded-md border border-line surface p-3 max-h-[420px] overflow-y-auto scroll-thin space-y-2 text-[13.5px] leading-7">
      {segments(words).map((b, i) => (
        <p key={i} className="flex gap-2">
          <span className="shrink-0 flex flex-col items-start w-[74px] pt-0.5 leading-5">
            <button className="font-mono text-[11.5px] text-muted hover:text-action tabular-nums" onClick={() => onSeek(b.start)}
              title={`Jump to ${fmtStamp(b.start)}`} aria-label={`Jump to ${fmtStamp(b.start)}`}>{fmtStamp(b.start)}</button>
            {b.speaker && <span className="label truncate max-w-full">{b.speaker.replace("speaker_", "Speaker ")}</span>}
          </span>
          <span className="min-w-0">
            {b.words.map((w, j) => (
              <span key={j} role="button" tabIndex={0} title={fmtStamp(w.start)} onClick={() => onSeek(w.start)} onKeyDown={(e) => e.key === "Enter" && onSeek(w.start)}
                className={`cursor-pointer rounded px-px ${t >= w.start && t < w.end ? "bg-[color-mix(in_srgb,var(--eleven)_30%,transparent)]" : "hover:bg-sunken"} ${w.type === "audio_event" ? "text-muted italic" : ""}`}>
                {w.text}{" "}
              </span>
            ))}
          </span>
        </p>
      ))}
    </div>
  );
}

/** Player plus transcript, wired for click-to-seek (Artifacts viewer, ElevenLabs history). */
export function TranscriptWithPlayer({ words, audioPath }: { words: Word[]; audioPath?: string | null }) {
  const [t, setT] = useState(0);
  const seek = useRef<AudioPlayerHandle | null>(null);
  return (
    <div className="space-y-2">
      {audioPath && <AudioPlayer path={audioPath} onTime={setT} seekRef={seek} />}
      <Transcript words={words} t={t} onSeek={(s) => seek.current?.seek(s)} />
    </div>
  );
}
