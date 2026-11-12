// Harness.Assets.PresetSetup - creates importer Presets and registers them as Preset Manager defaults with folder filters.
// Presets = DEFAULTS applied when an asset is first imported (artists may change them later).
// ImportRules = INVARIANTS enforced on every import. Use both, or only ImportRules if nobody edits import settings by hand.
// Menu:  Tools/Harness/Assets/Create Import Presets + Defaults
// Batch: -executeMethod Harness.Assets.PresetSetup.CreateAllBatch  (log: "PresetSetup RESULT: OK presets=3")
// ⚠ version-sensitive: defaults are set with Preset.Get/SetDefaultPresetsForType (UnityEditor.Presets.PresetManager is
//   internal in 6000.3 -> CS0122). The filter syntax glob:"<path>/**" is what the Preset Manager UI writes; confirmed on
//   6000.3.21f1 by importing new files under the filtered folders with ImportRules disabled (HARNESS_IMPORT_RULES_OFF=1).
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Presets;
using UnityEngine;

namespace Harness.Assets
{
    public static class PresetSetup
    {
        public const string PresetRoot = "Assets/Settings/Presets";
        const string TempFolder = "Assets/__HarnessPresetTemp";

        [MenuItem("Tools/Harness/Assets/Create Import Presets + Defaults")]
        public static void CreateAll()
        {
            Directory.CreateDirectory(PresetRoot);
            Directory.CreateDirectory(TempFolder);
            try
            {
                var t = new Texture2D(4, 4);
                File.WriteAllBytes(TempFolder + "/tmp.png", t.EncodeToPNG());
                UnityEngine.Object.DestroyImmediate(t);
                File.WriteAllBytes(TempFolder + "/tmp.wav", SilentWav(0.05f));
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

                var ti = (TextureImporter)AssetImporter.GetAtPath(TempFolder + "/tmp.png");
                ti.textureType = TextureImporterType.Sprite;
                ti.spriteImportMode = SpriteImportMode.Single;
                ti.filterMode = FilterMode.Point;
                ti.textureCompression = TextureImporterCompression.Uncompressed;
                ti.mipmapEnabled = false;
                ti.spritePixelsPerUnit = ImportRuleConfig.PixelsPerUnit;
                ti.alphaIsTransparency = true;
                ti.wrapMode = TextureWrapMode.Clamp;
                ti.npotScale = TextureImporterNPOTScale.None;
                var pixel = Save(ti, "Texture_PixelSprite");

                var ai = (AudioImporter)AssetImporter.GetAtPath(TempFolder + "/tmp.wav");
                var s = ai.defaultSampleSettings;
                s.loadType = AudioClipLoadType.DecompressOnLoad;
                s.compressionFormat = AudioCompressionFormat.ADPCM;
                s.preloadAudioData = true;
                ai.defaultSampleSettings = s;
                ai.forceToMono = true;
                ai.loadInBackground = false;
                var sfx = Save(ai, "Audio_SFX");

                s.loadType = AudioClipLoadType.Streaming;
                s.compressionFormat = AudioCompressionFormat.Vorbis;
                s.quality = ImportRuleConfig.MusicVorbisQuality;
                s.preloadAudioData = false;
                ai.defaultSampleSettings = s;
                ai.forceToMono = false;
                ai.loadInBackground = true;
                var music = Save(ai, "Audio_Music");

                SetDefault(pixel, "Assets/Art/Sprites");
                SetDefault(sfx, "Assets/Audio/SFX");
                SetDefault(music, "Assets/Audio/Music");
            }
            finally
            {
                AssetDatabase.DeleteAsset(TempFolder); // our own temp folder only
            }
            AssetDatabase.SaveAssets();
        }

        public static void CreateAllBatch()
        {
            int code = 0;
            try
            {
                CreateAll();
                Debug.Log("PresetSetup RESULT: OK presets=3 root=" + PresetRoot);
            }
            catch (Exception e)
            {
                Debug.LogError("PresetSetup RESULT: FAIL " + e);
                code = 1;
            }
            BatchExit.Exit(code);
        }

        /// <summary>Create the preset asset from source, or update the existing one in place (keeps its GUID).</summary>
        static Preset Save(UnityEngine.Object source, string name)
        {
            string path = $"{PresetRoot}/{name}.preset";
            var existing = AssetDatabase.LoadAssetAtPath<Preset>(path);
            if (existing != null)
            {
                if (!existing.UpdateProperties(source)) throw new InvalidOperationException("UpdateProperties failed for " + path);
                EditorUtility.SetDirty(existing);
                return existing;
            }
            var preset = new Preset(source);
            AssetDatabase.CreateAsset(preset, path);
            return preset;
        }

        /// <summary>Insert (or replace) the default preset for folder/**; keeps other filters intact.</summary>
        public static void SetDefault(Preset preset, string folder)
        {
            string filter = $"glob:\"{folder}/**\"";
            var type = preset.GetPresetType();
            var list = Preset.GetDefaultPresetsForType(type)
                .Where(d => d.filter != filter && d.preset != preset)
                .ToList();
            list.Insert(0, new DefaultPreset(filter, preset));
            if (!Preset.SetDefaultPresetsForType(type, list.ToArray()))
                throw new InvalidOperationException("SetDefaultPresetsForType failed for " + preset.name);
        }

        static byte[] SilentWav(float seconds, int rate = 44100)
        {
            int samples = Mathf.Max(1, (int)(seconds * rate));
            using (var ms = new MemoryStream())
            using (var w = new BinaryWriter(ms))
            {
                w.Write(new[] { 'R', 'I', 'F', 'F' }); w.Write(36 + samples * 2); w.Write(new[] { 'W', 'A', 'V', 'E' });
                w.Write(new[] { 'f', 'm', 't', ' ' }); w.Write(16); w.Write((short)1); w.Write((short)1);
                w.Write(rate); w.Write(rate * 2); w.Write((short)2); w.Write((short)16);
                w.Write(new[] { 'd', 'a', 't', 'a' }); w.Write(samples * 2);
                for (int i = 0; i < samples; i++) w.Write((short)0);
                return ms.ToArray();
            }
        }
    }
}
