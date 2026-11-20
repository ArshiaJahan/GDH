Replay: live recordings verify, and render writes MP4 and GIF

Three bugs kept the record -> verify -> render loop from working on a
real project:

- Live recordings diverged on `unity.input`. The input trace kept a
  frame marker for every Editor input update (about 16 per game frame
  while the Editor has focus), and replay advanced on Editor updates
  too, so record and replay disagreed on which frame events landed in.
  The trace now keeps only the replay loop's own update marker, and the
  replay controller is paused outside that update.
- Render never produced media. Nothing called ReplayCapture and nothing
  ran the ffmpeg export. The PlayMode test now captures a PNG per
  replayed frame when the request asks for capture (through hooks the
  Editor assembly installs), and GameDevWorkstation encodes them to the
  requested MP4/GIF after a passing render and lists them in the report.
- A render reported the previous verify's result. report.json left by
  an earlier op was reused; now only a report the Unity package wrote,
  or one written during this op, is kept.

com.gdw.replay goes to 0.1.2. Checked on Unity 6000.3.21f1: a seed-42
recording of the sample scene made in the focused Editor replayed in
batch with 1,968 of 1,968 frame hashes matching, and render wrote a
1280x720 MP4 (1,967 frames) and a GIF.

Interface the tests use (declarations only; the change adds or changes these):
- `def _export_capture(root: Path, run_id: str, request: dict) -> dict | None:`
- `def _tool_output(op: str, run_id: str, result: "BridgeResult | None", report: dict | None,`
- `static ReplayCapture()`
- `public static string Start(string outputDir, int totalFrames, int fps)`
- `// the replay controller, or record and replay disagree on which events land in which frame.`
- `void RunLoopUpdate()`
- `public static class ReplayCaptureHooks`
- `public static Func<string> CaptureFrame`
- `public static Action Stop`
