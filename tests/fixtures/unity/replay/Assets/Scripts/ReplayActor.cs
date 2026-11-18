using UnityEngine;
using UnityEngine.InputSystem;

namespace Gdw.Replay.Fixture
{
    /// <summary>
    /// Keyboard-driven kinematic actor using an InputAction.
    /// Moves when the action is pressed; the deterministic input trace guarantees identical movement.
    /// </summary>
    public class ReplayActor : MonoBehaviour
    {
        public float speed = 5f;
        public InputActionReference moveAction;

        Vector3 _startPosition;

        void Awake()
        {
            _startPosition = transform.position;
        }

        void Update()
        {
            if (moveAction == null) return;
            Vector2 input = moveAction.action.ReadValue<Vector2>();
            Vector3 move = new Vector3(input.x, input.y, 0f) * (speed * Time.deltaTime);
            transform.position += move;
        }

        public void ResetPosition()
        {
            transform.position = _startPosition;
        }
    }
}
