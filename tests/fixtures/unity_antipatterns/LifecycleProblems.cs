using System;
using System.Collections;
using UnityEngine;

public class LifecycleProblems : MonoBehaviour
{
    public static event Action Spawned;
    public static event Action Moved;
    public static event Action Hit;
    private Rigidbody2D body;

    void OnEnable() { Spawned += HandleSpawn; }
    void Awake() { Moved += HandleMove; }
    void Start() { Hit += HandleHit; }
    void HandleSpawn() { }
    void HandleMove() { }
    void HandleHit() { }

    IEnumerator Emit()
    {
        for (int i = 0; i < 10; i++)
        {
            yield return new WaitForSeconds(0.2f);
        }
        while (enabled)
            yield return new WaitForSecondsRealtime(0.5f);
        do { yield return new WaitForSeconds(0.1f); } while (enabled);
        foreach (var item in new[] { 1, 2 })
        {
            yield return new WaitForSeconds(0.3f);
        }
    }

    void SetSpeed()
    {
        Rigidbody2D localBody = body;
        localBody.velocity = Vector2.one;
    }
}

// An unsubscribe in another class must not satisfy LifecycleProblems.
public class OtherSubscriber : MonoBehaviour
{
    void OnDisable() { LifecycleProblems.Spawned -= HandleSpawn; }
    void HandleSpawn() { }
}
