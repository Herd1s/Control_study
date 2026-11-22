using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;

namespace ControlLab.UnityPrototype
{
    /// <summary>Settings presentation; the controller owns storage, textures and update work.</summary>
    public sealed class SettingsPanel : IDisposable
    {
        const string ProjectUrl = "https://github.com/Herd1s/Control_study";
        readonly VisualElement mask, panel;
        readonly Dictionary<string, VisualElement> pages = new Dictionary<string, VisualElement>();
        readonly Dictionary<string, Button> tabs = new Dictionary<string, Button>();
        readonly string[] pageNames = { "learning", "cart", "updates", "about" };
        readonly Button closeButton;
        Button rememberButton, checkButton, downloadButton, installButton, cancelButton;
        Label learningDescription, checkpointLabel, learningStatus, cartName, currentVersion, aboutVersion;
        Label updateStatus, updateNotes, globalStatus;
        VisualElement cartBody, cartTop, cartSkin, progressTrack, progressFill;
        bool remember = true, disposed, indeterminate;
        int lastWidth, lastHeight;
        string fullNotes = "";
        float pageFade = 1;

        public bool IsOpen { get; private set; }
        public string ActivePage { get; private set; } = "learning";

        public SettingsPanel(VisualElement host, Action onClose, Action<bool> onRememberChanged,
            Action onEditCart, Action onCheckUpdates, Action onDownload, Action onInstall, Action onCancelUpdate)
        {
            if (host == null) throw new ArgumentNullException(nameof(host));
            StyleSheet styles = Resources.Load<StyleSheet>("Settings");
            if (styles == null) throw new InvalidOperationException("Settings stylesheet is missing.");
            host.styleSheets.Add(styles);
            mask = new VisualElement { name = "settings-mask" };
            panel = Element("settings-panel", mask);
            var header = Element("settings-header", panel);
            var identity = Element("settings-identity", header);
            identity.Add(Text("settings-brand-mark", "C"));
            identity.Add(Text("settings-title", "设置"));
            closeButton = Button("settings-close", "返回课程", onClose, "settings-soft-button");
            header.Add(closeButton);
            var body = Element("settings-body", panel);
            var navigation = Element("settings-navigation", body);
            string[] titles = { "学习", "我的小车", "软件更新", "关于" };
            for (int i = 0; i < pageNames.Length; ++i)
            {
                string pageName = pageNames[i];
                int index = i;
                var tab = Button("settings-tab-" + pageName, titles[i], () => SelectPage(pageName), "settings-navigation-button");
                tab.RegisterCallback<KeyDownEvent>(evt =>
                {
                    int offset = evt.keyCode == KeyCode.UpArrow || evt.keyCode == KeyCode.LeftArrow ? -1 :
                        evt.keyCode == KeyCode.DownArrow || evt.keyCode == KeyCode.RightArrow ? 1 : 0;
                    if (offset == 0) return;
                    string next = pageNames[(index + offset + pageNames.Length) % pageNames.Length];
                    SelectPage(next); tabs[next].Focus(); evt.StopPropagation();
                });
                tabs.Add(pageName, tab); navigation.Add(tab);
            }
            var content = Element("settings-content", body);
            foreach (string name in pageNames)
            {
                var page = Element("settings-page-" + name, content, "settings-page");
                pages.Add(name, page);
                page.style.display = name == ActivePage ? DisplayStyle.Flex : DisplayStyle.None;
            }
            globalStatus = Text("settings-status", "");
            globalStatus.style.display = DisplayStyle.None;
            content.Add(globalStatus);
            BuildLearning(onRememberChanged);
            BuildCart(onEditCart);
            BuildUpdates(onCheckUpdates, onDownload, onInstall, onCancelUpdate);
            BuildAbout();
            tabs[ActivePage].AddToClassList("selected");
            host.Add(mask); mask.style.display = DisplayStyle.None;
            SetLearning(true, "尚未开始第一章", "");
            SetUpdate(AppVersion.Current, "准备好时，检查一下更新。", "", -1, true, false, false, false);
        }

        void BuildLearning(Action<bool> onRememberChanged)
        {
            var page = pages["learning"];
            Heading(page, "learning", "按自己的节奏学习", "随时离开，下次接着探索。");
            var preference = Element("settings-learning-card", page, "settings-card");
            var row = Element("settings-progress-row", preference);
            row.Add(Text("settings-progress-label", "下次继续上次进度"));
            rememberButton = Button("settings-remember", "开启", () => onRememberChanged?.Invoke(!remember), "settings-action");
            row.Add(rememberButton);
            learningDescription = Text("settings-description", "", "settings-copy");
            preference.Add(learningDescription);
            var checkpoint = Element("settings-checkpoint-card", page, "settings-soft-card");
            checkpoint.Add(Text("settings-checkpoint-title", "上次的学习位置", "settings-card-title"));
            checkpointLabel = Text("settings-checkpoint", "", "settings-copy"); checkpoint.Add(checkpointLabel);
            Spacer(page);
            learningStatus = Text("settings-learning-status", "小车装扮与学习记录始终保留。", "settings-footnote");
            page.Add(learningStatus);
        }

        void BuildCart(Action onEditCart)
        {
            var page = pages["cart"];
            Heading(page, "cart", "一辆属于你的小车", "换个颜色，给探索添一点自己的风格。");
            var card = Element("settings-cart-card", page, "settings-soft-card");
            var art = Element("settings-cart-art", card);
            Element("settings-cart-rail", art);
            cartBody = Element("settings-cart-body", art);
            cartTop = Element("settings-cart-top", art);
            cartSkin = Element("settings-cart-skin", cartBody);
            for (int i = 0; i < 2; ++i)
            {
                var wheel = Element("settings-cart-wheel-" + i, art, "settings-cart-wheel");
                Element("settings-cart-hub-" + i, wheel, "settings-cart-hub");
            }
            var details = Element("settings-cart-details", card);
            cartName = Text("settings-cart-name", "我的小车"); details.Add(cartName);
            details.Add(Text("settings-cart-summary", "颜色、照片与自由涂鸦", "settings-copy"));
            details.Add(Button("settings-edit-cart", "编辑外观", onEditCart, "settings-action", "settings-primary"));
            Spacer(page);
            page.Add(Text("settings-cart-return-note", "修改外观后，返回正在学习的课程。", "settings-footnote"));
        }

        void BuildUpdates(Action onCheck, Action onDownload, Action onInstall, Action onCancel)
        {
            var page = pages["updates"];
            Heading(page, "updates", "让探索继续生长", "有新版本时，由你决定何时更新。");
            var version = Element("settings-version-row", page);
            version.Add(Text("settings-version-mark", "C"));
            var details = Element("settings-version-details", version);
            details.Add(Text("settings-version-name", "ControlLab Unity", "settings-card-title"));
            currentVersion = Text("settings-current-version", "", "settings-copy"); details.Add(currentVersion);
            var card = Element("settings-update-card", page, "settings-card");
            updateStatus = Text("settings-update-status", "", "settings-card-title"); card.Add(updateStatus);
            updateNotes = Text("settings-update-notes", "", "settings-copy"); card.Add(updateNotes);
            progressTrack = Element("settings-update-progress", card);
            progressFill = Element("settings-update-progress-fill", progressTrack);
            var actions = Element("settings-update-actions", page);
            checkButton = Button("settings-update-check", "检查更新", onCheck, "settings-action", "settings-primary");
            downloadButton = Button("settings-update-download", "下载更新", onDownload, "settings-action", "settings-primary");
            installButton = Button("settings-update-install", "安装并重新打开", onInstall, "settings-action", "settings-primary");
            cancelButton = Button("settings-update-cancel", "取消", onCancel, "settings-action", "settings-secondary");
            actions.Add(checkButton); actions.Add(downloadButton); actions.Add(installButton); actions.Add(cancelButton);
            actions.Add(Button("settings-release-link", "版本记录", () => Application.OpenURL(ProjectUrl + "/releases"), "settings-action", "settings-secondary"));
            Spacer(page);
            page.Add(Text("settings-update-note", "更新软件，保留你的学习资料。", "settings-footnote"));
        }

        void BuildAbout()
        {
            var page = pages["about"];
            Heading(page, "about", "ControlLab", "从亲手感受，到理解控制。");
            var card = Element("settings-about-card", page, "settings-soft-card");
            card.Add(Text("settings-about-product", "Unity 教学实验室", "settings-card-title"));
            aboutVersion = Text("settings-about-version", "当前版本 · " + AppVersion.Current, "settings-copy"); card.Add(aboutVersion);
            page.Add(Text("settings-about-data", "学习进度、小车照片与涂鸦保存在这台电脑。\n软件更新不会清空这些资料。", "settings-about-copy"));
            Spacer(page);
            page.Add(Button("settings-project-link", "GitHub 项目", () => Application.OpenURL(ProjectUrl), "settings-action", "settings-secondary"));
        }

        public void Show()
        {
            if (disposed) return;
            IsOpen = true; mask.style.display = DisplayStyle.Flex; mask.BringToFront();
            pageFade = 1; pages[ActivePage].style.opacity = 1;
            Tick(); closeButton.Focus();
        }

        public void Hide() { IsOpen = false; mask.style.display = DisplayStyle.None; }
        public void SetCloseText(string text) => closeButton.text = string.IsNullOrEmpty(text) ? "返回课程" : text;

        public void SelectPage(string name)
        {
            if (!pages.ContainsKey(name)) throw new ArgumentOutOfRangeException(nameof(name));
            if (ActivePage == name) return;
            pages[ActivePage].style.display = DisplayStyle.None;
            tabs[ActivePage].EnableInClassList("selected", false);
            ActivePage = name; pages[name].style.display = DisplayStyle.Flex;
            tabs[name].EnableInClassList("selected", true);
            pageFade = IsOpen ? 0 : 1; pages[name].style.opacity = pageFade;
        }

        public void SetLearning(bool remember, string checkpoint, string status)
        {
            this.remember = remember;
            rememberButton.text = remember ? "开启" : "关闭";
            rememberButton.EnableInClassList("settings-primary", remember);
            rememberButton.EnableInClassList("settings-secondary", !remember);
            rememberButton.tooltip = remember ? "下次打开自动继续上次进度" : "下次从首页进入，学习记录仍然保留";
            learningDescription.text = remember ? "打开软件时，回到上次的页面与讲解。" : "下次从首页进入，已有学习记录仍然保留。";
            checkpointLabel.text = Clip(checkpoint, 90); checkpointLabel.tooltip = checkpoint ?? "";
            learningStatus.text = string.IsNullOrWhiteSpace(status) ? "小车装扮与学习记录始终保留。" : Clip(status, 96);
            learningStatus.tooltip = status ?? "";
        }

        public void SetCart(string name, Color color, Texture2D skin)
        {
            cartName.text = string.IsNullOrWhiteSpace(name) ? "我的小车" : name; cartName.tooltip = cartName.text;
            cartBody.style.backgroundColor = color;
            cartTop.style.backgroundColor = Color.Lerp(color, Color.white, .45f);
            // The studio owns this texture; this panel only borrows its preview.
            cartSkin.style.backgroundImage = skin == null ? new StyleBackground(StyleKeyword.None) : new StyleBackground(skin);
        }

        public void SetUpdate(string version, string status, string notes, float progress,
            bool canCheck, bool canDownload, bool canInstall, bool canCancel)
        {
            currentVersion.text = "当前版本 · " + (version ?? AppVersion.Current); aboutVersion.text = currentVersion.text;
            updateStatus.text = Clip(status, 110); updateStatus.tooltip = status ?? "";
            fullNotes = notes ?? ""; SetNotesPreview();
            checkButton.style.display = canDownload || canInstall ? DisplayStyle.None : DisplayStyle.Flex;
            checkButton.SetEnabled(canCheck);
            downloadButton.style.display = canDownload ? DisplayStyle.Flex : DisplayStyle.None;
            installButton.style.display = canInstall ? DisplayStyle.Flex : DisplayStyle.None;
            cancelButton.style.display = canCancel ? DisplayStyle.Flex : DisplayStyle.None;
            progressTrack.style.display = canCancel ? DisplayStyle.Flex : DisplayStyle.None;
            indeterminate = canCancel && (float.IsNaN(progress) || progress < 0);
            progressFill.style.width = Length.Percent(indeterminate ? 30 : Mathf.Clamp01(progress) * 100);
            if (!indeterminate) progressFill.style.left = 0;
        }

        public void SetStatus(string text)
        {
            globalStatus.text = Clip(text, 100); globalStatus.tooltip = text ?? "";
            globalStatus.style.display = string.IsNullOrWhiteSpace(text) ? DisplayStyle.None : DisplayStyle.Flex;
        }

        void SetNotesPreview()
        {
            updateNotes.text = Clip(fullNotes, lastWidth < 1000 || lastHeight < 700 ? 76 : 130);
            updateNotes.tooltip = Clip(fullNotes, 3000);
            updateNotes.style.display = string.IsNullOrWhiteSpace(fullNotes) ? DisplayStyle.None : DisplayStyle.Flex;
        }

        public void Tick()
        {
            if (disposed || !IsOpen) return;
            if (lastWidth != Screen.width || lastHeight != Screen.height)
            {
                lastWidth = Screen.width; lastHeight = Screen.height;
                mask.EnableInClassList("settings-compact", lastWidth < 1000 || lastHeight < 700);
                panel.style.width = Mathf.Max(1, Mathf.Min(1040, lastWidth - 48));
                panel.style.height = Mathf.Max(1, Mathf.Min(620, lastHeight - 48));
                SetNotesPreview();
            }
            if (pageFade < 1)
            {
                pageFade = Mathf.Min(1, pageFade + Mathf.Min(Time.unscaledDeltaTime, .1f) / .16f);
                pages[ActivePage].style.opacity = Mathf.SmoothStep(0, 1, pageFade);
            }
            if (indeterminate) progressFill.style.left = Length.Percent(Mathf.PingPong(Time.unscaledTime * 35, 70));
        }

        static void Heading(VisualElement parent, string name, string title, string subtitle)
        {
            var heading = Element("settings-" + name + "-heading", parent, "settings-heading");
            heading.Add(Text("settings-" + name + "-title", title, "settings-page-title"));
            heading.Add(Text("settings-" + name + "-lead", subtitle, "settings-lead"));
        }
        static void Spacer(VisualElement parent) => Element("", parent, "settings-spacer");
        static VisualElement Element(string name, VisualElement parent, string className = null)
        {
            var element = new VisualElement { name = name };
            if (!string.IsNullOrEmpty(className)) element.AddToClassList(className);
            parent.Add(element); return element;
        }
        static Label Text(string name, string text, string className = null)
        {
            var label = new Label(text) { name = name, enableRichText = false, pickingMode = PickingMode.Ignore };
            if (!string.IsNullOrEmpty(className)) label.AddToClassList(className);
            return label;
        }
        static Button Button(string name, string text, Action clicked, params string[] classes)
        {
            var button = new Button(() => clicked?.Invoke()) { name = name, text = text, enableRichText = false };
            foreach (string className in classes) button.AddToClassList(className);
            return button;
        }
        static string Clip(string value, int limit)
        {
            if (string.IsNullOrWhiteSpace(value)) return "";
            value = value.Trim(); if (value.Length <= limit) return value;
            int length = char.IsHighSurrogate(value[limit - 1]) ? limit - 1 : limit;
            return value.Substring(0, length).TrimEnd() + "…";
        }
        public void Dispose()
        {
            if (disposed) return;
            disposed = true; IsOpen = false;
            cartSkin.style.backgroundImage = new StyleBackground(StyleKeyword.None);
            mask.RemoveFromHierarchy();
        }
    }
}
