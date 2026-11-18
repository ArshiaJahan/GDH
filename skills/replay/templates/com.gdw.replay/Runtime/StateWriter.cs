using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using UnityEngine;

namespace Gdw.Replay
{
    /// <summary>
    /// Builds one provider's canonical payload (gdw-replay-state/1): FIELD_COUNT:u32, then fields
    /// sorted by name (ASCII ordinal), each NAME_LEN:u16 + UTF-8 name + TAG:u8 + value bytes.
    /// Integers are little-endian two's complement; floats/doubles keep their raw IEEE bits.
    /// </summary>
    public sealed class StateWriter
    {
        struct Entry
        {
            public string Name;
            public byte Tag;
            public byte[] Value;
        }

        [StructLayout(LayoutKind.Explicit)]
        struct FloatBits { [FieldOffset(0)] public float Value; [FieldOffset(0)] public int Bits; }

        [StructLayout(LayoutKind.Explicit)]
        struct DoubleBits { [FieldOffset(0)] public double Value; [FieldOffset(0)] public long Bits; }

        readonly List<Entry> _entries = new List<Entry>();
        readonly HashSet<string> _names = new HashSet<string>(StringComparer.Ordinal);

        public int FieldCount => _entries.Count;

        static void ValidateName(string name)
        {
            if (name == null) throw new ArgumentNullException(nameof(name));
            if (name.Length == 0 || name.Length > 128) throw new ReplayStateException("invalid field name: " + name);
            char c = name[0];
            bool firstOk = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
            if (!firstOk) throw new ReplayStateException("invalid field name: " + name);
            for (int i = 1; i < name.Length; i++)
            {
                c = name[i];
                bool ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '.' || c == '-';
                if (!ok) throw new ReplayStateException("invalid field name: " + name);
            }
        }

        void Add(string name, byte tag, byte[] value)
        {
            ValidateName(name);
            if (!_names.Add(name)) throw new ReplayStateException("duplicate field name: " + name);
            _entries.Add(new Entry { Name = name, Tag = tag, Value = value });
        }

        public void WriteBool(string name, bool value) => Add(name, 0x01, new[] { value ? (byte)1 : (byte)0 });

        public void WriteInt32(string name, int value) => Add(name, 0x02, Digest.I32(value));

        public void WriteUInt32(string name, uint value) => Add(name, 0x03, Digest.U32(value));

        public void WriteInt64(string name, long value) => Add(name, 0x04, Digest.I64(value));

        public void WriteUInt64(string name, ulong value) => Add(name, 0x05, Digest.U64(value));

        public void WriteFloat(string name, float value)
        {
            if (float.IsNaN(value)) throw new ReplayStateException("NaN is not allowed in canonical state: " + name);
            Add(name, 0x06, Digest.U32(unchecked((uint)new FloatBits { Value = value }.Bits)));
        }

        public void WriteDouble(string name, double value)
        {
            if (double.IsNaN(value)) throw new ReplayStateException("NaN is not allowed in canonical state: " + name);
            Add(name, 0x07, Digest.U64(unchecked((ulong)new DoubleBits { Value = value }.Bits)));
        }

        public void WriteString(string name, string value)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(value ?? "");
            Add(name, 0x08, Digest.Concat(Digest.U32((uint)bytes.Length), bytes));
        }

        public void WriteBytes(string name, ReadOnlySpan<byte> value)
        {
            byte[] bytes = value.ToArray();
            Add(name, 0x09, Digest.Concat(Digest.U32((uint)bytes.Length), bytes));
        }

        public void WriteVector3(string name, Vector3 value)
        {
            if (float.IsNaN(value.x) || float.IsNaN(value.y) || float.IsNaN(value.z))
                throw new ReplayStateException("NaN is not allowed in canonical state: " + name);
            Add(name, 0x0A, Digest.Concat(
                Digest.U32(unchecked((uint)new FloatBits { Value = value.x }.Bits)),
                Digest.U32(unchecked((uint)new FloatBits { Value = value.y }.Bits)),
                Digest.U32(unchecked((uint)new FloatBits { Value = value.z }.Bits))));
        }

        public void WriteQuaternion(string name, Quaternion value)
        {
            if (float.IsNaN(value.x) || float.IsNaN(value.y) || float.IsNaN(value.z) || float.IsNaN(value.w))
                throw new ReplayStateException("NaN is not allowed in canonical state: " + name);
            Add(name, 0x0B, Digest.Concat(
                Digest.U32(unchecked((uint)new FloatBits { Value = value.x }.Bits)),
                Digest.U32(unchecked((uint)new FloatBits { Value = value.y }.Bits)),
                Digest.U32(unchecked((uint)new FloatBits { Value = value.z }.Bits)),
                Digest.U32(unchecked((uint)new FloatBits { Value = value.w }.Bits))));
        }

        public byte[] ToBytes()
        {
            _entries.Sort((a, b) => StringComparer.Ordinal.Compare(a.Name, b.Name));
            var result = new List<byte>();
            result.AddRange(Digest.U32((uint)_entries.Count));
            for (int i = 0; i < _entries.Count; i++)
            {
                var entry = _entries[i];
                byte[] name = Encoding.UTF8.GetBytes(entry.Name);
                result.AddRange(Digest.U16((ushort)name.Length));
                result.AddRange(name);
                result.Add(entry.Tag);
                result.AddRange(entry.Value);
            }
            return result.ToArray();
        }
    }
}
