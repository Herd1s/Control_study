using System;
using System.Collections;
using System.IO;
using UnityEngine;

namespace ControlLab.UnityPrototype
{
    // Runs only on an explicit QA command line; normal learners see no test controls.
    public sealed class PrototypeCapture : MonoBehaviour
    {
        string requestPath, captureDirectory;

        void Awake()
        {
            var args = Environment.GetCommandLineArgs();
            for (var i = 0; i + 1 < args.Length; i++)
                if (args[i] == "--qa-state-path" && Path.IsPathRooted(args[i + 1]))
                {
                    requestPath = args[i + 1] + ".capture-request";
                    captureDirectory = Path.GetDirectoryName(Path.GetFullPath(args[i + 1]));
                }
        }

        void Update()
        {
            if (requestPath == null || !File.Exists(requestPath)) return;
            try
            {
                var name = File.ReadAllText(requestPath).Trim();
                // QA can request a PNG beside its state file, never an arbitrary path.
                if (name.Length == 0 || Path.GetFileName(name) != name ||
                    !name.EndsWith(".png", StringComparison.OrdinalIgnoreCase)) return;
                File.Delete(requestPath);
                ScreenCapture.CaptureScreenshot(Path.Combine(captureDirectory, name));
            }
            catch (IOException) { /* A transient writer lock is retried next frame. */ }
        }

        IEnumerator Start()
        {
            var arguments = Environment.GetCommandLineArgs();
            string path = null;
            for (var i = 0; i + 1 < arguments.Length; i++)
                if (arguments[i] == "--capture-path") path = arguments[i + 1];
            if (string.IsNullOrEmpty(path)) yield break;
            yield return new WaitForSecondsRealtime(2f);
            yield return new WaitForEndOfFrame();
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            ScreenCapture.CaptureScreenshot(path);
            yield return new WaitForSecondsRealtime(.6f);
            Debug.Log("CONTROLLAB_CAPTURE_OK " + path);
            if (Array.IndexOf(arguments, "--capture-and-exit") >= 0) Application.Quit();
        }
    }
}
