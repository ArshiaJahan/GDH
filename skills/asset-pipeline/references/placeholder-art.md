# Placeholder art

File: `templates/Editor/PlaceholderArt.cs` (`Harness.Assets.PlaceholderArt`).

## Naming convention
`Assets/Art/Sprites/Placeholders/<Category>/PH_<Category>_<name>.png`
- `PH_` prefix = "replace me". `grep`/`AssetDatabase.FindAssets("PH_ t:Sprite")` lists what is still placeholder; gdd-to-backlog/project-memory can track it as art debt.
- Categories match gameplay groups: Characters, Enemies, Projectiles, Pickups, Tiles, UI, FX.
- Colour code (defaults): player blue circle "P", melee enemy red diamond "E1", ranged enemy orange triangle "E2", boss dark red 32×32 "BOSS", player shot yellow, enemy shot magenta, coin gold, heart pink, chest brown "CH", floor/wall/door greys/teal. Same colour family per role so screenshots stay readable.

## Generate
- Defaults (12 sprites, 8–32 px, 16 PPU): menu `Tools/Harness/Assets/Generate Placeholder Sprites`, batch `-executeMethod Harness.Assets.PlaceholderArt.GenerateDefaultBatch` → `PlaceholderArt RESULT: OK created=12 root=Assets/Art/Sprites/Placeholders`.
- Custom: `PlaceholderArt.Generate(IEnumerable<Spec>, overwrite)`; `Spec(category, name, width, height, Shape.Rect|Circle|Triangle|Diamond, color, label)`. Labels use a built-in 3×5 pixel font (A–Z, 0–9, '-') and are skipped when the sprite is too small; ink is black or white by luminance. Existing files are skipped unless `overwrite`.
- Each file gets explicit pixel settings via `ApplyPixelSettings` (Sprite, Single, Point, uncompressed, no mipmaps, `ImportRuleConfig.PixelsPerUnit`, Clamp), so it works without ImportRules/Presets.
- Size placeholders like the final art (16×16 for a 16-PPU character = 1 unit) so colliders, camera framing and game feel survive the swap.
- MCP alternative (no labels): `manage_texture(action="create_sprite", ...)` as in SKILL.md step 6; `manage_texture(action="apply_pattern", pattern="checkerboard", ...)` for tile placeholders.
- Optional AI art: `generate_image` (MCP asset_gen group) exists; output still goes through the same folder rules. Not covered here.

## Replace with final art (keeps every reference)
1. Export the final PNG at the same pixel size (or update colliders deliberately).
2. Overwrite the bytes of `PH_<Category>_<name>.png` in place (file copy over the existing file, keep the `.meta`), or have the artist save over it. The GUID stays; every prefab, atlas and SO keeps pointing at it.
3. Rename to drop the prefix with `manage_asset(action="move", path=".../PH_Enemies_melee.png", destination=".../Enemies_melee.png")` (move within the same folder = rename; `destination` is documented for move/duplicate) or `AssetDatabase.RenameAsset` (never shell `mv`; scene-prefab-safety).
4. If the final art is a sprite sheet: switch `spriteImportMode` to Multiple and slice in the Sprite Editor; the single sprite referenced before is replaced by sub-sprites, so references to the old single sprite must be re-pointed (check with SceneAudit / `meta_check.py --refs`).
5. Run `asset_audit.py` and re-pack atlases.
