using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Gdw.Replay
{
    /// <summary>
    /// Framework provider "unity.transforms": count plus, per tracked subject, position/rotation/scale/active.
    /// Subjects are keyed by a stable <see cref="ReplayIdentity"/> string and written in ordinal id order.
    /// </summary>
    public sealed class TransformStateProvider : IReplayStateProvider
    {
        public static TransformStateProvider Instance { get; } = new TransformStateProvider();

        public string Id => "unity.transforms";

        readonly Dictionary<string, Transform> _subjects = new Dictionary<string, Transform>(StringComparer.Ordinal);

        TransformStateProvider() { ReplayRegistry.Instance.Register(Id, this); }

        public void Track(string id, Transform transform)
        {
            if (id == null) throw new ArgumentNullException(nameof(id));
            if (transform == null) throw new ArgumentNullException(nameof(transform));
            _subjects[id] = transform;
        }

        public void Untrack(string id)
        {
            if (id == null) throw new ArgumentNullException(nameof(id));
            _subjects.Remove(id);
        }

        public void WriteState(StateWriter writer)
        {
            writer.WriteUInt32("count", (uint)_subjects.Count);
            foreach (var kv in _subjects.OrderBy(k => k.Key, StringComparer.Ordinal))
            {
                string id = kv.Key;
                Transform t = kv.Value;
                writer.WriteVector3(id + ".position", t.position);
                writer.WriteQuaternion(id + ".rotation", t.rotation);
                writer.WriteVector3(id + ".scale", t.localScale);
                writer.WriteBool(id + ".active", t.gameObject.activeSelf);
            }
        }
    }
}
