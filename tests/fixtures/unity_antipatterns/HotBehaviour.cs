using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public class HotBehaviour : MonoBehaviour
{
    public GameObject prefab;
    public List<int> values;
    private Rigidbody2D body;
    private string label;

    void Update()
    {
        GetComponent<SpriteRenderer>().enabled = true;
        var target = GameObject.FindWithTag("Player");
        var objects = FindObjectsByType<Transform>(FindObjectsSortMode.None);
        var first = FindFirstObjectByType<Camera>();
        var any = FindAnyObjectByType<Camera>();
        var legacy = FindObjectsOfType<Camera>();
        var single = FindObjectOfType<Camera>();
        var camera = Camera.main;
        var filtered = values.Where(x => x > 0).Select(x => x + 1).ToList();
        bool exists = values.Any();
        int head = values.OrderBy(x => x).First();
        label = "Score: " + head;
        label = $"Target: {target.name}";
        label = string.Format("{0}", head);
        label = head.ToString();
        var list = new List<int>();
        var map = new Dictionary<string, int>();
        var set = new HashSet<int>();
        var buffer = new Transform[8];
        Instantiate(prefab);
        Destroy(target);
        Action work = delegate { label = "done"; };
        System.Action explicitWork = new System.Action(RefreshLabel);
        Debug.LogWarning(label);
        SendMessage("Refresh");
        BroadcastMessage("Refresh");
        var icon = Resources.Load<Sprite>("Icons/Player");
        if (target.tag == "Enemy" || "Enemy" == target.tag) body.WakeUp();
        body.velocity = Vector2.zero;
        Physics2D.OverlapCircleNonAlloc(transform.position, 2, new Collider2D[8]);
        RefreshLocal();
        SharedEffects.AllocatePulse();
    }

    void RefreshLabel() { }
    void RefreshLocal() { RefreshNested(); }
    void RefreshNested() { GetComponent<Collider2D>(); TooDeep(); }
    void TooDeep() { GameObject.Find("beyond-two-levels"); }
    void FixedUpdate() { Debug.Log("fixed tick"); }
    void LateUpdate() { Debug.Log("late tick"); }
    void OnGUI() { Debug.Log("gui tick"); }
    void OnTriggerStay2D(Collider2D other) { Debug.Log("contact"); }
    void OnCollisionStay2D(Collision2D other) { Debug.Log("contact"); }
    void OnTriggerStay(Collider other) { Debug.Log("contact"); }
    void OnCollisionStay(Collision other) { Debug.Log("contact"); }
}
