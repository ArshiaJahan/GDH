// Harness/SpriteFlashUnlit: URP 2D unlit sprite shader with a hit-flash (based on URP 17.3 Sprite-Unlit-Default).
// Flash.cs sets _FlashAmount (0..1) and _FlashColor per renderer with a MaterialPropertyBlock.
// The flash lerps RGB to _FlashColor and keeps the sprite alpha (silhouette). Works with the 2D Renderer
// (no LightMode tag = SRPDefaultUnlit, same as URP's own unlit sprite shader). Lit sprites: make a Sprite Lit
// Shader Graph with the same two properties instead.
Shader "Harness/SpriteFlashUnlit"
{
    Properties
    {
        _MainTex ("Sprite Texture", 2D) = "white" {}
        _FlashColor ("Flash Color", Color) = (1,1,1,1)
        _FlashAmount ("Flash Amount", Range(0,1)) = 0
        [MaterialToggle] _ZWrite("ZWrite", Float) = 0

        [HideInInspector] _Color ("Tint", Color) = (1,1,1,1)
        [HideInInspector] PixelSnap ("Pixel snap", Float) = 0
        [HideInInspector] _RendererColor ("RendererColor", Color) = (1,1,1,1)
        [HideInInspector] _AlphaTex ("External Alpha", 2D) = "white" {}
        [HideInInspector] _EnableExternalAlpha ("Enable External Alpha", Float) = 0
    }

    SubShader
    {
        Tags {"Queue" = "Transparent" "RenderType" = "Transparent" "RenderPipeline" = "UniversalPipeline" }

        Blend SrcAlpha OneMinusSrcAlpha, One OneMinusSrcAlpha
        Cull Off
        ZWrite [_ZWrite]

        Pass
        {
            HLSLPROGRAM
            #include "Packages/com.unity.render-pipelines.universal/Shaders/2D/Include/Core2D.hlsl"

            #pragma vertex UnlitVertex
            #pragma fragment FlashFragment

            struct Attributes
            {
                COMMON_2D_INPUTS
                half4 color : COLOR;
                UNITY_SKINNED_VERTEX_INPUTS
            };

            struct Varyings
            {
                COMMON_2D_OUTPUTS
                half4 color : COLOR;
            };

            #include "Packages/com.unity.render-pipelines.universal/Shaders/2D/Include/2DCommon.hlsl"

            #pragma multi_compile_instancing
            #pragma multi_compile _ DEBUG_DISPLAY SKINNED_SPRITE

            // Same layout for every variant (SRP Batcher requirement).
            CBUFFER_START(UnityPerMaterial)
                half4 _Color;
                half4 _FlashColor;
                half _FlashAmount;
            CBUFFER_END

            Varyings UnlitVertex(Attributes input)
            {
                UNITY_SKINNED_VERTEX_COMPUTE(input);
                SetUpSpriteInstanceProperties();
                input.positionOS = UnityFlipSprite(input.positionOS, unity_SpriteProps.xy);

                Varyings o = CommonUnlitVertex(input);
                o.color = input.color * _Color * unity_SpriteColor;
                return o;
            }

            half4 FlashFragment(Varyings input) : SV_Target
            {
                half4 c = CommonUnlitFragment(input, input.color);
                c.rgb = lerp(c.rgb, _FlashColor.rgb, saturate(_FlashAmount) * _FlashColor.a);
                return c;
            }
            ENDHLSL
        }
    }
}
