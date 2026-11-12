using UnityEngine;

public class SuppressedBehaviour : MonoBehaviour
{
    void Update()
    {
        GetComponent<Transform>(); // harness:allow HOT_GETCOMPONENT cached by generated wrapper
        // harness:allow HOT_FIND debug scene locator with bounded object count
        GameObject.Find("Player");
        // harness:allow HOT_DEBUG_LOG development overlay refresh
        Debug.Log("refresh");
        // harness:allow HOT_STRING_ALLOC bounded diagnostic text
        var text = $"Frame {Time.frameCount}";
        // harness:allow HOT_NEW_COLLECTION
        var missingReason = new int[4];
        /* harness:allow HOT_CAMERA_MAIN block comments are not suppressions */
        var camera = Camera.main;
        Debug.Log("unsuppressed");
    }
}
