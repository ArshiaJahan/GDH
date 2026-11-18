using System;
using System.Security.Cryptography;
using System.Text;

namespace Gdw.Replay
{
    /// <summary>
    /// Little-endian binary helpers and SHA-256 used by the canonical state encoding and the archive.
    /// The record/replay format is explicitly little-endian regardless of host endianness.
    /// </summary>
    internal static class Digest
    {
        public static byte[] Utf8(string s) => Encoding.UTF8.GetBytes(s ?? "");

        public static byte[] U16(ushort v) => new[] { (byte)v, (byte)(v >> 8) };

        public static byte[] U32(uint v) => new[] { (byte)v, (byte)(v >> 8), (byte)(v >> 16), (byte)(v >> 24) };

        public static byte[] U64(ulong v)
        {
            var b = new byte[8];
            for (int i = 0; i < 8; i++)
            {
                b[i] = (byte)v;
                v >>= 8;
            }
            return b;
        }

        public static byte[] I32(int v) => U32(unchecked((uint)v));

        public static byte[] I64(long v) => U64(unchecked((ulong)v));

        public static byte[] Concat(params byte[][] parts)
        {
            int total = 0;
            for (int i = 0; i < parts.Length; i++) total += parts[i]?.Length ?? 0;
            var result = new byte[total];
            int offset = 0;
            for (int i = 0; i < parts.Length; i++)
            {
                var p = parts[i];
                if (p == null) continue;
                Buffer.BlockCopy(p, 0, result, offset, p.Length);
                offset += p.Length;
            }
            return result;
        }

        public static byte[] Sha256(byte[] data)
        {
            using (var sha = SHA256.Create())
                return sha.ComputeHash(data);
        }

        public static string Sha256Hex(byte[] data)
        {
            byte[] hash = Sha256(data);
            var sb = new StringBuilder(hash.Length * 2);
            for (int i = 0; i < hash.Length; i++) sb.Append(hash[i].ToString("x2"));
            return sb.ToString();
        }
    }
}
