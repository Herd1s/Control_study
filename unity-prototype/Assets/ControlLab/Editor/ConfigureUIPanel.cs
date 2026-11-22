using UnityEditor;
using UnityEngine;
using UnityEngine.UIElements;

namespace ControlLab.UnityPrototype
{
    /// <summary>Keeps Unity's built-in UI and ICU resources reachable in a Player build.</summary>
    public static class ConfigureUIPanel
    {
        public static PanelSettings EnsureAsset()
        {
            const string path = "Assets/ControlLab/UI/Resources/LessonOnePanel.asset";
            var settings = AssetDatabase.LoadAssetAtPath<PanelSettings>(path);
            if (settings == null)
            {
                // In the Editor, PanelSettings initialization attaches the engine's
                // text resources; the serialized references are then included in builds.
                settings = ScriptableObject.CreateInstance<PanelSettings>();
                settings.name = "LessonOnePanel";
                AssetDatabase.CreateAsset(settings, path);
            }
            settings.scaleMode = PanelScaleMode.ConstantPixelSize;
            settings.sortingOrder = 10;
            settings.themeStyleSheet = AssetDatabase.LoadAssetAtPath<ThemeStyleSheet>(
                "Assets/ControlLab/UI/Resources/LessonOneTheme.tss");
            EditorUtility.SetDirty(settings);
            AssetDatabase.SaveAssets();
            return settings;
        }
    }
}
