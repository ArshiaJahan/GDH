using System;
using System.Collections.Generic;
using UnityEngine;

namespace Harness.Arch
{
    /// <summary>One asset listing every definition; resolves ids read from save files.</summary>
    [CreateAssetMenu(menuName = "Harness/Definitions/Database", fileName = "DefinitionDatabase")]
    public sealed class DefinitionDatabase : ScriptableObject
    {
        [SerializeField] List<Definition> definitions = new List<Definition>();
        [NonSerialized] Dictionary<string, Definition> byId;

        public IReadOnlyList<Definition> All => definitions;

        public void Add(Definition d) { definitions.Add(d); byId = null; }

        public bool TryGet<T>(string id, out T def) where T : Definition
        {
            if (byId == null) Build();
            if (id != null && byId.TryGetValue(id, out var d) && d is T t) { def = t; return true; }
            def = null;
            return false;
        }

        public IEnumerable<T> OfType<T>() where T : Definition
        {
            foreach (var d in definitions) if (d is T t) yield return t;
        }

        /// <summary>Problems (null entries, empty or duplicate ids). Empty list = valid. Run it in an EditMode test.</summary>
        public List<string> Validate()
        {
            var errors = new List<string>();
            var seen = new HashSet<string>();
            for (int i = 0; i < definitions.Count; i++)
            {
                var d = definitions[i];
                if (d == null) { errors.Add($"entry {i} is null"); continue; }
                if (string.IsNullOrEmpty(d.Id)) errors.Add($"{d.name}: empty id");
                else if (!seen.Add(d.Id)) errors.Add($"{d.name}: duplicate id '{d.Id}'");
            }
            return errors;
        }

        void Build()
        {
            byId = new Dictionary<string, Definition>();
            foreach (var d in definitions)
                if (d != null && !string.IsNullOrEmpty(d.Id) && !byId.ContainsKey(d.Id)) byId.Add(d.Id, d);
        }

        void OnEnable() => byId = null;
    }
}
