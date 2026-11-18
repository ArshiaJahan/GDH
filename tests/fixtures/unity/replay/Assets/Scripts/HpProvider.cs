using UnityEngine;

namespace Gdw.Replay.Fixture
{
    /// <summary>
    /// HP provider implementing IReplayStateProvider for deterministic health tracking.
    /// </summary>
    public class HpProvider : MonoBehaviour, IReplayStateProvider
    {
        [SerializeField] int _hp = 100;
        [SerializeField] bool _alive = true;

        public string Id => "game.hp";

        public int Hp
        {
            get => _hp;
            set { _hp = Mathf.Max(0, value); _alive = _hp > 0; }
        }

        public bool Alive => _alive;

        public void WriteState(StateWriter writer)
        {
            writer.WriteBool("alive", _alive);
            writer.WriteInt32("hp", _hp);
        }

        void Start()
        {
            ReplayRegistry.Instance.Register(Id, this);
        }

        void OnDestroy()
        {
            if (ReplayRegistry.Instance.IsRegistered(Id))
                ReplayRegistry.Instance.Unregister(Id);
        }
    }
}
