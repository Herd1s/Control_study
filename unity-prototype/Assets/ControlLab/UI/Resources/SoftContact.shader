Shader "ControlLab/SoftContact"
{
    Properties { _MainTex ("Contact", 2D) = "white" {} }
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
            result vert(data v) { result o; o.vertex = UnityObjectToClipPos(v.vertex); o.uv = v.uv; return o; }
            fixed4 frag(result i) : SV_Target { return tex2D(_MainTex, i.uv); }
            ENDCG
        }
    }
}
