using System.Text.Json;
using ControlLab.UnityPrototype;

// This adapter exercises the actual stores and filesystem behavior without
// starting Unity. The real Player tests separately verify Unity JsonUtility.
namespace UnityEngine
{
    public class UnityException : Exception { }
    public static class JsonUtility
    {
        public static string ToJson(object value, bool pretty) => JsonSerializer.Serialize(
            value, value.GetType(), new JsonSerializerOptions { IncludeFields = true, WriteIndented = pretty });
        public static void FromJsonOverwrite(string json, object target)
        {
            using var document = JsonDocument.Parse(json);
            foreach (var property in document.RootElement.EnumerateObject())
            {
                var field = target.GetType().GetField(property.Name);
                if (field != null)
                    field.SetValue(target, JsonSerializer.Deserialize(property.Value.GetRawText(), field.FieldType));
            }
        }
    }
}
namespace ControlLab.UnityPrototype
{
    public static class CartProfileStore { public static string ProfileDirectory { get; set; } }
}

static class Program
{
    static readonly List<object> Checks = new();
    static string caseRoot;
    static string PreferencesPath => Path.Combine(CartProfileStore.ProfileDirectory, "app-preferences.json");
    static string ProgressPath => Path.Combine(CartProfileStore.ProfileDirectory, "learning-progress.json");

    static void Fresh(string name)
    {
        CartProfileStore.ProfileDirectory = Path.Combine(caseRoot, name);
        Directory.CreateDirectory(CartProfileStore.ProfileDirectory);
    }
    static void Check(bool condition, string name)
    {
        Checks.Add(new { name, passed = condition });
        if (!condition) throw new Exception(name);
    }
    static LearningProgress Legacy(bool remember = false) => new LearningProgress
    {
        rememberProgress = remember, hasProgress = true, page = "Lesson", concept = 2, explanationOpen = true
    };

    static void Run()
    {
        Fresh("new-profile");
        var preference = AppPreferencesStore.Load(null);
        Check(preference.rememberProgress && preference.version == 1, "new profile defaults to automatic continue");
        Check(!File.Exists(PreferencesPath), "read with no legacy data does not create a file");

        Fresh("migrate-disabled");
        LearningProgressStore.Save(Legacy());
        byte[] checkpointBefore = File.ReadAllBytes(ProgressPath);
        byte[] appearanceBefore = { 1, 2, 3, 4 };
        string appearancePath = Path.Combine(CartProfileStore.ProfileDirectory, "cart-profile.json");
        File.WriteAllBytes(appearancePath, appearanceBefore);
        preference = AppPreferencesStore.Load(LearningProgressStore.Load());
        Check(!preference.rememberProgress && File.Exists(PreferencesPath), "disabled legacy preference migrates durably");
        Check(checkpointBefore.SequenceEqual(File.ReadAllBytes(ProgressPath)), "migration leaves the legacy checkpoint byte for byte intact");
        preference = AppPreferencesStore.Load(Legacy(true));
        Check(!preference.rememberProgress, "independent preference overrides a conflicting legacy flag on restart");
        preference.rememberProgress = true;
        AppPreferencesStore.Save(preference);
        Check(AppPreferencesStore.Load(Legacy()).rememberProgress, "reenabling continue persists independently");
        preference.rememberProgress = false;
        AppPreferencesStore.Save(preference);
        var checkpoint = LearningProgressStore.Load();
        Check(checkpoint.hasProgress && checkpoint.page == "Lesson" && checkpoint.concept == 2 && checkpoint.explanationOpen,
            "disabling continue does not erase or reset the saved lesson and explanation");
        Check(checkpointBefore.SequenceEqual(File.ReadAllBytes(ProgressPath)), "repeated preference toggles never rewrite checkpoint bytes");
        Check(appearanceBefore.SequenceEqual(File.ReadAllBytes(appearancePath)), "preference migration and toggles do not touch cart appearance");
        LearningProgressStore.Save(new LearningProgress
        {
            rememberProgress = false, hasProgress = true, page = "Lesson", concept = 1, explanationOpen = true
        });
        checkpoint = LearningProgressStore.Load();
        Check(checkpoint.hasProgress && checkpoint.concept == 1 && !checkpoint.rememberProgress,
            "new checkpoints remain valid while automatic continue is disabled");

        Fresh("migration-enabled");
        Check(AppPreferencesStore.Load(Legacy(true)).rememberProgress && File.Exists(PreferencesPath),
            "enabled legacy preference migrates durably");
        Fresh("old-disabled-without-checkpoint");
        preference = AppPreferencesStore.Load(new LearningProgress { rememberProgress = false });
        Check(!preference.rememberProgress && !File.Exists(ProgressPath), "old disabled format migrates without inventing lost progress");

        Fresh("corrupt-primary-with-backup");
        AppPreferencesStore.Save(new AppPreferences { rememberProgress = false });
        AppPreferencesStore.Save(new AppPreferences { rememberProgress = true });
        const string broken = "{broken";
        File.WriteAllText(PreferencesPath, broken);
        preference = AppPreferencesStore.Load(Legacy(true));
        Check(!preference.rememberProgress && AppPreferencesStore.LastLoadWarning.Length > 0,
            "valid preference backup wins over legacy fallback when primary is damaged");
        Check(File.ReadAllText(PreferencesPath) == broken, "loading a backup preserves the damaged primary");
        byte[] backupBefore = File.ReadAllBytes(PreferencesPath + ".bak");
        AppPreferencesStore.Save(new AppPreferences());
        Check(Directory.GetFiles(CartProfileStore.ProfileDirectory, "app-preferences.json.corrupt-*")
            .Any(path => File.ReadAllText(path) == broken), "explicit recovery archives the damaged preference bytes");
        Check(backupBefore.SequenceEqual(File.ReadAllBytes(PreferencesPath + ".bak")), "repair keeps the usable preference backup");
        Check(AppPreferencesStore.LastLoadWarning.Length == 0 && AppPreferencesStore.Load(Legacy()).rememberProgress,
            "explicit repair writes a usable preference and clears its warning");

        Fresh("backup-only");
        File.WriteAllText(PreferencesPath + ".bak", "{\"version\":1,\"rememberProgress\":false}");
        Check(!AppPreferencesStore.Load(Legacy(true)).rememberProgress && !File.Exists(PreferencesPath),
            "missing primary can recover backup without overwriting it during load");

        var invalid = new Dictionary<string, string>
        {
            ["missing schema"] = "{}",
            ["future version"] = "{\"version\":2,\"rememberProgress\":true}",
            ["wrong boolean type"] = "{\"version\":1,\"rememberProgress\":\"false\"}",
            ["boolean as version"] = "{\"version\":true,\"rememberProgress\":true}",
            ["integer as boolean"] = "{\"version\":1,\"rememberProgress\":1}",
            ["duplicate flag"] = "{\"version\":1,\"rememberProgress\":true,\"rememberProgress\":false}",
            ["unknown field"] = "{\"version\":1,\"injected\":true}",
            ["trailing comma"] = "{\"version\":1, }",
            ["trailing content"] = "{\"version\":1}extra",
            ["oversize"] = "{\"version\":1}" + new string(' ', 2049)
        };
        foreach (var item in invalid)
        {
            Fresh(item.Key.Replace(' ', '-'));
            File.WriteAllText(PreferencesPath, item.Value);
            preference = AppPreferencesStore.Load(Legacy());
            Check(!preference.rememberProgress && AppPreferencesStore.LastLoadWarning.Length > 0
                && File.ReadAllText(PreferencesPath) == item.Value, "reject and preserve " + item.Key);
        }
        Fresh("bad-utf8");
        byte[] badUtf8 = { 123, 255, 125 };
        File.WriteAllBytes(PreferencesPath, badUtf8);
        preference = AppPreferencesStore.Load(null);
        Check(preference.rememberProgress && AppPreferencesStore.LastLoadWarning.Length > 0
            && badUtf8.SequenceEqual(File.ReadAllBytes(PreferencesPath)), "invalid UTF8 uses default and preserves the source");

        Fresh("optional-field");
        File.WriteAllText(PreferencesPath, "{\"version\":1}");
        Check(AppPreferencesStore.Load(Legacy()).rememberProgress && AppPreferencesStore.LastLoadWarning.Length == 0,
            "omitted optional preference uses the field initializer not legacy data");
        Fresh("unordered-properties");
        File.WriteAllText(PreferencesPath, "{ \"rememberProgress\" : false , \"version\" : 1 }");
        Check(!AppPreferencesStore.Load(Legacy(true)).rememberProgress && AppPreferencesStore.LastLoadWarning.Length == 0,
            "valid field order and whitespace do not change preference interpretation");

        Fresh("invalid-legacy");
        preference = AppPreferencesStore.Load(new LearningProgress { version = 9, rememberProgress = false });
        Check(preference.rememberProgress && !File.Exists(PreferencesPath) && AppPreferencesStore.LastLoadWarning.Length > 0,
            "incompatible legacy data cannot overwrite default preferences");

        Fresh("locked-file");
        AppPreferencesStore.Save(new AppPreferences { rememberProgress = false });
        byte[] preferencesBefore = File.ReadAllBytes(PreferencesPath);
        bool failed = false;
        using (var locked = new FileStream(PreferencesPath, FileMode.Open, FileAccess.Read, FileShare.None))
        {
            try { AppPreferencesStore.Save(new AppPreferences()); }
            catch (IOException) { failed = true; }
        }
        Check(failed && preferencesBefore.SequenceEqual(File.ReadAllBytes(PreferencesPath)),
            "a locked target fails without destroying the previous preferences");
        Check(Directory.GetFiles(CartProfileStore.ProfileDirectory, "*.tmp").Length == 0,
            "failed atomic save cleans its temporary file");

        Fresh("blocked-directory");
        string blockedDirectory = Path.Combine(CartProfileStore.ProfileDirectory, "not-a-directory");
        File.WriteAllText(blockedDirectory, "existing file");
        CartProfileStore.ProfileDirectory = blockedDirectory;
        preference = AppPreferencesStore.Load(Legacy());
        Check(!preference.rememberProgress && AppPreferencesStore.LastLoadWarning.Length > 0
            && File.ReadAllText(blockedDirectory) == "existing file", "failed first migration keeps legacy preference usable and preserves blocking file");
    }

    static int Main(string[] arguments)
    {
        string output = Path.GetFullPath(arguments.Length > 0 ? arguments[0] : Path.Combine(Environment.CurrentDirectory, "Logs", "Verification", "preferences-check"));
        Directory.CreateDirectory(output);
        caseRoot = Path.Combine(output, "cases-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N"));
        string error = null;
        try { Run(); }
        catch (Exception exception) { error = exception.ToString(); }
        var report = new
        {
            passed = error == null, utc = DateTime.UtcNow.ToString("O"), checks = Checks, error,
            serializer = ".NET JsonUtility adapter; actual Unity serialization is verified by Player interaction checks",
            caseRoot
        };
        File.WriteAllText(Path.Combine(output, "result.json"), JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
        Console.WriteLine(error == null ? $"PASS: {Checks.Count} preference and checkpoint checks" : error);
        return error == null ? 0 : 1;
    }
}
