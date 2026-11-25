using System.Diagnostics;
using UnityEngine;

namespace GdwKit
{
    /// <summary>
    /// Debug lines visible in the Scene view (and the Game view with Gizmos on). Calls are compiled out
    /// of release builds, so they can stay in gameplay code.
    /// </summary>
    public static class DebugDraw
    {
        private const int Segments = 32;

        [Conditional("UNITY_EDITOR"), Conditional("DEVELOPMENT_BUILD")]
        public static void Circle(Vector3 center, float radius, Color color, float seconds = 0f, bool flat2D = false)
        {
            Vector3 prev = center + new Vector3(radius, 0f, 0f);
            for (int i = 1; i <= Segments; i++)
            {
                float a = i * Mathf.PI * 2f / Segments;
                Vector3 offset = flat2D
                    ? new Vector3(Mathf.Cos(a) * radius, Mathf.Sin(a) * radius, 0f)
                    : new Vector3(Mathf.Cos(a) * radius, 0f, Mathf.Sin(a) * radius);
                Vector3 next = center + offset;
                UnityEngine.Debug.DrawLine(prev, next, color, seconds);
                prev = next;
            }
        }

        [Conditional("UNITY_EDITOR"), Conditional("DEVELOPMENT_BUILD")]
        public static void Cross(Vector3 at, float size, Color color, float seconds = 0f)
        {
            float h = size * 0.5f;
            UnityEngine.Debug.DrawLine(at - Vector3.right * h, at + Vector3.right * h, color, seconds);
            UnityEngine.Debug.DrawLine(at - Vector3.up * h, at + Vector3.up * h, color, seconds);
            UnityEngine.Debug.DrawLine(at - Vector3.forward * h, at + Vector3.forward * h, color, seconds);
        }

        [Conditional("UNITY_EDITOR"), Conditional("DEVELOPMENT_BUILD")]
        public static void Arrow(Vector3 from, Vector3 to, Color color, float seconds = 0f)
        {
            UnityEngine.Debug.DrawLine(from, to, color, seconds);
            var dir = to - from;
            if (dir.sqrMagnitude < 1e-6f) return;
            var back = -dir.normalized * Mathf.Min(0.25f, dir.magnitude * 0.3f);
            var side = Vector3.Cross(dir, Vector3.up).sqrMagnitude > 1e-6f ? Vector3.Cross(dir, Vector3.up).normalized : Vector3.right;
            UnityEngine.Debug.DrawLine(to, to + back + side * back.magnitude * 0.5f, color, seconds);
            UnityEngine.Debug.DrawLine(to, to + back - side * back.magnitude * 0.5f, color, seconds);
        }

        [Conditional("UNITY_EDITOR"), Conditional("DEVELOPMENT_BUILD")]
        public static void Path(Vector3[] points, Color color, float seconds = 0f)
        {
            if (points == null) return;
            for (int i = 1; i < points.Length; i++) UnityEngine.Debug.DrawLine(points[i - 1], points[i], color, seconds);
        }
    }
}
