using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine;

namespace ControlLab.UnityPrototype
{
    [Serializable]
    public sealed class LearningProgress
    {
        public int version = 1;
        // Retained only to read older combined files and migrate the preference.
        // AppPreferencesStore owns startup behavior; this flag never clears a checkpoint.
        public bool rememberProgress = true;
        public bool hasProgress = false;
        public string page = "Studio";
        public int concept = 0;
        public bool explanationOpen = false;
    }

    /// <summary>A chapter checkpoint, independent of startup preferences and cart appearance.</summary>
    public static class LearningProgressStore
    {
        const int MaxJsonBytes = 8192;
        // This version has only flat, fixed-name scalar fields. Validate those before
        // Unity deserializes, so wrong types, duplicates and incomplete JSON cannot
        // silently turn into a plausible checkpoint. No user text is stored here.
        static readonly Regex Member = new Regex(
            "\\G\\s*\"(?<key>[A-Za-z][A-Za-z0-9]*)\"\\s*:\\s*(?:(?<boolean>true|false)|(?<number>-?(?:0|[1-9][0-9]*))|\"(?<text>[^\"\\\\\\u0000-\\u001F]*)\")\\s*",
            RegexOptions.CultureInvariant);
        public static string LastLoadWarning { get; private set; } = "";

        public static LearningProgress Load()
        {
            LastLoadWarning = "";
            string path = Path.Combine(CartProfileStore.ProfileDirectory, "learning-progress.json");
            if (TryRead(path, out LearningProgress progress)) return progress;
            if (TryRead(path + ".bak", out progress))
            {
                LastLoadWarning = "进度读取有误，已恢复上一次保存的位置。";
                return progress;
            }
            if (File.Exists(path) || File.Exists(path + ".bak"))
                LastLoadWarning = "进度暂时无法读取，先从首页开始。原文件仍保留。";
            return new LearningProgress();
        }

        public static void Save(LearningProgress progress)
        {
            if (progress == null) throw new ArgumentNullException(nameof(progress));
            LearningProgress normalized = Validate(progress);
            string directory = CartProfileStore.ProfileDirectory;
            Directory.CreateDirectory(directory);
            string path = Path.Combine(directory, "learning-progress.json");
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                byte[] json = new UTF8Encoding(false).GetBytes(JsonUtility.ToJson(normalized, true));
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    stream.Write(json, 0, json.Length);
                    stream.Flush(true);
                }
                if (!File.Exists(path)) File.Move(temporary, path);
                else if (TryRead(path, out _)) File.Replace(temporary, path, path + ".bak");
                else
                {
                    // A later save may recover from a bad file without destroying
                    // either the damaged original or a valid backup used by Load.
                    string preserved = path + ".corrupt-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")
                        + "-" + Guid.NewGuid().ToString("N");
                    File.Copy(path, preserved, false);
                    File.Replace(temporary, path, null);
                }
                LastLoadWarning = "";
            }
            catch (IOException error) { throw new IOException("学习进度保存失败，请检查目录是否可写。", error); }
            catch (UnauthorizedAccessException error) { throw new IOException("没有权限保存学习进度。", error); }
            finally
            {
                // Cleanup must not hide the original save error or remove an old save.
                try { if (File.Exists(temporary)) File.Delete(temporary); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }

        static bool TryRead(string path, out LearningProgress progress)
        {
            progress = null;
            try
            {
                if (!File.Exists(path)) return false;
                byte[] bytes;
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                {
                    if (stream.Length < 2 || stream.Length > MaxJsonBytes) return false;
                    bytes = new byte[(int)stream.Length];
                    int offset = 0;
                    while (offset < bytes.Length)
                    {
                        int count = stream.Read(bytes, offset, bytes.Length - offset);
                        if (count == 0) return false;
                        offset += count;
                    }
                }
                string json = new UTF8Encoding(false, true).GetString(bytes).TrimStart('\uFEFF');
                if (!HasValidSchema(json)) return false;
                // FromJsonOverwrite retains field initializers for omitted optional
                // settings, including rememberProgress=true for an older checkpoint.
                var decoded = new LearningProgress();
                JsonUtility.FromJsonOverwrite(json, decoded);
                progress = Validate(decoded);
                return true;
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException
                || error is ArgumentException || error is FormatException || error is InvalidDataException
                || error is UnityException)
            { return false; }
        }

        static bool HasValidSchema(string json)
        {
            string document = json.Trim();
            if (document.Length < 2 || document[0] != '{' || document[document.Length - 1] != '}') return false;
            var seen = new HashSet<string>(StringComparer.Ordinal);
            int position = 1;
            bool hasProgress = false;
            while (position < document.Length - 1)
            {
                Match member = Member.Match(document, position);
                if (!member.Success) return false;
                string key = member.Groups["key"].Value;
                if (!seen.Add(key)) return false;
                switch (key)
                {
                    case "version":
                        if (!member.Groups["number"].Success || member.Groups["number"].Value != "1") return false;
                        break;
                    case "concept":
                        if (!member.Groups["number"].Success || !int.TryParse(member.Groups["number"].Value, out int concept)
                            || concept < 0 || concept > 2) return false;
                        break;
                    case "rememberProgress":
                    case "explanationOpen":
                        if (!member.Groups["boolean"].Success) return false;
                        break;
                    case "hasProgress":
                        if (!member.Groups["boolean"].Success) return false;
                        hasProgress = member.Groups["boolean"].Value == "true";
                        break;
                    case "page":
                        if (!member.Groups["text"].Success) return false;
                        break;
                    default: return false;
                }
                position = member.Index + member.Length;
                if (position == document.Length - 1) break;
                if (document[position] != ',') return false;
                ++position;
                if (position == document.Length - 1) return false;
            }
            return seen.Contains("version") && (!hasProgress || seen.Contains("page"));
        }

        static LearningProgress Validate(LearningProgress progress)
        {
            if (progress.version != 1) throw new InvalidDataException("暂不支持这个学习进度版本。");
            if (progress.page != "Studio" && progress.page != "Lesson")
                throw new InvalidDataException("学习页面不存在。");
            if (progress.concept < 0 || progress.concept > 2)
                throw new InvalidDataException("讲解主题不存在。");
            return new LearningProgress
            {
                rememberProgress = progress.rememberProgress,
                hasProgress = progress.hasProgress,
                page = progress.hasProgress ? progress.page : "Studio",
                concept = progress.hasProgress ? progress.concept : 0,
                explanationOpen = progress.hasProgress && progress.page == "Lesson" && progress.explanationOpen
            };
        }
    }
}
