Replay: make live recording work end to end

Recording from the open Editor never produced an archive the reader accepted:

- `record` started the session in Edit Mode. Entering Play Mode then
  reloaded the domain and dropped it. Record now opens the scene, enters
  Play Mode and begins once Play Mode is running (SessionState carries the
  request across the reload); `replay_status` shows `starting` meanwhile.
- The recorder wrote empty strings for the project, scene, package-lock,
  input and provider-schema digests, and left `unity.input` out of the
  header's provider list after the input adapter unregistered it. The
  reader rejected every live recording as incompatible. The digests are
  now computed (input digests are the empty-input hash, noted in coverage),
  and the header lists the providers the frames hold.

com.gdw.replay goes to 0.1.1 so existing installs upgrade in place.
Checked on Unity 6000.3.21f1: a seed-42 recording of the sample scene
replayed in batch with 6,774 of 6,774 frame hashes matching.
[hidden test] keeps a real recorded header so the
C# writer and the Python reader can't drift apart again.

Interface the tests use (declarations only; the change adds or changes these):
- `static ReplayCommands()`
- `public string SchemaSha256(string id)`
- `var header = BuildHeader(_initialHash, result.Frames.Count > 0 ? result.Frames[0].Providers.Keys : null)`
- `var sorted = new List<Entry>(_entries)`
