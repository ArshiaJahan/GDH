// Harness.Headless: command-line argument helper for -executeMethod entry points (Unity 6000.3).
// Reads Environment.GetCommandLineArgs(). Names are matched case-insensitively, with or without the leading '-'.
using System;
using System.Collections.Generic;
using System.Globalization;

namespace Harness.Headless
{
    public static class HarnessArgs
    {
        static string[] s_Args;

        /// <summary>The process arguments (overridable for tests).</summary>
        public static string[] Args
        {
            get { return s_Args ?? (s_Args = Environment.GetCommandLineArgs()); }
            set { s_Args = value; }
        }

        static bool Matches(string arg, string name)
        {
            if (string.IsNullOrEmpty(arg) || arg[0] != '-') return false;
            return string.Equals(arg.TrimStart('-'), name.TrimStart('-'), StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>True when the flag is present (e.g. Has("dev") for -dev).</summary>
        public static bool Has(string name)
        {
            foreach (var a in Args) if (Matches(a, name)) return true;
            return false;
        }

        /// <summary>Value after the last occurrence of -name, or fallback when absent or followed by another flag.</summary>
        public static string Get(string name, string fallback = null)
        {
            var args = Args;
            string value = fallback;
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (!Matches(args[i], name)) continue;
                var next = args[i + 1];
                if (next.Length > 1 && next[0] == '-' && !char.IsDigit(next[1])) continue; // another flag
                value = next;
            }
            return value;
        }

        public static int GetInt(string name, int fallback)
        {
            int v;
            var s = Get(name);
            return s != null && int.TryParse(s, NumberStyles.Integer, CultureInfo.InvariantCulture, out v) ? v : fallback;
        }

        /// <summary>All values of -name (repeatable), each split on ';' (and on newlines). Empty entries dropped.</summary>
        public static List<string> GetList(string name)
        {
            var result = new List<string>();
            var args = Args;
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (!Matches(args[i], name)) continue;
                foreach (var part in args[i + 1].Split(new[] { ';', '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries))
                {
                    var p = part.Trim();
                    if (p.Length > 0) result.Add(p);
                }
            }
            return result;
        }
    }
}
