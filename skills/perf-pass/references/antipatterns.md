# Unity C# performance audit

Run before profiling to prioritize files, then measure the suspected costs in the
same reproducible scenario. Python 3.9+ and the standard library are sufficient:

```sh
python3 <skills>/perf-pass/scripts/unity_antipatterns.py --project <game>
python3 <skills>/perf-pass/scripts/unity_antipatterns.py --project <game> --changed Assets/Scripts/Enemy.cs --baseline <game>/.workspace/antipatterns-baseline.json
```

`--project` defaults to `.` and scans `Assets/**/*.cs`. A standalone folder with
C# files directly inside it can also be scanned without an Assets scaffold.
Library, Packages and Temp directories are skipped, including inside Assets.
Folders containing `Tests`
(case insensitive, including `Combat.Tests`) are skipped unless `--include-tests`.
`--changed` takes one or more project-relative or absolute paths; the entire
project remains indexed so a changed helper can be traced from an unchanged caller.

Hot roots are Update, FixedUpdate, LateUpdate, OnGUI and `On*Stay*` callbacks.
The audit follows two same-file call levels by method name and one terminal
cross-file call from a root or its same-file helpers. Reports show `via Class.Method`.
Name matching considers all overloads/classes with that name: review ambiguous
edges. This is a lexical audit, not a C# compiler: aliases, conditional compilation,
reflection, delegate dispatch, inheritance and full type resolution are outside its
model. Findings are leads to investigate with the Profiler.

Each distinct matching site contributes 1 × callback frequency: 1 for Update,
LateUpdate, FixedUpdate and OnGUI; 3 for On*Stay* as a contact-count estimate.
Multiple roots use the largest frequency rather than counting a helper repeatedly.
Same-rule sites on one line share a finding with a `sites` count. The top-files
table totals these scores. This estimates site frequency, not allocation bytes:
some rules concern CPU/API/lifetime costs and some calls allocate conditionally.
`TAG_STRING_COMPARE`, `COROUTINE_NEW_WAIT`, `EVENT_NO_UNSUBSCRIBE`,
`OBSOLETE_VELOCITY` and `NONALLOC_DEPRECATED` also run outside hot methods;
their default frequency is 1.

## Baseline and output

Without `--baseline`, every finding is new. A missing baseline starts empty. Use
`--baseline FILE --update-baseline` to record accepted existing debt, reviewing the
snapshot rather than silently accepting regressions. This writes the full-project
snapshot even with `--changed`. A version-1 JSON baseline has a `findings` object
keyed by the JSON tuple `[rule, project-relative file, normalized source line]`.
Whitespace outside literals and comments are ignored; line numbers are absent.
Inserting unrelated lines therefore does not create new findings. Identical
same-rule lines share a key, so this text-based ratchet cannot distinguish a newly
copied identical line from existing debt. Renaming a file or changing its code can
produce new findings.

Suppress a reviewed exception on the same line or immediately above its site:

```csharp
// harness:allow HOT_DEBUG_LOG bounded diagnostic in a development-only scene
Debug.Log(state);
```

The rule ID and a nonempty reason are required; suppression affects only that
rule. Block comments and strings cannot suppress findings. Comments and literal
contents are masked before matching; literal metadata identifies string
allocations without interpreting embedded text as calls.

`--json` emits one JSON object on stdout (`version`, `findings`, `total`, `new`,
`top_files`, `result`) and the RESULT footer on stderr, matching perf_report.py's
machine-readable convention. A finding includes `rule`, `file`, `line`,
`line_text`, `method`, `hot_method` (null for a cold method), `via` (call path),
`sites`, `frequency`, `score`, `key` and `is_new`.
`--md` prints Markdown; `--md FILE` writes a report file and prints its RESULT.
Text/Markdown stdout ends with the RESULT footer. Exit status is authoritative:
0 = no new findings, 1 = new findings, 2 = usage/input error. Help exits 0.
Successful scans end with exactly `RESULT: OK <n> findings (0 new)` or
`RESULT: FAIL <k> new`; input errors explain the problem on stderr.

## Rules and fixes (Unity 6000.3)

### HOT_GETCOMPONENT

Repeated component lookup adds CPU work across many behaviours. Cache the result
in Awake; refresh it when the object's component composition changes.
6000.3: TryGetComponent avoids some failure-path allocation, but repeated lookup
still deserves measurement and caching.

```csharp
// Before: Update
GetComponent<SpriteRenderer>().color = tint;
// After: cache in Awake
void Awake() { sprite = GetComponent<SpriteRenderer>(); }
void Update() { sprite.color = tint; }
```

### HOT_FIND

Scene searches scale with scene contents; plural results can allocate arrays.
Use serialized references, a registry, or a bounded search at initialization.
6000.3: newer FindObjectsByType/FindFirstObjectByType/FindAnyObjectByType APIs
still cost work; replacing an old Find call does not justify running it per frame.

```csharp
// Before: Update
target = GameObject.Find("Player");
// After: initialize once (or inject on spawn)
void Start() { target = GameObject.Find("Player"); }
```

### HOT_CAMERA_MAIN

Repeated access performs a camera lookup; many callers amplify its cost.
Cache the gameplay camera and refresh the reference when switching cameras.
6000.3: engine caching can reduce lookup cost; this is a CPU lead, not a claim
that every Camera.main access allocates.

```csharp
// Before: Update
point = Camera.main.ScreenToWorldPoint(mouse);
// After
void Awake() { view = Camera.main; }
void Update() { point = view.ScreenToWorldPoint(mouse); }
```

### HOT_LINQ

Iterator chains, delegate capture, sorting and materialization can consume CPU
and allocate. Reuse buffers and use explicit loops in measured hot paths.
6000.3: allocation depends on the operator/backend; Any is not guaranteed to
allocate. The scanner requires `using System.Linq` to reduce unrelated matches.

```csharp
// Before: Update
active = actors.Where(a => a.enabled).ToList();
// After: reuse active
active.Clear();
foreach (var actor in actors) if (actor.enabled) active.Add(actor);
```

### HOT_STRING_ALLOC

Concatenation, interpolation, string.Format and ToString can create managed
strings each frame. Update UI only when its value changes or use the text
component's numeric formatting API. Numeric addition and literal contents alone
are excluded; concatenation recognizes literals and declared string variables.
6000.3: incremental GC does not make steady allocation free.

```csharp
// Before: Update
label.text = $"Score: {score}";
// After: update when score changes
if (score != lastScore) { label.text = $"Score: {score}"; lastScore = score; }
```

### HOT_NEW_COLLECTION

New lists, dictionaries, sets and arrays allocate storage and create GC pressure.
Allocate once with suitable capacity, then clear/reuse; avoid unbounded retained
buffers. 6000.3: reused Physics2D List overloads still grow if capacity is too low.

```csharp
// Before: Update
var hits = new List<Collider2D>();
// After: field initialized once, reused in Update
readonly List<Collider2D> hits = new List<Collider2D>(32);
void Update() { hits.Clear(); /* fill hits */ }
```

### HOT_INSTANTIATE_DESTROY

Object creation/destruction runs engine work and lifecycle callbacks and can
allocate. Pool frequently spawned objects; reset state on return to the pool.
6000.3: UnityEngine.Pool.ObjectPool<T> is available; size and prewarm for the scenario.

```csharp
// Before: Update
var shot = Instantiate(prefab); Destroy(shot, 1f);
// After: fire and expiry events use an existing pool
var shot = pool.Get();
// On expiry:
pool.Release(shot);
```

### HOT_LAMBDA

Capturing lambdas and anonymous delegates can allocate closures/delegates.
Use a cached delegate or direct loop. 6000.3: noncapturing lambdas may be cached
by the compiler; inspect the Profiler before changing them. An expression-bodied
method's declaration arrow is not itself reported as a lambda.

```csharp
// Before: Update
actors.ForEach(actor => actor.Move(speed));
// After
foreach (var actor in actors) actor.Move(speed);
```

### HOT_DEBUG_LOG

Logging formats arguments and may capture stack traces or perform I/O. Remove
per-frame logs or emit diagnostics on a state transition under a build guard.
6000.3: disabled log output alone does not prevent argument evaluation.

```csharp
// Before: Update
Debug.Log(state);
// After: call only on state transitions in development builds
[System.Diagnostics.Conditional("DEVELOPMENT_BUILD")]
void LogTransition() { Debug.Log(state); }
```

### HOT_SENDMESSAGE

String-based SendMessage/BroadcastMessage performs dynamic dispatch and can fan
out over many components. Cache a typed receiver/interface and call it directly.
6000.3: this is CPU/dispatch overhead; allocation depends on argument boxing.

```csharp
// Before: Update
SendMessage("Move", speed);
// After: cached typed receiver
mover.Move(speed);
```

### HOT_RESOURCES_LOAD

Repeated loading/lookups can stall and allocate; resource lifetime also affects
memory. Load once at an appropriate boundary and reuse the reference.
6000.3: async loading changes scheduling, not the need to cache repeated requests.

```csharp
// Before: Update
sprite.sprite = Resources.Load<Sprite>("Icons/Player");
// After
void Awake() { playerIcon = Resources.Load<Sprite>("Icons/Player"); }
void Update() { sprite.sprite = playerIcon; }
```

### TAG_STRING_COMPARE

Reading .tag for a string comparison can create unnecessary string/interop work.
Use CompareTag for equality tests, including the reversed string == object.tag
form. 6000.3: CompareTag keeps the comparison on the engine side.

```csharp
// Before
if (other.tag == "Enemy") Hit();
// After
if (other.CompareTag("Enemy")) Hit();
```

### COROUTINE_NEW_WAIT

Constructing a wait on each loop iteration creates repeated garbage, including
in coroutines never called from Update. Cache a fixed WaitForSeconds duration.
6000.3: WaitForSecondsRealtime is mutable; own and reset it per routine, and avoid
sharing a live mutable wait across simultaneous routines. Variable waits require
an explicit timer or a carefully managed cache.

```csharp
// Before
while (running) { yield return new WaitForSeconds(0.2f); }
// After: pause is a cached field
while (running) { yield return pause; }
```

### EVENT_NO_UNSUBSCRIBE

A publisher can retain a subscriber and invoke stale handlers after disable or
destroy. Pair each event/handler subscribed in OnEnable/Awake/Start with the same
pair in OnDisable/OnDestroy of that class. Namespace-qualified partial class
declarations share teardown handlers across files, including with `--changed`.
Known scalar and Transform vector compound assignments are excluded from event
checks. 6000.3: static publishers need special care with disabled domain reload;
lifecycle pairing still matters.

```csharp
// Before
void OnEnable() { source.Changed += HandleChange; }
// After: retain OnEnable and add its matching teardown
void OnDisable() { source.Changed -= HandleChange; }
```

### OBSOLETE_VELOCITY

Rigidbody2D.velocity is obsolete in Unity 6000.3 (CS0618). Migrate typed 2D bodies
to linearVelocity; a Rigidbody's 3D velocity is outside this rule. The scanner
recognizes explicit Rigidbody2D fields/parameters/locals and common var
GetComponent<Rigidbody2D>() declarations; it cannot infer arbitrary return types.

```csharp
// Before: body is Rigidbody2D
body.velocity = direction * speed;
// After
body.linearVelocity = direction * speed;
```

### NONALLOC_DEPRECATED

Physics2D.*NonAlloc calls are deprecated with CS0618 in Unity 6000.3, rather than
removed. Migrate to ContactFilter2D + reused List overloads and preserve the old
layer/trigger filtering. Preallocate capacity and measure for growth allocations.

```csharp
// Before
int n = Physics2D.OverlapCircleNonAlloc(center, radius, buffer);
// After: filter and hits are cached and configured for this query
int n = Physics2D.OverlapCircle(center, radius, filter, hits);
```
