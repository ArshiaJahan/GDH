using NUnit.Framework;

namespace CoinDash.Tests
{
    public class ScoreBoardTests
    {
        [Test]
        public void M0_S01_CollectAddsPointsPerCoin()
        {
            var board = new ScoreBoard(3);
            board.Collect();
            board.Collect();
            Assert.AreEqual(2, board.CoinsCollected);
            Assert.AreEqual(2 * ScoreBoard.PointsPerCoin, board.Score);
            Assert.IsFalse(board.Won);
        }

        [Test]
        public void M0_S01_CollectingEveryCoinWinsAndStopsScoring()
        {
            var board = new ScoreBoard(2);
            board.Collect();
            board.Collect();
            board.Collect();
            Assert.IsTrue(board.Won);
            Assert.AreEqual(2, board.CoinsCollected);
            Assert.AreEqual(2 * ScoreBoard.PointsPerCoin, board.Score);
        }
    }
}
