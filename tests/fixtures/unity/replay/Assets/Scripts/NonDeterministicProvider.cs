using UnityEngine;

namespace Gdw.Replay.Fixture
{
    /// <summary>
    /// Deliberately non-deterministic provider controlled by a runtime toggle.
    /// When <see cref="Enabled"/> is true, writes wall-clock time each frame so the
    /// replay comparator reports divergence with this provider's id.
    /// </summary>
    public class NonDeterministicProvider : MonoBehaviour, IReplayStateProvider
    {
        /// <summary>Set true before recording, false during replay to force divergence.</summary>
        public static bool Enabled { get; set; }

        public string Id => "game.nondeterministic";

        float _startTime;
        int _callCount;

        void Start()
        {
            _startTime = Time.realtimeSinceStartup;
            if (Enabled)
                ReplayRegistry.Instance.Register(Id, this);
        }

        public void WriteState(StateWriter writer)
        {
            if (!Enabled) return;
            _callCount++;
            writer.WriteFloat("wall_time", Time.realtimeSinceStartup - _startTime);
            writer.WriteInt32("call_count", _callCount);
        }

        void OnDestroy()
        {
            if (ReplayRegistry.Instance.IsRegistered(Id))
                ReplayRegistry.Instance.Unregister(Id);
        }
    }
}
