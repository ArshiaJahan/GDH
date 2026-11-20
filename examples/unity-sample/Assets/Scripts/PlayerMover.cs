using Gdw.Replay;
using UnityEngine;
using UnityEngine.InputSystem;

namespace CoinDash
{
    /// <summary>Top-down movement on the XZ plane from WASD or arrow keys (Input System only).</summary>
    public sealed class PlayerMover : MonoBehaviour
    {
        [SerializeField] float speed = 5f;
        [SerializeField] float arenaHalfSize = 9f;

        void Awake() { TransformStateProvider.Instance.Track("player", transform); }

        void OnDestroy() { TransformStateProvider.Instance.Untrack("player"); }

        void Update()
        {
            var kb = Keyboard.current;
            if (kb == null) return;
            var dir = Vector3.zero;
            if (kb.wKey.isPressed || kb.upArrowKey.isPressed) dir.z += 1f;
            if (kb.sKey.isPressed || kb.downArrowKey.isPressed) dir.z -= 1f;
            if (kb.dKey.isPressed || kb.rightArrowKey.isPressed) dir.x += 1f;
            if (kb.aKey.isPressed || kb.leftArrowKey.isPressed) dir.x -= 1f;
            if (dir.sqrMagnitude > 1f) dir.Normalize();
            var p = transform.position + dir * speed * Time.deltaTime;
            p.x = Mathf.Clamp(p.x, -arenaHalfSize, arenaHalfSize);
            p.z = Mathf.Clamp(p.z, -arenaHalfSize, arenaHalfSize);
            transform.position = p;
        }
    }
}
