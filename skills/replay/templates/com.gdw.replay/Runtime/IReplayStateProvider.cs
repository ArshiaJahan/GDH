namespace Gdw.Replay
{
    /// <summary>A registered source of canonical state for one provider id.</summary>
    public interface IReplayStateProvider
    {
        string Id { get; }
        void WriteState(StateWriter writer);
    }
}
