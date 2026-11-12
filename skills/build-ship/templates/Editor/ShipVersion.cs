// Harness.Ship: version stamping for releases (Unity 6000.3).
//   Unity -batchmode -nographics -quit -projectPath P -executeMethod Harness.Ship.ShipVersion.Set -shipVersion 1.4.0 [-buildNumber 17]
//   Unity -batchmode -nographics -quit -projectPath P -executeMethod Harness.Ship.ShipVersion.Print
//   (headless-ops: unity.sh exec Harness.Ship.ShipVersion.Set -shipVersion 1.4.0). Both are synchronous: run them WITH -quit;
//   a bad version throws, which makes batchmode exit 1. No EditorApplication.Exit (it can crash at startup on 6000.3).
//   The flag is -shipVersion, not -version: Unity's own -version prints the editor version and exits, opening nothing.
// Set writes PlayerSettings.bundleVersion (= Application.version, shared by all platforms) and one integer build
// number to macOS, iOS and Android. Without -buildNumber the build number is max(current)+1.
// ⚠ version-sensitive: PlayerSettings.macOS.buildNumber is not on the 6000.3 bundleVersion docs page; it compiles
// on 6000.3.21f1 and is stored under ProjectSettings.asset buildNumber: Standalone.
// In the editor (MCP) the same three lines can be run with execute_code.
using System;
using System.Globalization;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

namespace Harness.Ship
{
    public static class ShipVersion
    {
        static readonly Regex SemVer = new Regex(@"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$");

        static string Arg(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
                if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase)) return args[i + 1];
            return null;
        }

        static void Say(string message)
        {
            Application.SetStackTraceLogType(LogType.Log, StackTraceLogType.None);
            Debug.Log("[HARNESS] " + message);
        }

        public static string Describe()
        {
            return "VERSION bundleVersion=" + PlayerSettings.bundleVersion
                + " macOS.buildNumber=" + PlayerSettings.macOS.buildNumber
                + " iOS.buildNumber=" + PlayerSettings.iOS.buildNumber
                + " Android.bundleVersionCode=" + PlayerSettings.Android.bundleVersionCode;
        }

        public static void Print()
        {
            Say(Describe());
        }

        /// <summary>Sets the version; usable from batchmode (exits) or from editor code (returns).</summary>
        public static bool Apply(string version, int buildNumber)
        {
            if (!SemVer.IsMatch(version ?? "")) { Say("VERSION FAIL not SemVer MAJOR.MINOR.PATCH: " + version); return false; }
            if (buildNumber <= 0) buildNumber = CurrentBuildNumber() + 1;
            string bn = buildNumber.ToString(CultureInfo.InvariantCulture);
            PlayerSettings.bundleVersion = version;
            PlayerSettings.macOS.buildNumber = bn;
            PlayerSettings.iOS.buildNumber = bn;
            PlayerSettings.Android.bundleVersionCode = buildNumber;
            AssetDatabase.SaveAssets();
            Say(Describe());
            return true;
        }

        public static void Set()
        {
            int bn;
            var bnArg = Arg("-buildNumber");
            if (bnArg == null || !int.TryParse(bnArg, NumberStyles.Integer, CultureInfo.InvariantCulture, out bn)) bn = 0;
            if (!Apply(Arg("-shipVersion"), bn))
                throw new ArgumentException("ShipVersion.Set: -shipVersion must be SemVer MAJOR.MINOR.PATCH, got " + Arg("-shipVersion"));
        }

        static int CurrentBuildNumber()
        {
            int best = Math.Max(0, PlayerSettings.Android.bundleVersionCode), v;
            if (int.TryParse(PlayerSettings.macOS.buildNumber, out v)) best = Math.Max(best, v);
            if (int.TryParse(PlayerSettings.iOS.buildNumber, out v)) best = Math.Max(best, v);
            return best;
        }
    }
}
