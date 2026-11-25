# Texturing and import settings

Audit first: `texture_audit.py <root>/Assets --profile mobile|desktop|pixel` reads every texture `.meta` and lists violations. Fix them through Presets or an AssetPostprocessor, not by hand one file at a time. The asset-pipeline skill has pixel-art Presets.

## Rules
- Size: set Max Size to the size the texture is shown at, not the source size. UI icons are often 128-256 and props 512-1024; use 2048 only for hero assets. Power-of-two sizes compress and mip best.
- Compression: ASTC (4x4 is sharpest, 6x6 a good default, 8x8 for large surfaces) on Android/iOS; BC7 (colour) and BC5 (normal maps) on desktop, with DXT5 as the fallback for older GPUs. Crunch only shrinks disk and download size (it decompresses at load, so runtime memory is the same). Use uncompressed only for pixel art or textures that need exact values.
- Mipmaps: on for 3D world textures, off for UI and screen-space sprites. Mipmap Streaming (Quality settings plus per-texture) cuts memory in large 3D scenes.
- Read/Write: off unless scripts read the pixels. On doubles the memory (a CPU copy).
- sRGB: on for colour/albedo, off for masks, normals and data textures (Texture Type: Normal map for normals).
- Filter: Point for pixel art, with compression None and no mipmaps; Bilinear/Trilinear otherwise. Aniso 2-4 for floors seen at an angle.
- Sprites: pack them into Sprite Atlases (v2) per screen or level, so one screen means one or a few batches. Tight mesh for irregular sprites reduces overdraw.
- Materials: share materials so the SRP Batcher can batch; use a `MaterialPropertyBlock` or per-instance properties for tints instead of creating material instances (`renderer.material` clones the material).
- Channel packing: put metallic, AO and smoothness into one mask texture (URP Lit uses metallic in R, occlusion in G, smoothness in A).
- Memory check: Memory Profiler package; for Android, check the texture memory budget for each device tier.

## Checklist
- [ ] `texture_audit.py` prints `RESULT: OK` for the profile.
- [ ] No Read/Write without a script that needs it.
- [ ] UI has no mips; the 3D world has mips.
- [ ] Sprites in atlases; atlas count per scene known.
- [ ] No `renderer.material` in runtime code that only needs a tint (`cs_lint.py --only MATERIAL_CLONE`).
