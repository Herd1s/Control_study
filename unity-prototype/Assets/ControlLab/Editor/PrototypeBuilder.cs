using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace ControlLab.UnityPrototype
{
    public static class PrototypeBuilder
    {
        [Serializable]
        sealed class PlayerBuildInfo
        {
            public string productId, version, platform, managedAssemblySha256;
        }

        [MenuItem("ControlLab/Build first lesson for Windows")]
        public static void Build()
        {
            Prepare();
            var output = Path.GetFullPath("Builds/Windows/ControlLab Unity.exe");
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = new[] { "Assets/ControlLab/Scenes/LessonOne.unity" },
                locationPathName = output,
                target = BuildTarget.StandaloneWindows64,
                options = BuildOptions.None
            });
            if (report.summary.result != BuildResult.Succeeded)
                throw new Exception("Prototype build failed: " + report.summary.result);
            string outputDirectory = Path.GetDirectoryName(output);
            string managed = Path.Combine(outputDirectory, "ControlLab Unity_Data", "Managed", "Assembly-CSharp.dll");
            string digest;
            using (var sha = System.Security.Cryptography.SHA256.Create())
                digest = BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(managed))).Replace("-", "").ToLowerInvariant();
            var info = new PlayerBuildInfo { productId = AppVersion.ProductId, version = AppVersion.Current,
                platform = AppVersion.Platform, managedAssemblySha256 = digest };
            File.WriteAllText(Path.Combine(outputDirectory, "build-info.json"), JsonUtility.ToJson(info, true),
                new System.Text.UTF8Encoding(false));
            Debug.Log("CONTROLLAB_BUILD_OK " + output);
        }

        [MenuItem("ControlLab/Open first lesson")]
        public static void Prepare()
        {
            PlayerSettings.companyName = "ControlLab";
            PlayerSettings.productName = "ControlLab Unity";
            PlayerSettings.bundleVersion = AppVersion.Current;
            PlayerSettings.defaultScreenWidth = 1366;
            PlayerSettings.defaultScreenHeight = 768;
            PlayerSettings.fullScreenMode = FullScreenMode.Windowed;
            PlayerSettings.resizableWindow = true;
            PlayerSettings.runInBackground = false;
            PlayerSettings.colorSpace = ColorSpace.Linear;
            // This prototype reads UnityEngine.Input; new-input-only mode would
            // make pointer handling throw even though the scripts compile.
            var settingsAssets = AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/ProjectSettings.asset");
            if (settingsAssets.Length > 0)
            {
                var settings = new SerializedObject(settingsAssets[0]);
                var inputHandler = settings.FindProperty("activeInputHandler");
                if (inputHandler != null && inputHandler.intValue != 0)
                {
                    inputHandler.intValue = 0;
                    settings.ApplyModifiedPropertiesWithoutUndo();
                }
            }
            PlayerSettings.SetScriptingBackend(NamedBuildTarget.Standalone, ScriptingImplementation.Mono2x);
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.StandaloneWindows64, false);
            PlayerSettings.SetGraphicsAPIs(BuildTarget.StandaloneWindows64, new[] { GraphicsDeviceType.Direct3D11 });
            QualitySettings.antiAliasing = 4;
            QualitySettings.shadows = ShadowQuality.All;
            QualitySettings.shadowResolution = ShadowResolution.High;
            QualitySettings.shadowDistance = 25f;
            QualitySettings.vSyncCount = 1;
            ConfigureUIPanel.EnsureAsset();

            // Runtime-created materials still need their shaders included in a build.
            if (!AssetDatabase.IsValidFolder("Assets/ControlLab/Resources"))
                AssetDatabase.CreateFolder("Assets/ControlLab", "Resources");
            if (!AssetDatabase.IsValidFolder("Assets/ControlLab/Resources/ShaderKeepers"))
                AssetDatabase.CreateFolder("Assets/ControlLab/Resources", "ShaderKeepers");
            foreach (var shaderName in new[] { "Standard", "Unlit/Color", "Sprites/Default", "Legacy Shaders/Transparent/Diffuse" })
            {
                var shader = Shader.Find(shaderName);
                if (shader == null) continue;
                var path = "Assets/ControlLab/Resources/ShaderKeepers/" + shaderName.Replace('/', '_') + ".mat";
                if (AssetDatabase.LoadAssetAtPath<Material>(path) == null)
                    AssetDatabase.CreateAsset(new Material(shader), path);
            }
            const string scenePath = "Assets/ControlLab/Scenes/LessonOne.unity";
            if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
                return;
            Scene scene;
            if (File.Exists(scenePath))
            {
                // Preserve any scene edits made after the first import.
                scene = EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single);
            }
            else
            {
                scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
                var root = new GameObject("ControlLab First Lesson");
                root.AddComponent<LessonOneExperience>();
                root.AddComponent<PrototypeCapture>();
                Directory.CreateDirectory("Assets/ControlLab/Scenes");
                EditorSceneManager.SaveScene(scene, scenePath);
            }
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(scene.path, true) };
            AssetDatabase.SaveAssets();
        }
    }
}
