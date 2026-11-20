namespace CoinDash
{
    /// <summary>Plain game rules, kept out of MonoBehaviours so EditMode tests can check them.</summary>
    public sealed class ScoreBoard
    {
        public const int PointsPerCoin = 10;

        public int Score { get; private set; }
        public int CoinsCollected { get; private set; }
        public int CoinsTotal { get; }
        public bool Won => CoinsCollected >= CoinsTotal;

        public ScoreBoard(int coinsTotal) { CoinsTotal = coinsTotal; }

        public void Collect()
        {
            if (Won) return;
            CoinsCollected++;
            Score += PointsPerCoin;
        }
    }
}
