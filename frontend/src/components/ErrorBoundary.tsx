import { Component, type ReactNode } from "react";

const RELOAD_KEY = "ws-preload-reload";

/** After an update while the app is open, a lazy page's chunk from the old build is gone (the backend
 *  answers 404). Vite fires `vite:preloadError`; reload once to pick up the new build. The
 *  sessionStorage guard stops a reload loop when the chunk is missing for another reason; the
 *  ErrorBoundary below then shows the error instead. */
export function installPreloadReload(win: Window = window, now: () => number = Date.now) {
  win.addEventListener("vite:preloadError", (e) => {
    const last = Number(win.sessionStorage.getItem(RELOAD_KEY) || 0);
    if (now() - last < 60_000) return; // already reloaded for this a moment ago: let the boundary show it
    win.sessionStorage.setItem(RELOAD_KEY, String(now()));
    e.preventDefault();
    win.location.reload();
  });
}

type Props = { children: ReactNode; resetKey?: unknown };
type State = { error: Error | null; key: unknown };

/** Shows "Something went wrong loading this page" with Reload and the error, instead of a blank app,
 *  when a page (or a lazy page's chunk) fails to render. Changing resetKey (e.g. the page) clears it. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, key: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null;
  }

  componentDidCatch(error: Error) {
    console.error("Page failed to load", error);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div role="alert" className="h-full flex items-center justify-center p-8 text-center">
        <div className="max-w-lg">
          <p className="font-medium mb-2">Something went wrong loading this page</p>
          <p className="text-muted text-[12px] font-mono break-words mb-4">{error.message || String(error)}</p>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>Reload</button>
        </div>
      </div>
    );
  }
}
