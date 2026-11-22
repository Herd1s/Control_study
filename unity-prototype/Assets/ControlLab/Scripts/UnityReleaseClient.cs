using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace ControlLab.UnityPrototype
{
    public interface IUpdateTransport : IDisposable
    {
        Task<byte[]> ReadAsync(Uri uri, int maximumBytes, bool api, CancellationToken cancellation);
        Task DownloadAsync(Uri uri, string temporaryPath, long expectedBytes,
            Action<long> progress, CancellationToken cancellation);
    }

    public sealed class UpdateException : Exception
    {
        public UpdateException(string message) : base(message) { }
        public UpdateException(string message, Exception inner) : base(message, inner) { }
    }

    /// <summary>Only GitHub HTTPS redirects are followed. Public releases require no user token.</summary>
    public sealed class GitHubUpdateTransport : IUpdateTransport
    {
        readonly HttpClient http;
        public GitHubUpdateTransport() : this(new HttpClientHandler { AllowAutoRedirect = false }) { }
        public GitHubUpdateTransport(HttpMessageHandler handler)
        {
            http = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(35) };
            http.DefaultRequestHeaders.UserAgent.ParseAdd("ControlLab-Unity/" + AppVersion.Current);
        }

        public static void ValidateUrl(Uri uri)
        {
            if (uri == null || !uri.IsAbsoluteUri || uri.Scheme != Uri.UriSchemeHttps || uri.Port != 443
                || !string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Fragment)
                || !(uri.Host == "api.github.com" || uri.Host == "github.com"
                    || uri.Host == "release-assets.githubusercontent.com" || uri.Host == "objects.githubusercontent.com"
                    || uri.Host == "github-releases.githubusercontent.com"))
                throw new UpdateException("更新地址不属于受支持的 GitHub HTTPS 来源。");
        }

        async Task<HttpResponseMessage> OpenAsync(Uri uri, bool api, CancellationToken cancellation)
        {
            for (int redirects = 0; redirects <= 5; redirects++)
            {
                ValidateUrl(uri);
                using (var request = new HttpRequestMessage(HttpMethod.Get, uri))
                {
                    request.Headers.Accept.ParseAdd(api ? "application/vnd.github+json" : "application/octet-stream");
                    if (api) request.Headers.Add("X-GitHub-Api-Version", "2022-11-28");
                    HttpResponseMessage response;
                    try { response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellation).ConfigureAwait(false); }
                    catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
                    { throw new UpdateException("连接 GitHub 超时，请稍后重试。"); }
                    catch (HttpRequestException error) { throw new UpdateException("暂时无法连接 GitHub，请检查网络后重试。", error); }
                    int code = (int)response.StatusCode;
                    if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308)
                    {
                        Uri next = response.Headers.Location;
                        response.Dispose();
                        if (next == null || redirects == 5) throw new UpdateException("更新下载地址重定向过多或不完整。");
                        uri = next.IsAbsoluteUri ? next : new Uri(uri, next);
                        continue;
                    }
                    if (code != 200)
                    {
                        response.Dispose();
                        if (code == 403 || code == 429) throw new UpdateException("GitHub 暂时限制请求，请稍后再检查。");
                        if (code == 404) throw new UpdateException("暂时无法读取发布信息，请稍后重试或查看项目。");
                        throw new UpdateException("GitHub 请求未完成（HTTP " + code + "），请稍后重试。");
                    }
                    return response;
                }
            }
            throw new UpdateException("更新下载地址无法解析。");
        }

        public async Task<byte[]> ReadAsync(Uri uri, int maximumBytes, bool api, CancellationToken cancellation)
        {
            using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation))
            {
                timeout.CancelAfter(TimeSpan.FromSeconds(45));
                try
                {
                    using (var response = await OpenAsync(uri, api, timeout.Token).ConfigureAwait(false))
                    using (var stream = await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
                    using (var data = new MemoryStream())
                    {
                        if (response.Content.Headers.ContentLength > maximumBytes)
                            throw new UpdateException("发布信息超过大小限制。");
                        var buffer = new byte[16384];
                        while (true)
                        {
                            int count = await stream.ReadAsync(buffer, 0, buffer.Length, timeout.Token).ConfigureAwait(false);
                            if (count == 0) break;
                            if (data.Length + count > maximumBytes) throw new UpdateException("发布信息超过大小限制。");
                            data.Write(buffer, 0, count);
                        }
                        return data.ToArray();
                    }
                }
                catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
                { throw new UpdateException("读取发布信息超时，请稍后重试。"); }
            }
        }

        public async Task DownloadAsync(Uri uri, string temporaryPath, long expectedBytes,
            Action<long> progress, CancellationToken cancellation)
        {
            using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation))
            {
                timeout.CancelAfter(TimeSpan.FromMinutes(15));
                try
                {
                    using (var response = await OpenAsync(uri, false, timeout.Token).ConfigureAwait(false))
                    using (var stream = await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
                    using (var output = new FileStream(temporaryPath, FileMode.CreateNew, FileAccess.Write, FileShare.None, 65536, true))
                    {
                        long? length = response.Content.Headers.ContentLength;
                        if (length.HasValue && length.Value != expectedBytes) throw new UpdateException("安装包大小与发布信息不一致，请重新检查更新。");
                        var buffer = new byte[65536];
                        long total = 0;
                        while (true)
                        {
                            int count;
                            using (var idle = CancellationTokenSource.CreateLinkedTokenSource(timeout.Token))
                            {
                                idle.CancelAfter(TimeSpan.FromSeconds(45));
                                count = await stream.ReadAsync(buffer, 0, buffer.Length, idle.Token).ConfigureAwait(false);
                            }
                            if (count == 0) break;
                            total += count;
                            if (total > expectedBytes) throw new UpdateException("安装包超过声明大小，下载已停止。");
                            await output.WriteAsync(buffer, 0, count, timeout.Token).ConfigureAwait(false);
                            progress?.Invoke(total);
                        }
                        if (total != expectedBytes) throw new UpdateException("安装包下载不完整，请重新下载。");
                        output.Flush(true);
                    }
                }
                catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
                { throw new UpdateException("下载连接超时，请重新下载。"); }
            }
        }

        public void Dispose() => http.Dispose();
    }

    public sealed class UnityRelease
    {
        public readonly string Version, Notes, AssetName, Sha256, Tag;
        public readonly long Size;
        public readonly Uri DownloadUrl;
        public UnityRelease(string version, string notes, string assetName, string sha256, string tag, long size, Uri downloadUrl)
        { Version = version; Notes = notes; AssetName = assetName; Sha256 = sha256; Tag = tag; Size = size; DownloadUrl = downloadUrl; }
    }

    [DataContract] public sealed class UnityUpdateManifest
    {
        [DataMember(IsRequired = true)] public int schema;
        [DataMember(IsRequired = true)] public string productId;
        [DataMember(IsRequired = true)] public string platform;
        [DataMember(IsRequired = true)] public string version;
        [DataMember(IsRequired = true)] public string assetName;
        [DataMember(IsRequired = true)] public long size;
        [DataMember(IsRequired = true)] public string sha256;
    }
    [DataContract] public sealed class GitHubReleaseAsset
    {
        [DataMember] public string name;
        [DataMember] public string browser_download_url;
        [DataMember] public string state;
        [DataMember] public long size;
    }
    [DataContract] public sealed class GitHubReleaseInfo
    {
        [DataMember] public string tag_name;
        [DataMember] public bool draft;
        [DataMember] public bool prerelease;
        [DataMember] public string body;
        [DataMember] public GitHubReleaseAsset[] assets;
    }

    /// <summary>Product-specific discovery. The repository also contains retired Python releases.</summary>
    public sealed class UnityReleaseClient
    {
        public const string ReleasesUrl = "https://api.github.com/repos/" + AppVersion.Repository + "/releases";
        public const long MaxInstallerBytes = 2L * 1024 * 1024 * 1024;
        readonly IUpdateTransport transport;
        public UnityReleaseClient(IUpdateTransport transport) { this.transport = transport ?? throw new ArgumentNullException(nameof(transport)); }

        public static Version ParseVersion(string value)
        {
            if (value == null || !Regex.IsMatch(value, @"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"))
                throw new UpdateException("发布版本号无效。");
            if (!Version.TryParse(value, out Version result)) throw new UpdateException("发布版本号无效。");
            return result;
        }

        public static T ReadJson<T>(byte[] bytes)
        {
            try
            {
                using (var stream = new MemoryStream(bytes, false))
                {
                    var serializer = new DataContractJsonSerializer(typeof(T), new DataContractJsonSerializerSettings { MaxItemsInObjectGraph = 30000 });
                    var value = serializer.ReadObject(stream);
                    if (value == null) throw new SerializationException("Empty JSON value.");
                    return (T)value;
                }
            }
            catch (Exception error) when (error is SerializationException || error is System.Xml.XmlException
                || error is FormatException || error is InvalidCastException || error is ArgumentException)
            { throw new UpdateException("发布信息格式不正确，暂不能更新。", error); }
        }

        public static Uri ValidateAssetUrl(string value, string tag, string name)
        {
            if (!Uri.TryCreate(value, UriKind.Absolute, out Uri uri)) throw new UpdateException("发布文件地址无效。");
            GitHubUpdateTransport.ValidateUrl(uri);
            string expected = "/" + AppVersion.Repository + "/releases/download/" + tag + "/" + name;
            if (uri.Host != "github.com" || !string.Equals(Uri.UnescapeDataString(uri.AbsolutePath), expected, StringComparison.Ordinal)
                || !string.IsNullOrEmpty(uri.Query))
                throw new UpdateException("安装文件不属于当前 Unity 版本和发布仓库。");
            return uri;
        }

        static GitHubReleaseAsset FindAsset(GitHubReleaseInfo release, string name)
        {
            GitHubReleaseAsset[] matches = (release.assets ?? Array.Empty<GitHubReleaseAsset>()).Where(a => a != null && a.name == name).ToArray();
            if (matches.Length != 1 || matches[0].state != "uploaded") throw new UpdateException("Unity 发布文件缺失或重复，请稍后重试。");
            return matches[0];
        }

        public async Task<UnityRelease> FindLatestAsync(CancellationToken cancellation)
        {
            var candidates = new List<GitHubReleaseInfo>();
            // Explicit pages avoid depending on the repository's global latest-release pointer.
            const int pageSize = 100, maxPages = 20;
            for (int page = 1; page <= maxPages; page++)
            {
                cancellation.ThrowIfCancellationRequested();
                byte[] bytes = await transport.ReadAsync(new Uri(ReleasesUrl + "?per_page=" + pageSize + "&page=" + page),
                    4 * 1024 * 1024, true, cancellation).ConfigureAwait(false);
                var releases = ReadJson<GitHubReleaseInfo[]>(bytes);
                foreach (var release in releases)
                    if (release != null && !release.draft && !release.prerelease && release.tag_name != null
                        && Regex.IsMatch(release.tag_name, @"^unity-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"))
                        candidates.Add(release);
                if (releases.Length < pageSize) break;
                if (page == maxPages) throw new UpdateException("发布列表过长，暂时无法确认最新版本，请查看项目页面。");
            }
            if (candidates.Count == 0) return null;
            candidates.Sort((a, b) => ParseVersion(b.tag_name.Substring(7)).CompareTo(ParseVersion(a.tag_name.Substring(7))));
            GitHubReleaseInfo newest = candidates[0];
            string version = newest.tag_name.Substring(7);
            GitHubReleaseAsset manifestAsset = FindAsset(newest, "unity-update.json");
            if (manifestAsset.size <= 0 || manifestAsset.size > 16384) throw new UpdateException("Unity 发布清单大小无效。");
            Uri manifestUrl = ValidateAssetUrl(manifestAsset.browser_download_url, newest.tag_name, "unity-update.json");
            byte[] manifestBytes = await transport.ReadAsync(manifestUrl, 16384, false, cancellation).ConfigureAwait(false);
            if (manifestBytes.LongLength != manifestAsset.size) throw new UpdateException("Unity 发布清单下载不完整。");
            UnityUpdateManifest manifest = ReadJson<UnityUpdateManifest>(manifestBytes);
            string assetName = "ControlLab-Unity-Setup-" + version + ".exe";
            if (manifest.schema != 1 || manifest.productId != AppVersion.ProductId || manifest.platform != AppVersion.Platform
                || manifest.version != version || manifest.assetName != assetName || manifest.size <= 0 || manifest.size > MaxInstallerBytes
                || manifest.sha256 == null || !Regex.IsMatch(manifest.sha256, @"^[0-9a-fA-F]{64}$"))
                throw new UpdateException("发布清单与当前 Unity 产品或平台不匹配，已停止更新。");
            GitHubReleaseAsset installer = FindAsset(newest, assetName);
            if (installer.size != manifest.size) throw new UpdateException("安装包大小与 Unity 发布清单不一致。");
            Uri installerUrl = ValidateAssetUrl(installer.browser_download_url, newest.tag_name, assetName);
            string notes = newest.body ?? "此版本没有附加更新说明。";
            notes = Regex.Replace(notes, @"[\x00-\x08\x0B\x0C\x0E-\x1F]", "");
            if (notes.Length > 4000) notes = notes.Substring(0, 4000) + "\n完整说明请查看项目页面。";
            return new UnityRelease(version, notes, assetName, manifest.sha256.ToLowerInvariant(), newest.tag_name, manifest.size, installerUrl);
        }
    }
}
