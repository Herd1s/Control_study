using System;
using System.IO;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;

namespace ControlLab.UnityPrototype
{
    /// <summary>Read-only state export, enabled exclusively by --qa-state-path.</summary>
    [DisallowMultipleComponent]
    public sealed class RuntimeProbe : MonoBehaviour
    {
        [Serializable] public sealed class ScreenPoint { public float x, y; }
        [Serializable] public sealed class ButtonState
        {
            public string name, text;
            public bool found, enabled, visible;
            public float x, y, width, height, centerX, centerY;
        }
        [Serializable] public sealed class VectorState
        {
            public bool visible;
            public float dx, dy, dz;
        }
        [Serializable] public sealed class Snapshot
        {
            public int schema = 1, frame, width, height, stepIndex;
            public bool focused, ready, isDragging, isRunning, hasFallen, explanationVisible;
            public double x, v, theta, omega, force, disturbanceForce, netForce, time;
            public string utc, endReason, headline, guidance, fontName;
            public float panelPixelsScaleX, panelPixelsScaleY;
            public ScreenPoint cartScreenPosition;
            public ButtonState resetButton, nudgeButton, explainButton;
            public ButtonState momentumButton, gravityButton, controlButton;
            public VectorState momentumVector, gravityVector;
            public int activeConcept;
            public bool heroHidden;
            public string explanationText;
            public float explanationBottom, poleTipScreenY;
            public bool stylesheetLoaded, themeLoaded, fontLoaded;
            public int rendererCount, unsupportedShaderCount;
            public string flowStage, cartName, cartColor;
            public float visualCartX, visualCartScale;
            public bool hasPhoto;
            public int drawingPixelCount, undoCount;
            public ButtonState[] studioElements;
            public bool rememberProgress, settingsOpen;
            public bool customizingCart;
            public string settingsPage, savedPage, updateState, updateStatus;
            public int savedConcept;
            public ButtonState[] settingsElements;
        }

        string outputPath, temporaryPath;
        LessonOneExperience experience;
        float nextWrite;
        bool warned;
        int consecutiveIoFailures;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void CreateWhenRequested()
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i + 1 < args.Length; ++i)
                if (args[i] == "--qa-state-path")
                {
                    new GameObject("ControlLab QA state probe").AddComponent<RuntimeProbe>();
                    return;
                }
        }

        void Awake()
        {
            enabled = false;
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i + 1 < args.Length; ++i)
                if (args[i] == "--qa-state-path") outputPath = args[i + 1];
            if (string.IsNullOrEmpty(outputPath)) return;
            if (!Path.IsPathRooted(outputPath) || !string.Equals(Path.GetExtension(outputPath), ".json", StringComparison.OrdinalIgnoreCase))
            {
                Debug.LogError("RuntimeProbe requires an absolute .json output path.");
                return;
            }
            try
            {
                outputPath = Path.GetFullPath(outputPath);
                Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
                temporaryPath = outputPath + "." + Guid.NewGuid().ToString("N") + ".tmp";
                enabled = true;
            }
            catch (Exception error) { Debug.LogError("RuntimeProbe path: " + error.Message); }
        }

        void LateUpdate()
        {
            if (Time.unscaledTime < nextWrite) return;
            nextWrite = Time.unscaledTime + .05f;
            if (experience == null) experience = UnityEngine.Object.FindAnyObjectByType<LessonOneExperience>();
            if (experience == null || experience.Model == null || experience.Document == null) return;
            VisualElement root = experience.Document.rootVisualElement;
            if (root == null || root.panel == null) return;
            try
            {
                Snapshot state = Capture(root);
                File.WriteAllText(temporaryPath, JsonUtility.ToJson(state));
                // A reader sees either the complete previous snapshot or the
                // complete new one. Never delete/replace unrelated files.
                if (File.Exists(outputPath)) File.Replace(temporaryPath, outputPath, null);
                else File.Move(temporaryPath, outputPath);
                consecutiveIoFailures = 0;
            }
            catch (IOException error)
            {
                // A file scanner or snapshot reader can briefly hold the target.
                // Retry on the next probe frame; persistent failures remain visible.
                if (++consecutiveIoFailures >= 3 && !warned)
                {
                    Debug.LogWarning("RuntimeProbe write: " + error.Message);
                    warned = true;
                }
            }
            catch (Exception error)
            {
                if (!warned) { Debug.LogWarning("RuntimeProbe write: " + error.Message); warned = true; }
            }
        }

        Snapshot Capture(VisualElement root)
        {
            PendulumModel model = experience.Model;
            // UI Toolkit worldBound is in panel units. Infer the actual panel
            // transform rather than assuming one UI unit equals one screen pixel.
            Vector2 origin = RuntimePanelUtils.ScreenToPanel(root.panel, Vector2.zero);
            Vector2 corner = RuntimePanelUtils.ScreenToPanel(root.panel, new Vector2(Screen.width, Screen.height));
            float scaleX = Screen.width / Mathf.Max(.0001f, corner.x - origin.x);
            float scaleY = Screen.height / Mathf.Max(.0001f, corner.y - origin.y);
            Vector3 cart = experience.CartScreenPosition;
            VisualElement explanation = root.Q<VisualElement>("explanation");
            Font font = root.resolvedStyle.unityFontDefinition.font;
            Snapshot state = new Snapshot
            {
                frame = Time.frameCount, width = Screen.width, height = Screen.height,
                flowStage = experience.FlowStage, cartName = experience.CartName, cartColor = experience.CartColor,
                visualCartX = experience.VisualCartX, visualCartScale = experience.VisualCartScale,
                hasPhoto = experience.Studio != null && experience.Studio.HasPhoto,
                drawingPixelCount = experience.Studio == null ? 0 : experience.Studio.DrawingPixelCount,
                undoCount = experience.Studio == null ? 0 : experience.Studio.UndoCount,
                studioElements = ReadStudioElements(root, origin, scaleX, scaleY),
                rememberProgress = experience.RememberProgress, settingsOpen = experience.SettingsOpen,
                customizingCart = experience.CustomizingCart, settingsPage = experience.SettingsPage,
                savedPage = experience.SavedPage, savedConcept = experience.SavedConcept,
                updateState = experience.UpdateState, updateStatus = experience.UpdateStatus,
                settingsElements = ReadStudioElements(root, origin, scaleX, scaleY, "settings-"),
                focused = Application.isFocused, ready = true, utc = DateTime.UtcNow.ToString("O"),
                x = model.X, v = model.V, theta = model.Theta, omega = model.Omega,
                force = model.Force, disturbanceForce = model.DisturbanceForce, netForce = model.NetForce,
                time = model.Time, stepIndex = model.StepIndex, endReason = model.EndReason,
                isDragging = model.IsDragging, isRunning = model.IsRunning, hasFallen = model.HasFallen,
                cartScreenPosition = new ScreenPoint { x = cart.x, y = Screen.height - cart.y },
                panelPixelsScaleX = scaleX, panelPixelsScaleY = scaleY,
                resetButton = ReadButton(root, "reset-button", origin, scaleX, scaleY),
                nudgeButton = ReadButton(root, "nudge-button", origin, scaleX, scaleY),
                explainButton = ReadButton(root, "explain-button", origin, scaleX, scaleY),
                momentumButton = ReadButton(root, "concept-momentum", origin, scaleX, scaleY),
                gravityButton = ReadButton(root, "concept-gravity", origin, scaleX, scaleY),
                controlButton = ReadButton(root, "concept-control", origin, scaleX, scaleY),
                activeConcept = experience.ActiveConcept,
                heroHidden = root.Q<VisualElement>("hero").resolvedStyle.display == DisplayStyle.None,
                explanationText = root.Q<Label>("explanation-text")?.text ?? "",
                explanationBottom = (explanation.worldBound.yMax - origin.y) * scaleY,
                poleTipScreenY = Screen.height - experience.PresentationCamera.WorldToScreenPoint(
                    new Vector3((float)(model.X + Math.Sin(model.Theta)), .48f + (float)Math.Cos(model.Theta), 0)).y,
                momentumVector = ReadVector("Momentum vector"),
                gravityVector = ReadVector("Gravity vector"),
                headline = root.Q<Label>("headline")?.text ?? "",
                guidance = root.Q<Label>("guidance")?.text ?? "",
                explanationVisible = explanation != null && explanation.resolvedStyle.display != DisplayStyle.None,
                stylesheetLoaded = root.styleSheets.count > 0,
                themeLoaded = experience.Document.panelSettings != null && experience.Document.panelSettings.themeStyleSheet != null,
                fontLoaded = font != null || root.resolvedStyle.unityFontDefinition.fontAsset != null,
                fontName = font == null ? "font asset or unavailable" : font.name
            };
            Renderer[] renderers = experience.GetComponentsInChildren<Renderer>(true);
            state.rendererCount = renderers.Length;
            foreach (Renderer renderer in renderers)
                foreach (Material material in renderer.sharedMaterials)
                    if (material == null || material.shader == null || !material.shader.isSupported)
                        ++state.unsupportedShaderCount;
            return state;
        }

        static ButtonState[] ReadStudioElements(VisualElement root, Vector2 origin, float scaleX, float scaleY, string prefix = "studio-")
        {
            var values = new List<ButtonState>();
            root.Query<VisualElement>().ForEach(element =>
            {
                if (string.IsNullOrEmpty(element.name) || (!element.name.StartsWith(prefix, StringComparison.Ordinal)
                    && !(prefix == "settings-" && element.name == "customize-cart"))) return;
                Rect bound = element.worldBound;
                bool visible = element.resolvedStyle.display != DisplayStyle.None && element.resolvedStyle.visibility == Visibility.Visible;
                for (var parent = element.parent; parent != null && visible; parent = parent.parent)
                    visible = parent.resolvedStyle.display != DisplayStyle.None;
                values.Add(new ButtonState { name = element.name, found = true, visible = visible,
                    enabled = element.enabledInHierarchy, text = element is TextElement text ? text.text : "",
                    x = (bound.x - origin.x) * scaleX, y = (bound.y - origin.y) * scaleY,
                    width = bound.width * scaleX, height = bound.height * scaleY,
                    centerX = (bound.center.x - origin.x) * scaleX, centerY = (bound.center.y - origin.y) * scaleY });
            });
            return values.ToArray();
        }

        VectorState ReadVector(string name)
        {
            foreach (var line in experience.GetComponentsInChildren<LineRenderer>(true))
            {
                if (line.name != name || line.positionCount < 2) continue;
                Vector3 vector = line.GetPosition(1) - line.GetPosition(0);
                if (!line.useWorldSpace) vector = line.transform.TransformVector(vector);
                return new VectorState { visible = line.enabled && line.gameObject.activeInHierarchy,
                    dx = vector.x, dy = vector.y, dz = vector.z };
            }
            return new VectorState();
        }

        static ButtonState ReadButton(VisualElement root, string name, Vector2 origin, float scaleX, float scaleY)
        {
            Button button = root.Q<Button>(name);
            ButtonState state = new ButtonState { name = name, found = button != null };
            if (button == null) return state;
            Rect bound = button.worldBound;
            state.text = button.text;
            state.enabled = button.enabledInHierarchy;
            state.visible = button.resolvedStyle.display != DisplayStyle.None && button.resolvedStyle.visibility == Visibility.Visible;
            state.x = (bound.x - origin.x) * scaleX;
            state.y = (bound.y - origin.y) * scaleY;
            state.width = bound.width * scaleX;
            state.height = bound.height * scaleY;
            state.centerX = state.x + state.width / 2;
            state.centerY = state.y + state.height / 2;
            return state;
        }

        void OnDestroy()
        {
            if (string.IsNullOrEmpty(temporaryPath)) return;
            try { if (File.Exists(temporaryPath)) File.Delete(temporaryPath); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }
}
