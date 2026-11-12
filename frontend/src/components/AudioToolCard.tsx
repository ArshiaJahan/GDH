import { AudioLines } from "lucide-react";
import { useEffect, useState } from "react";
import { get } from "../lib/api";
import type { Block } from "../lib/store";
import { AudioPlayer } from "./AudioPlayer";
import { GenericToolCall } from "./Chat";
import { toolRenderers } from "./toolRenderers";

/** Inline player for ElevenLabs outputs in the chat. */
function AudioToolCard({ b, result }: { b: Block; result?: Block }) {
  const text: string = result?.content?.[0]?.text ?? "";
  const itemId = (text.match(/\bitm_[0-9a-f]{16}\b/) ?? [])[0];
  const [item, setItem] = useState<any>(null);
  useEffect(() => { if (itemId) get(`/items/${itemId}`).then(setItem).catch(() => {}); }, [itemId]);
  if (!result || result.is_error || !item) return <GenericToolCall b={b} result={result} />;
  const label = { tts: "Speech", sound_effect: "Sound effect", music: "Music" }[b.name as string] ?? b.name;
  return (
    <div className="my-2">
      <div className="flex items-center gap-1.5 text-[12px] text-muted mb-1">
        <AudioLines size={13} style={{ color: "var(--eleven)" }} />{label} · {item.meta?.voice ? `${item.meta.voice} · ` : ""}{item.model} · {Math.round(item.meta?.credits ?? 0)} credits
      </div>
      <AudioPlayer path={item.path} />
      {b.name === "tts" && <div className="text-[12.5px] text-muted mt-1 line-clamp-2">{b.input.text}</div>}
    </div>
  );
}

toolRenderers.tts = AudioToolCard;
toolRenderers.sound_effect = AudioToolCard;
toolRenderers.music = AudioToolCard;
