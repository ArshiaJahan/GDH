using System.Globalization;
using System.Text;
using UnityEngine;

namespace Harness.Feel
{
    /// <summary>
    /// One log line per triggered feedback, for play-verify: <c>[FEEL] name=HitStop duration=0.08 nested=0</c>.
    /// Values use the invariant culture so check_criteria.py can parse them. Logging is on in the Editor and
    /// Development builds (Debug.isDebugBuild) and off in release builds; set <see cref="Enabled"/> to override.
    /// <see cref="Count"/> and <see cref="LastName"/> are kept even when logging is off (cheap test hooks).
    /// </summary>
    public static class FeelLog
    {
        public const string Prefix = "[FEEL]";
        public static bool Enabled = true;
        public static int Count { get; private set; }
        public static string LastName { get; private set; }

        static readonly StringBuilder Sb = new StringBuilder(128);

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()
        {
            Enabled = Debug.isDebugBuild;
            Count = 0;
            LastName = null;
        }

        public static void Log(string name, Object context = null) => Log(name, null, context);

        /// <param name="details">Extra "key=value key2=value2" text (no leading space).</param>
        public static void Log(string name, string details, Object context = null)
        {
            Count++;
            LastName = name;
            if (!Enabled) return;
            Sb.Clear().Append(Prefix).Append(" name=").Append(name);
            if (!string.IsNullOrEmpty(details)) Sb.Append(' ').Append(details);
            Debug.Log(Sb.ToString(), context);
        }

        /// <summary>Allocation-light overload: the string is only built when logging is enabled.</summary>
        public static void Log(string name, string k1, float v1, string k2 = null, float v2 = 0f, Object context = null)
        {
            Count++;
            LastName = name;
            if (!Enabled) return;
            Sb.Clear().Append(Prefix).Append(" name=").Append(name);
            Sb.Append(' ').Append(k1).Append('=').Append(F(v1));
            if (k2 != null) Sb.Append(' ').Append(k2).Append('=').Append(F(v2));
            Debug.Log(Sb.ToString(), context);
        }

        public static string F(float v) => v.ToString("0.###", CultureInfo.InvariantCulture);
    }
}
