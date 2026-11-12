using System;
using System.IO;
using System.Text;
using UnityEngine;

namespace Harness.Arch
{
    public struct LoadResult
    {
        public bool ok;
        public bool missing;       // no file: first launch
        public bool fromBackup;    // main file corrupt, .bak used
        public int migratedFrom;   // original version on disk
        public string error;
    }

    /// <summary>
    /// Versioned JSON files with atomic writes: write slot.json.tmp, flush to disk, then replace slot.json
    /// (previous file kept as slot.json.bak). JsonUtility by default (no Dictionary, no polymorphism, no top-level arrays;
    /// wrap lists in a class). Default root: Application.persistentDataPath/saves.
    /// </summary>
    public sealed class JsonSaveStore
    {
        static readonly UTF8Encoding Utf8NoBom = new UTF8Encoding(false);
        public string Root { get; }

        public JsonSaveStore(string root) { Root = root; }

        public static JsonSaveStore CreateDefault() => new JsonSaveStore(Path.Combine(Application.persistentDataPath, "saves"));

        public string PathFor(string slot) => Path.Combine(Root, slot + ".json");
        public bool Exists(string slot) => File.Exists(PathFor(slot));

        public void Save<T>(string slot, T data, bool prettyPrint = false) where T : SaveData
        {
            if (data == null) throw new ArgumentNullException(nameof(data));
            data.version = data.LatestVersion;
            Directory.CreateDirectory(Root);
            string path = PathFor(slot), tmp = path + ".tmp", bak = path + ".bak";
            byte[] bytes = Utf8NoBom.GetBytes(JsonUtility.ToJson(data, prettyPrint));
            using (var fs = new FileStream(tmp, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                fs.Write(bytes, 0, bytes.Length);
                fs.Flush(true); // fsync before the rename so a crash never leaves a half-written main file
            }
            if (!File.Exists(path)) { File.Move(tmp, path); return; }
            try
            {
                File.Replace(tmp, path, bak, true);
            }
            catch (PlatformNotSupportedException)
            {
                // Fallback for platforms without File.Replace: keep a backup copy, then swap.
                File.Copy(path, bak, true);
                File.Delete(path);
                File.Move(tmp, path);
            }
        }

        public LoadResult TryLoad<T>(string slot, out T data) where T : SaveData, new()
        {
            data = null;
            var result = new LoadResult();
            string path = PathFor(slot);
            if (!File.Exists(path) && !File.Exists(path + ".bak")) { result.missing = true; result.error = "no save"; return result; }

            foreach (var candidate in new[] { path, path + ".bak" })
            {
                if (!File.Exists(candidate)) continue;
                try
                {
                    string json = File.ReadAllText(candidate, Utf8NoBom);
                    var proto = new T();
                    int from;
                    if (proto.Migrations != null) json = proto.Migrations.Migrate(json, proto.LatestVersion, out from);
                    else
                    {
                        from = SaveMigrator.ReadVersion(json);
                        if (from != proto.LatestVersion)
                            throw new SaveVersionException($"version {from} != {proto.LatestVersion} and no migrations");
                    }
                    data = JsonUtility.FromJson<T>(json);
                    if (data == null) throw new FormatException("empty json");
                    data.version = proto.LatestVersion;
                    result.ok = true;
                    result.migratedFrom = from;
                    result.fromBackup = candidate != path;
                    if (result.fromBackup) Debug.LogWarning($"[Save] {slot}: main file unreadable, loaded backup");
                    return result;
                }
                catch (SaveVersionException e)
                {
                    result.error = e.Message; // newer or unmigratable: do not fall back, do not overwrite
                    return result;
                }
                catch (Exception e) when (e is ArgumentException || e is FormatException || e is IOException)
                {
                    result.error = $"{Path.GetFileName(candidate)}: {e.Message}";
                }
            }
            return result;
        }

        public void Delete(string slot)
        {
            string path = PathFor(slot);
            foreach (var p in new[] { path, path + ".bak", path + ".tmp" })
                if (File.Exists(p)) File.Delete(p);
        }
    }
}
