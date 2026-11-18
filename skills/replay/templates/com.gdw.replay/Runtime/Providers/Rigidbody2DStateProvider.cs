using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Gdw.Replay
{
    /// <summary>
    /// Framework provider "unity.physics2d" for 2D rigidbodies. Mirrors unity.physics; the 2D scalar
    /// rotation and angular velocity are encoded as F32, and Vector2 fields as VEC3 with z = 0.
    /// </summary>
    public sealed class Rigidbody2DStateProvider : IReplayStateProvider
    {
        public static Rigidbody2DStateProvider Instance { get; } = new Rigidbody2DStateProvider();

        public string Id => "unity.physics2d";

        readonly Dictionary<string, Rigidbody2D> _subjects = new Dictionary<string, Rigidbody2D>(StringComparer.Ordinal);

        Rigidbody2DStateProvider() { ReplayRegistry.Instance.Register(Id, this); }

        public void Track(string id, Rigidbody2D body)
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
                Rigidbody2D body = kv.Value;
                writer.WriteVector3(id + ".position", new Vector3(body.position.x, body.position.y, 0f));
                writer.WriteFloat(id + ".rotation", body.rotation);
                writer.WriteVector3(id + ".linear_velocity", new Vector3(body.linearVelocity.x, body.linearVelocity.y, 0f));
                writer.WriteFloat(id + ".angular_velocity", body.angularVelocity);
                writer.WriteBool(id + ".sleeping", body.IsSleeping());
            }
        }
    }
}
