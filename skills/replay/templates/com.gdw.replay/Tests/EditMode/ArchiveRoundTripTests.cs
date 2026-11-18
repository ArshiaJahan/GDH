using System;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;

namespace Gdw.Replay.Tests
{
    /// <summary>
    /// Verifies that a v1 .gdwreplay ZIP written by <see cref="ReplayArchive.Write"/> round-trips
    /// through <see cref="ReplayArchive.Read"/>, including the full header, frames, markers and
    /// input trace with manifest digest verification.
    /// </summary>
    public class ArchiveRoundTripTests
    {
        string _path;

        [SetUp]
        public void SetUp()
        {
            _path = Path.Combine(Path.GetTempPath(), "gdw_replay_test_" + Guid.NewGuid().ToString("N") + ".gdwreplay");
        }

        [TearDown]
        public void TearDown()
        {
            if (File.Exists(_path)) File.Delete(_path);
        }

        static ReplayHeader BuildHeader()
        {
            var header = new ReplayHeader
            {
                RunId = "test-run-123",
                CreatedUtc = "2026-11-18T00:00:00Z",
                Seed = 42,
            };
            header.Unity.Version = "6000.3.0f1";
            header.Scene.Guid = "0123456789abcdef0123456789abcdef";
            header.Scene.Path = "Assets/Scenes/Main.unity";
            header.StateHash.Algorithm = "sha256";
            header.StateHash.Encoding = "hex";
            return header;
        }

        [Test]
        public void WriteThenRead_RoundTripsAllMembers()
        {
            var header = BuildHeader();
            var frames = new List<ReplayFrame>
            {
                new ReplayFrame { Frame = 0, Tick = 0, FixedTicks = 1, Hash = "h0" },
                new ReplayFrame { Frame = 1, Tick = 1, FixedTicks = 0, InputUpdate = true, EventStart = 0, EventCount = 2, Hash = "h1" },
            };
            var markers = new List<ReplayMarker>
            {
                new ReplayMarker { Frame = 1, Tick = 1, Label = "boom", Data = "{\"hp\":0}" },
            };
            var manifest = new ReplayManifest
            {
                Format = "gdwreplay-manifest",
                Version = 1,
                Complete = true,
                Frames = frames.Count,
                Ticks = 1,
                ToolVersion = "0.1.0",
            };
            var inputTrace = new byte[] { 0x01, 0x02, 0x03, 0x04 };

            ReplayArchive.Write(_path, header, frames, markers, inputTrace, manifest);

            var read = ReplayArchive.Read(_path);

            Assert.AreEqual(header.RunId, read.Header.RunId);
            Assert.AreEqual(header.Seed, read.Header.Seed);
            Assert.AreEqual("Assets/Scenes/Main.unity", read.Header.Scene.Path);
            Assert.AreEqual("0123456789abcdef0123456789abcdef", read.Header.Scene.Guid);
            Assert.AreEqual("6000.3.0f1", read.Header.Unity.Version);
            Assert.AreEqual("sha256", read.Header.StateHash.Algorithm);

            Assert.AreEqual(2, read.Frames.Count);
            Assert.AreEqual(0, read.Frames[0].Frame);
            Assert.AreEqual(true, read.Frames[1].InputUpdate);
            Assert.AreEqual("h1", read.Frames[1].Hash);

            Assert.AreEqual(1, read.Markers.Count);
            Assert.AreEqual("boom", read.Markers[0].Label);

            Assert.AreEqual(inputTrace.Length, read.InputTraceSize);
            Assert.AreEqual(4, read.Manifest.Files.Count);
            Assert.IsFalse(string.IsNullOrEmpty(read.Sha256));
            Assert.AreEqual(System.IO.Path.GetFullPath(_path), read.Path);
        }
    }
}
