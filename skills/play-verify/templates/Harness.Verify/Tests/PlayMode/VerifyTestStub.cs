using UnityEngine;

namespace Harness.Verify.Tests
{
    /// <summary>Stand-in "game" component for the harness self-tests (watch target and SendMessage receiver).</summary>
    public class VerifyTestStub : MonoBehaviour
    {
        public int current = 100;
        public void Damage(int amount) { current -= amount; }
    }
}
