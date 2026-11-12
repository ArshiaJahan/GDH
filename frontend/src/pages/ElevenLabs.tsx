import { ExternalLink, Mic, Play, Send, Square, Star, Upload } from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { get, post, upload } from "../lib/api";
import { actions, sessionProfile, useStore } from "../lib/store";
import { AudioPlayer, type AudioPlayerHandle } from "../components/AudioPlayer";
import { Transcript, TranscriptWithPlayer } from "../components/Transcript";
import { Empty, fmtAgo } from "../components/ui";

type Voice = { voice_id: string; name: string; category?: string; labels?: Record<string, string>; preview_url?: string; description?: string; public_owner_id?: string; shared?: boolean };
type Section = "tts" | "stt" | "sfx" | "music" | "voice_changer" | "voices" | "history";

const SECTIONS: { id: Section; label: string; feature?: string }[] = [
  { id: "tts", label: "Text to speech", feature: "tts" },
  { id: "stt", label: "Speech to text", feature: "stt" },
  { id: "sfx", label: "Sound effects", feature: "sfx" },
  { id: "music", label: "Music", feature: "music" },
  { id: "voice_changer", label: "Voice changer", feature: "voice_changer" },
  { id: "voices", label: "Voices" },
  { id: "history", label: "History" },
];
const FORMATS = ["mp3_44100_128", "mp3_44100_192", "mp3_22050_32", "wav_44100", "opus_48000_128"];

function useSessionTarget() {
  const sessions = useStore((s) => s.sessions);
  const currentId = useStore((s) => s.currentId);
  return { sessions, currentId };
}

/** The ElevenLabs profile this page uses (its picker; defaults to the open session's profile). */
const ProfileCtx = createContext<string | undefined>(undefined);
/** Who a generation is for: the open session and the page's profile. */
function useTarget() {
  const profile = useContext(ProfileCtx);
  return () => ({ session_id: useStore.getState().currentId, profile });
}

async function sendItemToChat(itemId: string) {
  const sid = useStore.getState().currentId;
  if (!sid) return actions.toast("Open a session first.", "error");
  const r = await post(`/items/${itemId}/send`, { target: "chat", session_id: sid });
  actions.attachToChat(sid, r.attachment, r.warning);
}

export function ElevenLabsPage() {
  const [status, setStatus] = useState<any>(null);
  const [section, setSection] = useState<Section>("tts");
  const [voices, setVoices] = useState<Voice[]>([]);
  const [models, setModels] = useState<any[]>([]);
  const [favs, setFavs] = useState<string[]>([]);
  const profiles: string[] = useStore((s) => s.appState?.accounts?.elevenlabs) ?? ["default"];
  const session = useStore((s) => s.sessions.find((x) => x.id === s.currentId));
  const [picked, setPicked] = useState<string | null>(null);
  const profile = picked && profiles.includes(picked) ? picked : session ? sessionProfile(session, "elevenlabs", profiles) : profiles[0];

  // `alive` drops responses for a profile the picker has already left (A → B → A quickly must not
  // end up showing B's voices or quota).
  const load = async (alive: () => boolean = () => true) => {
    const q = `profile=${encodeURIComponent(profile)}`;
    const st = await get(`/elevenlabs/status?${q}`);
    if (!alive()) return;
    setStatus(st);
    if (st.has_key && st.status === "online") {
      get<Voice[]>(`/elevenlabs/voices?${q}`).then((v) => { if (alive()) setVoices(v); }).catch((e) => { if (alive()) actions.toast(e.message, "error"); });
      get<any[]>(`/elevenlabs/models?${q}`).then((m) => { if (alive()) setModels(m.filter((x) => x.can_do_text_to_speech)); }).catch(() => {});
      get<string[]>("/elevenlabs/favorites").then((f) => { if (alive()) setFavs(f); });
    } else {
      setVoices([]);
      setModels([]);
    }
  };
  useEffect(() => {
    let alive = true;
    load(() => alive).catch(() => {});
    return () => { alive = false; };
  }, [profile]);
  // The quota is re-read a few seconds after each generation; keep the bar current for this profile.
  useEffect(() => actions.onEvent((e) => {
    if (e.type !== "elevenlabs.quota" || e.data?.profile !== profile) return;
    setStatus((s: any) => s && { ...s, subscription: e.data.subscription, subscription_checked_at: e.data.checked_at });
  }), [profile]);
  const picker = profiles.length > 1 && (
    <label className="flex items-center gap-2 text-[13px] text-muted">Account
      <select className="input py-0.5 w-auto" value={profile} onChange={(e) => setPicked(e.target.value)} aria-label="ElevenLabs account profile">
        {profiles.map((p) => <option key={p}>{p}</option>)}
      </select>
    </label>
  );

  const feats = status?.features ?? {};
  const shown = SECTIONS.filter((s) => !s.feature || feats[s.feature] !== false);
  const sub = status?.subscription;

  if (status && !status.has_key) {
    return (
      <Page right={picker}>
        <div className="max-w-lg text-[13px] space-y-2">
          <p>{profiles.length > 1 ? `The ${profile} profile has no ElevenLabs API key yet.` : "Add your ElevenLabs API key to use speech, transcription, sound and music."}</p>
          <button className="btn btn-primary" onClick={() => actions.go("settings", { section: "accounts" })}>Open Settings → Accounts</button>
        </div>
      </Page>
    );
  }
  return (
    <ProfileCtx.Provider value={profile}>
    <Page right={picker}>
      {sub && <QuotaBar sub={sub} />}
      {status?.status && status.status !== "online" && (
        <div className="mb-3 text-[13px] text-bad">ElevenLabs is {status.status.replace("_", " ")}. Check the key in Settings, then refresh on My usage.</div>
      )}
      <div className="flex gap-6">
        <nav className="w-40 shrink-0 text-[13px]" aria-label="ElevenLabs sections">
          {shown.map((s) => (
            <button key={s.id} onClick={() => setSection(s.id)} aria-current={section === s.id}
              className={`block w-full text-left px-2 py-1.5 rounded ${section === s.id ? "bg-sunken text-text" : "text-muted hover:text-text"}`}>{s.label}</button>
          ))}
          {feats.music === false && <div className="px-2 pt-2 text-[12px] text-faint">Music needs a paid plan.</div>}
        </nav>
        <div className="flex-1 min-w-0">
          {section === "tts" && <TTS voices={voices} favs={favs} models={models} defaults={status?.defaults ?? {}} />}
          {section === "stt" && <STT />}
          {section === "sfx" && <SFX />}
          {section === "music" && <Music />}
          {section === "voice_changer" && <VoiceChanger voices={voices} />}
          {section === "voices" && <Voices voices={voices} favs={favs} setFavs={setFavs} reload={() => load()} features={feats} />}
          {section === "history" && <History />}
        </div>
      </div>
    </Page>
    </ProfileCtx.Provider>
  );
}

function Page({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-[1080px] mx-auto px-6 py-5">
        <div className="flex items-center gap-3 mb-4"><h1 className="text-lg font-semibold">ElevenLabs</h1><div className="ml-auto">{right}</div></div>
        {children}
      </div>
    </div>
  );
}

function QuotaBar({ sub }: { sub: any }) {
  const pct = sub.character_limit ? Math.min(1, sub.character_count / sub.character_limit) : 0;
  return (
    <div className="mb-5 rounded-md border border-line surface px-3 py-2.5 text-[13px]">
      <div className="flex items-baseline gap-3">
        <span className="font-medium">{(sub.character_limit - sub.character_count).toLocaleString()} credits left</span>
        <span className="text-muted">{sub.character_count.toLocaleString()} of {sub.character_limit.toLocaleString()} used</span>
        <span className="ml-auto text-muted">Resets {sub.next_character_count_reset_unix ? new Date(sub.next_character_count_reset_unix * 1000).toLocaleDateString() : "—"} · {sub.tier} plan</span>
      </div>
      <div className="h-2 mt-1.5 rounded-sm bg-sunken overflow-hidden" role="meter" aria-valuenow={Math.round(pct * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Credits used">
        <div className="h-full" style={{ width: `${pct * 100}%`, background: pct > 0.9 ? "var(--bad)" : "var(--eleven)" }} />
      </div>
    </div>
  );
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return <label className="block mb-3"><span className="label block mb-1">{label}</span>{children}{hint && <span className="block text-[12px] text-faint mt-1">{hint}</span>}</label>;
}

function Slider({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) {
  return (
    <label className="block">
      <span className="flex justify-between label"><span>{label}</span><span className="tabular-nums">{value.toFixed(2)}</span></span>
      <input type="range" className="w-full accent-[var(--eleven)]" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function Result({ r }: { r: any }) {
  return (
    <div className="mt-3">
      <AudioPlayer path={r.path} />
      <div className="flex items-center gap-2 mt-1.5 text-[12px] text-muted">
        <span>{Math.round(r.credits)} credits</span>
        <button className="btn py-0.5 ml-auto" onClick={() => sendItemToChat(r.item_id)}><Send size={12} /> Send to chat</button>
      </div>
    </div>
  );
}

function useBusy() {
  const [busy, setBusy] = useState(false);
  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    try { return await fn(); } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(false); }
  };
  return { busy, run };
}

function VoicePicker({ voices, favs, value, onChange }: { voices: Voice[]; favs: string[]; value: string; onChange: (v: string) => void }) {
  const sorted = useMemo(() => [...voices].sort((a, b) => Number(favs.includes(b.voice_id)) - Number(favs.includes(a.voice_id))), [voices, favs]);
  const v = voices.find((x) => x.voice_id === value);
  return (
    <div className="flex gap-2 items-center">
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)} aria-label="Voice">
        {sorted.map((x) => <option key={x.voice_id} value={x.voice_id}>{favs.includes(x.voice_id) ? "★ " : ""}{x.name}{x.labels?.accent ? ` · ${x.labels.accent}` : ""}</option>)}
      </select>
      {v?.preview_url && <PreviewButton url={v.preview_url} />}
    </div>
  );
}

let previewAudio: HTMLAudioElement | null = null;
function PreviewButton({ url }: { url: string }) {
  return (
    <button className="btn px-2 shrink-0" title="Preview voice" aria-label="Preview voice" onClick={() => {
      previewAudio?.pause();
      previewAudio = new Audio(url);
      previewAudio.play().catch(() => actions.toast("Couldn't play the preview.", "error"));
    }}><Play size={13} /></button>
  );
}

function TTS({ voices, favs, models, defaults }: { voices: Voice[]; favs: string[]; models: any[]; defaults: any }) {
  const [text, setText] = useState("");
  const [voice, setVoice] = useState(defaults.voice_id || "");
  const [model, setModel] = useState(defaults.model_id || "eleven_v4");
  const [fmt, setFmt] = useState(defaults.output_format || "mp3_44100_128");
  const [vs, setVs] = useState({ stability: 0.5, similarity_boost: 0.75, style: 0, speed: 1 });
  const [res, setRes] = useState<any>(null);
  const { busy, run } = useBusy();
  const target = useTarget();
  useEffect(() => { if (!voice && voices[0]) setVoice(voices[0].voice_id); }, [voices]);
  const m = models.find((x) => x.model_id === model);
  const mult = m?.model_rates?.character_cost_multiplier ?? 1;
  const max = m?.maximum_text_length_per_request ?? 10000;
  const onlyStability = model.startsWith("eleven_v3");
  return (
    <div className="grid grid-cols-[1fr_260px] gap-6">
      <div>
        <Field label="Text" hint={<span className={text.length > max ? "text-bad" : ""}>{text.length.toLocaleString()} / {max.toLocaleString()} characters · about {Math.ceil(text.length * mult).toLocaleString()} credits</span>}>
          <textarea className="input min-h-48 leading-6" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type or paste what you want spoken." />
        </Field>
        <button className="btn btn-primary" disabled={busy || !text.trim() || !voice || text.length > max}
          onClick={() => run(async () => setRes(await post("/elevenlabs/tts", { text, voice_id: voice, model_id: model, output_format: fmt,
            voice_settings: onlyStability ? { stability: vs.stability } : vs, ...target() })))}>
          {busy ? "Generating…" : "Generate speech"}
        </button>
        {res && <Result r={res} />}
      </div>
      <div>
        <Field label="Voice"><VoicePicker voices={voices} favs={favs} value={voice} onChange={setVoice} /></Field>
        <Field label="Model">
          <select className="input" value={model} onChange={(e) => setModel(e.target.value)}>
            {(models.length ? models : [{ model_id: model, name: model }]).map((x) => <option key={x.model_id} value={x.model_id}>{x.name ?? x.model_id}</option>)}
          </select>
        </Field>
        <Field label="Output format">
          <select className="input" value={fmt} onChange={(e) => setFmt(e.target.value)}>{FORMATS.map((f) => <option key={f}>{f}</option>)}</select>
        </Field>
        <div className="space-y-2">
          <Slider label="Stability" value={vs.stability} min={0} max={1} step={0.05} onChange={(v) => setVs({ ...vs, stability: v })} />
          {!onlyStability && (
            <>
              <Slider label="Similarity" value={vs.similarity_boost} min={0} max={1} step={0.05} onChange={(v) => setVs({ ...vs, similarity_boost: v })} />
              <Slider label="Style" value={vs.style} min={0} max={1} step={0.05} onChange={(v) => setVs({ ...vs, style: v })} />
              <Slider label="Speed" value={vs.speed} min={0.7} max={1.2} step={0.01} onChange={(v) => setVs({ ...vs, speed: v })} />
            </>
          )}
          {onlyStability && <div className="text-[12px] text-faint">This model only takes stability.</div>}
        </div>
      </div>
    </div>
  );
}

function Recorder({ onFile }: { onFile: (f: File) => void }) {
  const [rec, setRec] = useState<MediaRecorder | null>(null);
  const [secs, setSecs] = useState(0);
  const start = async () => {
    try {
      // Microphone permission is requested only here, the first time you press record.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/mp4") ? "audio/mp4" : "audio/webm";
      const r = new MediaRecorder(stream, { mimeType: mime });
      const chunks: Blob[] = [];
      r.ondataavailable = (e) => chunks.push(e.data);
      r.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        onFile(new File(chunks, `recording-${Date.now()}.${mime === "audio/mp4" ? "m4a" : "webm"}`, { type: mime }));
      };
      r.start();
      setRec(r);
      setSecs(0);
    } catch {
      actions.toast("Microphone access was denied. Allow it in System Settings → Privacy & Security → Microphone.", "error");
    }
  };
  useEffect(() => { if (!rec) return; const t = setInterval(() => setSecs((s) => s + 1), 1000); return () => clearInterval(t); }, [rec]);
  return rec ? (
    <button className="btn" onClick={() => { rec.stop(); setRec(null); }}><Square size={13} className="text-bad" /> Stop · {secs}s</button>
  ) : (
    <button className="btn" onClick={start}><Mic size={13} /> Record</button>
  );
}

function AudioInput({ file, setFile }: { file: { path: string; name: string } | null; setFile: (f: { path: string; name: string } | null) => void }) {
  const inp = useRef<HTMLInputElement>(null);
  const take = async (f: File) => setFile(await upload(f));
  return (
    <div className="flex items-center gap-2">
      <button className="btn" onClick={() => inp.current?.click()}><Upload size={13} /> Upload audio or video</button>
      <input ref={inp} type="file" hidden accept="audio/*,video/*" onChange={(e) => e.target.files?.[0] && take(e.target.files[0])} />
      <Recorder onFile={take} />
      {file && <span className="chip">{file.name}</span>}
    </div>
  );
}

function STT() {
  const [file, setFile] = useState<{ path: string; name: string } | null>(null);
  const [lang, setLang] = useState("");
  const [diarize, setDiarize] = useState(true);
  const [res, setRes] = useState<any>(null);
  const [t, setT] = useState(0);
  const seek = useRef<AudioPlayerHandle | null>(null);
  const { busy, run } = useBusy();
  const target = useTarget();
  return (
    <div>
      <AudioInput file={file} setFile={setFile} />
      <div className="flex gap-4 items-end mt-3">
        <Field label="Language (blank = detect)"><input className="input w-40" value={lang} onChange={(e) => setLang(e.target.value)} placeholder="en, es, ja…" /></Field>
        <label className="flex items-center gap-2 mb-3 text-[13px]"><input type="checkbox" checked={diarize} onChange={(e) => setDiarize(e.target.checked)} /> Speaker labels</label>
        <button className="btn btn-primary mb-3" disabled={!file || busy}
          onClick={() => run(async () => setRes(await post("/elevenlabs/stt", { path: file!.path, language_code: lang, diarize, ...target() })))}>
          {busy ? "Transcribing…" : "Transcribe"}
        </button>
      </div>
      {res && file && (
        <div className="mt-2">
          <AudioPlayer path={file.path} onTime={setT} seekRef={seek} />
          <div className="flex items-center mt-2 mb-1 text-[12px] text-muted">
            {res.language} · {Math.round(res.duration_s)}s{res.credits != null ? ` · ${res.credits_estimated ? "≈" : ""}${Math.round(res.credits).toLocaleString()} credits` : ""} · click a time or word to jump there
            <button className="btn py-0.5 ml-auto" onClick={() => sendItemToChat(res.item_id).then(() => actions.setComposerText(res.labelled))}><Send size={12} /> Send transcript to chat</button>
          </div>
          <Transcript words={res.words} t={t} onSeek={(s) => seek.current?.seek(s)} />
        </div>
      )}
    </div>
  );
}

function SFX() {
  const [text, setText] = useState("");
  const [dur, setDur] = useState<number | "">("");
  const [infl, setInfl] = useState(0.3);
  const [loop, setLoop] = useState(false);
  const [n, setN] = useState(1);
  const [res, setRes] = useState<any[]>([]);
  const { busy, run } = useBusy();
  const target = useTarget();
  return (
    <div className="max-w-2xl">
      <Field label="Describe the sound"><textarea className="input min-h-20" value={text} onChange={(e) => setText(e.target.value)} placeholder="Rain on a tin roof, distant thunder" /></Field>
      <div className="grid grid-cols-3 gap-4">
        <Field label="Duration (s, blank = auto)" hint={dur ? `about ${Math.round(Number(dur) * 40)} credits each` : undefined}>
          <input type="number" min={0.5} max={30} step={0.5} className="input" value={dur} onChange={(e) => setDur(e.target.value ? Number(e.target.value) : "")} />
        </Field>
        <Field label="Variations"><select className="input" value={n} onChange={(e) => setN(Number(e.target.value))}>{[1, 2, 3, 4].map((x) => <option key={x}>{x}</option>)}</select></Field>
        <div><Slider label="Prompt influence" value={infl} min={0} max={1} step={0.05} onChange={setInfl} /><label className="flex items-center gap-2 mt-2 text-[13px]"><input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Seamless loop</label></div>
      </div>
      <button className="btn btn-primary" disabled={!text.trim() || busy}
        onClick={() => run(async () => setRes(await post("/elevenlabs/sfx", { text, duration_s: dur || null, prompt_influence: infl, loop, variations: n, ...target() })))}>
        {busy ? "Generating…" : "Generate"}
      </button>
      {res.map((r) => <Result key={r.item_id} r={r} />)}
    </div>
  );
}

function Music() {
  const [prompt, setPrompt] = useState("");
  const [dur, setDur] = useState(30);
  const [inst, setInst] = useState(false);
  const [n, setN] = useState(1);
  const [res, setRes] = useState<any[]>([]);
  const { busy, run } = useBusy();
  const target = useTarget();
  return (
    <div className="max-w-2xl">
      <Field label="Prompt"><textarea className="input min-h-20" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Warm lo-fi beat with soft piano, 80 bpm, for a podcast intro" /></Field>
      <div className="grid grid-cols-3 gap-4 items-end">
        <Field label="Duration (s)"><input type="number" min={3} max={600} className="input" value={dur} onChange={(e) => setDur(Number(e.target.value))} /></Field>
        <Field label="Variations"><select className="input" value={n} onChange={(e) => setN(Number(e.target.value))}>{[1, 2, 3].map((x) => <option key={x}>{x}</option>)}</select></Field>
        <label className="flex items-center gap-2 mb-3 text-[13px]"><input type="checkbox" checked={inst} onChange={(e) => setInst(e.target.checked)} /> Instrumental</label>
      </div>
      <button className="btn btn-primary" disabled={!prompt.trim() || busy}
        onClick={() => run(async () => setRes(await post("/elevenlabs/music", { prompt, duration_s: dur, instrumental: inst, variations: n, ...target() })))}>
        {busy ? "Composing…" : "Compose"}
      </button>
      {res.map((r) => <Result key={r.item_id} r={r} />)}
    </div>
  );
}

function VoiceChanger({ voices }: { voices: Voice[] }) {
  const [file, setFile] = useState<{ path: string; name: string } | null>(null);
  const [voice, setVoice] = useState("");
  const [res, setRes] = useState<any>(null);
  const { busy, run } = useBusy();
  const target = useTarget();
  useEffect(() => { if (!voice && voices[0]) setVoice(voices[0].voice_id); }, [voices]);
  return (
    <div className="max-w-2xl">
      <AudioInput file={file} setFile={setFile} />
      <div className="mt-3"><Field label="Target voice"><VoicePicker voices={voices} favs={[]} value={voice} onChange={setVoice} /></Field></div>
      <div className="text-[12px] text-faint mb-2">Billed about 1,000 credits per minute of audio.</div>
      <button className="btn btn-primary" disabled={!file || !voice || busy}
        onClick={() => run(async () => setRes(await post("/elevenlabs/voice-changer", { path: file!.path, voice_id: voice, ...target() })))}>
        {busy ? "Converting…" : "Change voice"}
      </button>
      {res && <Result r={res} />}
    </div>
  );
}

function Voices({ voices, favs, setFavs, reload, features }: { voices: Voice[]; favs: string[]; setFavs: (f: string[]) => void; reload: () => void; features: any }) {
  const [tab, setTab] = useState<"mine" | "library">("mine");
  const [q, setQ] = useState("");
  const [lib, setLib] = useState<Voice[]>([]);
  const { busy, run } = useBusy();
  const target = useTarget();
  const toggleFav = async (id: string) => setFavs(await post("/elevenlabs/favorites", { voice_ids: favs.includes(id) ? favs.filter((x) => x !== id) : [...favs, id] }));
  const searchLib = () => run(async () => setLib(await get(`/elevenlabs/voices?shared=true&search=${encodeURIComponent(q)}&profile=${encodeURIComponent(target().profile ?? "")}`)));
  useEffect(() => { if (tab === "library" && !lib.length && features.voice_library !== false) searchLib(); }, [tab]);
  const list = tab === "mine" ? voices.filter((v) => !q || v.name.toLowerCase().includes(q.toLowerCase())) : lib;
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <div className="inline-flex rounded border border-line overflow-hidden text-[13px]">
          {(["mine", "library"] as const).map((t) => <button key={t} className={`px-3 py-1 ${tab === t ? "bg-sunken font-medium" : ""}`} aria-pressed={tab === t} onClick={() => setTab(t)}>{t === "mine" ? "My voices" : "Voice library"}</button>)}
        </div>
        <input className="input w-56" placeholder="Search voices" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && tab === "library" && searchLib()} />
        <div className="ml-auto flex gap-2">
          <a className="btn" href="https://elevenlabs.io/app/voice-lab" target="_blank" rel="noreferrer"><ExternalLink size={13} /> Design or clone on ElevenLabs</a>
        </div>
      </div>
      <p className="text-[12px] text-faint mb-3">Voice design and cloning happen on ElevenLabs, through their consent and verification flow. Only clone voices you have the rights to.</p>
      {tab === "library" && features.voice_library === false && <Empty>The shared voice library isn't available through the API on the free plan.</Empty>}
      <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-2">
        {list.map((v) => (
          <div key={v.voice_id} className="rounded-md border border-line surface p-2.5 text-[13px]">
            <div className="flex items-center gap-1.5">
              <span className="font-medium truncate">{v.name}</span>
              {tab === "mine" && <button className="ml-auto" onClick={() => toggleFav(v.voice_id)} aria-pressed={favs.includes(v.voice_id)} aria-label="Favorite" title="Favorite"><Star size={14} fill={favs.includes(v.voice_id) ? "var(--warn)" : "none"} style={{ color: favs.includes(v.voice_id) ? "var(--warn)" : "var(--faint)" }} /></button>}
            </div>
            <div className="text-[12px] text-muted truncate">{[v.category, ...Object.values(v.labels ?? {})].filter(Boolean).join(" · ")}</div>
            <div className="flex gap-1.5 mt-2">
              {v.preview_url && <PreviewButton url={v.preview_url} />}
              {tab === "library" && v.public_owner_id && (
                <button className="btn" disabled={busy} onClick={() => run(async () => { await post("/elevenlabs/voices/add", { public_owner_id: v.public_owner_id, voice_id: v.voice_id, name: v.name, ...target() }); actions.toast(`Added ${v.name} to your voices`); reload(); })}>Add to my voices</button>
              )}
            </div>
          </div>
        ))}
      </div>
      {tab === "mine" && !voices.length && <Empty>No voices yet.</Empty>}
    </div>
  );
}

function History() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => { get("/elevenlabs/history").then(setRows); }, []);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div>
      {!rows.length && <Empty>Nothing generated yet.</Empty>}
      <table className="w-full text-[13px]">
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b border-line align-top">
              <td className="py-2 pr-3 w-full">
                <button className="text-left hover:text-action" onClick={() => setOpen(open === r.id ? null : r.id)}>{r.title}</button>
                <div className="text-[12px] text-muted">{r.meta?.feature} · {r.model}{r.meta?.voice ? ` · ${r.meta.voice}` : ""} · {r.session_title ?? "no session"} · {fmtAgo(r.created_at)}</div>
                {open === r.id && r.mime?.startsWith("audio") && <div className="mt-2"><AudioPlayer path={r.path} /></div>}
                {open === r.id && r.subtype === "transcript" && <div className="mt-2"><SavedTranscript item={r} /></div>}
              </td>
              <td className="py-2 pr-3 text-right tabular-nums whitespace-nowrap">{r.meta?.credits != null ? `${r.meta.credits_estimated ? "≈" : ""}${Math.round(r.meta.credits)} credits` : ""}</td>
              <td className="py-2"><button className="btn py-0.5" onClick={() => sendItemToChat(r.id)} title="Send to chat" aria-label={`Send ${r.title} to chat`}><Send size={12} /></button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A saved transcript: timestamped words with the source audio when it's still on disk. */
function SavedTranscript({ item }: { item: any }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => { get(`/elevenlabs/transcript?item_id=${item.id}`).then(setData).catch(() => setData({})); }, [item.id]);
  if (!data) return <div className="text-muted">Loading…</div>;
  if (!data.words?.length) return <div className="whitespace-pre-wrap text-muted">{item.extracted_text}</div>;
  return <TranscriptWithPlayer words={data.words} audioPath={item.meta?.audio ?? data.source} />;
}
