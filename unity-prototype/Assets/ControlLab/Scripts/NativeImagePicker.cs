using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using UnityEngine;

namespace ControlLab.UnityPrototype
{
    /// <summary>Windows-owned modal dialogs; cancellation is not an error.</summary>
    public static class NativeImagePicker
    {
        static readonly int[] CustomColors = new int[16];

        public static string PickImage()
        {
            RequireWindows();
            string workingDirectory = Environment.CurrentDirectory;
            IntPtr fileBuffer = Marshal.AllocHGlobal(32768 * sizeof(char));
            try
            {
                Marshal.WriteInt16(fileBuffer, 0);
                OpenFileName dialog = new OpenFileName
                {
                    structSize = Marshal.SizeOf(typeof(OpenFileName)), owner = OwnerWindow(),
                    filter = "图片文件 (*.png;*.jpg;*.jpeg)\0*.png;*.jpg;*.jpeg\0PNG 图片\0*.png\0JPEG 图片\0*.jpg;*.jpeg\0\0",
                    filterIndex = 1, file = fileBuffer, maxFile = 32768,
                    title = "为小车选择一张图片", defaultExtension = "png",
                    flags = 0x00080000 | 0x00001000 | 0x00000800 | 0x00000008 | 0x02000000
                };
                if (GetOpenFileNameW(ref dialog)) return Path.GetFullPath(Marshal.PtrToStringUni(fileBuffer));
                ThrowDialogError();
                return null;
            }
            finally
            {
                Marshal.FreeHGlobal(fileBuffer);
                if (Environment.CurrentDirectory != workingDirectory) Environment.CurrentDirectory = workingDirectory;
            }
        }

        public static Color? PickColor(Color current)
        {
            RequireWindows();
            string workingDirectory = Environment.CurrentDirectory;
            IntPtr colors = Marshal.AllocHGlobal(16 * sizeof(int));
            try
            {
                Marshal.Copy(CustomColors, 0, colors, CustomColors.Length);
                Color32 initial = current;
                ChooseColor dialog = new ChooseColor
                {
                    structSize = Marshal.SizeOf(typeof(ChooseColor)), owner = OwnerWindow(),
                    rgbResult = initial.r | (initial.g << 8) | (initial.b << 16),
                    customColors = colors, flags = 0x00000001 | 0x00000002
                };
                if (!ChooseColorW(ref dialog)) { ThrowDialogError(); return null; }
                Marshal.Copy(colors, CustomColors, 0, CustomColors.Length);
                return new Color((dialog.rgbResult & 255) / 255f,
                    ((dialog.rgbResult >> 8) & 255) / 255f, ((dialog.rgbResult >> 16) & 255) / 255f, current.a);
            }
            finally
            {
                Marshal.FreeHGlobal(colors);
                if (Environment.CurrentDirectory != workingDirectory) Environment.CurrentDirectory = workingDirectory;
            }
        }

        static void RequireWindows()
        {
            if (Application.platform != RuntimePlatform.WindowsPlayer && Application.platform != RuntimePlatform.WindowsEditor)
                throw new NotSupportedException("图片和颜色选择器目前仅支持 Windows。");
        }

        static IntPtr OwnerWindow()
        {
            using (Process process = Process.GetCurrentProcess())
            {
                IntPtr active = GetActiveWindow();
                uint owner;
                if (active != IntPtr.Zero && GetWindowThreadProcessId(active, out owner) != 0 && owner == process.Id)
                    return active;
                return process.MainWindowHandle;
            }
        }

        static void ThrowDialogError()
        {
            uint code = CommDlgExtendedError();
            if (code != 0) throw new InvalidOperationException("无法打开系统选择窗口（错误代码 0x" + code.ToString("X") + "）。");
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct OpenFileName
        {
            public int structSize;
            public IntPtr owner, instance;
            [MarshalAs(UnmanagedType.LPWStr)] public string filter;
            public IntPtr customFilter;
            public int maxCustomFilter, filterIndex;
            public IntPtr file;
            public int maxFile;
            public IntPtr fileTitle;
            public int maxFileTitle;
            public string initialDirectory, title;
            public uint flags;
            public ushort fileOffset, fileExtension;
            public string defaultExtension;
            public IntPtr customData, hook;
            public string templateName;
            public IntPtr reserved;
            public uint reservedFlags, flagsEx;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct ChooseColor
        {
            public int structSize;
            public IntPtr owner, instance;
            public int rgbResult;
            public IntPtr customColors;
            public uint flags;
            public IntPtr customData, hook;
            public string templateName;
        }

        [DllImport("comdlg32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
        [return: MarshalAs(UnmanagedType.Bool)] static extern bool GetOpenFileNameW(ref OpenFileName value);
        [DllImport("comdlg32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
        [return: MarshalAs(UnmanagedType.Bool)] static extern bool ChooseColorW(ref ChooseColor value);
        [DllImport("comdlg32.dll")] static extern uint CommDlgExtendedError();
        [DllImport("user32.dll")] static extern IntPtr GetActiveWindow();
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    }
}
