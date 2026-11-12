import { Download, Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { fileUrl } from "../lib/api";
import { downloadPath } from "../lib/native";

export type AudioPlayerHandle = { seek: (s: number) => void };

/** Waveform player. `onTime` lets a transcript highlight the current word. */
export function AudioPlayer({ path, src, height = 44, onTime, seekRef, compact }: {
  path?: string; src?: string; height?: number; onTime?: (t: number) => void;
  seekRef?: React.MutableRefObject<AudioPlayerHandle | null>; compact?: boolean;
}) {
  const el = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(0);
  const url = src ?? (path ? fileUrl(path) : "");

  useEffect(() => {
    if (!el.current || !url) return;
    const css = getComputedStyle(document.documentElement);
    const w = WaveSurfer.create({
      container: el.current, height, url, barWidth: 2, barGap: 1, barRadius: 2, cursorWidth: 1,
      waveColor: css.getPropertyValue("--line").trim(), progressColor: css.getPropertyValue("--eleven").trim(),
      cursorColor: css.getPropertyValue("--text").trim(), normalize: true,
    });
    w.on("play", () => setPlaying(true));
    w.on("pause", () => setPlaying(false));
    w.on("finish", () => setPlaying(false));
    w.on("ready", (d) => setDur(d));
    w.on("timeupdate", (t) => { setTime(t); onTime?.(t); });
    ws.current = w;
    if (seekRef) seekRef.current = { seek: (s) => { w.setTime(s); w.play(); } };
    return () => { w.destroy(); ws.current = null; };
  }, [url, height]);

  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  return (
    <div className={`flex items-center gap-2 ${compact ? "" : "rounded-md border border-line surface-raised px-2 py-1.5"}`}>
      <button className="btn btn-ghost px-1.5 shrink-0" onClick={() => ws.current?.playPause()} aria-label={playing ? "Pause" : "Play"}>
        {playing ? <Pause size={15} /> : <Play size={15} />}
      </button>
      <div ref={el} className="flex-1 min-w-0" />
      <span className="text-[11.5px] text-muted tabular-nums shrink-0">{fmt(time)} / {fmt(dur)}</span>
      {path && <button className="btn btn-ghost px-1.5 shrink-0" onClick={() => downloadPath(path)} aria-label="Download" title="Download"><Download size={14} /></button>}
    </div>
  );
}
