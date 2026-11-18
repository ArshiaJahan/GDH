namespace Gdw.Replay
{
    /// <summary>
    /// Optional game-supplied snapshot/reset adapter. v1 ships this interface and uses it only when
    /// a game registers one; the default reset adapter is scene-reset.
    /// </summary>
    public interface IReplaySnapshot
    {
        void Capture(StateWriter writer);
        void Restore();
    }
}
