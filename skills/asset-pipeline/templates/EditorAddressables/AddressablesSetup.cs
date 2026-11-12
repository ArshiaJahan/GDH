// OPTIONAL. Harness.Assets.AddressablesSetup - groups/labels from folders and a batchmode content build.
// Compiles only when com.unity.addressables >= 2.0 is installed (asmdef versionDefines + defineConstraints).
// ⚠ version-sensitive: written against Addressables 2.x (bench: 2.9.1; 6000.3 "released" version 2.10.x).
// Batch: -executeMethod Harness.Assets.AddressablesSetup.BuildContentBatch  (log: "Addressables RESULT: OK|FAIL ...")
#if HARNESS_ADDRESSABLES
using System;
using System.IO;
using UnityEditor;
using UnityEditor.AddressableAssets;
using UnityEditor.AddressableAssets.Build;
using UnityEditor.AddressableAssets.Settings;
using UnityEditor.AddressableAssets.Settings.GroupSchemas;
using UnityEngine;

namespace Harness.Assets
{
    public static class AddressablesSetup
    {
        public static AddressableAssetSettings Settings => AddressableAssetSettingsDefaultObject.GetSettings(true);

        public static AddressableAssetGroup EnsureGroup(string groupName)
        {
            var s = Settings;
            var g = s.FindGroup(groupName);
            if (g == null)
                g = s.CreateGroup(groupName, false, false, true, null, typeof(BundledAssetGroupSchema), typeof(ContentUpdateGroupSchema));
            return g;
        }

        /// <summary>Mark every asset under folder addressable in groupName, address = file name, with label.</summary>
        public static int AddFolder(string folder, string groupName, string label)
        {
            var s = Settings;
            var g = EnsureGroup(groupName);
            int n = 0;
            foreach (var guid in AssetDatabase.FindAssets("", new[] { folder }))
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (AssetDatabase.IsValidFolder(path)) continue;
                var e = s.CreateOrMoveEntry(guid, g, false, false);
                e.address = Path.GetFileNameWithoutExtension(path);
                if (!string.IsNullOrEmpty(label)) e.SetLabel(label, true, true, false);
                n++;
            }
            s.SetDirty(AddressableAssetSettings.ModificationEvent.BatchModification, null, true, true);
            AssetDatabase.SaveAssets();
            return n;
        }

        public static void BuildContentBatch()
        {
            int code = 0;
            try
            {
                AddressableAssetSettings.BuildPlayerContent(out AddressablesPlayerBuildResult result);
                if (!string.IsNullOrEmpty(result.Error))
                {
                    Debug.LogError("Addressables RESULT: FAIL " + result.Error);
                    code = 1;
                }
                else Debug.Log($"Addressables RESULT: OK duration={result.Duration:F1}s output={result.OutputPath}");
            }
            catch (Exception e)
            {
                Debug.LogError("Addressables RESULT: FAIL " + e);
                code = 2;
            }
            BatchExit.Exit(code);
        }
    }
}
#endif
