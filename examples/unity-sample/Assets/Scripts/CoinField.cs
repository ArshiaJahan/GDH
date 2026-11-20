using System.Collections.Generic;
using Gdw.Replay;
using UnityEngine;

namespace CoinDash
{
    /// <summary>Places coins from the seeded "coins" stream and collects them by distance (no physics).</summary>
    public sealed class CoinField : MonoBehaviour
    {
        [SerializeField] Transform player;
        [SerializeField] float pickupRadius = 0.8f;
        [SerializeField] float spread = 8f;

        readonly List<Transform> _coins = new List<Transform>();

        void Start()
        {
            var rng = GdwRandom.Stream("coins");
            int count = GameState.Current.CoinCount;
            for (int i = 0; i < count; i++)
            {
                var coin = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                coin.name = $"Coin{i}";
                Destroy(coin.GetComponent<Collider>());
                coin.transform.SetParent(transform, false);
                coin.transform.localScale = new Vector3(0.6f, 0.05f, 0.6f);
                coin.transform.position = new Vector3(rng.Range(-spread, spread), 0.5f, rng.Range(-spread, spread));
                coin.GetComponent<Renderer>().material.color = new Color(1f, 0.8f, 0.1f);
                _coins.Add(coin.transform);
            }
        }

        void Update()
        {
            for (int i = _coins.Count - 1; i >= 0; i--)
            {
                var c = _coins[i];
                var d = c.position - player.position;
                d.y = 0f;
                if (d.sqrMagnitude <= pickupRadius * pickupRadius)
                {
                    GameState.Current.Board.Collect();
                    Destroy(c.gameObject);
                    _coins.RemoveAt(i);
                }
                else
                {
                    c.Rotate(0f, 180f * Time.deltaTime, 0f, Space.World);
                }
            }
        }
    }
}
