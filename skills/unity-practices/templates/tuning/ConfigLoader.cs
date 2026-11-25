using System.IO;
using UnityEngine;

namespace GdwKit
{
    /// <summary>
    /// Development builds only: overrides configs from persistentDataPath/tuning/&lt;asset name&gt;.json, so
    /// playtesters can try numbers without a rebuild. Write a starting file with the context menu.
    /// Works on runtime copies, so the shipped assets are never changed.
    /// </summary>
    public sealed class ConfigLoader : MonoBehaviour
    {
        [SerializeField] private ConfigAsset[] configs = new ConfigAsset[0];

        public static string Folder => Path.Combine(Application.persistentDataPath, "tuning");

        private void Awake()
        {
            if (!Debug.isDebugBuild && !Application.isEditor) return;
            foreach (var c in configs)
            {
                if (!c) continue;
                var file = Path.Combine(Folder, c.name + ".json");
                if (!File.Exists(file)) continue;
                if (!Application.isEditor) c.ApplyJson(File.ReadAllText(file)); // player: assets are in-memory copies
                else Debug.Log($"[TUNING] {file} exists; JSON overrides apply in development builds, not in the editor");
            }
        }

        [ContextMenu("Write JSON templates")]
        private void WriteTemplates()
        {
            Directory.CreateDirectory(Folder);
            foreach (var c in configs)
                if (c) File.WriteAllText(Path.Combine(Folder, c.name + ".json"), c.ToJson());
            Debug.Log($"[TUNING] wrote {configs.Length} templates to {Folder}");
        }
    }
}
