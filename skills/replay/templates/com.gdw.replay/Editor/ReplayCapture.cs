// Gdw.Replay.Editor: per-frame PNG capture for deterministic replay export.
//
// This is the PNG-per-frame backend (the default for `backend: "auto"` / `backend: "png"`).
// It freezes simulation while writing synchronous frame captures, producing
//   <project>/Logs/harness/replay/<run_id>/capture/frames/frame-%06d.png
// at a fixed frame rate.  The Recorder backend is used only when `backend: "recorder"`
// is requested AND com.unity.recorder is already present in the project (detected via
// reflection; no hard dependency).
//
// Camera RenderTexture path is used when there is no active Game View (batch / headless);
// the Game View is preferred when available because overlay UI is captured.
//
// Namespace: Gdw.Replay
// Depends on: UnityEditor, UnityEngine (no Recorder dependency)

using System;
using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace Gdw.Replay
{
    /// <summary>
    /// Per-frame PNG capture for replay export.  Called by ReplayLoop after each
    /// post-LateUpdate checkpoint when capture is active.
    /// </summary>
    [InitializeOnLoad]
    public static class ReplayCapture
    {
        static string s_OutputDir;
        static int s_FrameNumber;
        static int s_TotalFrames;
        static int s_Fps;
        static bool s_Active;
        static Camera s_CaptureCamera;
        static RenderTexture s_RenderTexture;
        static Texture2D s_ReadTexture;

        /// <summary>Start a capture session.</summary>
        /// <param name="outputDir">Absolute path to the capture/frames/ directory.</param>
        /// <param name="totalFrames">Total number of frames to capture.</param>
        /// <param name="fps">Frame rate (determines capture delta-time).</param>
        /// <returns>"ok" or "error: ..."</returns>
        public static string Start(string outputDir, int totalFrames, int fps)
        {
            if (s_Active)
                return "error: capture already active";

            try
            {
                Directory.CreateDirectory(outputDir);
            }
            catch (Exception ex)
            {
                return "error: cannot create output directory: " + ex.Message;
            }

            s_OutputDir = outputDir;
            s_TotalFrames = Mathf.Max(1, totalFrames);
            s_FrameNumber = 0;
            s_Fps = Mathf.Max(1, fps);
            s_Active = true;

            // Set up a camera RenderTexture fallback for headless / no-Game-View.
            var cam = Camera.main ?? UnityEngine.Object.FindObjectOfType<Camera>();
            if (cam != null && !Application.isBatchMode)
            {
                // Prefer the active Game View; fall back to a dedicated camera RT.
                s_CaptureCamera = cam;
            }
            else if (cam != null)
            {
                s_CaptureCamera = cam;
                int w = Screen.width > 0 ? Screen.width : 1920;
                int h = Screen.height > 0 ? Screen.height : 1080;
                s_RenderTexture = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32);
                s_RenderTexture.Create();
                s_ReadTexture = new Texture2D(w, h, TextureFormat.RGBA32, false);
            }
            else
            {
                return "error: no camera found for capture";
            }

            Debug.LogFormat("[REPLAY] capture started: {0} frames at {1} fps -> {2}",
                s_TotalFrames, s_Fps, s_OutputDir);
            return "ok";
        }

        /// <summary>Capture the current frame (synchronous).  Call once per frame.</summary>
        /// <returns>"ok" when a frame was written, "done" when all frames captured, or "error: ..."</returns>
        public static string CaptureFrame()
        {
            if (!s_Active)
                return "error: capture not active";

            if (s_FrameNumber >= s_TotalFrames)
            {
                Stop();
                return "done";
            }

            try
            {
                string path = Path.Combine(s_OutputDir,
                    string.Format("frame-{0:D6}.png", s_FrameNumber));

                if (s_RenderTexture != null && s_CaptureCamera != null)
                {
                    // RenderTexture path: render the camera into the RT and read pixels.
                    RenderTexture prev = s_CaptureCamera.targetTexture;
                    s_CaptureCamera.targetTexture = s_RenderTexture;
                    s_CaptureCamera.Render();
                    s_CaptureCamera.targetTexture = prev;

                    RenderTexture.active = s_RenderTexture;
                    s_ReadTexture.ReadPixels(new Rect(0, 0, s_RenderTexture.width, s_RenderTexture.height), 0, 0);
                    RenderTexture.active = null;

                    File.WriteAllBytes(path, s_ReadTexture.EncodeToPNG());
                }
                else
                {
                    // Game View / ScreenCapture path.
                    ScreenCapture.CaptureScreenshot(path);
                }

                s_FrameNumber++;
            }
            catch (Exception ex)
            {
                return "error: " + ex.Message;
            }

            return "ok";
        }

        /// <summary>Stop capture and clean up resources.</summary>
        public static void Stop()
        {
            if (!s_Active)
                return;

            s_Active = false;
            Debug.LogFormat("[REPLAY] capture stopped: {0} frames written to {1}",
                s_FrameNumber, s_OutputDir);

            if (s_RenderTexture != null)
            {
                s_RenderTexture.Release();
                s_RenderTexture = null;
            }
            if (s_ReadTexture != null)
            {
                UnityEngine.Object.DestroyImmediate(s_ReadTexture);
                s_ReadTexture = null;
            }
            s_CaptureCamera = null;
        }

        /// <summary>Current status.</summary>
        public static string Status()
        {
            if (!s_Active)
                return "idle";
            return string.Format("capturing frame {0}/{1}", s_FrameNumber, s_TotalFrames);
        }

        /// <summary>Cancel a running capture.</summary>
        public static string Cancel()
        {
            if (!s_Active)
                return "idle";
            Stop();
            return "cancelled";
        }
    }
}
