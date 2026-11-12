// Harness.Assets.AtlasSetup - one Sprite Atlas v2 (.spriteatlasv2) per sprite folder, pixel-art packing, included in build.
//   Assets/Art/Sprites/<Folder>/**  ->  Assets/Art/Atlases/<Folder>.spriteatlasv2
// Menu:  Tools/Harness/Assets/Create Or Update Folder Atlases, Tools/Harness/Assets/Pack All Atlases
// Batch: -executeMethod Harness.Assets.AtlasSetup.SetupAndPackBatch  (log: "AtlasSetup RESULT: OK atlases=N sprites=M")
// ⚠ version-sensitive: Sprite Atlas V2 must be enabled (Editor Settings > Sprite Atlas Mode); this sets SpriteAtlasV2.
//   The V1 -> V2 project upgrade cannot be undone.
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.U2D;
using UnityEngine;
using UnityEngine.U2D;
using Object = UnityEngine.Object;

namespace Harness.Assets
{
    public static class AtlasSetup
    {
        public const string SpritesRoot = "Assets/Art/Sprites";
        public const string AtlasRoot = "Assets/Art/Atlases";
        public const int Padding = 4;
        public const int MaxSize = 2048;

        [MenuItem("Tools/Harness/Assets/Create Or Update Folder Atlases")]
        public static List<string> CreateOrUpdateFolderAtlases()
        {
            EnsureV2();
            var made = new List<string>();
            if (!AssetDatabase.IsValidFolder(SpritesRoot)) return made;
            Directory.CreateDirectory(AtlasRoot);
            AssetDatabase.Refresh();

            foreach (var folder in AssetDatabase.GetSubFolders(SpritesRoot))
            {
                string atlasPath = $"{AtlasRoot}/{Path.GetFileName(folder)}.spriteatlasv2";
                var folderAsset = AssetDatabase.LoadAssetAtPath<DefaultAsset>(folder);
                SpriteAtlasAsset atlas = File.Exists(atlasPath) ? SpriteAtlasAsset.Load(atlasPath) : new SpriteAtlasAsset();
                if (!File.Exists(atlasPath)) atlas.Add(new Object[] { folderAsset }); // folder entry: picks up new sprites automatically
                SpriteAtlasAsset.Save(atlas, atlasPath);
                AssetDatabase.ImportAsset(atlasPath, ImportAssetOptions.ForceSynchronousImport);
                ConfigureImporter(atlasPath);
                made.Add(atlasPath);
            }
            AssetDatabase.SaveAssets();
            return made;
        }

        static void ConfigureImporter(string atlasPath)
        {
            var imp = AssetImporter.GetAtPath(atlasPath) as SpriteAtlasImporter;
            if (imp == null) throw new InvalidOperationException("No SpriteAtlasImporter for " + atlasPath);
            imp.packingSettings = new SpriteAtlasPackingSettings
            {
                blockOffset = 1,
                padding = Padding,          // avoids bleeding between point-filtered sprites
                enableRotation = false,     // rotation breaks pixel alignment for 2D
                enableTightPacking = false, // tight packing + point filter can clip edge pixels
                enableAlphaDilation = false,
            };
            imp.textureSettings = new SpriteAtlasTextureSettings
            {
                readable = false,
                generateMipMaps = false,
                sRGB = true,
                filterMode = FilterMode.Point,
                anisoLevel = 0,
            };
            var ps = imp.GetPlatformSettings("DefaultTexturePlatform");
            ps.maxTextureSize = MaxSize;
            ps.textureCompression = TextureImporterCompression.Uncompressed;
            ps.format = TextureImporterFormat.Automatic;
            imp.SetPlatformSettings(ps);
            imp.includeInBuild = true;
            imp.SaveAndReimport();
        }

        public static void EnsureV2()
        {
            if (EditorSettings.spritePackerMode != SpritePackerMode.SpriteAtlasV2)
                EditorSettings.spritePackerMode = SpritePackerMode.SpriteAtlasV2;
        }

        [MenuItem("Tools/Harness/Assets/Pack All Atlases")]
        public static void PackAll()
        {
            EnsureV2();
            SpriteAtlasUtility.PackAllAtlases(EditorUserBuildSettings.activeBuildTarget, false);
        }

        /// <summary>Returns (atlases, total sprites, empty atlas paths) for every atlas under Assets/.</summary>
        public static (int atlases, int sprites, List<string> empty) Inspect()
        {
            int count = 0, sprites = 0;
            var empty = new List<string>();
            foreach (var guid in AssetDatabase.FindAssets("t:SpriteAtlas", new[] { "Assets" }))
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                var atlas = AssetDatabase.LoadAssetAtPath<SpriteAtlas>(path);
                if (atlas == null) continue;
                count++;
                sprites += atlas.spriteCount;
                if (atlas.spriteCount == 0) empty.Add(path);
            }
            return (count, sprites, empty);
        }

        public static void SetupAndPackBatch()
        {
            int code = 0;
            try
            {
                CreateOrUpdateFolderAtlases();
                PackAll();
                var (atlases, sprites, empty) = Inspect();
                foreach (var e in empty) Debug.LogWarning("AtlasSetup EMPTY " + e);
                bool ok = atlases > 0 && empty.Count == 0;
                Debug.Log($"AtlasSetup RESULT: {(ok ? "OK" : "FAIL")} atlases={atlases} sprites={sprites} empty={empty.Count} mode={EditorSettings.spritePackerMode}");
                code = ok ? 0 : 1;
            }
            catch (Exception e)
            {
                Debug.LogError("AtlasSetup RESULT: FAIL " + e);
                code = 2;
            }
            BatchExit.Exit(code);
        }
    }
}
