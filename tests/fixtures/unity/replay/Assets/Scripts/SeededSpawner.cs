using UnityEngine;

namespace Gdw.Replay.Fixture
{
    /// <summary>
    /// Seeded spawner using GdwRandom.Stream for deterministic spawning.
    /// Spawns a configurable number of objects at random positions.
    /// </summary>
    public class SeededSpawner : MonoBehaviour
    {
        public GameObject prefab;
        public string streamName = "spawner";
        public int count = 10;
        public float radius = 5f;

        void Start()
        {
            var stream = GdwRandom.Stream(streamName);
            for (int i = 0; i < count; i++)
            {
                Vector3 pos = transform.position + new Vector3(
                    stream.Range(-radius, radius),
                    stream.Range(-radius, radius),
                    0f
                );
                var go = prefab != null ? Instantiate(prefab, pos, Quaternion.identity) : new GameObject();
                go.transform.position = pos;
                go.name = $"Spawned_{i}";
            }
        }
    }
}
