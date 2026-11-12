using UnityEngine;

namespace Harness.Arch
{
    /// <summary>Put on a prefab (e.g. every enemy) to be listed in a set while enabled.</summary>
    public sealed class RuntimeSetMember : MonoBehaviour
    {
        [SerializeField] TransformRuntimeSet set;

        public void SetSet(TransformRuntimeSet s)
        {
            if (isActiveAndEnabled && set) set.Remove(transform);
            set = s;
            if (isActiveAndEnabled && set) set.Add(transform);
        }

        void OnEnable() { if (set) set.Add(transform); }
        void OnDisable() { if (set) set.Remove(transform); }
    }
}
