// Harness.Assets.ImportRules - folder-based import invariants, enforced on every (re)import. Unity 6000.3.
//   Assets/Art/Sprites/**  : Sprite, Point filter, uncompressed, no mipmaps, PPU = ImportRuleConfig.PixelsPerUnit, Clamp
//   Assets/Audio/SFX/**    : Decompress On Load + ADPCM, preload, mono on first import
//   Assets/Audio/Music/**  : Streaming + Vorbis (quality 0.7), no preload, load in background
// Opt out per folder: put assets under a "_NoRules" folder. Disable globally: env HARNESS_IMPORT_RULES_OFF=1.
// Keep scripts/asset_audit.py rules in sync with ImportRuleConfig.
using System;
using UnityEditor;
using UnityEngine;

namespace Harness.Assets
{
    public static class ImportRuleConfig
    {
        public const string SpritesRoot = "Assets/Art/Sprites/";
        public const string SfxRoot = "Assets/Audio/SFX/";
        public const string MusicRoot = "Assets/Audio/Music/";
        public const string OptOutFolder = "/_NoRules/";
        /// <summary>One value for the whole game: tile size in pixels (16 or 32 for most pixel art).</summary>
        public const int PixelsPerUnit = 16;
        public const float MusicVorbisQuality = 0.7f;
        public static readonly string[] Platforms = { "Standalone", "WebGL", "iPhone", "Android" };

        public static bool Enabled => Environment.GetEnvironmentVariable("HARNESS_IMPORT_RULES_OFF") != "1";

        public static bool Applies(string assetPath, string root) =>
            Enabled && assetPath.StartsWith(root, StringComparison.Ordinal) && !assetPath.Contains(OptOutFolder);
    }

    public sealed class ImportRules : AssetPostprocessor
    {
        // Run after other postprocessors so these invariants win.
        public override int GetPostprocessOrder() => 1000;

        void OnPreprocessTexture()
        {
            if (!ImportRuleConfig.Applies(assetPath, ImportRuleConfig.SpritesRoot)) return;
            var ti = (TextureImporter)assetImporter;
            bool firstImport = ti.importSettingsMissing;

            ti.textureType = TextureImporterType.Sprite;
            if (firstImport) ti.spriteImportMode = SpriteImportMode.Single; // artists may switch sheets to Multiple
            ti.filterMode = FilterMode.Point;
            ti.textureCompression = TextureImporterCompression.Uncompressed;
            ti.mipmapEnabled = false;
            ti.spritePixelsPerUnit = ImportRuleConfig.PixelsPerUnit;
            ti.alphaIsTransparency = true;
            ti.wrapMode = TextureWrapMode.Clamp;
            ti.npotScale = TextureImporterNPOTScale.None;

            foreach (var platform in ImportRuleConfig.Platforms)
            {
                var ps = ti.GetPlatformTextureSettings(platform);
                if (ps.overridden && ps.textureCompression != TextureImporterCompression.Uncompressed)
                    Debug.LogWarning($"[ImportRules] {assetPath}: {platform} override compresses a pixel-art sprite; remove the override");
            }
        }

        void OnPreprocessAudio()
        {
            bool sfx = ImportRuleConfig.Applies(assetPath, ImportRuleConfig.SfxRoot);
            bool music = ImportRuleConfig.Applies(assetPath, ImportRuleConfig.MusicRoot);
            if (!sfx && !music) return;
            var ai = (AudioImporter)assetImporter;
            bool firstImport = ai.importSettingsMissing;
            var s = ai.defaultSampleSettings;

            if (sfx)
            {
                s.loadType = AudioClipLoadType.DecompressOnLoad;
                s.compressionFormat = AudioCompressionFormat.ADPCM;
                s.preloadAudioData = true;
                ai.loadInBackground = false;
                if (firstImport) ai.forceToMono = true; // 2D SFX rarely need stereo; artists may turn it back off
            }
            else
            {
                s.loadType = AudioClipLoadType.Streaming;
                s.compressionFormat = AudioCompressionFormat.Vorbis;
                s.quality = ImportRuleConfig.MusicVorbisQuality;
                s.preloadAudioData = false;
                ai.loadInBackground = true;
            }
            ai.defaultSampleSettings = s;

            foreach (var platform in ImportRuleConfig.Platforms)
                if (ai.ContainsSampleSettingsOverride(platform))
                    Debug.LogWarning($"[ImportRules] {assetPath}: {platform} audio override present; check it matches the folder rule");
        }

        [MenuItem("Tools/Harness/Assets/Reimport Rule Folders")]
        public static void ReimportRuleFolders()
        {
            foreach (var root in new[] { ImportRuleConfig.SpritesRoot, ImportRuleConfig.SfxRoot, ImportRuleConfig.MusicRoot })
            {
                var folder = root.TrimEnd('/');
                if (AssetDatabase.IsValidFolder(folder))
                    AssetDatabase.ImportAsset(folder, ImportAssetOptions.ImportRecursive | ImportAssetOptions.ForceUpdate);
            }
        }

        /// <summary>Batchmode: -executeMethod Harness.Assets.ImportRules.ReimportRuleFoldersBatch</summary>
        public static void ReimportRuleFoldersBatch()
        {
            ReimportRuleFolders();
            Debug.Log("ImportRules RESULT: OK reimported rule folders");
            BatchExit.Exit(0);
        }
    }
}
