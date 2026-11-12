// Harness.Assets.PlaceholderArt - generates labelled, colour-coded placeholder sprites (PNG) with pixel-art import settings.
// Naming: Assets/Art/Sprites/Placeholders/<Category>/PH_<Category>_<name>.png  (PH_ prefix = "replace me").
// Replace later by overwriting the PNG bytes at the same path (GUID and every reference survive), then rename/move with
// AssetDatabase.RenameAsset/MoveAsset to drop the PH_ prefix.
// Menu: Tools/Harness/Assets/Generate Placeholder Sprites
// Batch: -executeMethod Harness.Assets.PlaceholderArt.GenerateDefaultBatch   (log: "PlaceholderArt RESULT: OK ...")
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace Harness.Assets
{
    public static class PlaceholderArt
    {
        public const string Root = "Assets/Art/Sprites/Placeholders";
        public enum Shape { Rect, Circle, Triangle, Diamond }

        [Serializable]
        public struct Spec
        {
            public string category, name, label;
            public int width, height;
            public Color color;
            public Shape shape;
            public Spec(string category, string name, int w, int h, Shape shape, Color color, string label = "")
            { this.category = category; this.name = name; width = w; height = h; this.shape = shape; this.color = color; this.label = label; }
            public string AssetPath => $"{Root}/{category}/PH_{category}_{name}.png";
        }

        /// <summary>A starter set for a top-down/side 2D roguelike at 16 PPU.</summary>
        public static readonly Spec[] RoguelikeDefaults =
        {
            new Spec("Characters", "player", 16, 16, Shape.Circle, new Color(0.25f, 0.55f, 1f), "P"),
            new Spec("Enemies", "melee", 16, 16, Shape.Diamond, new Color(0.9f, 0.2f, 0.2f), "E1"),
            new Spec("Enemies", "ranged", 16, 16, Shape.Triangle, new Color(1f, 0.55f, 0.1f), "E2"),
            new Spec("Enemies", "boss", 32, 32, Shape.Rect, new Color(0.55f, 0.05f, 0.15f), "BOSS"),
            new Spec("Projectiles", "player_shot", 8, 8, Shape.Circle, new Color(1f, 0.95f, 0.3f)),
            new Spec("Projectiles", "enemy_shot", 8, 8, Shape.Circle, new Color(1f, 0.3f, 0.9f)),
            new Spec("Pickups", "coin", 8, 8, Shape.Circle, new Color(1f, 0.8f, 0.1f)),
            new Spec("Pickups", "heart", 8, 8, Shape.Diamond, new Color(1f, 0.4f, 0.6f)),
            new Spec("Pickups", "chest", 16, 16, Shape.Rect, new Color(0.55f, 0.35f, 0.15f), "CH"),
            new Spec("Tiles", "floor", 16, 16, Shape.Rect, new Color(0.35f, 0.35f, 0.38f)),
            new Spec("Tiles", "wall", 16, 16, Shape.Rect, new Color(0.15f, 0.15f, 0.18f), "W"),
            new Spec("Tiles", "door", 16, 16, Shape.Rect, new Color(0.1f, 0.6f, 0.6f), "D"),
        };

        [MenuItem("Tools/Harness/Assets/Generate Placeholder Sprites")]
        public static void GenerateDefaultsMenu()
        {
            var created = Generate(RoguelikeDefaults, false);
            Debug.Log($"PlaceholderArt RESULT: OK created={created.Count} root={Root}");
        }

        public static void GenerateDefaultBatch()
        {
            int code = 0;
            try
            {
                var created = Generate(RoguelikeDefaults, false);
                Debug.Log($"PlaceholderArt RESULT: OK created={created.Count} root={Root}");
            }
            catch (Exception e)
            {
                Debug.LogError("PlaceholderArt RESULT: FAIL " + e);
                code = 1;
            }
            BatchExit.Exit(code);
        }

        /// <summary>Writes PNGs for specs that don't exist yet (or all, when overwrite), imports them with pixel settings.</summary>
        public static List<string> Generate(IEnumerable<Spec> specs, bool overwrite)
        {
            var written = new List<string>();
            foreach (var spec in specs)
            {
                string path = spec.AssetPath;
                if (File.Exists(path) && !overwrite) continue;
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                File.WriteAllBytes(path, Draw(spec)); // overwriting keeps the existing .meta (GUID)
                written.Add(path);
            }
            if (written.Count == 0) return written;

            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            foreach (var path in written) ApplyPixelSettings(path);
            return written;
        }

        /// <summary>Pixel-art sprite settings, set explicitly so this works without ImportRules installed.</summary>
        public static void ApplyPixelSettings(string path)
        {
            var ti = AssetImporter.GetAtPath(path) as TextureImporter;
            if (ti == null) throw new InvalidOperationException("Not a texture: " + path);
            ti.textureType = TextureImporterType.Sprite;
            ti.spriteImportMode = SpriteImportMode.Single;
            ti.filterMode = FilterMode.Point;
            ti.textureCompression = TextureImporterCompression.Uncompressed;
            ti.mipmapEnabled = false;
            ti.spritePixelsPerUnit = ImportRuleConfig.PixelsPerUnit;
            ti.alphaIsTransparency = true;
            ti.wrapMode = TextureWrapMode.Clamp;
            ti.npotScale = TextureImporterNPOTScale.None;
            ti.SaveAndReimport();
        }

        public static byte[] Draw(Spec spec)
        {
            int w = Mathf.Max(1, spec.width), h = Mathf.Max(1, spec.height);
            var px = new Color32[w * h];
            Color32 fill = spec.color;
            Color32 edge = Color.Lerp(spec.color, Color.black, 0.5f);
            for (int y = 0; y < h; y++)
                for (int x = 0; x < w; x++)
                {
                    bool inside = Inside(spec.shape, x, y, w, h);
                    bool border = inside && (!Inside(spec.shape, x - 1, y, w, h) || !Inside(spec.shape, x + 1, y, w, h) ||
                                             !Inside(spec.shape, x, y - 1, w, h) || !Inside(spec.shape, x, y + 1, w, h));
                    px[y * w + x] = !inside ? new Color32(0, 0, 0, 0) : border ? edge : fill;
                }
            DrawLabel(px, w, h, spec.label, Luminance(spec.color) > 0.5f ? new Color32(0, 0, 0, 255) : new Color32(255, 255, 255, 255));

            var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
            try
            {
                tex.SetPixels32(px);
                tex.Apply(false);
                return tex.EncodeToPNG();
            }
            finally { UnityEngine.Object.DestroyImmediate(tex); }
        }

        static bool Inside(Shape s, int x, int y, int w, int h)
        {
            if (x < 0 || y < 0 || x >= w || y >= h) return false;
            float u = (x + 0.5f) / w * 2f - 1f, v = (y + 0.5f) / h * 2f - 1f; // -1..1
            switch (s)
            {
                case Shape.Circle: return u * u + v * v <= 1f;
                case Shape.Diamond: return Mathf.Abs(u) + Mathf.Abs(v) <= 1f;
                case Shape.Triangle: return v >= -1f && Mathf.Abs(u) <= (1f - v) * 0.5f; // apex up
                default: return true;
            }
        }

        static float Luminance(Color c) => 0.2126f * c.r + 0.7152f * c.g + 0.0722f * c.b;

        // 3x5 bitmap font: A-Z, 0-9, '-'. Rows top to bottom, '#' = pixel.
        static readonly Dictionary<char, string> Glyphs = new Dictionary<char, string>
        {
            {'A',".#.#.#####.##.#"},{'B',"##.#.###.#.###."},{'C',".###..#..#...##"},{'D',"##.#.##.##.###."},
            {'E',"####..##.#..###"},{'F',"####..##.#..#.."},{'G',".###..#.##.#.##"},{'H',"#.##.#####.##.#"},
            {'I',"###.#..#..#.###"},{'J',"..#..#..##.#.#."},{'K',"#.##.###.#.##.#"},{'L',"#..#..#..#..###"},
            {'M',"#.########.##.#"},{'N',"##.#.##.##.##.#"},{'O',".#.#.##.##.#.#."},{'P',"##.#.###.#..#.."},
            {'Q',".#.#.##.###..##"},{'R',"##.#.###.#.##.#"},{'S',".###...#...###."},{'T',"###.#..#..#..#."},
            {'U',"#.##.##.##.####"},{'V',"#.##.##.##.#.#."},{'W',"#.##.########.#"},{'X',"#.##.#.#.#.##.#"},
            {'Y',"#.##.#.#..#..#."},{'Z',"###..#.#.#..###"},{'0',"####.##.##.####"},{'1',".#.##..#..#.###"},
            {'2',"##...#.#.#..###"},{'3',"##...#.#...###."},{'4',"#.##.####..#..#"},{'5',"####..##...###."},
            {'6',".###..####.####"},{'7',"###..#.#..#..#."},{'8',"####.#####.####"},{'9',"####.####..###."},
            {'-',"......###......"},
        };

        static void DrawLabel(Color32[] px, int w, int h, string label, Color32 ink)
        {
            if (string.IsNullOrEmpty(label)) return;
            label = label.ToUpperInvariant();
            int scale = Mathf.Max(1, Mathf.Min((w - 2) / (label.Length * 4), (h - 2) / 6));
            int textW = (label.Length * 4 - 1) * scale, textH = 5 * scale;
            if (textW > w || textH > h) return; // too small for a label; colour + shape still identify it
            int ox = (w - textW) / 2, oy = (h - textH) / 2;
            for (int i = 0; i < label.Length; i++)
            {
                if (!Glyphs.TryGetValue(label[i], out var g)) continue;
                for (int row = 0; row < 5; row++)
                    for (int col = 0; col < 3; col++)
                    {
                        if (g[row * 3 + col] != '#') continue;
                        for (int sy = 0; sy < scale; sy++)
                            for (int sx = 0; sx < scale; sx++)
                            {
                                int x = ox + (i * 4 + col) * scale + sx;
                                int y = oy + (4 - row) * scale + sy; // texture rows go bottom-up
                                if (x >= 0 && y >= 0 && x < w && y < h) px[y * w + x] = ink;
                            }
                    }
            }
        }
    }
}
