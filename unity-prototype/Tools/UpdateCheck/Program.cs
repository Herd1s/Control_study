using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Diagnostics;
using ControlLab.UnityPrototype;

static class Program
{
    static readonly List<object> Checks = new();
    static readonly byte[] Package = Encoding.UTF8.GetBytes("MZ - isolated updater contract fixture, never executed");
    static string fixtureRoot;
    static string Hex(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    static byte[] Json(object value) => JsonSerializer.SerializeToUtf8Bytes(value);
    static void Expect(bool passed, string name)
    {
        Checks.Add(new {name,passed});
        if (!passed) throw new Exception("FAIL: " + name);
    }
    static async Task Reject(Func<Task> action, string name)
    {
        bool rejected = false;
        try { await action(); } catch (UpdateException) { rejected = true; }
        Expect(rejected,name);
    }
    static string Cache(string label) => Path.Combine(fixtureRoot,label);

    static FakeTransport Release(string version="0.3.0", Action<Dictionary<string,object>> mutate=null)
    {
        var fake = new FakeTransport();
        string assetName = "ControlLab-Unity-Setup-" + version + ".exe";
        string tag = "unity-v" + version;
        var manifest = new Dictionary<string,object> {
            ["schema"]=1,["productId"]=AppVersion.ProductId,["platform"]=AppVersion.Platform,
            ["version"]=version,["assetName"]=assetName,["size"]=Package.LongLength,["sha256"]=Hex(Package)
        };
        mutate?.Invoke(manifest);
        byte[] encoded = Json(manifest);
        fake.Responses["page1"] = Json(new[] {new {
            tag_name=tag,draft=false,prerelease=false,body="更顺手的小车。\n保留你的装扮。",
            assets=new[] {
                new {name="unity-update.json",state="uploaded",size=(long)encoded.Length,browser_download_url=Asset(tag,"unity-update.json")},
                new {name=assetName,state="uploaded",size=Package.LongLength,browser_download_url=Asset(tag,assetName)}
            }
        }});
        fake.Responses[Asset(tag,"unity-update.json")] = encoded;
        fake.Package = Package;
        return fake;
    }
    static string Asset(string tag,string name) => AppVersion.ProjectUrl+"/releases/download/"+tag+"/"+name;

    static async Task Main(string[] args)
    {
        string output=Path.GetFullPath(args.Length>0?args[0]:"Logs/Verification/update-check");
        Directory.CreateDirectory(output);
        fixtureRoot=Path.Combine(output,"fixture-"+DateTime.UtcNow.ToString("yyyyMMddHHmmssfff"));
        Directory.CreateDirectory(fixtureRoot);
        bool live=args.Contains("--live");
        bool passed=false;
        string failure=null;
        object liveResult=null;
        try
        {
            Expect(UnityReleaseClient.ParseVersion("0.10.0")>UnityReleaseClient.ParseVersion("0.2.0"),"numeric semantic version ordering");
            await Reject(()=>Task.FromResult(UnityReleaseClient.ParseVersion("1.2.3-preview")),"pre-release version is not a stable update");
            using(var oldOnly=new FakeTransport())
            {
                oldOnly.Responses["page1"]=Json(new[]{new {tag_name="v99.0.0",draft=false,prerelease=false,assets=Array.Empty<object>()}});
                Expect(await new UnityReleaseClient(oldOnly).FindLatestAsync(default)==null,"retired Python release cannot become a Unity update");
            }
            using(var draft=new FakeTransport())
            {
                draft.Responses["page1"]=Json(new[]{new {tag_name="unity-v9.0.0",draft=true,prerelease=false},new {tag_name="unity-v8.0.0",draft=false,prerelease=true}});
                Expect(await new UnityReleaseClient(draft).FindLatestAsync(default)==null,"draft and preview releases ignored");
            }
            using(var pages=Release())
            {
                pages.Responses["page2"]=pages.Responses["page1"];
                pages.Responses["page1"]=Json(Enumerable.Range(0,100).Select(i=>new {tag_name="v0.2."+i,draft=false,prerelease=false}).ToArray());
                var result=await new UnityReleaseClient(pages).FindLatestAsync(default);
                Expect(result.Version=="0.3.0" && pages.Reads.Contains("page2"),"pagination finds Unity beyond old product releases");
            }
            foreach(var item in new (string Key,object Value,string Name)[]{
                ("productId","controllab-python","wrong product manifest rejected"),
                ("platform","linux-x64","wrong platform manifest rejected"),
                ("version","4.0.0","tag and manifest version mismatch rejected"),
                ("assetName","ControlLab-Setup-0.3.0.exe","Python installer filename rejected"),
                ("sha256","bad","missing trustworthy hash rejected"),
                ("size",Package.LongLength+1,"manifest and asset size mismatch rejected"),
                ("size",UnityReleaseClient.MaxInstallerBytes+1,"oversized installer rejected"),
                ("schema",7,"unknown manifest schema rejected")})
            {
                using(var bad=Release(mutate:m=>m[item.Key]=item.Value))
                    await Reject(()=>new UnityReleaseClient(bad).FindLatestAsync(default),item.Name);
            }
            await Reject(()=>Task.FromResult(UnityReleaseClient.ValidateAssetUrl("https://evil.example/install.exe","unity-v0.3.0","install.exe")),"non-GitHub asset URL rejected");
            await Reject(()=>Task.FromResult(UnityReleaseClient.ValidateAssetUrl("https://github.com/someone/else/releases/download/unity-v0.3.0/file.exe","unity-v0.3.0","file.exe")),"asset from another repository rejected");
            await Reject(()=>Task.FromResult(UnityReleaseClient.ValidateAssetUrl(Asset("unity-v0.3.0","file.exe")+"?redirect=1","unity-v0.3.0","file.exe")),"initial release asset query not trusted");
            await Reject(()=>Task.FromResult(UnityReleaseClient.ReadJson<UnityUpdateManifest>(Encoding.UTF8.GetBytes("{\"schema\":1,"))),"truncated manifest rejected");
            await Reject(()=>Task.FromResult(UnityReleaseClient.ReadJson<UnityUpdateManifest>(Json(new {schema=1,productId=AppVersion.ProductId}))),"required manifest fields enforced");
            using(var duplicate=Release())
            {
                var listing=JsonSerializer.Deserialize<JsonElement>(duplicate.Responses["page1"]);
                var original=listing[0];
                duplicate.Responses["page1"]=Json(new[]{new {tag_name="unity-v0.3.0",draft=false,prerelease=false,
                    assets=new[]{original.GetProperty("assets")[0],original.GetProperty("assets")[1],original.GetProperty("assets")[1]}}});
                await Reject(()=>new UnityReleaseClient(duplicate).FindLatestAsync(default),"duplicate installer assets rejected");
            }

            foreach(var code in new[]{HttpStatusCode.NotFound,HttpStatusCode.Forbidden,(HttpStatusCode)429})
            {
                using var wire=new GitHubUpdateTransport(new ResponseHandler(_=>new HttpResponseMessage(code)));
                string message="";
                try { await wire.ReadAsync(new Uri(UnityReleaseClient.ReleasesUrl),1024,true,default); } catch(UpdateException error){message=error.Message;}
                Expect(code==HttpStatusCode.NotFound?message.Contains("无法读取"):message.Contains("限制请求"),"HTTP "+(int)code+" has an honest actionable status");
            }
            int redirectCalls=0;
            using(var wire=new GitHubUpdateTransport(new ResponseHandler(_=>{
                redirectCalls++; var response=new HttpResponseMessage(HttpStatusCode.Redirect);response.Headers.Location=new Uri("http://127.0.0.1/private");return response;
            })))
            {
                await Reject(()=>wire.ReadAsync(new Uri(UnityReleaseClient.ReleasesUrl),1024,true,default),"unsafe redirect rejected before second request");
                Expect(redirectCalls==1,"redirect target was not contacted");
            }
            using(var no=new UnityUpdateService("0.2.0",Cache("none"),new FakeTransport()))
            { await no.CheckAsync();Expect(no.Snapshot.State==UnityUpdateState.NoRelease && !no.Snapshot.CanInstall,"no release is not an installation error"); }
            using(var current=new UnityUpdateService("0.3.0",Cache("current"),Release()))
            { await current.CheckAsync();Expect(current.Snapshot.State==UnityUpdateState.UpToDate && !current.Snapshot.CanDownload,"equal current version is already up to date"); }
            using(var cancelTransport=new FakeTransport { WaitRead=true })
            using(var cancelled=new UnityUpdateService("0.2.0",Cache("cancel-check"),cancelTransport))
            {
                Task task=cancelled.CheckAsync();await Task.Delay(30);cancelled.Cancel();await task;
                Expect(cancelled.Snapshot.State==UnityUpdateState.Cancelled && cancelled.Snapshot.CanCheck,"check cancellation releases UI for retry");
            }
            var launch=new CaptureLauncher();
            Expect(UnityUpdateService.RestartProfileArgument(new[]{"app.exe","--profile-directory",Cache("资料 空格")})
                ==" /PROFILEDIR=\""+Cache("资料 空格")+"\"","explicit isolated profile is forwarded as one quoted argument");
            Expect(UnityUpdateService.RestartProfileArgument(new[]{"app.exe","--other","unrelated"})=="","unrelated arguments are never forwarded");
            await Reject(()=>Task.FromResult(UnityUpdateService.RestartProfileArgument(new[]{"app.exe","--profile-directory","relative"})),"relative restart profile rejected");
            string successCache=Cache("下载 fixture");
            string currentExe=Path.Combine(fixtureRoot,"ControlLab Unity.exe");File.WriteAllBytes(currentExe,Package);
            using(var success=new UnityUpdateService("0.2.0",successCache,Release(),launch))
            {
                await success.CheckAsync();Expect(success.Snapshot.State==UnityUpdateState.Available && success.Snapshot.CanDownload,"valid Unity update can be downloaded");
                await success.DownloadAsync();Expect(success.Snapshot.State==UnityUpdateState.Ready && success.Snapshot.CanInstall,"complete size and SHA256 permit installation");
                Expect(!Directory.GetFiles(successCache,"*.part").Any(),"successful download removes temporary staging file");
                Expect(success.TryLaunchInstaller(currentExe,out string error),"verified installer handoff succeeds with injected launcher");
                Expect(launch.Count==1 && launch.Info.Arguments.Contains("/WAITFORPID="+Process.GetCurrentProcess().Id) && launch.Info.Arguments.Contains("/RESTARTAPP=1"),"handoff waits for original process and requests restart");
                Expect(success.Snapshot.State==UnityUpdateState.Installing && File.Exists(Path.Combine(successCache,"pending-update.json")),"handoff records pending rather than completed install");
            }
            using(var pending=new UnityUpdateService("0.2.0",successCache,new FakeTransport()))
            {pending.ConfirmInstallation(currentExe);Expect(File.Exists(Path.Combine(successCache,"pending-update.json")) && pending.Snapshot.Status.Contains("尚未"),"old process version does not confirm installation");}
            File.WriteAllBytes(Path.Combine(fixtureRoot,"installation.json"),Json(new {productId=AppVersion.ProductId,version="0.3.0",status="installed"}));
            using(var confirmed=new UnityUpdateService("0.3.0",successCache,new FakeTransport()))
            {confirmed.ConfirmInstallation(currentExe);Expect(!File.Exists(Path.Combine(successCache,"pending-update.json")) && File.Exists(Path.Combine(successCache,"last-update.json")),"matching installed marker and restarted version confirm update");}
            using(var corrupt=Release())
            {
                corrupt.Package=(byte[])Package.Clone();
                corrupt.Package[corrupt.Package.Length-1]^=1; // Preserve size and MZ header to reach the digest check.
                using var service=new UnityUpdateService("0.2.0",Cache("hash-error"),corrupt);
                await service.CheckAsync();await service.DownloadAsync();
                Expect(service.Snapshot.State==UnityUpdateState.Error && !service.Snapshot.CanInstall,"corrupt payload never enables install");
                Expect(!Directory.GetFiles(Cache("hash-error"),"*.part").Any(),"failed download cleans staging file");
            }
            using(var cancelTransport=Release())
            {
                cancelTransport.WaitDownload=true;
                using var service=new UnityUpdateService("0.2.0",Cache("cancel-download"),cancelTransport);
                await service.CheckAsync();Task task=service.DownloadAsync();await Task.Delay(40);service.Cancel();await task;
                Expect(service.Snapshot.State==UnityUpdateState.Cancelled && service.Snapshot.CanDownload && !service.Snapshot.CanInstall,"cancelled download remains retryable without install");
                Expect(!Directory.GetFiles(Cache("cancel-download"),"*.part").Any(),"cancelled download cleans staging file");
            }
            var never=new CaptureLauncher();
            using(var tampered=new UnityUpdateService("0.2.0",Cache("tamper"),Release(),never))
            {
                await tampered.CheckAsync();await tampered.DownloadAsync();
                byte[] altered=(byte[])Package.Clone();altered[altered.Length-1]^=1;
                File.WriteAllBytes(Directory.GetFiles(Cache("tamper"),"*.exe").Single(),altered);
                Expect(!tampered.TryLaunchInstaller(currentExe,out _) && never.Count==0,"installation rechecks a modified cached file");
            }
            using(var failed=new UnityUpdateService("0.2.0",Cache("launch-failure"),Release(),new CaptureLauncher { Fail=true }))
            {
                await failed.CheckAsync();await failed.DownloadAsync();
                Expect(!failed.TryLaunchInstaller(currentExe,out _) && failed.Snapshot.State==UnityUpdateState.Error,"launcher failure does not claim installation completed");
            }
            using(var missing=new UnityUpdateService("0.2.0",Cache("missing-cache"),Release(),never))
            {
                await missing.CheckAsync();await missing.DownloadAsync();
                File.Delete(Directory.GetFiles(Cache("missing-cache"),"*.exe").Single());
                Expect(!missing.TryLaunchInstaller(currentExe,out _) && !missing.Snapshot.CanInstall && missing.Snapshot.CanDownload,
                    "missing verified installer returns to downloadable state");
                Expect(never.Count==0,"missing cache never launches a process");
            }
            passed=true;
            if(live)
            {
                using var service=new UnityUpdateService(AppVersion.Current,Cache("live"));
                await service.CheckAsync();
                liveResult=new {state=service.Snapshot.State.ToString(),status=service.Snapshot.Status,availableVersion=service.Snapshot.AvailableVersion,networkSuccess=service.Snapshot.State!=UnityUpdateState.Error};
            }
        }
        catch(Exception error){failure=error.ToString();Console.Error.WriteLine(error.Message);}
        finally
        {
            var report=new {utc=DateTime.UtcNow.ToString("O"),passed,checks=Checks,live=liveResult,error=failure,fixtureRoot};
            File.WriteAllText(Path.Combine(output,"result.json"),JsonSerializer.Serialize(report,new JsonSerializerOptions {WriteIndented=true}));
        }
        Console.WriteLine(JsonSerializer.Serialize(new {passed,checks=Checks.Count,live=liveResult,report=Path.Combine(output,"result.json")}));
        Environment.ExitCode=passed?0:1;
    }

    sealed class FakeTransport : IUpdateTransport
    {
        public Dictionary<string,byte[]> Responses=new();public List<string> Reads=new();public byte[] Package;
        public bool WaitRead,WaitDownload;
        public async Task<byte[]> ReadAsync(Uri uri,int maximumBytes,bool api,CancellationToken cancellation)
        {
            if(WaitRead)await Task.Delay(Timeout.Infinite,cancellation);
            string key=uri.Host=="api.github.com"?"page"+(uri.Query.Contains("&page=2")?"2":"1"):uri.AbsoluteUri;
            Reads.Add(key);return Responses.TryGetValue(key,out byte[] result)?result:Encoding.UTF8.GetBytes("[]");
        }
        public async Task DownloadAsync(Uri uri,string path,long expected,Action<long> progress,CancellationToken cancellation)
        {
            await File.WriteAllBytesAsync(path,Package,cancellation);progress(Package.Length);
            if(WaitDownload)await Task.Delay(Timeout.Infinite,cancellation);
        }
        public void Dispose(){}
    }
    sealed class CaptureLauncher : IInstallerProcessLauncher
    {public int Count;public ProcessStartInfo Info;public bool Fail;public void Start(ProcessStartInfo info){if(Fail)throw new IOException("test launch failure");Count++;Info=info;}}
    sealed class ResponseHandler : HttpMessageHandler
    {readonly Func<HttpRequestMessage,HttpResponseMessage> response;public ResponseHandler(Func<HttpRequestMessage,HttpResponseMessage> response){this.response=response;}protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken token)=>Task.FromResult(response(request));}
}
