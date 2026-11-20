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

        [Test]
        public void EveryFifthCoinIsWorthDouble()
        {
            var board = new ScoreBoard(12);
            for (int i = 0; i < 4; i++) board.Collect();
            Assert.AreEqual(40, board.Score);
            board.Collect();
            Assert.AreEqual(60, board.Score, "the 5th coin is worth 20");
            for (int i = 0; i < 5; i++) board.Collect();
            Assert.AreEqual(120, board.Score, "so is the 10th");
            board.Collect();
            Assert.AreEqual(130, board.Score);
        }

        [Test]
        public void NoBonusAfterTheGameIsWon()
        {
            var board = new ScoreBoard(4);
            for (int i = 0; i < 6; i++) board.Collect();
            Assert.IsTrue(board.Won);
            Assert.AreEqual(40, board.Score, "the 5th pickup comes after the win and scores nothing");
        }
    }
}
