using System;
using UnityEngine;
using UnityEngine.UIElements;

namespace ControlLab.UnityPrototype
{
    /// <summary>
    /// Owns photo, drawing and composite textures. Preview consumers borrow SkinTexture;
    /// do not destroy it. Layers remain separate until composed for display or exported on Finish.
    /// </summary>
    public sealed class CartStudio : IDisposable
    {
        readonly VisualElement root, panel;
        readonly Action<CartProfile, Texture2D> onPreview;
        readonly Action onStart;
        readonly SkinPaintCanvas canvas;
        readonly Label status;
        readonly Button undoButton, removePhotoButton, brushButton, eraserButton, finishButton;
        readonly Button[] bodyButtons = new Button[6];
        readonly Button[] inkButtons = new Button[5];
        readonly Button[] sizeButtons = new Button[3];
        readonly Color32[] compositePixels;
        Texture2D photo;
        Color32[] photoPixels;
        Color bodyColor;
        bool disposed, dirty;
        int lastWidth, lastHeight;
        public bool Visible { get; private set; }
        public CartProfile Profile { get; }
        public Texture2D SkinTexture { get; }
        public bool HasPhoto { get; private set; }
        public int DrawingPixelCount => canvas.DrawingPixelCount;
        public int UndoCount => canvas.UndoCount;

        public CartStudio(VisualElement host, Action<CartProfile, Texture2D> preview, Action start)
        {
            onPreview = preview;
            onStart = start;
            Profile = CartProfileStore.Load();
            Profile.displayName = CartProfileStore.SanitizeName(Profile.displayName);
            Profile.bodyColor = CartProfileStore.NormalizeColor(Profile.bodyColor);
            if (!ColorUtility.TryParseHtmlString(Profile.bodyColor, out bodyColor)) bodyColor = new Color(0, .4f, .8f);
            photo = CartProfileStore.DecodeLayer(Profile.photoPng);
            photoPixels = photo.GetPixels32();
            HasPhoto = !string.IsNullOrEmpty(Profile.photoPng);
            SkinTexture = new Texture2D(CartProfileStore.SkinWidth, CartProfileStore.SkinHeight, TextureFormat.RGBA32, false)
                { name = "Student cart skin", wrapMode = TextureWrapMode.Clamp, filterMode = FilterMode.Bilinear };
            compositePixels = new Color32[CartProfileStore.SkinWidth * CartProfileStore.SkinHeight];

            root = new VisualElement { name = "studio-root", pickingMode = PickingMode.Ignore };
            root.styleSheets.Add(Resources.Load<StyleSheet>("CartStudio"));
            host.Add(root);
            panel = new VisualElement { name = "studio-panel" };
            root.Add(panel);
            panel.Add(new Label("装扮你的小车") { name = "studio-title" });
            var name = new TextField("名字") { name = "studio-name", value = Profile.displayName, maxLength = 16 };
            name.RegisterValueChangedCallback(e =>
            {
                Profile.displayName = CartProfileStore.SanitizeName(e.newValue);
                PublishPreview(false);
            });
            panel.Add(name);

            var bodyRow = Row("studio-body-colors", panel);
            bodyRow.Add(new Label("车色") { name = "studio-color-label" });
            string[] bodyColors = { "#0878E8", "#39A88D", "#E28C45", "#C65C72", "#8B79C7", "#596879" };
            for (int i = 0; i < bodyColors.Length; i++)
            {
                string color = bodyColors[i];
                var choice = MakeSwatch("studio-body-" + i, color, () => SetBodyColor(color));
                bodyButtons[i] = choice;
                bodyRow.Add(choice);
            }
            bodyRow.Add(MakeButton("studio-body-custom", "+", () =>
            {
                try
                {
                    Color? color = NativeImagePicker.PickColor(bodyColor);
                    if (color.HasValue) SetBodyColor("#" + ColorUtility.ToHtmlStringRGB(color.Value));
                }
                catch (Exception) { status.text = "选色窗口没能打开，请先选一种颜色。"; }
            }, "studio-custom"));

            var photoRow = Row("studio-photo-actions", panel);
            photoRow.Add(MakeButton("studio-photo-add", "添加照片", AddPhoto));
            removePhotoButton = MakeButton("studio-photo-remove", "移除照片", RemovePhoto);
            photoRow.Add(removePhotoButton);
            canvas = new SkinPaintCanvas(CartProfileStore.DecodeLayer(Profile.drawingPng), () => PublishPreview(true));
            panel.Add(canvas);

            var tools = Row("studio-paint-tools", panel);
            brushButton = MakeButton("studio-tool-brush", "画笔", () => SetEraser(false));
            eraserButton = MakeButton("studio-tool-eraser", "橡皮", () => SetEraser(true));
            tools.Add(brushButton); tools.Add(eraserButton);
            string[] inkColors = { "#FFFFFF", "#202B3A", "#FFC857", "#F26B78", "#7CD2CC" };
            for (int i = 0; i < inkColors.Length; i++)
            {
                string color = inkColors[i];
                var choice = MakeSwatch("studio-ink-" + i, color, () => SetInkColor(color));
                choice.AddToClassList("ink-swatch");
                inkButtons[i] = choice;
                tools.Add(choice);
            }
            tools.Add(MakeButton("studio-ink-custom", "+", () =>
            {
                try
                {
                    Color? color = NativeImagePicker.PickColor(canvas.BrushColor);
                    if (color.HasValue) SetInkColor("#" + ColorUtility.ToHtmlStringRGB(color.Value));
                }
                catch (Exception) { status.text = "选色窗口没能打开，请先选一种颜色。"; }
            }, "studio-custom"));

            var actions = Row("studio-drawing-actions", panel);
            string[] sizes = { "细", "中", "粗" };
            float[] diameters = { 6, 16, 32 };
            for (int i = 0; i < sizes.Length; i++)
            {
                int selected = i;
                var button = MakeButton("studio-size-" + i, sizes[i], () =>
                {
                    canvas.BrushDiameter = diameters[selected];
                    for (int j = 0; j < sizeButtons.Length; j++) sizeButtons[j].EnableInClassList("selected", j == selected);
                    PublishPreview(false);
                }, "studio-size");
                sizeButtons[i] = button;
                actions.Add(button);
            }
            actions.Add(new VisualElement { name = "studio-actions-spacer" });
            undoButton = MakeButton("studio-undo", "撤销", () => canvas.Undo());
            actions.Add(undoButton);
            actions.Add(MakeButton("studio-clear", "清空", () => canvas.ClearDrawing()));
            status = new Label("照片与涂鸦只保存在这台电脑。") { name = "studio-status" };
            if (!string.IsNullOrEmpty(CartProfileStore.LastLoadWarning))
            {
                status.text = "资料读取有误，请确认小车外观。";
                status.tooltip = CartProfileStore.LastLoadWarning;
            }
            panel.Add(status);
            finishButton = MakeButton("studio-finish", "完成，进入第一章", Finish, "studio-primary");
            panel.Add(finishButton);
            brushButton.AddToClassList("selected");
            inkButtons[0].AddToClassList("selected");
            sizeButtons[1].AddToClassList("selected");
            UpdateBodySelection();
            PublishPreview(true);
            dirty = false;
            Show();
        }

        static VisualElement Row(string name, VisualElement parent)
        {
            var row = new VisualElement { name = name };
            row.AddToClassList("studio-row"); parent.Add(row); return row;
        }

        static Button MakeButton(string name, string text, Action clicked, string extraClass = null)
        {
            var button = new Button(clicked) { name = name, text = text };
            button.AddToClassList("studio-button");
            if (extraClass != null) button.AddToClassList(extraClass);
            return button;
        }

        static Button MakeSwatch(string name, string hex, Action clicked)
        {
            var button = new Button(clicked) { name = name, tooltip = hex };
            button.AddToClassList("studio-swatch");
            ColorUtility.TryParseHtmlString(hex, out Color color);
            button.style.backgroundColor = color;
            button.userData = hex;
            return button;
        }

        void SetBodyColor(string hex)
        {
            Profile.bodyColor = CartProfileStore.NormalizeColor(hex);
            ColorUtility.TryParseHtmlString(Profile.bodyColor, out bodyColor);
            UpdateBodySelection();
            PublishPreview(false);
        }

        void UpdateBodySelection()
        {
            foreach (Button choice in bodyButtons)
                choice.EnableInClassList("selected", string.Equals((string)choice.userData, Profile.bodyColor, StringComparison.OrdinalIgnoreCase));
        }

        void SetInkColor(string hex)
        {
            ColorUtility.TryParseHtmlString(hex, out Color color);
            canvas.BrushColor = color;
            SetEraser(false);
            foreach (Button choice in inkButtons)
                choice.EnableInClassList("selected", string.Equals((string)choice.userData, hex, StringComparison.OrdinalIgnoreCase));
            PublishPreview(false);
        }

        void SetEraser(bool erasing)
        {
            canvas.FinishStroke();
            canvas.Erasing = erasing;
            brushButton.EnableInClassList("selected", !erasing);
            eraserButton.EnableInClassList("selected", erasing);
            PublishPreview(false);
        }

        void AddPhoto()
        {
            canvas.FinishStroke();
            try
            {
                string path = NativeImagePicker.PickImage();
                if (string.IsNullOrEmpty(path)) return;
                Texture2D replacement = CartProfileStore.LoadPhoto(path);
                UnityEngine.Object.Destroy(photo);
                photo = replacement;
                photoPixels = photo.GetPixels32();
                HasPhoto = true;
                status.text = "照片已添加，也可以在上面画。";
                PublishPreview(true);
            }
            catch (Exception) { status.text = "照片没能打开，请换一张图片。"; }
        }

        void RemovePhoto()
        {
            UnityEngine.Object.Destroy(photo);
            photo = CartProfileStore.DecodeLayer(null);
            photoPixels = photo.GetPixels32();
            HasPhoto = false;
            status.text = "照片已移除，涂鸦仍然保留。";
            PublishPreview(true);
        }

        void PublishPreview(bool composite)
        {
            if (disposed || canvas == null) return;
            dirty = true;
            if (composite)
            {
                Color32[] drawing = canvas.Pixels;
                for (int i = 0; i < compositePixels.Length; i++)
                {
                    Color32 top = drawing[i], bottom = photoPixels[i];
                    float topAlpha = top.a / 255f;
                    float bottomWeight = bottom.a / 255f * (1f - topAlpha);
                    float alpha = topAlpha + bottomWeight;
                    compositePixels[i] = alpha <= 0 ? new Color32(0, 0, 0, 0) : new Color32(
                        (byte)Mathf.RoundToInt((top.r * topAlpha + bottom.r * bottomWeight) / alpha),
                        (byte)Mathf.RoundToInt((top.g * topAlpha + bottom.g * bottomWeight) / alpha),
                        (byte)Mathf.RoundToInt((top.b * topAlpha + bottom.b * bottomWeight) / alpha),
                        (byte)Mathf.RoundToInt(alpha * 255f));
                }
                SkinTexture.SetPixels32(compositePixels);
                SkinTexture.Apply(false, false);
            }
            canvas.SetDisplay(SkinTexture, bodyColor);
            undoButton?.SetEnabled(canvas.UndoCount > 0);
            removePhotoButton?.SetEnabled(HasPhoto);
            onPreview?.Invoke(Profile, SkinTexture);
        }

        /// <summary>Save unfinished appearance on normal exit or focus loss, without entering a lesson.</summary>
        public bool SaveDraft()
        {
            if (disposed) return true;
            canvas.FinishStroke();
            if (!dirty) return true;
            try
            {
                Profile.displayName = CartProfileStore.SanitizeName(Profile.displayName);
                Profile.photoPng = HasPhoto ? CartProfileStore.Encode(photo) : string.Empty;
                Profile.drawingPng = CartProfileStore.Encode(canvas.DrawingTexture);
                CartProfileStore.Save(Profile);
                dirty = false;
                return true;
            }
            catch (Exception) { status.text = "还没能保存，请再试一次。"; return false; }
        }

        void Finish()
        {
            // Even the default appearance gets its first on-disk profile on Finish.
            dirty = true;
            if (!SaveDraft()) { finishButton.SetEnabled(true); return; }
            finishButton.SetEnabled(false);
            onStart?.Invoke();
        }

        public void Show()
        {
            Visible = true;
            root.style.display = DisplayStyle.Flex;
            finishButton.SetEnabled(true);
            Tick();
        }

        public void SetCustomizeMode(bool editing)
        {
            finishButton.text = editing ? "保存并返回课程" : "完成，进入第一章";
        }

        public void Hide()
        {
            canvas.FinishStroke();
            Visible = false;
            root.style.display = DisplayStyle.None;
        }

        public void Tick()
        {
            if (!Visible || disposed) return;
            if (!Application.isFocused) canvas.FinishStroke();
            if (Screen.width == lastWidth && Screen.height == lastHeight) return;
            canvas.FinishStroke();
            lastWidth = Screen.width; lastHeight = Screen.height;
            root.EnableInClassList("compact", Screen.width < 1000 || Screen.height < 700);
        }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            canvas.Dispose();
            root.RemoveFromHierarchy();
            UnityEngine.Object.Destroy(photo);
            UnityEngine.Object.Destroy(SkinTexture);
        }
    }
}
