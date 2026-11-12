# Save system: versioned JSON, migrations, atomic writes

Files: `templates/Runtime/Save/{SaveData,SaveMigrator,JsonSaveStore}.cs`; concrete saves `Roguelike/MetaProgress.cs` (v2 with a v1 migration) and `Roguelike/RunState.cs` (v1). Tests: `Tests/EditMode/SaveSystemTests.cs`.

## Layout on disk
- Root: `Application.persistentDataPath/saves/` (`JsonSaveStore.CreateDefault()`). macOS editor: `~/Library/Application Support/<company>/<product>`; macOS player: `~/Library/Application Support/unity.<company>.<product>` (uses the editor path if it already exists); Windows: `%userprofile%\AppData\LocalLow\<company>\<product>`; Web: IndexedDB (`idbfs/<md5>`); [UNVERIFIED] whether Web builds in 6000.3 still need an explicit filesystem sync after writing, and whether `File.Replace` works there (the fallback path covers `PlatformNotSupportedException` only).
- One file per slot: `meta.json` (MetaProgress), `run.json` (RunState, deleted on death/win), optionally `settings.json`. `<slot>.json.bak` = previous good file, `<slot>.json.tmp` exists only mid-write.

## Write path (atomic)
`Save(slot, data)` sets `data.version = LatestVersion`, serializes with `JsonUtility.ToJson`, writes `slot.json.tmp`, `Flush(true)` (fsync), then `File.Replace(tmp, main, bak)`; first save is a plain move. Platforms without `File.Replace` fall back to copy-to-bak + delete + move. A crash at any point leaves either the old main file or the new one, plus a `.bak`.

## Read path
`TryLoad<T>(slot, out data)` → `LoadResult { ok, missing, fromBackup, migratedFrom, error }`.
1. Neither main nor `.bak` exists → `missing = true` (first launch: create a new object).
2. Main file: read version (`{"version":n}` probe), run migrations to `LatestVersion`, `FromJson`. Parse/IO error → try `.bak` (`fromBackup = true`, logs a warning).
3. Version newer than the build, or a gap in the migration chain → `SaveVersionException`: `ok = false`, no fallback, file untouched. Never call `Save` for that slot afterwards in this session; tell the player instead.

## Adding a save type
```csharp
[Serializable] public sealed class SettingsSave : SaveData
{
    public const int CurrentVersion = 1;
    public override int LatestVersion => CurrentVersion;
    public float musicVolume = 0.8f, sfxVolume = 1f;
    public SettingsSave() { version = CurrentVersion; }
}
```
Fields must be public or `[SerializeField]`, types `[Serializable]`. Lists of `[Serializable]` classes are fine.

## Changing a save shape (migration)
1. Copy the current class as a nested DTO `V<n>` (exact old fields) and never edit it again.
2. Change the live class, bump `CurrentVersion` to n+1.
3. Register: `new SaveMigrator().Register<V1, MetaProgress>(1, old => new MetaProgress { currency = old.gold, ... })`; return it from `Migrations`. Steps are keyed by the version they upgrade FROM and must raise `version` (`Register<TOld,TNew>` does it for you; raw `Func<string,string>` steps must set it themselves).
4. Test with a literal old JSON string written as a file, e.g. `{"version":1,"gold":5,"runsStarted":2,"runsWon":0,"unlockedIds":["a"]}` → load → assert mapped fields and `migratedFrom == 1` (see `Migration_V1GoldBecomesCurrency`).
5. Renames lose data silently with JsonUtility (unknown fields are ignored, missing fields keep defaults). Every rename or meaning change needs a version bump.

## JsonUtility vs Newtonsoft
- JsonUtility (default): fast, no dependency; no `Dictionary`, no polymorphism (`List<BaseClass>` loses subclasses), no top-level arrays, no properties, no null for nested `[Serializable]` classes. Workarounds: parallel key/value lists, a `type` string + one list per subtype.
- Newtonsoft (`com.unity.nuget.newtonsoft-json`, bench has 3.2.2; [UNVERIFIED] the 6000.3-recommended version): add the package and a `Unity.Newtonsoft.Json` asmdef reference, then replace the two `JsonUtility` calls in `JsonSaveStore`/`SaveMigrator` (keep the version probe). Use `TypeNameHandling.None` unless you need polymorphism; never `TypeNameHandling.All` on untrusted files.
- Never `BinaryFormatter` (unsafe, obsolete). `PlayerPrefs` only for small settings.

## Tests that must stay green
`RoundTrip_MetaProgress_PreservesFields`, `RoundTrip_RunState_ResumesRngExactly`, `Migration_V1GoldBecomesCurrency`, `Migrator_MissingStep_Throws`, `NewerVersion_IsRefused_AndFileUntouched`, `CorruptMainFile_FallsBackToBackup`, `Save_IsAtomic_NoTempLeft_BackupKept`, `Missing_ReportsMissing`. They write to a temp folder, never to `persistentDataPath`.
