using UnityEngine;

namespace Harness.Arch
{
    [CreateAssetMenu(menuName = "Harness/Events/Int Channel", fileName = "IntEventChannel")]
    public sealed class IntEventChannel : EventChannel<int> { }
}
