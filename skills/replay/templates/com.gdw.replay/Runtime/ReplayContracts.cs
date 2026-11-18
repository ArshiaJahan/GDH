using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace Gdw.Replay
{
    public sealed class ReplayCompatibilityException : Exception
    {
        public ReplayCompatibilityException(string message) : base(message) { }
        public ReplayCompatibilityException(string message, Exception inner) : base(message, inner) { }
    }

    public sealed class ReplayStateException : Exception
    {
        public ReplayStateException(string message) : base(message) { }
        public ReplayStateException(string message, Exception inner) : base(message, inner) { }
    }

    /// <summary>In-process result surfaced through <see cref="ReplaySession.Finished"/>.</summary>
    public sealed class ReplayResult
    {
        public string Status = "error";
        public long Frames;
        public long Ticks;
        public long FirstDivergentFrame = -1;
        public string DivergentProviderId;
        public string ExpectedHash;
        public string ActualHash;
        public string Message;
        public string ReportPath;
    }

    [Serializable]
    public sealed class ReplayOptions
    {
        public uint Seed;
        public float FixedDeltaTime = 1f / 60f;
        public string ScenePath;
        public string RunId;
        public bool Strict = true;
    }

    /// <summary>Positive reduced rational used for fixed_dt / render_dt.</summary>
    public sealed class Rational
    {
        public int Num = 1;
        public int Den = 1;

        public Rational() { }
        public Rational(int num, int den) { Num = num; Den = den; Reduce(); }

        public float Value => Den == 0 ? 0f : (float)Num / Den;

        public static Rational FromFloat(float value)
        {
            if (value <= 0f || float.IsNaN(value) || float.IsInfinity(value)) return new Rational(1, 60);
            double target = value;
            for (int den = 1; den <= 1000000; den++)
            {
                long num = (long)Math.Round(target * den);
                if (num <= 0) continue;
                if (Math.Abs((double)num / den - target) <= 1e-9)
                    return new Rational((int)num, den);
            }
            return new Rational(1, 60);
        }

        void Reduce()
        {
            if (Den == 0) { Num = 1; Den = 1; return; }
            if (Den < 0) { Num = -Num; Den = -Den; }
            int g = Gcd(Math.Abs(Num), Math.Abs(Den));
            if (g > 0) { Num /= g; Den /= g; }
        }

        static int Gcd(int a, int b)
        {
            while (b != 0) { int t = a % b; a = b; b = t; }
            return a;
        }
    }

    public sealed class ReplayFrame
    {
        public long Frame;
        public long Tick;
        public int FixedTicks;
        public bool InputUpdate;
        public int EventStart;
        public int EventCount;
        public string Hash;
        public Dictionary<string, string> Providers = new Dictionary<string, string>(StringComparer.Ordinal);

        internal JsonValue ToJson()
        {
            var providers = Json.Obj();
            foreach (var kv in Providers) Json.Set(providers, kv.Key, Json.String(kv.Value));
            var o = Json.Obj();
            Json.Set(o, "frame", Json.Number(Frame));
            Json.Set(o, "tick", Json.Number(Tick));
            Json.Set(o, "fixed_ticks", Json.Number(FixedTicks));
            Json.Set(o, "input_update", Json.Bool(InputUpdate));
            Json.Set(o, "event_start", Json.Number(EventStart));
            Json.Set(o, "event_count", Json.Number(EventCount));
            Json.Set(o, "hash", Json.String(Hash));
            Json.Set(o, "providers", Json.Object(providers));
            return Json.Object(o);
        }

        internal static ReplayFrame FromJson(JsonValue v)
        {
            var o = v;
            var frame = new ReplayFrame
            {
                Frame = Json.Long(o, "frame"),
                Tick = Json.Long(o, "tick"),
                FixedTicks = Json.Int(o, "fixed_ticks"),
                InputUpdate = Json.Bool(o, "input_update"),
                EventStart = Json.Int(o, "event_start"),
                EventCount = Json.Int(o, "event_count"),
                Hash = Json.Str(o, "hash"),
            };
            if (o.Has("providers") && o.Get("providers").Kind == JsonKind.Object)
            {
                foreach (var kv in o.Get("providers").AsObject()) frame.Providers[kv.Key] = kv.Value.AsString();
            }
            return frame;
        }
    }

    public sealed class ReplayMarker
    {
        public long Frame;
        public long Tick;
        public string Label;
        public string Data;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "frame", Json.Number(Frame));
            Json.Set(o, "tick", Json.Number(Tick));
            Json.Set(o, "label", Json.String(Label));
            Json.Set(o, "data", Json.String(Data));
            return Json.Object(o);
        }

        internal static ReplayMarker FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayMarker
            {
                Frame = Json.Long(o, "frame"),
                Tick = Json.Long(o, "tick"),
                Label = Json.Str(o, "label"),
                Data = Json.Str(o, "data"),
            };
        }
    }

    public sealed class ReplayConsoleCounts
    {
        public int Errors;
        public int Warnings;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "errors", Json.Number(Errors));
            Json.Set(o, "warnings", Json.Number(Warnings));
            return Json.Object(o);
        }

        internal static ReplayConsoleCounts FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayConsoleCounts { Errors = Json.Int(o, "errors"), Warnings = Json.Int(o, "warnings") };
        }
    }

    public sealed class ReplayManifestFile
    {
        public string Name;
        public long Bytes;
        public string Sha256;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "name", Json.String(Name));
            Json.Set(o, "bytes", Json.Number(Bytes));
            Json.Set(o, "sha256", Json.String(Sha256));
            return Json.Object(o);
        }

        internal static ReplayManifestFile FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayManifestFile { Name = Json.Str(o, "name"), Bytes = Json.Long(o, "bytes"), Sha256 = Json.Str(o, "sha256") };
        }
    }

    public sealed class ReplayManifest
    {
        public string Format = "gdwreplay-manifest";
        public int Version = 1;
        public bool Complete;
        public long Frames;
        public long Ticks;
        public long Events;
        public ReplayConsoleCounts Console = new ReplayConsoleCounts();
        public string FinalFrameHash;
        public string CreatedUtc;
        public string ToolVersion;
        public List<ReplayManifestFile> Files = new List<ReplayManifestFile>();

        internal JsonValue ToJson()
        {
            var files = new List<JsonValue>();
            foreach (var f in Files) files.Add(f.ToJson());
            var o = Json.Obj();
            Json.Set(o, "format", Json.String(Format));
            Json.Set(o, "version", Json.Number(Version));
            Json.Set(o, "complete", Json.Bool(Complete));
            Json.Set(o, "frames", Json.Number(Frames));
            Json.Set(o, "ticks", Json.Number(Ticks));
            Json.Set(o, "events", Json.Number(Events));
            Json.Set(o, "console", Console.ToJson());
            Json.Set(o, "final_frame_hash", Json.String(FinalFrameHash));
            Json.Set(o, "created_utc", Json.String(CreatedUtc));
            Json.Set(o, "tool_version", Json.String(ToolVersion));
            Json.Set(o, "files", Json.Array(files));
            return Json.Object(o);
        }

        internal static ReplayManifest FromJson(JsonValue v)
        {
            var o = v;
            var manifest = new ReplayManifest
            {
                Format = Json.Str(o, "format", "gdwreplay-manifest"),
                Version = Json.Int(o, "version", 1),
                Complete = Json.Bool(o, "complete"),
                Frames = Json.Long(o, "frames"),
                Ticks = Json.Long(o, "ticks"),
                Events = Json.Long(o, "events"),
                Console = o.Has("console") ? ReplayConsoleCounts.FromJson(o.Get("console")) : new ReplayConsoleCounts(),
                FinalFrameHash = Json.Str(o, "final_frame_hash"),
                CreatedUtc = Json.Str(o, "created_utc"),
                ToolVersion = Json.Str(o, "tool_version"),
            };
            if (o.Has("files"))
            {
                foreach (var f in o.Get("files").AsArray()) manifest.Files.Add(ReplayManifestFile.FromJson(f));
            }
            return manifest;
        }
    }

    public sealed class ReplayUnityInfo
    {
        public string Version;
        public string Revision;
        public string ScriptingBackend;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "version", Json.String(Version));
            Json.Set(o, "revision", Json.String(Revision));
            Json.Set(o, "scripting_backend", Json.String(ScriptingBackend));
            return Json.Object(o);
        }

        internal static ReplayUnityInfo FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayUnityInfo { Version = Json.Str(o, "version"), Revision = Json.Str(o, "revision"), ScriptingBackend = Json.Str(o, "scripting_backend") };
        }
    }

    public sealed class ReplayOsInfo
    {
        public string Platform;
        public string Version;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "platform", Json.String(Platform));
            Json.Set(o, "version", Json.String(Version));
            return Json.Object(o);
        }

        internal static ReplayOsInfo FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayOsInfo { Platform = Json.Str(o, "platform"), Version = Json.Str(o, "version") };
        }
    }

    public sealed class ReplayCpuInfo
    {
        public string Model;
        public string Architecture;
        public int Cores;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "model", Json.String(Model));
            Json.Set(o, "architecture", Json.String(Architecture));
            Json.Set(o, "cores", Json.Number(Cores));
            return Json.Object(o);
        }

        internal static ReplayCpuInfo FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayCpuInfo { Model = Json.Str(o, "model"), Architecture = Json.Str(o, "architecture"), Cores = Json.Int(o, "cores") };
        }
    }

    public sealed class ReplayProjectInfo
    {
        public string Id;
        public string Name;
        public string ContentSha256;
        public bool Dirty;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "id", Json.String(Id));
            Json.Set(o, "name", Json.String(Name));
            Json.Set(o, "content_sha256", Json.String(ContentSha256));
            Json.Set(o, "dirty", Json.Bool(Dirty));
            return Json.Object(o);
        }

        internal static ReplayProjectInfo FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayProjectInfo { Id = Json.Str(o, "id"), Name = Json.Str(o, "name"), ContentSha256 = Json.Str(o, "content_sha256"), Dirty = Json.Bool(o, "dirty") };
        }
    }

    public sealed class ReplaySceneInfo
    {
        public string Guid;
        public string Path;
        public string ContentSha256;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "guid", Json.String(Guid));
            Json.Set(o, "path", Json.String(Path));
            Json.Set(o, "content_sha256", Json.String(ContentSha256));
            return Json.Object(o);
        }

        internal static ReplaySceneInfo FromJson(JsonValue v)
        {
            var o = v;
            return new ReplaySceneInfo { Guid = Json.Str(o, "guid"), Path = Json.Str(o, "path"), ContentSha256 = Json.Str(o, "content_sha256") };
        }
    }

    public sealed class ReplayPackagesInfo
    {
        public Dictionary<string, string> Versions = new Dictionary<string, string>(StringComparer.Ordinal);
        public string LockSha256;

        internal JsonValue ToJson()
        {
            var versions = Json.Obj();
            foreach (var kv in Versions) Json.Set(versions, kv.Key, Json.String(kv.Value));
            var o = Json.Obj();
            Json.Set(o, "versions", Json.Object(versions));
            Json.Set(o, "lock_sha256", Json.String(LockSha256));
            return Json.Object(o);
        }

        internal static ReplayPackagesInfo FromJson(JsonValue v)
        {
            var o = v;
            var info = new ReplayPackagesInfo { LockSha256 = Json.Str(o, "lock_sha256") };
            if (o.Has("versions"))
            {
                foreach (var kv in o.Get("versions").AsObject()) info.Versions[kv.Key] = kv.Value.AsString();
            }
            return info;
        }
    }

    public sealed class ReplayInputInfo
    {
        public string SettingsSha256;
        public string ActionsSha256;
        public string LayoutsSha256;
        public string SystemVersion;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "settings_sha256", Json.String(SettingsSha256));
            Json.Set(o, "actions_sha256", Json.String(ActionsSha256));
            Json.Set(o, "layouts_sha256", Json.String(LayoutsSha256));
            Json.Set(o, "system_version", Json.String(SystemVersion));
            return Json.Object(o);
        }

        internal static ReplayInputInfo FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayInputInfo
            {
                SettingsSha256 = Json.Str(o, "settings_sha256"),
                ActionsSha256 = Json.Str(o, "actions_sha256"),
                LayoutsSha256 = Json.Str(o, "layouts_sha256"),
                SystemVersion = Json.Str(o, "system_version"),
            };
        }
    }

    public sealed class ReplayDeviceInfo
    {
        public string Description;
        public string Layout;
        public string StateFormatSha256;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "description", Json.String(Description));
            Json.Set(o, "layout", Json.String(Layout));
            Json.Set(o, "state_format_sha256", Json.String(StateFormatSha256));
            return Json.Object(o);
        }
    }

    public sealed class ReplayProviderInfo
    {
        public string Id;
        public string SchemaSha256;
        public bool Gameplay;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "id", Json.String(Id));
            Json.Set(o, "schema_sha256", Json.String(SchemaSha256));
            Json.Set(o, "gameplay", Json.Bool(Gameplay));
            return Json.Object(o);
        }
    }

    public sealed class ReplayResetAdapterInfo
    {
        public string Id;
        public string InitialStateSha256;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "id", Json.String(Id));
            Json.Set(o, "initial_state_sha256", Json.String(InitialStateSha256));
            return Json.Object(o);
        }

        internal static ReplayResetAdapterInfo FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayResetAdapterInfo { Id = Json.Str(o, "id"), InitialStateSha256 = Json.Str(o, "initial_state_sha256") };
        }
    }

    public sealed class ReplayStateHashInfo
    {
        public string Algorithm;
        public string Encoding;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "algorithm", Json.String(Algorithm));
            Json.Set(o, "encoding", Json.String(Encoding));
            return Json.Object(o);
        }

        internal static ReplayStateHashInfo FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayStateHashInfo { Algorithm = Json.Str(o, "algorithm"), Encoding = Json.Str(o, "encoding") };
        }
    }

    public sealed class ReplayFeaturesInfo
    {
        public List<string> Required = new List<string>();
        public List<string> Optional = new List<string>();

        internal JsonValue ToJson()
        {
            var required = new List<JsonValue>();
            var optional = new List<JsonValue>();
            foreach (var s in Required) required.Add(Json.String(s));
            foreach (var s in Optional) optional.Add(Json.String(s));
            var o = Json.Obj();
            Json.Set(o, "required", Json.Array(required));
            Json.Set(o, "optional", Json.Array(optional));
            return Json.Object(o);
        }

        internal static ReplayFeaturesInfo FromJson(JsonValue v)
        {
            var o = v;
            var info = new ReplayFeaturesInfo();
            if (o.Has("required")) foreach (var s in o.Get("required").AsArray()) info.Required.Add(s.AsString());
            if (o.Has("optional")) foreach (var s in o.Get("optional").AsArray()) info.Optional.Add(s.AsString());
            return info;
        }
    }

    public sealed class ReplayCoverageInfo
    {
        public List<string> Unsupported = new List<string>();
        public string Notes;

        internal JsonValue ToJson()
        {
            var unsupported = new List<JsonValue>();
            foreach (var s in Unsupported) unsupported.Add(Json.String(s));
            var o = Json.Obj();
            Json.Set(o, "unsupported", Json.Array(unsupported));
            Json.Set(o, "notes", Json.String(Notes));
            return Json.Object(o);
        }

        internal static ReplayCoverageInfo FromJson(JsonValue v)
        {
            var o = v;
            var info = new ReplayCoverageInfo { Notes = Json.Str(o, "notes") };
            if (o.Has("unsupported")) foreach (var s in o.Get("unsupported").AsArray()) info.Unsupported.Add(s.AsString());
            return info;
        }
    }

    public sealed class ReplayHeader
    {
        public string Format = "gdwreplay";
        public int Major = 1;
        public int Minor = 0;
        public string RunId;
        public string CreatedUtc;
        public string ToolVersion = "0.1.0";
        public ReplayUnityInfo Unity = new ReplayUnityInfo();
        public ReplayOsInfo Os = new ReplayOsInfo();
        public ReplayCpuInfo Cpu = new ReplayCpuInfo();
        public ReplayProjectInfo Project = new ReplayProjectInfo();
        public ReplaySceneInfo Scene = new ReplaySceneInfo();
        public uint Seed;
        public Rational FixedDt = new Rational(1, 60);
        public Rational RenderDt = new Rational(1, 60);
        public ReplayPackagesInfo Packages = new ReplayPackagesInfo();
        public ReplayInputInfo Input = new ReplayInputInfo();
        public List<ReplayDeviceInfo> Devices = new List<ReplayDeviceInfo>();
        public List<ReplayProviderInfo> Providers = new List<ReplayProviderInfo>();
        public ReplayResetAdapterInfo ResetAdapter = new ReplayResetAdapterInfo();
        public ReplayStateHashInfo StateHash = new ReplayStateHashInfo();
        public ReplayFeaturesInfo Features = new ReplayFeaturesInfo();
        public ReplayCoverageInfo Coverage = new ReplayCoverageInfo();

        internal JsonValue ToJson()
        {
            var devices = new List<JsonValue>();
            var providers = new List<JsonValue>();
            foreach (var d in Devices) devices.Add(d.ToJson());
            foreach (var p in Providers) providers.Add(p.ToJson());

            var o = Json.Obj();
            Json.Set(o, "format", Json.String(Format));
            Json.Set(o, "major", Json.Number(Major));
            Json.Set(o, "minor", Json.Number(Minor));
            Json.Set(o, "run_id", Json.String(RunId));
            Json.Set(o, "created_utc", Json.String(CreatedUtc));
            Json.Set(o, "tool_version", Json.String(ToolVersion));
            Json.Set(o, "unity", Unity.ToJson());
            Json.Set(o, "os", Os.ToJson());
            Json.Set(o, "cpu", Cpu.ToJson());
            Json.Set(o, "project", Project.ToJson());
            Json.Set(o, "scene", Scene.ToJson());
            Json.Set(o, "seed", Json.Number((long)Seed));
            Json.Set(o, "fixed_dt", RationalToJson(FixedDt));
            Json.Set(o, "render_dt", RationalToJson(RenderDt));
            Json.Set(o, "packages", Packages.ToJson());
            Json.Set(o, "input", Input.ToJson());
            Json.Set(o, "devices", Json.Array(devices));
            Json.Set(o, "providers", Json.Array(providers));
            Json.Set(o, "reset_adapter", ResetAdapter.ToJson());
            Json.Set(o, "state_hash", StateHash.ToJson());
            Json.Set(o, "features", Features.ToJson());
            Json.Set(o, "coverage", Coverage.ToJson());
            return Json.Object(o);
        }

        internal static ReplayHeader FromJson(JsonValue v)
        {
            var o = v;
            var header = new ReplayHeader
            {
                Format = Json.Str(o, "format", "gdwreplay"),
                Major = Json.Int(o, "major", 1),
                Minor = Json.Int(o, "minor", 0),
                RunId = Json.Str(o, "run_id"),
                CreatedUtc = Json.Str(o, "created_utc"),
                ToolVersion = Json.Str(o, "tool_version", "0.1.0"),
                Seed = Json.UInt(o, "seed"),
                FixedDt = o.Has("fixed_dt") ? RationalFromJson(o.Get("fixed_dt")) : new Rational(1, 60),
                RenderDt = o.Has("render_dt") ? RationalFromJson(o.Get("render_dt")) : new Rational(1, 60),
            };
            if (o.Has("unity")) header.Unity = ReplayUnityInfo.FromJson(o.Get("unity"));
            if (o.Has("os")) header.Os = ReplayOsInfo.FromJson(o.Get("os"));
            if (o.Has("cpu")) header.Cpu = ReplayCpuInfo.FromJson(o.Get("cpu"));
            if (o.Has("project")) header.Project = ReplayProjectInfo.FromJson(o.Get("project"));
            if (o.Has("scene")) header.Scene = ReplaySceneInfo.FromJson(o.Get("scene"));
            if (o.Has("packages")) header.Packages = ReplayPackagesInfo.FromJson(o.Get("packages"));
            if (o.Has("input")) header.Input = ReplayInputInfo.FromJson(o.Get("input"));
            if (o.Has("devices")) foreach (var d in o.Get("devices").AsArray()) header.Devices.Add(ReplayDeviceInfoFromJson(d));
            if (o.Has("providers")) foreach (var p in o.Get("providers").AsArray()) header.Providers.Add(ReplayProviderInfoFromJson(p));
            if (o.Has("reset_adapter")) header.ResetAdapter = ReplayResetAdapterInfo.FromJson(o.Get("reset_adapter"));
            if (o.Has("state_hash")) header.StateHash = ReplayStateHashInfo.FromJson(o.Get("state_hash"));
            if (o.Has("features")) header.Features = ReplayFeaturesInfo.FromJson(o.Get("features"));
            if (o.Has("coverage")) header.Coverage = ReplayCoverageInfo.FromJson(o.Get("coverage"));
            return header;
        }

        static JsonValue RationalToJson(Rational r)
        {
            var o = Json.Obj();
            Json.Set(o, "num", Json.Number(r.Num));
            Json.Set(o, "den", Json.Number(r.Den));
            return Json.Object(o);
        }

        static Rational RationalFromJson(JsonValue v)
        {
            var o = v;
            return new Rational(Json.Int(o, "num", 1), Json.Int(o, "den", 1));
        }

        static ReplayDeviceInfo ReplayDeviceInfoFromJson(JsonValue v)
        {
            var o = v;
            return new ReplayDeviceInfo { Description = Json.Str(o, "description"), Layout = Json.Str(o, "layout"), StateFormatSha256 = Json.Str(o, "state_format_sha256") };
        }

        static ReplayProviderInfo ReplayProviderInfoFromJson(JsonValue v)
        {
            var o = v;
            return new ReplayProviderInfo { Id = Json.Str(o, "id"), SchemaSha256 = Json.Str(o, "schema_sha256"), Gameplay = Json.Bool(o, "gameplay") };
        }
    }

    public sealed class ReplayCaptureOptions
    {
        public List<string> Formats = new List<string>();
        public string Backend = "auto";
        public int StartFrame;
        public int EndFrameExclusive;
        public int Width = 1280;
        public int Height = 720;
        public int Fps = 60;

        internal JsonValue ToJson()
        {
            var formats = new List<JsonValue>();
            foreach (var f in Formats) formats.Add(Json.String(f));
            var o = Json.Obj();
            Json.Set(o, "formats", Json.Array(formats));
            Json.Set(o, "backend", Json.String(Backend));
            Json.Set(o, "start_frame", Json.Number(StartFrame));
            Json.Set(o, "end_frame_exclusive", Json.Number(EndFrameExclusive));
            Json.Set(o, "width", Json.Number(Width));
            Json.Set(o, "height", Json.Number(Height));
            Json.Set(o, "fps", Json.Number(Fps));
            return Json.Object(o);
        }

        internal static ReplayCaptureOptions FromJson(JsonValue v)
        {
            var o = v;
            var capture = new ReplayCaptureOptions
            {
                Backend = Json.Str(o, "backend", "auto"),
                StartFrame = Json.Int(o, "start_frame"),
                EndFrameExclusive = Json.Int(o, "end_frame_exclusive"),
                Width = Json.Int(o, "width", 1280),
                Height = Json.Int(o, "height", 720),
                Fps = Json.Int(o, "fps", 60),
            };
            if (o.Has("formats")) foreach (var f in o.Get("formats").AsArray()) capture.Formats.Add(f.AsString());
            return capture;
        }
    }

    public sealed class ReplayRequest
    {
        public string Schema = "gdw.replay.request/1";
        public string Op;
        public string RunId;
        public string ReplayPath;
        public string Scene;
        public uint Seed;
        public Rational FixedDt = new Rational(1, 60);
        public List<string> Subjects = new List<string>();
        public ReplayCaptureOptions Capture;

        internal JsonValue ToJson()
        {
            var subjects = new List<JsonValue>();
            foreach (var s in Subjects) subjects.Add(Json.String(s));
            var o = Json.Obj();
            Json.Set(o, "schema", Json.String(Schema));
            Json.Set(o, "op", Json.String(Op));
            Json.Set(o, "run_id", Json.String(RunId));
            Json.Set(o, "replay_path", Json.String(ReplayPath));
            Json.Set(o, "scene", Json.String(Scene));
            Json.Set(o, "seed", Json.Number((long)Seed));
            var fixedDt = Json.Obj();
            Json.Set(fixedDt, "num", Json.Number(FixedDt.Num));
            Json.Set(fixedDt, "den", Json.Number(FixedDt.Den));
            Json.Set(o, "fixed_dt", Json.Object(fixedDt));
            Json.Set(o, "subjects", Json.Array(subjects));
            Json.Set(o, "capture", Capture != null ? Capture.ToJson() : Json.Null);
            return Json.Object(o);
        }

        internal static ReplayRequest FromJson(JsonValue v)
        {
            var o = v;
            var request = new ReplayRequest
            {
                Schema = Json.Str(o, "schema", "gdw.replay.request/1"),
                Op = Json.Str(o, "op"),
                RunId = Json.Str(o, "run_id"),
                ReplayPath = Json.Str(o, "replay_path"),
                Scene = Json.Str(o, "scene"),
                Seed = Json.UInt(o, "seed"),
            };
            if (o.Has("fixed_dt"))
            {
                var f = o.Get("fixed_dt");
                request.FixedDt = new Rational(Json.Int(f, "num", 1), Json.Int(f, "den", 1));
            }
            if (o.Has("subjects")) foreach (var s in o.Get("subjects").AsArray()) request.Subjects.Add(s.AsString());
            if (o.Has("capture") && o.Get("capture").Kind == JsonKind.Object) request.Capture = ReplayCaptureOptions.FromJson(o.Get("capture"));
            return request;
        }
    }

    public sealed class ReplayExpectedCompared
    {
        public long Expected;
        public long Compared;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "expected", Json.Number(Expected));
            Json.Set(o, "compared", Json.Number(Compared));
            return Json.Object(o);
        }

        internal static ReplayExpectedCompared FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayExpectedCompared { Expected = Json.Long(o, "expected"), Compared = Json.Long(o, "compared") };
        }
    }

    public sealed class ReplayNearbyMarker
    {
        public long Frame;
        public long Tick;
        public string Label;

        internal JsonValue ToJson()
        {
            var o = Json.Obj();
            Json.Set(o, "frame", Json.Number(Frame));
            Json.Set(o, "tick", Json.Number(Tick));
            Json.Set(o, "label", Json.String(Label));
            return Json.Object(o);
        }

        internal static ReplayNearbyMarker FromJson(JsonValue v)
        {
            var o = v;
            return new ReplayNearbyMarker { Frame = Json.Long(o, "frame"), Tick = Json.Long(o, "tick"), Label = Json.Str(o, "label") };
        }
    }

    public sealed class ReplayArtifacts
    {
        public string Archive;
        public string Report;
        public string ResultsXml;
        public string EditorLog;
        public string CaptureDir;
        public List<string> Exports = new List<string>();

        internal JsonValue ToJson()
        {
            var exports = new List<JsonValue>();
            foreach (var e in Exports) exports.Add(Json.String(e));
            var o = Json.Obj();
            Json.Set(o, "archive", Json.String(Archive));
            Json.Set(o, "report", Json.String(Report));
            Json.Set(o, "results_xml", Json.String(ResultsXml));
            Json.Set(o, "editor_log", Json.String(EditorLog));
            Json.Set(o, "capture_dir", Json.String(CaptureDir));
            Json.Set(o, "exports", Json.Array(exports));
            return Json.Object(o);
        }

        internal static ReplayArtifacts FromJson(JsonValue v)
        {
            var o = v;
            var artifacts = new ReplayArtifacts
            {
                Archive = Json.Str(o, "archive"),
                Report = Json.Str(o, "report"),
                ResultsXml = Json.Str(o, "results_xml"),
                EditorLog = Json.Str(o, "editor_log"),
                CaptureDir = Json.Str(o, "capture_dir"),
            };
            if (o.Has("exports")) foreach (var e in o.Get("exports").AsArray()) artifacts.Exports.Add(e.AsString());
            return artifacts;
        }
    }

    public sealed class ReplayReport
    {
        public string Schema = "gdw.replay.report/1";
        public string RunId;
        public string RequestDigest;
        public string ReplaySha256;
        public string HeaderSha256;
        public string LogSha256;
        public string ContentSha256;
        public string Route;
        public string Status;
        public string Environment = "matched";
        public List<string> EnvironmentDiff = new List<string>();
        public ReplayExpectedCompared Frames = new ReplayExpectedCompared();
        public ReplayExpectedCompared Ticks = new ReplayExpectedCompared();
        public long? FirstDivergentFrame;
        public long? FirstDivergentTick;
        public string ProviderId;
        public string ExpectedHash;
        public string ActualHash;
        public List<string> MissingProviderIds = new List<string>();
        public List<string> ExtraProviderIds = new List<string>();
        public List<ReplayNearbyMarker> NearbyMarkers = new List<ReplayNearbyMarker>();
        public ReplayConsoleCounts Console = new ReplayConsoleCounts();
        public ReplayArtifacts Artifacts = new ReplayArtifacts();
        public string Message;
        public string StartedUtc;
        public string EndedUtc;

        internal JsonValue ToJson()
        {
            var diff = new List<JsonValue>();
            foreach (var d in EnvironmentDiff) diff.Add(Json.String(d));
            var missing = new List<JsonValue>();
            foreach (var d in MissingProviderIds) missing.Add(Json.String(d));
            var extra = new List<JsonValue>();
            foreach (var d in ExtraProviderIds) extra.Add(Json.String(d));
            var nearby = new List<JsonValue>();
            foreach (var d in NearbyMarkers) nearby.Add(d.ToJson());

            var o = Json.Obj();
            Json.Set(o, "schema", Json.String(Schema));
            Json.Set(o, "run_id", Json.String(RunId));
            Json.Set(o, "request_digest", Json.String(RequestDigest));
            Json.Set(o, "replay_sha256", Json.String(ReplaySha256));
            Json.Set(o, "header_sha256", Json.String(HeaderSha256));
            Json.Set(o, "log_sha256", Json.String(LogSha256));
            Json.Set(o, "content_sha256", Json.String(ContentSha256));
            Json.Set(o, "route", Json.String(Route));
            Json.Set(o, "status", Json.String(Status));
            Json.Set(o, "environment", Json.String(Environment));
            Json.Set(o, "environment_diff", Json.Array(diff));
            Json.Set(o, "frames", Frames.ToJson());
            Json.Set(o, "ticks", Ticks.ToJson());
            Json.Set(o, "first_divergent_frame", FirstDivergentFrame.HasValue ? Json.Number(FirstDivergentFrame.Value) : Json.Null);
            Json.Set(o, "first_divergent_tick", FirstDivergentTick.HasValue ? Json.Number(FirstDivergentTick.Value) : Json.Null);
            Json.Set(o, "provider_id", ProviderId != null ? Json.String(ProviderId) : Json.Null);
            Json.Set(o, "expected_hash", ExpectedHash != null ? Json.String(ExpectedHash) : Json.Null);
            Json.Set(o, "actual_hash", ActualHash != null ? Json.String(ActualHash) : Json.Null);
            Json.Set(o, "missing_provider_ids", Json.Array(missing));
            Json.Set(o, "extra_provider_ids", Json.Array(extra));
            Json.Set(o, "nearby_markers", Json.Array(nearby));
            Json.Set(o, "console", Console.ToJson());
            Json.Set(o, "artifacts", Artifacts.ToJson());
            Json.Set(o, "message", Json.String(Message));
            Json.Set(o, "started_utc", Json.String(StartedUtc));
            Json.Set(o, "ended_utc", Json.String(EndedUtc));
            return Json.Object(o);
        }

        internal static ReplayReport FromJson(JsonValue v)
        {
            var o = v;
            var report = new ReplayReport
            {
                Schema = Json.Str(o, "schema", "gdw.replay.report/1"),
                RunId = Json.Str(o, "run_id"),
                RequestDigest = Json.Str(o, "request_digest"),
                ReplaySha256 = Json.Str(o, "replay_sha256"),
                HeaderSha256 = Json.Str(o, "header_sha256"),
                LogSha256 = Json.Str(o, "log_sha256"),
                ContentSha256 = Json.Str(o, "content_sha256"),
                Route = Json.Str(o, "route"),
                Status = Json.Str(o, "status"),
                Environment = Json.Str(o, "environment", "matched"),
                Frames = o.Has("frames") ? ReplayExpectedCompared.FromJson(o.Get("frames")) : new ReplayExpectedCompared(),
                Ticks = o.Has("ticks") ? ReplayExpectedCompared.FromJson(o.Get("ticks")) : new ReplayExpectedCompared(),
                ProviderId = Json.Str(o, "provider_id"),
                ExpectedHash = Json.Str(o, "expected_hash"),
                ActualHash = Json.Str(o, "actual_hash"),
                Console = o.Has("console") ? ReplayConsoleCounts.FromJson(o.Get("console")) : new ReplayConsoleCounts(),
                Artifacts = o.Has("artifacts") ? ReplayArtifacts.FromJson(o.Get("artifacts")) : new ReplayArtifacts(),
                Message = Json.Str(o, "message"),
                StartedUtc = Json.Str(o, "started_utc"),
                EndedUtc = Json.Str(o, "ended_utc"),
            };
            if (o.Has("first_divergent_frame") && o.Get("first_divergent_frame").Kind == JsonKind.Number)
                report.FirstDivergentFrame = o.Get("first_divergent_frame").AsLong();
            if (o.Has("first_divergent_tick") && o.Get("first_divergent_tick").Kind == JsonKind.Number)
                report.FirstDivergentTick = o.Get("first_divergent_tick").AsLong();
            if (o.Has("environment_diff")) foreach (var d in o.Get("environment_diff").AsArray()) report.EnvironmentDiff.Add(d.AsString());
            if (o.Has("missing_provider_ids")) foreach (var d in o.Get("missing_provider_ids").AsArray()) report.MissingProviderIds.Add(d.AsString());
            if (o.Has("extra_provider_ids")) foreach (var d in o.Get("extra_provider_ids").AsArray()) report.ExtraProviderIds.Add(d.AsString());
            if (o.Has("nearby_markers")) foreach (var d in o.Get("nearby_markers").AsArray()) report.NearbyMarkers.Add(ReplayNearbyMarker.FromJson(d));
            return report;
        }
    }

    /// <summary>
    /// Runtime-only interface for the input adapter. The InputSystem assembly implements this;
    /// the Runtime assembly never references Unity.InputSystem directly.
    /// Register via <see cref="ReplayInput.Factory"/> before calling BeginRecord/BeginReplay.
    /// </summary>
    public interface IReplayInputAdapter : IDisposable
    {
        void StartCapture();
        void StartReplay();
        byte[] GetTraceBytes();
        void SetTrace(byte[] traceBytes);
        bool Overflowed { get; }
        long EventCount { get; }
    }

    /// <summary>
    /// Static factory hook that keeps Gdw.Replay.Runtime free of the Unity.InputSystem dependency.
    /// Set <see cref="Factory"/> from the Editor assembly (or the InputSystem assembly) before
    /// starting a record or replay session.
    /// </summary>
    public static class ReplayInput
    {
        /// <summary>Factory: (runDirectory, maxTraceMb) -> IReplayInputAdapter. Set once at startup.</summary>
        public static Func<string, int, IReplayInputAdapter> Factory { get; set; }

        /// <summary>True when a factory is registered.</summary>
        public static bool IsAvailable => Factory != null;

        /// <summary>Creates an adapter via the registered factory.</summary>
        public static IReplayInputAdapter Create(string runDirectory, int maxTraceMb = 256)
        {
            if (Factory == null)
                throw new ReplayStateException(
                    "Input System adapter is not registered. " +
                    "Ensure Gdw.Replay.InputSystem is present and ReplayCommands has set ReplayInput.Factory.");
            return Factory(runDirectory, maxTraceMb);
        }
    }

    public static class ReplayContracts
    {
        public static ReplayRequest ReadRequest(string path)
        {
            if (path == null) throw new ArgumentNullException(nameof(path));
            return ReplayRequest.FromJson(ParseFile(path, "request.json"));
        }

        public static ReplayReport ReadReport(string path)
        {
            if (path == null) throw new ArgumentNullException(nameof(path));
            return ReplayReport.FromJson(ParseFile(path, "report.json"));
        }

        internal static JsonValue ParseFile(string path, string member)
        {
            try
            {
                return Json.Parse(File.ReadAllText(path, Encoding.UTF8));
            }
            catch (Exception e) when (e is IOException || e is FormatException || e is InvalidOperationException)
            {
                throw new ReplayCompatibilityException("cannot parse " + member + ": " + e.Message, e);
            }
        }
    }
}
