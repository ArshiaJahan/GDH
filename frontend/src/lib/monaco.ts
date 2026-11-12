// Monaco is bundled locally (no CDN). Import this module only from lazily loaded components
// (DiffView, SkillEditor) so the editor stays out of the main bundle.
import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";
import { useEffect, useState } from "react";
import { useStore } from "./store";

(self as any).MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });

export { monaco };

const mq = window.matchMedia("(prefers-color-scheme: dark)");

/** "vs-dark" or "vs", following the app theme (and the system setting when it's "system"). */
export function useMonacoTheme(): "vs" | "vs-dark" {
  const theme = useStore((s) => s.theme);
  const [sysDark, setSysDark] = useState(mq.matches);
  useEffect(() => {
    const on = (e: MediaQueryListEvent) => setSysDark(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return theme === "dark" || (theme === "system" && sysDark) ? "vs-dark" : "vs";
}
