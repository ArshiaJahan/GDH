import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { get, post, put, type UnityBackend, type UnityState } from "../lib/api";
import { actions, useStore } from "../lib/store";
import { UNITY_ROUTE_LABEL } from "../lib/unity";
import { Popover } from "./Popover";

const ACTION_LABEL: Record<string, string> = {
  install_pipeline: "Install Pipeline package (one-time, edits Packages/manifest.json)",
  use_mcp_once: "Use MCP for this check",
  use_clone: "Run on a copy of the files",
  close_editor: "Close Unity (exits without saving)",
  install_harness: "Install harness editor scripts (3 files, local only)",
};
/** Actions that make sense whatever the route (the others only for an open Editor without a bridge). */
const ANY_ROUTE = new Set(["install_harness"]);
const BACKENDS: [UnityBackend | "", string][] = [["", "Project default"], ["auto", "Auto"], ["mcp", "MCP"], ["cli", "CLI"]];
const WARN = "var(--warn, #c98a00)";

/** Which Unity route compile/test/build use for this session, with a quick backend switch and the
 *  recovery actions when the Editor is open but nothing can drive it. Renders nothing outside Unity projects. */
export function UnityChip({ sessionId }: { sessionId: string }) {
  const [st, setSt] = useState<UnityState | null>(null);
  const [open, setOpen] = useState(false);
  const seq = useRef(0);
  const q = `/unity/state?session_id=${encodeURIComponent(sessionId)}`;

  const load = useCallback(async () => {
    const n = ++seq.current;
    try {
      const r = await get<UnityState>(q);
      if (n === seq.current) setSt(r);
    } catch { if (n === seq.current) setSt(null); }
  }, [q]);

  useEffect(() => { setSt(null); setOpen(false); load(); }, [load]);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const off = actions.onEvent((e) => {
      if (e.type === "unity.state" && (e.session_id === sessionId || e.data?.session_id === sessionId) && e.data) {
        seq.current++; // a newer state than any fetch in flight
        setSt(e.data as UnityState);
      } else if (e.type === "job.updated" && e.data?.kind === "unity") {
        clearTimeout(t);
        t = setTimeout(load, 400);
      }
    });
    const focus = () => load();
    window.addEventListener("focus", focus);
    return () => { off(); clearTimeout(t); window.removeEventListener("focus", focus); };
  }, [sessionId, load]);

  const close = useCallback(() => setOpen(false), []);
  if (!st || !st.unity_project) return null;

  const safe = st.live?.state === "safe_mode";
  const route = st.route;
  let label: string, color: string | undefined, tip: string;
  if (st.busy) { label = `busy: ${st.busy.label}`; tip = st.reason || `Unity is busy: ${st.busy.label}`; }
  else if (safe) { label = "Safe Mode"; color = "var(--bad)"; tip = "compile errors at boot"; }
  else if (route === "unavailable" && st.editor_open) { label = "Editor open — no bridge"; color = WARN; tip = st.reason; }
  else if (route === "unavailable") { label = "unavailable"; tip = st.reason; }
  else { label = (UNITY_ROUTE_LABEL[route] ?? route) + (st.clone ? " · on a copy" : ""); tip = st.reason; }
  tip = tip || `Unity route: ${UNITY_ROUTE_LABEL[route] ?? route}`;
  const aria = st.busy ? "Unity: busy" : safe ? "Unity: Safe Mode" : `Unity: ${UNITY_ROUTE_LABEL[route] ?? route}${route === "unavailable" && st.editor_open ? ", Editor open" : ""}`;

  const act = async (a: string) => {
    close();
    try {
      const r = await post<{ status: string; message?: string }>(`/unity/actions/${a}`, { session_id: sessionId });
      actions.toast(r?.message || (r?.status === "pending" ? "Waiting for your approval in the chat" : `Unity: ${r?.status ?? "done"}`), r?.status === "error" ? "error" : undefined);
    } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const setBackend = async (b: UnityBackend | "") => {
    try { setSt(await put<UnityState>("/unity/backend", { session_id: sessionId, scope: "session", backend: b || null })); }
    catch (e: any) { actions.toast(e.message, "error"); }
  };
  const cancel = async () => {
    if (!st.busy) return;
    close();
    try { await post(`/unity/jobs/${st.busy.job_id}/cancel`, {}); actions.toast("Cancelling the Unity job"); } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const cur = (st.session_backend ?? "") as UnityBackend | "";
  const shown = st.actions.filter((a) => a in ACTION_LABEL && (ANY_ROUTE.has(a) || (route === "unavailable" && st.editor_open)));
  const actionLabel = (a: string) => a === "install_harness" && st.harness?.outdated
    ? `Update harness editor scripts (version ${st.harness.version ?? "?"} → ${st.harness.current_version ?? "?"})` : ACTION_LABEL[a];
  const item = "block w-full text-left px-2 py-1 rounded hover:bg-sunken text-[12px]";

  return (
    <span className="relative inline-flex">
      <button type="button" className="chip inline-flex items-center gap-1 text-[11.5px] py-0" style={{ color }} title={tip}
        aria-label={aria} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {st.busy && <Loader2 size={11} className="animate-spin" />}
        Unity · {label}
      </button>
      <Popover open={open} onClose={close} align="right" above label="Unity backend" className="w-72 p-2">
        <div role="menu" aria-label="Unity" className="flex flex-col gap-0.5">
          {st.busy && (
            <>
              <button role="menuitem" className={item} onClick={() => { useStore.setState({ terminalOpen: true }); close(); }}>Show terminal</button>
              <button role="menuitem" className={item} onClick={cancel}>Cancel</button>
            </>
          )}
          {shown.map((a) => (
            <button key={a} role="menuitem" className={item} onClick={() => act(a)}>{actionLabel(a)}</button>
          ))}
          {st.reason && <div className="px-2 py-1 text-[11.5px] text-muted">{st.reason}</div>}
        </div>
        <div className="label mt-1 px-2" id="unity-backend-label">Backend for this session</div>
        <div role="radiogroup" aria-labelledby="unity-backend-label" className="flex flex-col">
          {BACKENDS.map(([v, text]) => (
            <label key={v || "default"} className="flex items-center gap-2 px-2 py-0.5 text-[12px]">
              <input type="radio" name={`unity-backend-${sessionId}`} checked={cur === v} onChange={() => setBackend(v)} />
              {v === "" ? `${text} (${(st.project_backend ?? st.global_backend).toUpperCase()})` : text}
            </label>
          ))}
        </div>
      </Popover>
    </span>
  );
}
