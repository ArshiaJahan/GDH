using UnityEngine;

namespace Gdw.Replay.Fixture
{
    /// <summary>
    /// Rotates its transform every frame while a replay session is active (so scene state before the
    /// session starts never depends on wall-clock frame time) and is tracked by the transform provider.
    /// </summary>
    public class Spinner : MonoBehaviour
    {
        public float degreesPerSecond = 90f;

        void Start()
        {
            TransformStateProvider.Instance.Track("spinner", transform);
        }

        void Update()
        {
            if (ReplaySession.Current == null) return;
            transform.Rotate(0f, 0f, degreesPerSecond * Time.deltaTime);
        }

        void OnDestroy()
        {
            TransformStateProvider.Instance.Untrack("spinner");
        }
    }
}
