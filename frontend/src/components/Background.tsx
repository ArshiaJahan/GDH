import { useEffect, useRef, useState } from "react";
import { fileUrl, inTauri } from "../lib/api";
import { useStore } from "../lib/store";

/** Optional app background: image, GIF or looping muted video, behind translucent panels. */
export function Background() {
  const appearance = useStore((s) => s.appState?.appearance);
  const theme = useStore((s) => s.theme);
  const [dark, setDark] = useState(document.documentElement.dataset.theme === "dark");
  const [reduce, setReduce] = useState(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [hidden, setHidden] = useState(document.hidden);
  const [lowBattery, setLowBattery] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const [still, setStill] = useState<string | null>(null);

  useEffect(() => {
    const obs = new MutationObserver(() => setDark(document.documentElement.dataset.theme === "dark"));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onMq = () => setReduce(mq.matches);
    mq.addEventListener("change", onMq);
    const onVis = () => setHidden(document.hidden);
    document.addEventListener("visibilitychange", onVis);
    return () => { obs.disconnect(); mq.removeEventListener("change", onMq); document.removeEventListener("visibilitychange", onVis); };
  }, [theme]);

  // Battery: the app asks macOS (WebKit has no Battery API); browsers that have one use it.
  useEffect(() => {
    let timer: any;
    const check = async () => {
      try {
        if (inTauri()) {
          const { invoke } = await import("@tauri-apps/api/core");
          const p = await invoke<{ on_battery: boolean; percent: number | null }>("power_status");
          setLowBattery(p.on_battery && (p.percent ?? 100) < 20);
        } else if ((navigator as any).getBattery) {
          const b = await (navigator as any).getBattery();
          setLowBattery(!b.charging && b.level < 0.2);
        }
      } catch {}
    };
    check();
    timer = setInterval(check, 60_000);
    return () => clearInterval(timer);
  }, []);

  const bg = appearance?.[dark ? "dark" : "light"];
  const opacity = appearance?.panel_opacity ?? 1;
  useEffect(() => {
    document.documentElement.style.setProperty("--panel-alpha", bg?.path ? String(opacity) : "1");
  }, [bg?.path, opacity]);

  const paused = hidden || lowBattery || reduce;
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    if (paused) v.pause();
    else v.play().catch(() => {});
  }, [paused, bg?.path]);

  // GIFs can't be paused: with Reduce motion on, show a still frame drawn to a canvas.
  useEffect(() => {
    setStill(null);
    if (!bg?.path || bg.kind !== "gif" || !reduce) return;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      c.getContext("2d")!.drawImage(img, 0, 0);
      try { setStill(c.toDataURL("image/png")); } catch {}
    };
    img.src = fileUrl(bg.path);
  }, [bg?.path, bg?.kind, reduce]);

  if (!bg?.path) return null;
  const url = fileUrl(bg.path);
  const fit = bg.fit ?? "cover";
  const filter = bg.blur ? `blur(${bg.blur}px)` : undefined;
  const common = { position: "fixed" as const, inset: bg.blur ? -bg.blur * 2 : 0, filter, zIndex: 0 };
  return (
    <div aria-hidden className="pointer-events-none">
      {bg.kind === "video" ? (
        <video ref={video} src={url} muted loop playsInline autoPlay={!paused} preload="auto"
          style={{ ...common, width: `calc(100% + ${bg.blur ? bg.blur * 4 : 0}px)`, height: `calc(100% + ${bg.blur ? bg.blur * 4 : 0}px)`, objectFit: fit === "contain" ? "contain" : "cover" }} />
      ) : (
        <div style={{ ...common, backgroundImage: `url("${bg.kind === "gif" && reduce && still ? still : url}")`,
          backgroundSize: fit === "tile" ? "auto" : fit, backgroundRepeat: fit === "tile" ? "repeat" : "no-repeat", backgroundPosition: "center" }} />
      )}
      <div style={{ position: "fixed", inset: 0, background: `rgba(0,0,0,${bg.dim ?? 0.35})`, zIndex: 0 }} />
    </div>
  );
}
