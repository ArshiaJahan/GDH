// Requires com.unity.inputsystem >= 1.8 (HARNESS_INPUT_SYSTEM is set by Game.Runtime.asmdef versionDefines).
// ⚠ version-sensitive: project-wide actions (InputSystem.actions) exist since Input System 1.8; tested with 1.20.1.
#if HARNESS_INPUT_SYSTEM
using System;
using UnityEngine;
using UnityEngine.InputSystem;

namespace Harness.Arch
{
    /// <summary>
    /// Thin ScriptableObject between the Input System and gameplay: gameplay subscribes to C# events and never
    /// touches InputActions. Leave "actions" empty to use the project-wide actions asset
    /// (Project Settings > Input System Package; Unity 6 templates ship Assets/InputSystem_Actions.inputactions).
    /// </summary>
    [CreateAssetMenu(menuName = "Harness/Input/Input Reader", fileName = "InputReader")]
    public sealed class InputReader : ScriptableObject
    {
        [SerializeField, Tooltip("Empty = InputSystem.actions (project-wide)")] InputActionAsset actions;
        [SerializeField] string gameplayMap = "Player";
        [SerializeField] string uiMap = "UI";
        [SerializeField] string moveAction = "Player/Move";
        [SerializeField] string attackAction = "Player/Attack";
        [SerializeField] string interactAction = "Player/Interact";
        [SerializeField] string dashAction = "Player/Sprint";
        [SerializeField] string pauseAction = "UI/Cancel";

        public event Action<Vector2> Move;
        public event Action AttackStarted;
        public event Action AttackCanceled;
        public event Action Interact;
        public event Action Dash;
        public event Action Pause;

        public Vector2 MoveValue { get; private set; }

        InputActionAsset asset;
        InputAction move, attack, interact, dash, pause;
        bool bound;

        public InputActionAsset Asset => actions != null ? actions : InputSystem.actions;

        /// <summary>Gameplay map on, UI map off. Call from the player/bootstrap on spawn.</summary>
        public void EnableGameplay()
        {
            Bind();
            asset?.FindActionMap(uiMap)?.Disable();
            asset?.FindActionMap(gameplayMap)?.Enable();
            pause?.Enable(); // pause stays available during gameplay
        }

        /// <summary>UI map on, gameplay map off (menus, pause screen).</summary>
        public void EnableUI()
        {
            Bind();
            asset?.FindActionMap(gameplayMap)?.Disable();
            asset?.FindActionMap(uiMap)?.Enable();
            MoveValue = Vector2.zero;
            Move?.Invoke(Vector2.zero);
        }

        public void DisableAll()
        {
            asset?.FindActionMap(gameplayMap)?.Disable();
            asset?.FindActionMap(uiMap)?.Disable();
        }

        void Bind()
        {
            if (bound) return;
            asset = Asset;
            if (asset == null) { Debug.LogError("[InputReader] no InputActionAsset and no project-wide actions set"); return; }
            move = Find(moveAction); attack = Find(attackAction); interact = Find(interactAction);
            dash = Find(dashAction); pause = Find(pauseAction);
            if (move != null) { move.performed += OnMove; move.canceled += OnMove; }
            if (attack != null) { attack.started += OnAttackStarted; attack.canceled += OnAttackCanceled; }
            if (interact != null) interact.performed += OnInteract;
            if (dash != null) dash.performed += OnDash;
            if (pause != null) pause.performed += OnPause;
            bound = true;
        }

        void Unbind()
        {
            if (!bound) return;
            if (move != null) { move.performed -= OnMove; move.canceled -= OnMove; }
            if (attack != null) { attack.started -= OnAttackStarted; attack.canceled -= OnAttackCanceled; }
            if (interact != null) interact.performed -= OnInteract;
            if (dash != null) dash.performed -= OnDash;
            if (pause != null) pause.performed -= OnPause;
            bound = false;
        }

        InputAction Find(string path)
        {
            if (string.IsNullOrEmpty(path)) return null;
            var a = asset.FindAction(path, false);
            if (a == null) Debug.LogWarning($"[InputReader] action '{path}' not found in {asset.name}");
            return a;
        }

        void OnMove(InputAction.CallbackContext c) { MoveValue = c.ReadValue<Vector2>(); Move?.Invoke(MoveValue); }
        void OnAttackStarted(InputAction.CallbackContext c) => AttackStarted?.Invoke();
        void OnAttackCanceled(InputAction.CallbackContext c) => AttackCanceled?.Invoke();
        void OnInteract(InputAction.CallbackContext c) => Interact?.Invoke();
        void OnDash(InputAction.CallbackContext c) => Dash?.Invoke();
        void OnPause(InputAction.CallbackContext c) => Pause?.Invoke();

        void OnDisable() { Unbind(); MoveValue = Vector2.zero; }
    }
}
#endif
