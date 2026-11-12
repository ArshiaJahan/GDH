using System.Collections.Generic;
using UnityEngine;

public static class SharedEffects
{
    public static void AllocatePulse()
    {
        var pulse = new List<Vector2>();
        AllocateDeeper();
    }

    static void AllocateDeeper() { GameObject.Find("beyond-cross-file-level"); }
}
