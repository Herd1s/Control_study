using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace ControlLab.UnityPrototype
{
    public enum UnityUpdateState { Idle, Checking, NoRelease, UpToDate, Available, Downloading, Ready, Error, Cancelled, Installing }

    /// <summary>Immutable snapshot: background operations never touch Unity's UI or game objects.</summary>
    public sealed class UnityUpdateSnapshot
    {
        public UnityUpdateState State { get; }
        public string Status { get; }
        public string Notes { get; }
        public string AvailableVersion { get; }
        public float Progress { get; }
        public bool CanCheck { get; }
        public bool CanDownload { get; }
        public bool CanInstall { get; }
        public bool CanCancel { get; }
        internal UnityUpdateSnapshot(UnityUpdateState state, string status, UnityRelease release, float progress, bool ready)
        {
            State = state; Status = status; Notes = release?.Notes ?? ""; AvailableVersion = release?.Version ?? ""; Progress = progress;
            bool busy = state == UnityUpdateState.Checking || state == UnityUpdateState.Downloading || state == UnityUpdateState.Installing;
            CanCheck = !busy;
            CanDownload = !busy && release != null && !ready;
            CanInstall = !busy && ready;
            CanCancel = state == UnityUpdateState.Checking || state == UnityUpdateState.Downloading;
        }
    }

    public interface IInstallerProcessLauncher { void Start(ProcessStartInfo startInfo); }
    public sealed class InstallerProcessLauncher : IInstallerProcessLauncher
    {
        public void Start(ProcessStartInfo startInfo)
        {
            using (Process process = Process.Start(startInfo))
                if (process == null) throw new IOException("安装器没有启动。");
        }
    }

    [DataContract] sealed class PendingUnityUpdate
    {
        [DataMember(IsRequired = true)] public int schema = 1;
        [DataMember(IsRequired = true)] public string productId;
        [DataMember(IsRequired = true)] public string version;
        [DataMember(IsRequired = true)] public string sha256;
        [DataMember] public string status;
        [DataMember] public string utc;
    }
    [DataContract] sealed class UnityInstallationMarker
    {
        [DataMember] public string productId = string.Empty;
        [DataMember] public string version = string.Empty;
        [DataMember] public string status = string.Empty;
    }

    /// <summary>Manual check → verified download → external installer. Disposing cancels network work.</summary>
    public sealed class UnityUpdateService : IDisposable
    {
        readonly object gate = new object();
        readonly string currentVersion, directory;
        readonly IUpdateTransport transport;
        readonly IInstallerProcessLauncher launcher;
        readonly UnityReleaseClient releases;
        CancellationTokenSource operation;
        UnityRelease release;
        string verifiedPath;
        UnityUpdateSnapshot snapshot;
        bool disposed;

        public UnityUpdateSnapshot Snapshot { get { lock (gate) return snapshot; } }

        public UnityUpdateService(string currentVersion, string dataDirectory,
            IUpdateTransport transport = null, IInstallerProcessLauncher launcher = null)
        {
            UnityReleaseClient.ParseVersion(currentVersion);
            if (string.IsNullOrWhiteSpace(dataDirectory) || !Path.IsPathFullyQualified(dataDirectory))
                throw new ArgumentException("Update cache must use an absolute local directory.", nameof(dataDirectory));
            this.currentVersion = currentVersion;
            directory = Path.GetFullPath(dataDirectory);
            this.transport = transport ?? new GitHubUpdateTransport();
            this.launcher = launcher ?? new InstallerProcessLauncher();
            releases = new UnityReleaseClient(this.transport);
            snapshot = new UnityUpdateSnapshot(UnityUpdateState.Idle, "检查新版本，按自己的时间更新。", null, 0, false);
        }

        CancellationTokenSource Begin(UnityUpdateState state, string status)
        {
            lock (gate)
            {
                if (disposed || operation != null || snapshot.State == UnityUpdateState.Installing) return null;
                operation = new CancellationTokenSource();
                Set(state, status, -1);
                return operation;
            }
        }

        void Set(UnityUpdateState state, string status, float progress = 0)
        {
            snapshot = new UnityUpdateSnapshot(state, status, release, progress, !string.IsNullOrEmpty(verifiedPath));
        }

        public Task CheckAsync()
        {
            var token = Begin(UnityUpdateState.Checking, "正在检查新版本…");
            if (token == null) return Task.CompletedTask;
            return Task.Run(async () =>
            {
                try
                {
                    UnityRelease found = await releases.FindLatestAsync(token.Token).ConfigureAwait(false);
                    token.Token.ThrowIfCancellationRequested();
                    lock (gate)
                    {
                        if (disposed) return;
                        release = null;
                        verifiedPath = null;
                        if (found == null) Set(UnityUpdateState.NoRelease, "尚无 Unity 正式安装包，可以继续使用当前版本。");
                        else if (UnityReleaseClient.ParseVersion(found.Version) <= UnityReleaseClient.ParseVersion(currentVersion))
                            Set(UnityUpdateState.UpToDate, "你正在使用最新的 Unity 正式版本。");
                        else
                        {
                            release = found;
                            Set(UnityUpdateState.Available, "发现新版本 " + found.Version + " · " + FormatSize(found.Size));
                        }
                    }
                }
                catch (OperationCanceledException) { PublishCancelled("检查已取消。"); }
                catch (Exception error) { PublishError(error); }
                finally { End(token); }
            });
        }

        public Task DownloadAsync()
        {
            UnityRelease selected;
            lock (gate)
            {
                if (disposed || release == null || !snapshot.CanDownload) return Task.CompletedTask;
                selected = release;
            }
            var token = Begin(UnityUpdateState.Downloading, "正在下载安装包…");
            if (token == null) return Task.CompletedTask;
            return Task.Run(async () =>
            {
                string temporary = null;
                try
                {
                    Directory.CreateDirectory(directory);
                    string destination = Path.Combine(directory, selected.AssetName);
                    temporary = destination + "." + Guid.NewGuid().ToString("N") + ".part";
                    await transport.DownloadAsync(selected.DownloadUrl, temporary, selected.Size, count =>
                    {
                        lock (gate)
                            if (!disposed) Set(UnityUpdateState.Downloading, "正在下载 " + FormatSize(count) + " / " + FormatSize(selected.Size),
                                (float)Math.Min(.99, (double)count / selected.Size));
                    }, token.Token).ConfigureAwait(false);
                    token.Token.ThrowIfCancellationRequested();
                    if (!VerifyPackage(temporary, selected, token.Token)) throw new UpdateException("安装包校验失败，请重新下载。");
                    // Replacing only the exact versioned cache path never touches the installed program.
                    if (File.Exists(destination)) File.Replace(temporary, destination, null);
                    else File.Move(temporary, destination);
                    temporary = null;
                    lock (gate)
                    {
                        if (disposed) return;
                        verifiedPath = destination;
                        Set(UnityUpdateState.Ready, "下载完成，学习资料会在安装前保存。", 1);
                    }
                }
                catch (OperationCanceledException) { PublishCancelled("下载已取消，可以稍后重新下载。"); }
                catch (Exception error) { PublishError(error); }
                finally
                {
                    try { if (temporary != null && File.Exists(temporary)) File.Delete(temporary); }
                    catch (IOException) { }
                    catch (UnauthorizedAccessException) { }
                    End(token);
                }
            });
        }

        public static bool VerifyPackage(string path, UnityRelease selected, CancellationToken cancellation)
        {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (SHA256 hash = SHA256.Create())
            {
                if (stream.Length != selected.Size) return false;
                // Windows installers must at least be PE files, not HTML/error pages with a matching filename.
                if (stream.ReadByte() != 'M' || stream.ReadByte() != 'Z') return false;
                stream.Position = 0;
                var buffer = new byte[65536];
                int count;
                while ((count = stream.Read(buffer, 0, buffer.Length)) != 0)
                {
                    cancellation.ThrowIfCancellationRequested();
                    hash.TransformBlock(buffer, 0, count, buffer, 0);
                }
                hash.TransformFinalBlock(Array.Empty<byte>(), 0, 0);
                string actual = BitConverter.ToString(hash.Hash).Replace("-", "").ToLowerInvariant();
                return string.Equals(actual, selected.Sha256, StringComparison.OrdinalIgnoreCase);
            }
        }

        /// <summary>Call only after all learning and appearance data has been successfully saved.</summary>
        public bool TryLaunchInstaller(string currentExePath, out string error)
        {
            error = null;
            lock (gate)
            {
                if (disposed || operation != null || !snapshot.CanInstall || release == null || verifiedPath == null)
                { error = "安装包还没有准备好。"; return false; }
                try
                {
                    if (string.IsNullOrWhiteSpace(currentExePath) || !Path.IsPathFullyQualified(currentExePath)
                        || Path.GetFileName(currentExePath) != "ControlLab Unity.exe" || !File.Exists(currentExePath))
                        throw new UpdateException("请在构建好的 ControlLab Unity 软件中安装更新。");
                    bool packageValid;
                    try { packageValid = VerifyPackage(verifiedPath, release, CancellationToken.None); }
                    catch (IOException) { packageValid = false; }
                    catch (UnauthorizedAccessException) { packageValid = false; }
                    if (!packageValid)
                    {
                        verifiedPath = null;
                        throw new UpdateException("安装包在下载后发生了变化，请重新下载。");
                    }
                    Directory.CreateDirectory(directory);
                    string logPath = Path.Combine(directory, "install-" + release.Version + "-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + ".log");
                    string arguments = "/SP- /SILENT /SUPPRESSMSGBOXES /NORESTART /WAITFORPID=" + Process.GetCurrentProcess().Id
                        + " /RESTARTAPP=1 /LOG=" + Quote(logPath) + RestartProfileArgument(Environment.GetCommandLineArgs());
                    WritePending("launching");
                    launcher.Start(new ProcessStartInfo
                    {
                        FileName = verifiedPath,
                        Arguments = arguments,
                        WorkingDirectory = directory,
                        UseShellExecute = false
                    });
                    Set(UnityUpdateState.Installing, "正在交给安装器，完成后会重新打开软件。", 1);
                    return true;
                }
                catch (Exception failure)
                {
                    error = Friendly(failure);
                    Set(UnityUpdateState.Error, error);
                    return false;
                }
            }
        }

        internal static string RestartProfileArgument(string[] arguments)
        {
            // Preserve only the existing isolated-profile option, never arbitrary
            // restart command lines or an executable supplied by release metadata.
            for (int i = 0; i < arguments.Length; i++)
                if (arguments[i] == "--profile-directory")
                {
                    if (i + 1 >= arguments.Length || !Path.IsPathFullyQualified(arguments[i + 1]))
                        throw new UpdateException("重启资料目录必须使用绝对路径。");
                    return " /PROFILEDIR=" + Quote(Path.GetFullPath(arguments[i + 1]));
                }
            return string.Empty;
        }

        static string Quote(string path)
        {
            if (path.IndexOf('"') >= 0 || path.IndexOf('\r') >= 0 || path.IndexOf('\n') >= 0)
                throw new UpdateException("安装日志路径无效。");
            int trailingSlashes = path.Length - path.TrimEnd('\\').Length;
            return "\"" + path + new string('\\', trailingSlashes) + "\"";
        }

        void WritePending(string status)
        {
            var pending = new PendingUnityUpdate { productId = AppVersion.ProductId, version = release.Version,
                sha256 = release.Sha256, status = status, utc = DateTime.UtcNow.ToString("O") };
            WriteJson(Path.Combine(directory, "pending-update.json"), pending);
        }

        static void WriteJson<T>(string path, T value)
        {
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    new DataContractJsonSerializer(typeof(T)).WriteObject(stream, value);
                    stream.Flush(true);
                }
                if (File.Exists(path)) File.Replace(temporary, path, path + ".bak");
                else File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        /// <summary>A successful installer launch is not an installed update; check after restart.</summary>
        public void ConfirmInstallation(string currentExePath)
        {
            lock (gate)
            {
                if (disposed || operation != null || snapshot.State != UnityUpdateState.Idle) return;
                string pendingPath = Path.Combine(directory, "pending-update.json");
                if (!File.Exists(pendingPath)) return;
                try
                {
                    if (new FileInfo(pendingPath).Length > 8192) throw new UpdateException("上次更新记录无法读取。");
                    PendingUnityUpdate pending = UnityReleaseClient.ReadJson<PendingUnityUpdate>(File.ReadAllBytes(pendingPath));
                    string markerPath = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(currentExePath)), "installation.json");
                    if (pending.schema != 1 || pending.productId != AppVersion.ProductId) throw new UpdateException("上次更新记录无法读取。");
                    if (pending.version == currentVersion && Path.GetFileName(currentExePath) == "ControlLab Unity.exe"
                        && File.Exists(markerPath) && new FileInfo(markerPath).Length <= 8192)
                    {
                        var marker = UnityReleaseClient.ReadJson<UnityInstallationMarker>(File.ReadAllBytes(markerPath));
                        if (marker.productId == AppVersion.ProductId && marker.version == currentVersion && marker.status == "installed")
                        {
                            pending.status = "confirmed-on-restart";
                            WriteJson(Path.Combine(directory, "last-update.json"), pending);
                            File.Delete(pendingPath);
                            Set(UnityUpdateState.Idle, "已更新到 " + currentVersion + "，学习资料已保留。");
                            return;
                        }
                    }
                    Set(UnityUpdateState.Idle, "上次更新尚未确认完成，可以重新检查更新。");
                }
                catch (Exception) { Set(UnityUpdateState.Idle, "上次更新记录暂时无法读取，可以重新检查更新。"); }
            }
        }

        static string FormatSize(long bytes) => (bytes / 1048576d).ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + " MB";
        static string Friendly(Exception error)
        {
            if (error is UpdateException) return error.Message;
            if (error is UnauthorizedAccessException) return "没有权限保存或启动安装包，请检查本机目录。";
            if (error is IOException) return "安装包未能读写，请检查磁盘空间后重试。";
            return "更新操作未完成，请稍后重试或查看项目页面。";
        }
        void PublishError(Exception error) { lock (gate) if (!disposed) Set(UnityUpdateState.Error, Friendly(error)); }
        void PublishCancelled(string message) { lock (gate) if (!disposed) Set(UnityUpdateState.Cancelled, message); }
        void End(CancellationTokenSource token)
        {
            lock (gate)
            {
                if (operation == token) operation = null;
                token.Dispose();
            }
        }
        public void Cancel() { lock (gate) operation?.Cancel(); }
        public void Dispose()
        {
            lock (gate)
            {
                if (disposed) return;
                disposed = true;
                operation?.Cancel();
                transport.Dispose();
            }
        }
    }
}
