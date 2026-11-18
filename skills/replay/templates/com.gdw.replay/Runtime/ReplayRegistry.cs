using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

namespace Gdw.Replay
{
    /// <summary>Aggregate and per-provider hashes for one checkpoint.</summary>
    public readonly struct ReplayHashes
    {
        public string Aggregate { get; }
        public IReadOnlyDictionary<string, string> Providers { get; }

        public ReplayHashes(string aggregate, IReadOnlyDictionary<string, string> providers)
        {
            Aggregate = aggregate;
            Providers = providers;
        }
    }

    /// <summary>
    /// Holds registered state providers and snapshots, and computes the canonical state hash
    /// (gdw-replay-state/1): "GDWSTATE" + VERSION:u16(1) + COUNT:u32 + provider blocks in ID order.
    /// </summary>
    public sealed class ReplayRegistry
    {
        static readonly ReplayRegistry _instance = new ReplayRegistry();
        public static ReplayRegistry Instance => _instance;

        readonly Dictionary<string, IReplayStateProvider> _providers = new Dictionary<string, IReplayStateProvider>(StringComparer.Ordinal);
        readonly Dictionary<string, IReplaySnapshot> _snapshots = new Dictionary<string, IReplaySnapshot>(StringComparer.Ordinal);

        internal ReplayRegistry() { }

        public void Register(string id, IReplayStateProvider provider)
        {
            if (id == null) throw new ArgumentNullException(nameof(id));
            if (provider == null) throw new ArgumentNullException(nameof(provider));
            _providers[id] = provider;
        }

        public void Unregister(string id)
        {
            if (id == null) throw new ArgumentNullException(nameof(id));
            _providers.Remove(id);
        }

        public bool IsRegistered(string id) => id != null && _providers.ContainsKey(id);

        public IReadOnlyList<string> Ids => _providers.Keys.OrderBy(x => x, StringComparer.Ordinal).ToList();

        public string ComputeHash(string id)
        {
            if (!_providers.TryGetValue(id, out var provider))
                throw new ReplayStateException("unknown provider: " + id);
            return Digest.Sha256Hex(BuildBlock(id, provider));
        }

        public ReplayHashes ComputeAll()
        {
            var ids = _providers.Keys.OrderBy(x => x, StringComparer.Ordinal).ToList();
            var providers = new Dictionary<string, string>(StringComparer.Ordinal);
            var blocks = new List<byte[]>(ids.Count);
            for (int i = 0; i < ids.Count; i++)
            {
                byte[] block = BuildBlock(ids[i], _providers[ids[i]]);
                blocks.Add(block);
                providers[ids[i]] = Digest.Sha256Hex(block);
            }

            var canonical = new List<byte>();
            canonical.AddRange(Encoding.UTF8.GetBytes("GDWSTATE"));
            canonical.AddRange(Digest.U16(1));
            canonical.AddRange(Digest.U32((uint)ids.Count));
            for (int i = 0; i < blocks.Count; i++) canonical.AddRange(blocks[i]);

            return new ReplayHashes(Digest.Sha256Hex(canonical.ToArray()), providers);
        }

        static byte[] BuildBlock(string id, IReplayStateProvider provider)
        {
            var writer = new StateWriter();
            provider.WriteState(writer);
            byte[] payload = writer.ToBytes();
            byte[] idBytes = Encoding.UTF8.GetBytes(id);
            return Digest.Concat(Digest.U32((uint)idBytes.Length), idBytes, Digest.U32((uint)payload.Length), payload);
        }

        public void RegisterSnapshot(string id, IReplaySnapshot snapshot)
        {
            if (id == null) throw new ArgumentNullException(nameof(id));
            if (snapshot == null) throw new ArgumentNullException(nameof(snapshot));
            _snapshots[id] = snapshot;
        }

        public bool RestoreSnapshot(string id)
        {
            if (id == null || !_snapshots.TryGetValue(id, out var snapshot)) return false;
            snapshot.Restore();
            return true;
        }
    }
}
