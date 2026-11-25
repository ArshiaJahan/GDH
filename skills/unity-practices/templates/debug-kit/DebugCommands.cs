using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace GdwKit
{
    /// <summary>Marks a static method as a debug command: [DebugCommand("god", "toggle invulnerability")].</summary>
    [AttributeUsage(AttributeTargets.Method)]
    public sealed class DebugCommandAttribute : Attribute
    {
        public string Name { get; }
        public string Help { get; }

        public DebugCommandAttribute(string name, string help = "")
        {
            Name = name.ToLowerInvariant();
            Help = help;
        }
    }

    /// <summary>
    /// Finds [DebugCommand] static methods in the game's assemblies and runs them from a text line,
    /// e.g. DebugCommands.Run("spawn Grunt 10"). Arguments: int, float, bool, string, enums.
    /// Used by DebugConsole, and by agents through MCP execute_code or -executeMethod.
    /// </summary>
    public static class DebugCommands
    {
        private static Dictionary<string, (MethodInfo method, string help)> _commands;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void ResetStatics() => _commands = null;

        public static IReadOnlyDictionary<string, (MethodInfo method, string help)> All
        {
            get
            {
                if (_commands == null) Discover();
                return _commands;
            }
        }

        private static void Discover()
        {
            _commands = new Dictionary<string, (MethodInfo, string)>();
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                var n = asm.GetName().Name;
                if (n.StartsWith("Unity", StringComparison.Ordinal) || n.StartsWith("System", StringComparison.Ordinal)
                    || n.StartsWith("Mono", StringComparison.Ordinal) || n == "mscorlib" || n == "netstandard"
                    || n.StartsWith("nunit", StringComparison.OrdinalIgnoreCase))
                    continue;
                Type[] types;
                try { types = asm.GetTypes(); }
                catch (ReflectionTypeLoadException e) { types = Array.FindAll(e.Types, t => t != null); }
                foreach (var t in types)
                foreach (var m in t.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
                {
                    var attr = m.GetCustomAttribute<DebugCommandAttribute>();
                    if (attr != null) _commands[attr.Name] = (m, attr.Help);
                }
            }
        }

        /// <summary>Run one command line. Returns the output text (errors start with "error:").</summary>
        public static string Run(string line)
        {
            var parts = Tokenize(line);
            if (parts.Count == 0) return "";
            var name = parts[0].ToLowerInvariant();
            if (!All.TryGetValue(name, out var cmd)) return $"error: unknown command '{name}' (try help)";
            var ps = cmd.method.GetParameters();
            var args = new object[ps.Length];
            for (int i = 0; i < ps.Length; i++)
            {
                if (i + 1 < parts.Count)
                {
                    if (!TryParse(parts[i + 1], ps[i].ParameterType, out args[i]))
                        return $"error: '{parts[i + 1]}' is not a {ps[i].ParameterType.Name} for {ps[i].Name}";
                }
                else if (ps[i].HasDefaultValue) args[i] = ps[i].DefaultValue;
                else return $"error: {name} needs {ps[i].Name} ({ps[i].ParameterType.Name})";
            }
            try
            {
                var result = cmd.method.Invoke(null, args);
                var text = result?.ToString() ?? "ok";
                Debug.Log($"[DEBUGCMD] {line} -> {text}");
                return text;
            }
            catch (TargetInvocationException e)
            {
                return $"error: {e.InnerException?.Message ?? e.Message}";
            }
        }

        private static bool TryParse(string s, Type type, out object value)
        {
            value = null;
            var inv = CultureInfo.InvariantCulture;
            if (type == typeof(string)) { value = s; return true; }
            if (type == typeof(int) && int.TryParse(s, NumberStyles.Integer, inv, out var i)) { value = i; return true; }
            if (type == typeof(float) && float.TryParse(s, NumberStyles.Float, inv, out var f)) { value = f; return true; }
            if (type == typeof(bool))
            {
                if (s == "1" || s.Equals("on", StringComparison.OrdinalIgnoreCase)) { value = true; return true; }
                if (s == "0" || s.Equals("off", StringComparison.OrdinalIgnoreCase)) { value = false; return true; }
                if (bool.TryParse(s, out var b)) { value = b; return true; }
            }
            if (type.IsEnum)
            {
                try { value = Enum.Parse(type, s, true); return true; }
                catch (ArgumentException) { return false; }
            }
            return false;
        }

        private static List<string> Tokenize(string line)
        {
            var list = new List<string>();
            var sb = new StringBuilder();
            bool quoted = false;
            foreach (var c in line ?? "")
            {
                if (c == '"') { quoted = !quoted; continue; }
                if (char.IsWhiteSpace(c) && !quoted)
                {
                    if (sb.Length > 0) { list.Add(sb.ToString()); sb.Clear(); }
                    continue;
                }
                sb.Append(c);
            }
            if (sb.Length > 0) list.Add(sb.ToString());
            return list;
        }

        // ------------------------------------------------------------ built-in commands

        [DebugCommand("help", "list commands")]
        private static string Help()
        {
            var sb = new StringBuilder();
            foreach (var kv in All)
            {
                sb.Append(kv.Key);
                foreach (var p in kv.Value.method.GetParameters()) sb.Append(" <").Append(p.Name).Append('>');
                if (!string.IsNullOrEmpty(kv.Value.help)) sb.Append(" - ").Append(kv.Value.help);
                sb.Append('\n');
            }
            return sb.ToString().TrimEnd();
        }

        [DebugCommand("timescale", "set Time.timeScale (1 = normal)")]
        private static string TimeScale(float scale)
        {
            Time.timeScale = Mathf.Clamp(scale, 0f, 100f);
            return $"timeScale = {Time.timeScale}";
        }

        [DebugCommand("reload", "reload the active scene")]
        private static string Reload()
        {
            var scene = SceneManager.GetActiveScene();
            SceneManager.LoadScene(scene.buildIndex >= 0 ? scene.name : scene.path);
            return $"reloading {scene.name}";
        }
    }
}
