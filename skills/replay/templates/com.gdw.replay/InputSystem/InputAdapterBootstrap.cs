using UnityEngine;

namespace Gdw.Replay
{
    /// <summary>Registers the Input System adapter factory so record/replay works in any process (batch tests included).</summary>
    static class InputAdapterBootstrap
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void Register()
        {
            if (ReplayInput.Factory == null)
                ReplayInput.Factory = (dir, mb) => new InputTraceAdapter(dir, mb);
        }
    }
}
