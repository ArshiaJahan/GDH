#if UNITY_EDITOR
using CoinDash;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>Rebuilds Assets/Scenes/Main.unity: Unity -batchmode -executeMethod SampleSceneBuilder.Build -quit</summary>
public static class SampleSceneBuilder
{
    const string ScenePath = "Assets/Scenes/Main.unity";

    [MenuItem("Coin Dash/Rebuild Main scene")]
    public static void Build()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

        var cam = new GameObject("Main Camera", typeof(Camera), typeof(AudioListener));
        cam.tag = "MainCamera";
        cam.transform.SetPositionAndRotation(new Vector3(0f, 16f, -10f), Quaternion.Euler(58f, 0f, 0f));

        var light = new GameObject("Directional Light", typeof(Light));
        light.GetComponent<Light>().type = LightType.Directional;
        light.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

        var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
        ground.name = "Ground";
        ground.transform.localScale = new Vector3(2f, 1f, 2f);

        var state = new GameObject("GameState", typeof(GameState));

        var player = GameObject.CreatePrimitive(PrimitiveType.Capsule);
        player.name = "Player";
        Object.DestroyImmediate(player.GetComponent<Collider>());
        player.transform.position = new Vector3(0f, 1f, 0f);
        player.AddComponent<PlayerMover>();

        var field = new GameObject("CoinField", typeof(CoinField));
        var so = new SerializedObject(field.GetComponent<CoinField>());
        so.FindProperty("player").objectReferenceValue = player.transform;
        so.ApplyModifiedPropertiesWithoutUndo();

        EditorSceneManager.SaveScene(scene, ScenePath);
        EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
        AssetDatabase.SaveAssets();
        Debug.Log("[CoinDash] Main scene rebuilt");
    }
}
#endif
