using UnityEngine;
using UnityEngine.Events;

namespace Harness.Arch
{
    /// <summary>Scene-side receiver: forwards a VoidEventChannel to a UnityEvent wired in the inspector.</summary>
    public sealed class VoidEventListener : MonoBehaviour
    {
        [SerializeField] VoidEventChannel channel;
        [SerializeField] UnityEvent response = new UnityEvent();
        public UnityEvent Response => response;

        public void SetChannel(VoidEventChannel c)
        {
            if (isActiveAndEnabled && channel != null) channel.Raised -= OnRaised;
            channel = c;
            if (isActiveAndEnabled && channel != null) channel.Raised += OnRaised;
        }

        void OnEnable() { if (channel != null) channel.Raised += OnRaised; }
        void OnDisable() { if (channel != null) channel.Raised -= OnRaised; }
        void OnRaised() => response.Invoke();
    }
}
