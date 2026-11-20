using Gdw.Replay;
using UnityEngine;

namespace CoinDash
{
    /// <summary>Owns the ScoreBoard and exposes it to replay as the "game.score" provider.</summary>
    public sealed class GameState : MonoBehaviour, IReplayStateProvider
    {
        public static GameState Current { get; private set; }

        [SerializeField] int coinCount = 8;

        public ScoreBoard Board { get; private set; }
        public int CoinCount => coinCount;

        public string Id => "game.score";

        void Awake()
        {
            Current = this;
            Board = new ScoreBoard(coinCount);
            ReplayRegistry.Instance.Register(Id, this);
        }

        void OnDestroy()
        {
            ReplayRegistry.Instance.Unregister(Id);
            if (Current == this) Current = null;
        }

        public void WriteState(StateWriter writer)
        {
            writer.WriteInt32("score", Board.Score);
            writer.WriteInt32("collected", Board.CoinsCollected);
            writer.WriteBool("won", Board.Won);
        }

        void OnGUI()
        {
            if (Board == null) return; // not set up yet, or after a domain reload
            GUI.Label(new Rect(12, 10, 300, 24), $"Score {Board.Score}   Coins {Board.CoinsCollected}/{Board.CoinsTotal}");
            if (Board.Won) GUI.Label(new Rect(12, 34, 300, 24), "All coins collected!");
        }
    }
}
