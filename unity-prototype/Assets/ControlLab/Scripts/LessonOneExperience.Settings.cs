using System;
using System.IO;
using UnityEngine;
using UnityEngine.UIElements;

namespace ControlLab.UnityPrototype
{
    public sealed partial class LessonOneExperience
    {
        LearningProgress progress;
        AppPreferences preferences;
        bool progressReady, settingsOpen, ignorePointerUntilReleased, preserveCheckpointOnStudio;
        SettingsPanel settingsPanel;
        Button settingsButton;
        UnityUpdateService updater;
        object shownUpdateSnapshot;
        string settingsMessage = "";

        public bool RememberProgress => preferences == null || preferences.rememberProgress;
        public bool SettingsOpen => settingsOpen;
        public string SettingsPage => settingsPanel?.ActivePage ?? "learning";
        public string SavedPage => progress?.page ?? "Studio";
        public int SavedConcept => progress?.concept ?? 0;
        public string UpdateState => updater?.Snapshot.State.ToString() ?? "Idle";
        public string UpdateStatus => updater?.Snapshot.Status ?? "";

        void InitializeSettings()
        {
            settingsButton = new Button(OpenSettings) { name = "settings-button", text = "设置" };
            settingsButton.AddToClassList("pill");
            settingsButton.AddToClassList("secondary");
            overlay.Add(settingsButton);
            updater = new UnityUpdateService(AppVersion.Current, Path.Combine(CartProfileStore.ProfileDirectory, "updates"));
            if (!Application.isEditor)
                using (var current = System.Diagnostics.Process.GetCurrentProcess())
                    updater.ConfirmInstallation(current.MainModule.FileName);
            settingsPanel = new SettingsPanel(overlay, CloseSettings, SetRememberProgress, EditCartFromSettings,
                CheckUpdates, DownloadUpdate, InstallUpdate, () => updater.Cancel());
            UpdateSettingsText();
            string warning = AppPreferencesStore.LastLoadWarning;
            if (string.IsNullOrEmpty(warning)) warning = LearningProgressStore.LastLoadWarning;
            if (!string.IsNullOrEmpty(warning)) SetSettingsMessage(warning);
            RefreshUpdateView();
        }

        void RestoreLearningProgress()
        {
            // Opting out changes the startup page, not the stored lesson position.
            preserveCheckpointOnStudio = progress.hasProgress && progress.page == "Lesson";
            if (RememberProgress && progress.hasProgress && progress.page == "Lesson")
            {
                int concept = progress.concept;
                bool showExplanation = progress.explanationOpen;
                EnterFirstChapter();
                SelectConcept(concept);
                if (showExplanation) ToggleExplanation();
                preserveCheckpointOnStudio = false;
            }
            progressReady = true;
            UpdateSettingsText();
        }

        void UpdateSettingsText()
        {
            if (settingsPanel == null) return;
            string checkpoint = progress != null && progress.hasProgress && progress.page == "Lesson"
                ? "第一章 · " + new[] { "动量与惯性", "重力与力矩", "怎样接住" }[progress.concept]
                : "装扮小车 · 准备出发";
            settingsPanel.SetLearning(RememberProgress, checkpoint, settingsMessage);
            settingsPanel.SetCart(cartName, cartBaseColor, studio?.SkinTexture);
            settingsPanel.SetCloseText(stage == ExperienceStage.Studio ? "返回小车" : "返回课程");
        }

        void SetSettingsMessage(string message)
        {
            settingsMessage = message;
            settingsPanel?.SetStatus(message);
        }

        void SetRememberProgress(bool remember)
        {
            try
            {
                var replacement = new AppPreferences { rememberProgress = remember };
                AppPreferencesStore.Save(replacement);
                preferences = replacement;
                SetSettingsMessage("已保存，学习记录和小车装扮始终保留。");
            }
            catch (Exception) { SetSettingsMessage("设置未能保存，请检查本机保存目录。"); }
            UpdateSettingsText();
        }

        void SetBackgroundEnabled(bool enabled)
        {
            string[] names = { "topbar", "hero", "footer", "explanation", "studio-root" };
            foreach (string name in names) overlay.Q<VisualElement>(name)?.SetEnabled(enabled);
            settingsButton.SetEnabled(enabled);
        }

        void OpenSettings()
        {
            if (settingsOpen) return;
            EndDrag();
            settingsOpen = true;
            SetBackgroundEnabled(false);
            UpdateSettingsText();
            settingsPanel.Show();
        }

        void CloseSettings()
        {
            if (!settingsOpen) return;
            updater.Cancel();
            settingsOpen = false;
            ignorePointerUntilReleased = true;
            settingsPanel.Hide();
            SetBackgroundEnabled(true);
            settingsButton.Focus();
        }

        void EditCartFromSettings()
        {
            CloseSettings();
            if (stage == ExperienceStage.Arriving) EnterFirstChapter();
            ShowStudio();
        }

        void TickSettings()
        {
            settingsPanel?.Tick();
            RefreshUpdateView();
        }

        void RefreshUpdateView()
        {
            if (updater == null || settingsPanel == null) return;
            var snapshot = updater.Snapshot;
            if (ReferenceEquals(snapshot, shownUpdateSnapshot)) return;
            shownUpdateSnapshot = snapshot;
            settingsPanel.SetUpdate(AppVersion.Current, snapshot.Status, snapshot.Notes, snapshot.Progress,
                snapshot.CanCheck, snapshot.CanDownload, snapshot.CanInstall && !Application.isEditor, snapshot.CanCancel);
        }

        async void CheckUpdates()
        {
            try { await updater.CheckAsync(); }
            catch (Exception) { if (this != null) SetSettingsMessage("检查更新未完成，请稍后重试。"); }
        }

        async void DownloadUpdate()
        {
            try { await updater.DownloadAsync(); }
            catch (Exception) { if (this != null) SetSettingsMessage("下载未完成，请稍后重试。"); }
        }

        void InstallUpdate()
        {
            if (Application.isEditor) { SetSettingsMessage("请在独立运行的软件中安装更新。"); return; }
            if (!SaveSession()) return;
            string executable;
            using (var current = System.Diagnostics.Process.GetCurrentProcess()) executable = current.MainModule.FileName;
            if (!updater.TryLaunchInstaller(executable, out string error)) { SetSettingsMessage(error); return; }
            // The installer waits for this process, then replaces files and starts the new Player.
            Application.Quit();
        }

        bool SaveLearningProgress()
        {
            if (!progressReady || progress == null) return true;
            bool preserve = customizingCart || (stage == ExperienceStage.Studio && preserveCheckpointOnStudio);
            var checkpoint = new LearningProgress
            {
                rememberProgress = RememberProgress, // Backwards-readable; preferences are authoritative.
                hasProgress = preserve ? progress.hasProgress : true,
                page = preserve ? progress.page : (stage == ExperienceStage.Studio ? "Studio" : "Lesson"),
                concept = preserve ? progress.concept : activeConcept,
                explanationOpen = preserve ? progress.explanationOpen : stage == ExperienceStage.Lesson && explanationOpen
            };
            try
            {
                LearningProgressStore.Save(checkpoint);
                progress = checkpoint;
                UpdateSettingsText();
                return true;
            }
            catch (Exception) { SetSettingsMessage("进度未能保存，请检查本机保存目录。"); return false; }
        }

        bool SaveSession()
        {
            if (!progressReady) return true;
            bool appearanceSaved = studio == null || studio.SaveDraft();
            bool progressSaved = SaveLearningProgress();
            if (!appearanceSaved) SetSettingsMessage("小车装扮未能保存，请检查本机保存目录。");
            return appearanceSaved && progressSaved;
        }
    }
}
