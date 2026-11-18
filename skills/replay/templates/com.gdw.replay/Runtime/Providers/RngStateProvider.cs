namespace Gdw.Replay
{
    /// <summary>
    /// Framework provider "unity.rng": the seed and every cached GdwRandom stream's state and draw count,
    /// in ordinal stream-name order.
    /// </summary>
    public sealed class RngStateProvider : IReplayStateProvider
    {
        public static RngStateProvider Instance { get; } = new RngStateProvider();

        public string Id => "unity.rng";

        RngStateProvider() { ReplayRegistry.Instance.Register(Id, this); }

        public void WriteState(StateWriter writer)
        {
            writer.WriteUInt32("seed", GdwRandom.Seed);
            foreach (var name in GdwRandom.StreamNames)
            {
                var stream = GdwRandom.Stream(name);
                writer.WriteUInt64("stream." + name + ".draws", stream.Draws);
                writer.WriteUInt32("stream." + name + ".state", stream.State);
            }
        }
    }
}
