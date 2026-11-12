using UnityEngine;

namespace Harness.Arch
{
    // One file per concrete type: Unity needs file name == class name for ScriptableObject assets.
    [CreateAssetMenu(menuName = "Harness/Variables/Int", fileName = "IntVariable")]
    public sealed class IntVariable : Variable<int> { }
}
