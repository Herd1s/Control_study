using System;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;

namespace ControlLab.UnityPrototype
{
    [Serializable]
    public sealed class CartProfile
    {
        public int version = 1;
        public string displayName = "我的小车";
        public string bodyColor = "#0878E8";
        public string photoPng = "";
        public string drawingPng = "";
    }

    /// <summary>Local-only profile and bounded, metadata-free image layers.</summary>
    public static class CartProfileStore
    {
        public const int SkinWidth = 512, SkinHeight = 192;
        const int MaxPhotoBytes = 8 * 1024 * 1024, MaxLayerBytes = 2 * 1024 * 1024;
        const int MaxJsonBytes = 8 * 1024 * 1024, MaxImageSide = 8192, MaxImagePixels = 16000000;
        public static string LastLoadWarning { get; private set; } = "";

        public static string ProfileDirectory
        {
            get
            {
                string[] args = Environment.GetCommandLineArgs();
                for (int i = 0; i < args.Length; ++i)
                    if (args[i] == "--profile-directory")
                    {
                        if (i + 1 >= args.Length || !Path.IsPathFullyQualified(args[i + 1]))
                            throw new ArgumentException("测试资料目录必须使用绝对路径。");
                        return Path.GetFullPath(args[i + 1]);
                    }
                return Path.Combine(Application.persistentDataPath, "garage");
            }
        }

        public static CartProfile Load()
        {
            LastLoadWarning = "";
            string path = Path.Combine(ProfileDirectory, "cart-profile.json");
            CartProfile profile;
            if (TryRead(path, out profile)) return profile;
            bool damaged = File.Exists(path);
            if (TryRead(path + ".bak", out profile))
            {
                LastLoadWarning = "小车资料无法读取，已使用上一次保存的版本。原文件仍保留。";
                return profile;
            }
            if (damaged || File.Exists(path + ".bak"))
                LastLoadWarning = "小车资料已损坏，暂时使用默认外观。原文件仍保留。";
            return new CartProfile();
        }

        public static void Save(CartProfile profile)
        {
            if (profile == null) throw new ArgumentNullException(nameof(profile));
            CartProfile normalized = Validate(profile);
            string directory = ProfileDirectory;
            Directory.CreateDirectory(directory);
            string path = Path.Combine(directory, "cart-profile.json");
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                byte[] json = new UTF8Encoding(false).GetBytes(JsonUtility.ToJson(normalized, true));
                using (FileStream stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                { stream.Write(json, 0, json.Length); stream.Flush(true); }
                if (File.Exists(path))
                {
                    CartProfile previous;
                    if (TryRead(path, out previous)) File.Replace(temporary, path, path + ".bak");
                    else
                    {
                        // An explicit save may replace a damaged profile, but
                        // must retain that evidence and any valid backup.
                        string preserved = path + ".corrupt-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")
                            + "-" + Guid.NewGuid().ToString("N");
                        File.Copy(path, preserved, false);
                        File.Replace(temporary, path, null);
                    }
                }
                else File.Move(temporary, path);
                LastLoadWarning = "";
            }
            catch (IOException error) { throw new IOException("小车资料保存失败，请检查目录是否可写。", error); }
            catch (UnauthorizedAccessException error) { throw new IOException("没有权限保存小车资料，请选择可写目录。", error); }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        static bool TryRead(string path, out CartProfile profile)
        {
            profile = null;
            if (!File.Exists(path)) return false;
            try
            {
                if (new FileInfo(path).Length > MaxJsonBytes) return false;
                CartProfile decoded = JsonUtility.FromJson<CartProfile>(File.ReadAllText(path, Encoding.UTF8));
                if (decoded == null || decoded.version != 1) return false;
                profile = Validate(decoded);
                return true;
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException
                || error is ArgumentException || error is FormatException || error is InvalidDataException
                || error is UnityException)
            { return false; }
        }

        static CartProfile Validate(CartProfile profile)
        {
            if (profile.version != 1) throw new InvalidDataException("小车资料版本暂不受支持。");
            ValidateLayer(profile.photoPng);
            ValidateLayer(profile.drawingPng);
            return new CartProfile { displayName = SanitizeName(profile.displayName),
                bodyColor = NormalizeColor(profile.bodyColor), photoPng = profile.photoPng ?? "",
                drawingPng = profile.drawingPng ?? "" };
        }

        static void ValidateLayer(string encoded)
        {
            if (string.IsNullOrEmpty(encoded)) return;
            Texture2D texture = DecodeLayer(encoded);
            DisposeTexture(texture);
        }

        public static Texture2D DecodeLayer(string base64)
        {
            if (string.IsNullOrEmpty(base64)) return TransparentLayer();
            if (base64.Length > (MaxLayerBytes + 2) / 3 * 4)
                throw new InvalidDataException("皮肤图层过大，请重新导入。");
            byte[] bytes;
            try { bytes = Convert.FromBase64String(base64); }
            catch (FormatException error) { throw new InvalidDataException("皮肤图层数据无效。", error); }
            int width, height;
            ReadDimensions(bytes, out width, out height, true);
            if (width != SkinWidth || height != SkinHeight || bytes.Length > MaxLayerBytes)
                throw new InvalidDataException("皮肤图层尺寸必须为 512 × 192。");
            return DecodeImage(bytes, width, height);
        }

        public static string Encode(Texture2D texture)
        {
            if (texture == null) throw new ArgumentNullException(nameof(texture));
            if (texture.width != SkinWidth || texture.height != SkinHeight)
                throw new ArgumentException("皮肤图层尺寸必须为 512 × 192。");
            byte[] bytes = texture.EncodeToPNG();
            if (bytes == null || bytes.Length == 0 || bytes.Length > MaxLayerBytes)
                throw new InvalidDataException("皮肤图层无法保存，请重新绘制或导入。");
            return Convert.ToBase64String(bytes);
        }

        public static Texture2D LoadPhoto(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) throw new ArgumentException("请选择 PNG 或 JPEG 图片。");
            string extension = Path.GetExtension(path).ToLowerInvariant();
            if (extension != ".png" && extension != ".jpg" && extension != ".jpeg")
                throw new InvalidDataException("目前只支持 PNG 和 JPEG 图片。");
            byte[] bytes;
            try
            {
                using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                {
                    if (stream.Length < 24 || stream.Length > MaxPhotoBytes)
                        throw new InvalidDataException("图片为空或超过 8 MB，请选择较小的图片。");
                    bytes = new byte[(int)stream.Length];
                    int offset = 0;
                    while (offset < bytes.Length)
                    {
                        int read = stream.Read(bytes, offset, bytes.Length - offset);
                        if (read == 0) throw new InvalidDataException("图片读取不完整，请重新选择。");
                        offset += read;
                    }
                }
            }
            catch (UnauthorizedAccessException error) { throw new IOException("没有权限读取这张图片。", error); }
            catch (IOException error)
            { throw new IOException("无法读取这张图片，请确认文件仍然存在。", error); }
            int width, height;
            ReadDimensions(bytes, out width, out height, false);
            Texture2D source = DecodeImage(bytes, width, height);
            Texture2D layer = null;
            try
            {
                layer = TransparentLayer();
                float factor = Math.Min((float)SkinWidth / width, (float)SkinHeight / height);
                int fittedWidth = Math.Max(1, Math.Min(SkinWidth, Mathf.RoundToInt(width * factor)));
                int fittedHeight = Math.Max(1, Math.Min(SkinHeight, Mathf.RoundToInt(height * factor)));
                int left = (SkinWidth - fittedWidth) / 2, bottom = (SkinHeight - fittedHeight) / 2;
                Color32[] pixels = new Color32[SkinWidth * SkinHeight];
                for (int y = 0; y < fittedHeight; ++y)
                    for (int x = 0; x < fittedWidth; ++x)
                        pixels[(y + bottom) * SkinWidth + x + left] = source.GetPixelBilinear(
                            (x + .5f) / fittedWidth, (y + .5f) / fittedHeight);
                layer.SetPixels32(pixels);
                layer.Apply(false, false);
                // Only this newly rasterized canvas leaves this function.
                // EncodeToPNG writes pixel content; source EXIF/path is absent.
                return layer;
            }
            catch { if (layer != null) DisposeTexture(layer); throw; }
            finally { DisposeTexture(source); }
        }

        static Texture2D TransparentLayer()
        {
            Texture2D texture = new Texture2D(SkinWidth, SkinHeight, TextureFormat.RGBA32, false);
            texture.name = "Cart skin layer";
            texture.wrapMode = TextureWrapMode.Clamp;
            texture.filterMode = FilterMode.Bilinear;
            texture.SetPixels32(new Color32[SkinWidth * SkinHeight]);
            texture.Apply(false, false);
            return texture;
        }

        static Texture2D DecodeImage(byte[] bytes, int width, int height)
        {
            Texture2D texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            try
            {
                if (!texture.LoadImage(bytes, false) || texture.width != width || texture.height != height)
                    throw new InvalidDataException("图片内容损坏或格式不受支持，请换一张图片。");
                texture.wrapMode = TextureWrapMode.Clamp;
                texture.filterMode = FilterMode.Bilinear;
                return texture;
            }
            catch { DisposeTexture(texture); throw; }
        }

        static void ReadDimensions(byte[] bytes, out int width, out int height, bool pngOnly)
        {
            width = height = 0;
            if (bytes.Length >= 33 && bytes[0] == 137 && bytes[1] == 80 && bytes[2] == 78
                && bytes[3] == 71 && bytes[4] == 13 && bytes[5] == 10 && bytes[6] == 26 && bytes[7] == 10
                && Read32(bytes, 8) == 13 && bytes[12] == 73 && bytes[13] == 72 && bytes[14] == 68 && bytes[15] == 82)
            {
                width = Read32(bytes, 16); height = Read32(bytes, 20);
            }
            else if (!pngOnly && bytes.Length >= 4 && bytes[0] == 255 && bytes[1] == 216)
            {
                int offset = 2;
                while (offset + 3 < bytes.Length)
                {
                    if (bytes[offset++] != 255) break;
                    while (offset < bytes.Length && bytes[offset] == 255) ++offset;
                    if (offset >= bytes.Length) break;
                    int marker = bytes[offset++];
                    if (marker == 217 || marker == 218) break;
                    if (marker == 1 || (marker >= 208 && marker <= 215)) continue;
                    if (offset + 2 > bytes.Length) break;
                    int length = (bytes[offset] << 8) | bytes[offset + 1];
                    if (length < 2 || offset + length > bytes.Length) break;
                    if ((marker >= 192 && marker <= 195) || (marker >= 197 && marker <= 199)
                        || (marker >= 201 && marker <= 203) || (marker >= 205 && marker <= 207))
                    {
                        if (length < 8) break;
                        height = (bytes[offset + 3] << 8) | bytes[offset + 4];
                        width = (bytes[offset + 5] << 8) | bytes[offset + 6];
                        break;
                    }
                    offset += length;
                }
            }
            if (width <= 0 || height <= 0) throw new InvalidDataException("不是有效的 PNG 或 JPEG 图片。");
            if (width > MaxImageSide || height > MaxImageSide || (long)width * height > MaxImagePixels)
                throw new InvalidDataException("图片分辨率过大，请缩小至 1600 万像素以内，单边不超过 8192 像素。");
        }

        static int Read32(byte[] bytes, int offset)
        { return (bytes[offset] << 24) | (bytes[offset + 1] << 16) | (bytes[offset + 2] << 8) | bytes[offset + 3]; }

        public static string SanitizeName(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return "我的小车";
            StringBuilder clean = new StringBuilder();
            bool visible = false;
            for (int i = 0; i < value.Length && i < 512; ++i)
            {
                char character = value[i];
                UnicodeCategory category = CharUnicodeInfo.GetUnicodeCategory(value, i);
                if (char.IsControl(character) || category == UnicodeCategory.Format
                    || category == UnicodeCategory.LineSeparator || category == UnicodeCategory.ParagraphSeparator)
                    continue;
                if (char.IsHighSurrogate(character) && i + 1 < value.Length && char.IsLowSurrogate(value[i + 1]))
                { clean.Append(character).Append(value[++i]); visible = true; continue; }
                if (char.IsSurrogate(character)) continue;
                clean.Append(character);
                if (!char.IsWhiteSpace(character) && category != UnicodeCategory.NonSpacingMark
                    && category != UnicodeCategory.SpacingCombiningMark && category != UnicodeCategory.EnclosingMark)
                    visible = true;
            }
            if (!visible) return "我的小车";
            TextElementEnumerator elements = StringInfo.GetTextElementEnumerator(clean.ToString().Trim());
            StringBuilder result = new StringBuilder();
            for (int count = 0; count < 24 && elements.MoveNext(); ++count) result.Append(elements.GetTextElement());
            string name = result.ToString().Trim();
            return string.IsNullOrWhiteSpace(name) ? "我的小车" : name;
        }

        public static string NormalizeColor(string value)
        {
            Color color;
            return !string.IsNullOrWhiteSpace(value) && ColorUtility.TryParseHtmlString(value.Trim(), out color)
                ? "#" + ColorUtility.ToHtmlStringRGB(color) : "#0878E8";
        }

        static void DisposeTexture(Texture2D texture)
        {
            if (Application.isPlaying) UnityEngine.Object.Destroy(texture);
            else UnityEngine.Object.DestroyImmediate(texture);
        }
    }
}
