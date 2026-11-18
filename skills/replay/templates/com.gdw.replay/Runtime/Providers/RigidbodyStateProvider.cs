using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Gdw.Replay
{
    /// <summary>
    /// Framework provider "unity.physics" for 3D rigidbodies: count plus pose, velocity and sleep state
    /// per tracked subject, written in ordinal id order.
    /// </summary>
    public sealed class RigidbodyStateProvider : IReplayStateProvider
    {
        public static RigidbodyStateProvider Instance { get; } = new RigidbodyStateProvider();

        public string Id => "unity.physics";

        readonly Dictionary<string, Rigidbody> _subjects = new Dictionary<string, Rigidbody>(StringComparer.Ordinal);

        RigidbodyStateProvider() { ReplayRegistry.Instance.Register(Id, this); }

        public void Track(string id, Rigidbody body)
        {
            if (id == null) throw new ArgumentNullException(nameof(id));
            if (body == null) throw new ArgumentNullException(nameof(body));
            _subjects[id] = body;
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
                Rigidbody body = kv.Value;
                writer.WriteVector3(id + ".position", body.position);
                writer.WriteQuaternion(id + ".rotation", body.rotation);
                writer.WriteVector3(id + ".linear_velocity", body.linearVelocity);
                writer.WriteVector3(id + ".angular_velocity", body.angularVelocity);
                writer.WriteBool(id + ".sleeping", body.IsSleeping());
            }
        }
    }
}
