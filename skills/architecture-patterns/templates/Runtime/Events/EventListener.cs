using UnityEngine;
using UnityEngine.Events;

namespace Harness.Arch
{
    /// <summary>Typed receiver base. Concrete subclass per channel type, each in its own file.</summary>
    public abstract class EventListener<T, TChannel> : MonoBehaviour where TChannel : EventChannel<T>
    {
        [SerializeField] TChannel channel;
        [SerializeField] UnityEvent<T> response = new UnityEvent<T>();
        public UnityEvent<T> Response => response;

        public void SetChannel(TChannel c)
        {
            if (isActiveAndEnabled && channel != null) channel.Raised -= OnRaised;
            channel = c;
            if (isActiveAndEnabled && channel != null) channel.Raised += OnRaised;
        }

        protected virtual void OnEnable() { if (channel != null) channel.Raised += OnRaised; }
        protected virtual void OnDisable() { if (channel != null) channel.Raised -= OnRaised; }
        void OnRaised(T value) => response.Invoke(value);
    }
}
