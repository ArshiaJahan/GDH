#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;

namespace Gdw.Replay
{
    /// <summary>A single legacy Input Manager read found in project gameplay code.</summary>
    public sealed class LegacyInputFinding
    {
        /// <summary>Project-relative POSIX path, e.g. <c>Assets/Scripts/Player.cs</c>.</summary>
        public string File;
        /// <summary>One-based line number.</summary>
        public int Line;
        /// <summary>The matched call, e.g. <c>Input.GetAxis</c>.</summary>
        public string Call;

        public override string ToString() => File + ":" + Line + " " + Call;
    }

    /// <summary>Result of <see cref="LegacyInputDetector.ScanProject"/>.</summary>
    public sealed class LegacyInputReport
    {
        public bool HasLegacyGameplay;
        /// <summary>ProjectSettings <c>activeInputHandler</c>: 0 old, 1 new, 2 both, -1 unknown.</summary>
        public int ActiveInputHandler = -1;
        public string ActiveInputHandlerName = "unknown";
        public List<LegacyInputFinding> Findings = new List<LegacyInputFinding>();
        /// <summary>Readiness message naming the offending files and calls; empty when ready.</summary>
        public string Message = "";
    }

    /// <summary>
    /// Editor-time readiness scan for gameplay that reads the legacy Input Manager. The replay adapter only
    /// supports Input System gameplay; a mixed project passes silently otherwise. Call from ReplayCommands
    /// before starting a record or replay and surface <see cref="LegacyInputReport.Message"/> as a readiness error.
    /// </summary>
    public static class LegacyInputDetector
    {
        /// <summary>
        /// Readiness-error text for record/replay start: null when the project may proceed, otherwise a message
        /// naming the offending files and calls (decision #2: legacy gameplay input is an error, not a warning).
        /// </summary>
        public static string RefusalMessage(LegacyInputReport report)
        {
            if (report == null || !report.HasLegacyGameplay) return null;
            return "Replay refused: legacy Input Manager gameplay input is not supported. " + report.Message;
        }

        static readonly Regex LegacyQualified = new Regex(
            @"UnityEngine\s*\.\s*Input\s*\.\s*(?<call>[A-Za-z_][A-Za-z0-9_]*)",
            RegexOptions.CultureInvariant);

        static readonly Regex LegacyUnqualified = new Regex(
            @"(?<![A-Za-z0-9_.])Input\s*\.\s*(?<call>GetAxis|GetAxisRaw|GetButton|GetButtonDown|GetButtonUp|GetKey|GetKeyDown|GetKeyUp|GetMouseButton|GetMouseButtonDown|GetMouseButtonUp|GetTouch|GetJoystickNames|GetJoystickButton|mousePosition|mouseScrollDelta|anyKey|anyKeyDown|inputString|touchCount|touches|touchSupported|acceleration|accelerationEventCount|GetAccelerationEvents|gyro|compass|location)\b",
            RegexOptions.CultureInvariant);

        static readonly Regex UsingUnityEngine = new Regex(
            @"^\s*using\s+UnityEngine\s*;", RegexOptions.CultureInvariant);

        static readonly string[] SkippedDirectories = { "Editor", "obj", "bin", ".git", "Library", "Temp" };

        /// <summary>Scans <paramref name="projectRoot"/>/Assets and ProjectSettings/ProjectSettings.asset.</summary>
        public static LegacyInputReport ScanProject(string projectRoot)
        {
            if (string.IsNullOrEmpty(projectRoot)) throw new ArgumentException("project root is required", nameof(projectRoot));
            string root = Path.GetFullPath(projectRoot);
            if (!Directory.Exists(root)) throw new DirectoryNotFoundException("project not found: " + projectRoot);

            var report = new LegacyInputReport();
            ReadActiveInputHandler(root, report);

            string assets = Path.Combine(root, "Assets");
            if (!Directory.Exists(assets)) return report;

            foreach (string file in EnumerateSources(assets))
            {
                ScanFile(root, file, report);
            }

            if (report.Findings.Count > 0)
            {
                report.HasLegacyGameplay = true;
                report.Message = BuildMessage(report);
            }
            else if (report.ActiveInputHandler == 0)
            {
                report.HasLegacyGameplay = true;
                report.Message =
                    "the project's active input handler is the legacy Input Manager, which the replay adapter does not support. " +
                    "Switch Player Settings > Active Input Handling to Input System (or Both) and move gameplay reads to the Input System.";
            }

            return report;
        }

        static IEnumerable<string> EnumerateSources(string assetsRoot)
        {
            var pending = new Stack<string>();
            pending.Push(assetsRoot);
            while (pending.Count > 0)
            {
                string dir = pending.Pop();
                if (IsSkippedDirectory(dir)) continue;

                string[] files;
                string[] dirs;
                try
                {
                    files = Directory.GetFiles(dir, "*.cs", SearchOption.TopDirectoryOnly);
                    dirs = Directory.GetDirectories(dir, "*", SearchOption.TopDirectoryOnly);
                }
                catch (UnauthorizedAccessException) { continue; }
                catch (DirectoryNotFoundException) { continue; }

                for (int i = 0; i < files.Length; i++) yield return files[i];
                for (int i = 0; i < dirs.Length; i++) pending.Push(dirs[i]);
            }
        }

        static bool IsSkippedDirectory(string path)
        {
            string name = Path.GetFileName(path);
            for (int i = 0; i < SkippedDirectories.Length; i++)
            {
                if (string.Equals(name, SkippedDirectories[i], StringComparison.OrdinalIgnoreCase)) return true;
            }
            return false;
        }

        static void ScanFile(string root, string file, LegacyInputReport report)
        {
            string[] lines;
            try { lines = File.ReadAllLines(file); }
            catch (IOException) { return; }
            catch (UnauthorizedAccessException) { return; }

            bool hasUnityEngineUsing = false;
            for (int i = 0; i < lines.Length; i++)
            {
                if (UsingUnityEngine.IsMatch(lines[i])) { hasUnityEngineUsing = true; break; }
            }

            // ENABLE_LEGACY_INPUT_MANAGER is defined for activeInputHandler 0 and 2 only.
            bool legacySymbolActive = report.ActiveInputHandler != 1;
            int legacyIfDepth = -1;
            int depth = 0;

            for (int i = 0; i < lines.Length; i++)
            {
                string line = lines[i];
                string trimmed = line.TrimStart();

                if (trimmed.StartsWith("#if", StringComparison.Ordinal))
                {
                    if (trimmed.IndexOf("ENABLE_LEGACY_INPUT_MANAGER", StringComparison.Ordinal) >= 0)
                        legacyIfDepth = depth;
                    depth++;
                    continue;
                }
                if (trimmed.StartsWith("#endif", StringComparison.Ordinal))
                {
                    depth = Math.Max(0, depth - 1);
                    if (legacyIfDepth == depth) legacyIfDepth = -1;
                    continue;
                }
                if (legacyIfDepth >= 0 && depth > legacyIfDepth && !legacySymbolActive) continue;
                if (trimmed.StartsWith("//", StringComparison.Ordinal) || trimmed.StartsWith("*", StringComparison.Ordinal)) continue;

                int comment = line.IndexOf("//", StringComparison.Ordinal);
                string code = comment >= 0 ? line.Substring(0, comment) : line;

                Match qualified = LegacyQualified.Match(code);
                if (qualified.Success)
                {
                    AddFinding(root, file, i + 1, "UnityEngine.Input." + qualified.Groups["call"].Value, report);
                    continue;
                }

                if (!hasUnityEngineUsing) continue;
                Match unqualified = LegacyUnqualified.Match(code);
                if (!unqualified.Success) continue;
                AddFinding(root, file, i + 1, "Input." + unqualified.Groups["call"].Value, report);
            }
        }

        static void AddFinding(string root, string file, int line, string call, LegacyInputReport report)
        {
            string relative = Path.GetRelativePath(root, file).Replace('\\', '/');
            report.Findings.Add(new LegacyInputFinding { File = relative, Line = line, Call = call });
        }

        static void ReadActiveInputHandler(string root, LegacyInputReport report)
        {
            string path = Path.Combine(root, "ProjectSettings", "ProjectSettings.asset");
            if (!File.Exists(path)) return;

            string[] lines;
            try { lines = File.ReadAllLines(path); }
            catch (IOException) { return; }
            catch (UnauthorizedAccessException) { return; }

            for (int i = 0; i < lines.Length; i++)
            {
                string line = lines[i].Trim();
                if (!line.StartsWith("activeInputHandler:", StringComparison.Ordinal)) continue;
                string value = line.Substring("activeInputHandler:".Length).Trim();
                if (!int.TryParse(value, out int handler)) continue;
                report.ActiveInputHandler = handler;
                report.ActiveInputHandlerName = handler == 0 ? "old" : handler == 1 ? "new" : handler == 2 ? "both" : "unknown";
                return;
            }
        }

        static string BuildMessage(LegacyInputReport report)
        {
            int shown = Math.Min(report.Findings.Count, 5);
            var parts = new List<string>(shown);
            for (int i = 0; i < shown; i++) parts.Add(report.Findings[i].ToString());
            string list = string.Join(", ", parts);
            if (report.Findings.Count > shown) list += ", ... (" + report.Findings.Count + " total)";
            return "legacy Input Manager gameplay input found (activeInputHandler=" +
                   report.ActiveInputHandler + "): " + list +
                   ". Gameplay must use the Input System so record/replay can drive virtual devices.";
        }
    }
}
#endif
