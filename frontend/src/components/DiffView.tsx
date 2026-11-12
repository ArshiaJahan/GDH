// Monaco is bundled locally (no CDN) and loaded only when a diff is opened.
import { DiffEditor } from "@monaco-editor/react";
import { useMonacoTheme } from "../lib/monaco";

export default function DiffView({ original, modified, language }: { original: string; modified: string; language: string }) {
  const theme = useMonacoTheme();
  return (
    <DiffEditor height="70vh" original={original} modified={modified} language={language} theme={theme}
      options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false }, fontSize: 12.5, fontFamily: "IBM Plex Mono, Menlo, monospace",
                 scrollBeyondLastLine: false, renderOverviewRuler: false }} />
  );
}
