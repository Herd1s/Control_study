Shader "ControlLab/CartSkin"
{
    Properties { _MainTex ("Personal skin", 2D) = "white" {} }
    SubShader
    {
        Tags { "Queue"="Transparent" "RenderType"="Transparent" }
        Blend SrcAlpha OneMinusSrcAlpha
        ZWrite Off
        Cull Off
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            sampler2D _MainTex;
            struct data { float4 vertex : POSITION; float2 uv : TEXCOORD0; };
            struct result { float4 vertex : SV_POSITION; float2 uv : TEXCOORD0; };
            result vert(data v) { result o; o.vertex=UnityObjectToClipPos(v.vertex); o.uv=v.uv; return o; }
            fixed4 frag(result i) : SV_Target
            {
                fixed4 color = tex2D(_MainTex, i.uv);
                float2 q = abs((i.uv-.5) * float2(2.857, 1)) - (float2(2.857, 1)*.5-.1);
                float distance = length(max(q, 0)) + min(max(q.x,q.y),0) - .1;
                color.a *= 1-smoothstep(-.005,.005,distance);
                return color;
            }
            ENDCG
        }
    }
}
