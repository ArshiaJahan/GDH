using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.Pool;

namespace Harness.Perf.Tests
{
    /// <summary>
    /// Worst-case 2D roguelike load for perf tests: N enemies (Rigidbody2D + CircleCollider2D + SpriteRenderer)
    /// chasing a point, a few overlap queries per frame, and projectiles every frame.
    /// allocating = false: the patterns perf-pass asks for (ObjectPool, cached lists, ContactFilter2D + List query).
    /// allocating = true: the anti-patterns it removes (Instantiate/Destroy per shot, LINQ, string concat, new List).
    /// </summary>
    public sealed class SwarmScenario : MonoBehaviour
    {
        const int ShotLifeFrames = 30;
        Sprite sprite;
        int shotsPerFrame;
        bool allocating;
        Rigidbody2D[] bodies;
        ObjectPool<GameObject> shots;
        readonly List<(GameObject go, int until)> live = new List<(GameObject, int)>(512);
        readonly List<Collider2D> hits = new List<Collider2D>(64);
        ContactFilter2D filter;
        int frame;
        public string debugText;

        public void Init(Sprite s, int enemies, int shots, bool alloc)
        {
            sprite = s;
            shotsPerFrame = shots;
            allocating = alloc;
            filter = new ContactFilter2D { useTriggers = false };
            filter.SetLayerMask(Physics2D.AllLayers);
            bodies = new Rigidbody2D[enemies];
            for (int i = 0; i < enemies; i++)
            {
                var go = new GameObject("Enemy" + i, typeof(SpriteRenderer), typeof(Rigidbody2D), typeof(CircleCollider2D));
                go.transform.SetParent(transform);
                go.transform.position = new Vector3((i % 20) - 10f, (i / 20) - 8f, 0f);
                go.GetComponent<SpriteRenderer>().sprite = sprite;
                var rb = go.GetComponent<Rigidbody2D>();
                rb.gravityScale = 0f;
                bodies[i] = rb;
            }
            this.shots = new ObjectPool<GameObject>(CreateShot, g => g.SetActive(true), g => g.SetActive(false),
                g => Destroy(g), false, 128, 512);
        }

        GameObject CreateShot()
        {
            var g = new GameObject("Shot", typeof(SpriteRenderer));
            g.transform.SetParent(transform);
            g.GetComponent<SpriteRenderer>().sprite = sprite;
            return g;
        }

        void Update()
        {
            if (bodies == null) return;
            frame++;
            float t = Time.time;
            Vector2 target = new Vector2(Mathf.Sin(t) * 5f, Mathf.Cos(t * 0.7f) * 4f);
            for (int i = 0; i < bodies.Length; i++)
            {
                Vector2 d = target - bodies[i].position;
                bodies[i].linearVelocity = d.normalized * 2f;
            }
            for (int q = 0; q < 4; q++)
                Physics2D.OverlapCircle(bodies[(frame * 7 + q * 31) % bodies.Length].position, 1.5f, filter, hits);

            for (int s = 0; s < shotsPerFrame; s++)
            {
                GameObject g;
                if (allocating)
                {
                    g = new GameObject("Shot" + frame + "_" + s, typeof(SpriteRenderer));
                    g.transform.SetParent(transform);
                    g.GetComponent<SpriteRenderer>().sprite = sprite;
                }
                else g = shots.Get();
                g.transform.position = new Vector3(Random.Range(-10f, 10f), Random.Range(-8f, 8f), 0f);
                live.Add((g, frame + ShotLifeFrames)); // frame-based so the load does not depend on fps
            }
            for (int i = live.Count - 1; i >= 0; i--)
            {
                if (live[i].until > frame) continue;
                if (allocating) Destroy(live[i].go); else shots.Release(live[i].go);
                live.RemoveAt(i);
            }
            if (allocating)
            {
                var near = bodies.Where(b => b.position.sqrMagnitude < 25f).ToList();
                debugText = "near=" + near.Count + " frame=" + frame;
            }
        }
    }
}
