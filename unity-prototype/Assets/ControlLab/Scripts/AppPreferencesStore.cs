using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine;

namespace ControlLab.UnityPrototype
{
    [Serializable]
    public sealed class AppPreferences
    {
        public int version = 1;
        public bool rememberProgress = true;
    }

    /// <summary>
    /// Startup preferences are stored separately from learning-progress.json.
    /// Migrating or changing them never writes, clears or normalizes a lesson checkpoint.
    /// </summary>
    public static class AppPreferencesStore
    {
        const int MaxJsonBytes = 2048;
        static readonly Regex Member = new Regex(
            "\\G\\s*\"(?<key>[A-Za-z][A-Za-z0-9]*)\"\\s*:\\s*(?<value>true|false|1)\\s*",
            RegexOptions.CultureInvariant);
        public static string LastLoadWarning { get; private set; } = "";

        public static AppPreferences Load(LearningProgress legacy)
        {
            LastLoadWarning = "";
            string path = Path.Combine(CartProfileStore.ProfileDirectory, "app-preferences.json");
            if (TryRead(path, out AppPreferences preferences)) return preferences;
            if (TryRead(path + ".bak", out preferences))
            {
                LastLoadWarning = "设置读取有误，已恢复上一次保存的设置。";
                return preferences;
            }

            bool legacyIsValid = legacy != null && legacy.version == 1
                && (legacy.page == "Studio" || legacy.page == "Lesson")
                && legacy.concept >= 0 && legacy.concept <= 2;
            preferences = new AppPreferences
            {
                rememberProgress = !legacyIsValid || legacy.rememberProgress
            };
            if (File.Exists(path) || File.Exists(path + ".bak"))
            {
                // A read must not silently repair an unrecognized/damaged file.
                // An explicit save will archive it before replacing its contents.
                LastLoadWarning = "设置暂时无法读取，已沿用原启动偏好。原文件仍保留。";
                return preferences;
            }

            if (legacyIsValid)
            {
                // This is the one-time migration from the combined v1 format.
                // A new preferences file becomes authoritative on later launches.
                try { Save(preferences); }
                catch (IOException)
                {
                    LastLoadWarning = "启动偏好已读取，但暂时未能保存到新设置文件。";
                }
            }
            else if (legacy != null)
                LastLoadWarning = "旧启动偏好无法读取，已使用默认设置。";
            return preferences;
        }

        public static void Save(AppPreferences preferences)
        {
            if (preferences == null) throw new ArgumentNullException(nameof(preferences));
            if (preferences.version != 1) throw new InvalidDataException("暂不支持这个设置版本。");
            var normalized = new AppPreferences { rememberProgress = preferences.rememberProgress };
            string directory = CartProfileStore.ProfileDirectory;
            string path = Path.Combine(directory, "app-preferences.json");
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                Directory.CreateDirectory(directory);
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
                    string preserved = path + ".corrupt-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")
                        + "-" + Guid.NewGuid().ToString("N");
                    File.Copy(path, preserved, false);
                    File.Replace(temporary, path, null);
                }
                LastLoadWarning = "";
            }
            catch (IOException error) { throw new IOException("设置保存失败，请检查目录是否可写。", error); }
            catch (UnauthorizedAccessException error) { throw new IOException("没有权限保存设置。", error); }
            finally
            {
                try { if (File.Exists(temporary)) File.Delete(temporary); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }

        static bool TryRead(string path, out AppPreferences preferences)
        {
            preferences = null;
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
                var decoded = new AppPreferences();
                JsonUtility.FromJsonOverwrite(json, decoded);
                preferences = decoded;
                return true;
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException
                || error is ArgumentException || error is FormatException || error is UnityException)
            { return false; }
        }

        static bool HasValidSchema(string json)
        {
            string document = json.Trim();
            if (document.Length < 2 || document[0] != '{' || document[document.Length - 1] != '}') return false;
            var seen = new HashSet<string>(StringComparer.Ordinal);
            int position = 1;
            while (position < document.Length - 1)
            {
                Match member = Member.Match(document, position);
                if (!member.Success) return false;
                string key = member.Groups["key"].Value;
                string value = member.Groups["value"].Value;
                if (!seen.Add(key)) return false;
                if (key == "version") { if (value != "1") return false; }
                else if (key == "rememberProgress") { if (value != "true" && value != "false") return false; }
                else return false;
                position = member.Index + member.Length;
                if (position == document.Length - 1) break;
                if (document[position] != ',') return false;
                ++position;
                if (position == document.Length - 1) return false;
            }
            return seen.Contains("version");
        }
    }
}
