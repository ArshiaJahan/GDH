// Harness.Trailer: renders title / caption / end-slate cards to transparent-capable PNGs (Edit Mode only).
//
//   TrailerCards.Render("Trailer/<slug>/cards.json") -> "rendered <n> cards to <dir>" | "error: ..."
//
// cards.json: {"font":"Assets/Fonts/Game SDF.asset","w":1920,"h":1080,"out_dir":"Trailer/<slug>/cards",
//   "cards":[{"id":"title","text":"...","size":96,"color":"#ffffff","bg":"#00000000","align":"center|left|right",
//   "valign":"middle|top|bottom","image":"Assets/Art/Logo.png","image_h":0.4,"margin":96}]}
//
// An additive empty scene (never saved, always closed) holds a Camera + Screen Space - Camera canvas that is rendered
// into a RenderTexture and written with EncodeToPNG. Text uses TextMeshPro with the project font asset when
// HARNESS_TMP is defined and a font is available, else the legacy UI Text with the built-in font.
// out_dir is relative to the Unity project root and must be outside Assets/ (no AssetDatabase import of generated art).
// Note: PNG alpha at anti-aliased text edges is approximate (UI blends into an alpha-0 background), which is fine for
// overlays on video; use an opaque "bg" for cards that need exact edges.

using System;
using System.Collections.Generic;
using System.IO;
#if HARNESS_TMP
using TMPro;
using UnityEngine.UI;
#endif
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Harness.Trailer
{
#if !HARNESS_TMP
    // com.unity.ugui 2.x (uGUI + TextMeshPro, in every Unity 6 template) is missing: keep the assembly compiling.
    public static class TrailerCards
    {
        public static string Render(string cardsJsonPath)
        {
            return "error: TrailerCards needs the com.unity.ugui 2.x package (uGUI + TextMeshPro)";
        }
    }
#else
    public static class TrailerCards
    {
        [Serializable]
        class CardSpec
        {
            public string id = "";
            public string text = "";
            public float size = 64f;
            public string color = "#ffffff";
            public string bg = "#00000000";
            public string align = "center";
            public string valign = "middle";
            public string image = "";
            public float image_h = 0.4f;
            public float margin = 96f;
        }

        [Serializable]
        class CardsFile
        {
            public string font = "";
            public int w = 1920;
            public int h = 1080;
            public string out_dir = "";
            public CardSpec[] cards = new CardSpec[0];
        }

        public static string Render(string cardsJsonPath)
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode) return "error: cards can only be rendered in Edit Mode";
            string abs = TrailerJob.Resolve(cardsJsonPath);
            if (string.IsNullOrEmpty(abs) || !File.Exists(abs)) return "error: cards file not found: " + cardsJsonPath;
            CardsFile f;
            try { f = JsonUtility.FromJson<CardsFile>(File.ReadAllText(abs)); }
            catch (Exception e) { return "error: invalid JSON: " + e.Message; }
            if (f == null || f.cards == null || f.cards.Length == 0) return "error: no cards";
            if (f.w < 16 || f.h < 16 || f.w > 8192 || f.h > 8192) return "error: w/h out of range";
            if (string.IsNullOrEmpty(f.out_dir)) return "error: out_dir is required";
            string outDir = TrailerJob.Resolve(f.out_dir);
            if (TrailerJob.IsUnderAssets(outDir)) return "error: capture output must be outside Assets/";
            var ids = new HashSet<string>();
            foreach (var c in f.cards)
            {
                if (c == null || string.IsNullOrEmpty(c.id) || c.id.IndexOfAny(new[] { '/', '\\', ':' }) >= 0 || c.id.Contains(".."))
                    return "error: every card needs a simple id";
                if (!ids.Add(c.id)) return "error: duplicate card id " + c.id;
            }

            for (int i = 0; i < SceneManager.sceneCount; i++)
                if (string.IsNullOrEmpty(SceneManager.GetSceneAt(i).path))
                    return "error: save or close the untitled scene first (cards are built in a temporary additive scene)";

            UnityEngine.Object font = LoadFont(f.font);
            Scene prevActive = SceneManager.GetActiveScene();
            Scene scene = default(Scene);
            RenderTexture rt = null;
            int count = 0;
            try
            {
                Directory.CreateDirectory(outDir);
                scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Additive);
                SceneManager.SetActiveScene(scene); // new GameObjects land in the active scene
                rt = new RenderTexture(f.w, f.h, 24, RenderTextureFormat.ARGB32);
                rt.antiAliasing = 1;
                rt.Create();
                foreach (var spec in f.cards)
                {
                    string file = Path.Combine(outDir, spec.id + ".png");
                    RenderCard(spec, f, font, rt, file);
                    Debug.Log("[TRAILER] card=" + spec.id + " file=" + file);
                    count++;
                }
            }
            catch (Exception e) { return "error: " + e.Message; }
            finally
            {
                RenderTexture.active = null;
                if (rt != null) { rt.Release(); UnityEngine.Object.DestroyImmediate(rt); }
                if (prevActive.IsValid() && prevActive.isLoaded) SceneManager.SetActiveScene(prevActive);
                if (scene.IsValid()) EditorSceneManager.CloseScene(scene, true);
            }
            return "rendered " + count + " cards to " + outDir;
        }

        static void RenderCard(CardSpec spec, CardsFile f, UnityEngine.Object font, RenderTexture rt, string file)
        {
            var created = new List<UnityEngine.Object>();
            Texture2D png = null;
            try
            {
                Color bg = ParseColor(spec.bg, new Color(0f, 0f, 0f, 0f));
                var camGo = new GameObject("TrailerCardCamera");
                created.Add(camGo);
                // Far from anything in the user's open scenes, and culling only the UI layer the card lives on.
                camGo.transform.position = FarAway;
                var cam = camGo.AddComponent<Camera>();
                cam.cullingMask = 1 << CardLayer;
                cam.clearFlags = CameraClearFlags.SolidColor;
                cam.backgroundColor = bg;
                cam.orthographic = true;
                cam.orthographicSize = f.h * 0.5f;
                cam.allowHDR = false;
                cam.allowMSAA = false;
                cam.targetTexture = rt;
                cam.enabled = false; // rendered manually

                var canvasGo = new GameObject("TrailerCardCanvas", typeof(RectTransform));
                created.Add(canvasGo);
                var canvas = canvasGo.AddComponent<Canvas>();
                canvas.renderMode = RenderMode.ScreenSpaceCamera;
                canvas.worldCamera = cam;
                canvas.planeDistance = 5f;
                var scaler = canvasGo.AddComponent<CanvasScaler>();
                scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
                scaler.referenceResolution = new Vector2(f.w, f.h);
                scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
                scaler.matchWidthOrHeight = 0.5f;

                float m = Mathf.Max(0f, spec.margin);
                var content = NewRect("Content", canvasGo.transform);
                content.anchorMin = Vector2.zero;
                content.anchorMax = Vector2.one;
                content.offsetMin = new Vector2(m, m);
                content.offsetMax = new Vector2(-m, -m);

                float ax = spec.align == "left" ? 0f : spec.align == "right" ? 1f : 0.5f;
                float imgH = 0f;
                Texture2D tex = string.IsNullOrEmpty(spec.image) ? null : AssetDatabase.LoadAssetAtPath<Texture2D>(spec.image);
                if (!string.IsNullOrEmpty(spec.image) && tex == null) Debug.LogWarning("[TRAILER] card " + spec.id + ": image not found " + spec.image);
                if (tex != null)
                {
                    imgH = Mathf.Clamp01(spec.image_h <= 0f ? 0.4f : spec.image_h) * f.h;
                    float imgW = imgH * tex.width / Mathf.Max(1, tex.height);
                    float maxW = f.w - 2f * m;
                    if (imgW > maxW && imgW > 0f) { imgH *= maxW / imgW; imgW = maxW; }
                    var r = NewRect("Image", content);
                    r.anchorMin = r.anchorMax = r.pivot = new Vector2(ax, 1f);
                    r.sizeDelta = new Vector2(imgW, imgH);
                    r.anchoredPosition = Vector2.zero;
                    var raw = r.gameObject.AddComponent<RawImage>();
                    raw.texture = tex;
                    raw.raycastTarget = false;
                }
                if (!string.IsNullOrEmpty(spec.text))
                {
                    var tr = NewRect("Text", content);
                    tr.anchorMin = Vector2.zero;
                    tr.anchorMax = Vector2.one;
                    tr.offsetMin = Vector2.zero;
                    tr.offsetMax = new Vector2(0f, imgH > 0f ? -(imgH + f.h * 0.03f) : 0f);
                    AddText(tr.gameObject, spec, font);
                }

                SetLayer(canvasGo.transform, CardLayer);
                Canvas.ForceUpdateCanvases();
                LayoutRebuilder.ForceRebuildLayoutImmediate(canvasGo.GetComponent<RectTransform>());
                Canvas.ForceUpdateCanvases();
                cam.Render();

                RenderTexture.active = rt;
                png = new Texture2D(f.w, f.h, TextureFormat.RGBA32, false);
                png.ReadPixels(new Rect(0, 0, f.w, f.h), 0, 0);
                png.Apply(false);
                RenderTexture.active = null;
                File.WriteAllBytes(file, png.EncodeToPNG());
            }
            finally
            {
                RenderTexture.active = null;
                foreach (var o in created)
                {
                    if (o == null) continue;
                    var go = o as GameObject;
                    if (go != null) { var c = go.GetComponent<Camera>(); if (c != null) c.targetTexture = null; }
                    UnityEngine.Object.DestroyImmediate(o);
                }
                if (png != null) UnityEngine.Object.DestroyImmediate(png);
            }
        }

        const int CardLayer = 5; // Unity's built-in "UI" layer
        static readonly Vector3 FarAway = new Vector3(0f, -100000f, -10f);

        static void SetLayer(Transform t, int layer)
        {
            t.gameObject.layer = layer;
            for (int i = 0; i < t.childCount; i++) SetLayer(t.GetChild(i), layer);
        }

        static RectTransform NewRect(string name, Transform parent)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            return (RectTransform)go.transform;
        }

        static void AddText(GameObject go, CardSpec spec, UnityEngine.Object font)
        {
            Color col = ParseColor(spec.color, Color.white);
            int h = spec.align == "left" ? 0 : spec.align == "right" ? 2 : 1; // 0 left, 1 center, 2 right
            int v = spec.valign == "top" ? 0 : spec.valign == "bottom" ? 2 : 1; // 0 top, 1 middle, 2 bottom
#if HARNESS_TMP
            var tmpFont = font as TMP_FontAsset;
            if (tmpFont != null)
            {
                var tmp = go.AddComponent<TextMeshProUGUI>();
                tmp.font = tmpFont;
                tmp.text = spec.text;
                tmp.fontSize = spec.size;
                tmp.color = col;
                tmp.raycastTarget = false;
                TextAlignmentOptions[,] map =
                {
                    { TextAlignmentOptions.TopLeft, TextAlignmentOptions.Top, TextAlignmentOptions.TopRight },
                    { TextAlignmentOptions.Left, TextAlignmentOptions.Center, TextAlignmentOptions.Right },
                    { TextAlignmentOptions.BottomLeft, TextAlignmentOptions.Bottom, TextAlignmentOptions.BottomRight },
                };
                tmp.alignment = map[v, h];
                tmp.ForceMeshUpdate();
                return;
            }
#endif
            var t = go.AddComponent<Text>();
            t.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            t.text = spec.text;
            t.fontSize = Mathf.RoundToInt(spec.size);
            t.color = col;
            t.raycastTarget = false;
            t.horizontalOverflow = HorizontalWrapMode.Wrap;
            t.verticalOverflow = VerticalWrapMode.Overflow;
            TextAnchor[,] amap =
            {
                { TextAnchor.UpperLeft, TextAnchor.UpperCenter, TextAnchor.UpperRight },
                { TextAnchor.MiddleLeft, TextAnchor.MiddleCenter, TextAnchor.MiddleRight },
                { TextAnchor.LowerLeft, TextAnchor.LowerCenter, TextAnchor.LowerRight },
            };
            t.alignment = amap[v, h];
        }

        /// <summary>TMP font asset (project asset, else the TMP default) or null to use the legacy UI Text.</summary>
        static UnityEngine.Object LoadFont(string fontPath)
        {
#if HARNESS_TMP
            TMP_FontAsset fa = null;
            if (!string.IsNullOrEmpty(fontPath)) fa = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(fontPath);
            if (fa == null && !string.IsNullOrEmpty(fontPath)) Debug.LogWarning("[TRAILER] font asset not found: " + fontPath + " (using TMP default)");
            if (fa == null)
            {
                try { fa = TMP_Settings.defaultFontAsset; } catch (Exception) { fa = null; } // TMP Essentials may be missing
            }
            return fa;
#else
            return null;
#endif
        }

        static Color ParseColor(string s, Color fallback)
        {
            Color c;
            return !string.IsNullOrEmpty(s) && ColorUtility.TryParseHtmlString(s, out c) ? c : fallback;
        }
    }
#endif
}
