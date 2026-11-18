using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace Gdw.Replay
{
    /// <summary>
    /// Reads and writes the v1 .gdwreplay ZIP. <see cref="Write"/> stages a temp file and moves it
    /// into place atomically; <see cref="Read"/> validates size, entry, ratio and digest limits.
    /// </summary>
    public sealed class ReplayArchive
    {
        const int MaxEntries = 64;
        const long MaxArchiveBytes = 512L * 1024 * 1024;
        const long MaxMemberBytes = 256L * 1024 * 1024;
        const long MaxHeaderBytes = 1024 * 1024;
        const long MaxCompressionRatio = 200;

        public string Path;
        public string Sha256;
        public ReplayHeader Header;
        public List<ReplayFrame> Frames;
        public List<ReplayMarker> Markers;
        public ReplayManifest Manifest;
        public byte[] InputTrace;
        public long InputTraceSize;
        public long UncompressedSize;

        ReplayArchive() { }

        public static void Write(string path, ReplayHeader header, IEnumerable<ReplayFrame> frames, IEnumerable<ReplayMarker> markers, byte[] inputTrace, ReplayManifest manifest)
        {
            if (path == null) throw new ArgumentNullException(nameof(path));
            if (header == null) throw new ArgumentNullException(nameof(header));
            if (frames == null) throw new ArgumentNullException(nameof(frames));
            if (markers == null) throw new ArgumentNullException(nameof(markers));
            inputTrace = inputTrace ?? new byte[0];
            if (manifest == null) throw new ArgumentNullException(nameof(manifest));

            byte[] headerBytes = Digest.Utf8(Json.Serialize(header.ToJson()));
            if (headerBytes.LongLength > MaxHeaderBytes) throw new ReplayStateException("header too large");

            var frameList = frames as List<ReplayFrame> ?? new List<ReplayFrame>(frames);
            var markerList = markers as List<ReplayMarker> ?? new List<ReplayMarker>(markers);
            byte[] framesBytes = WriteLines(frameList);
            byte[] markersBytes = WriteLines(markerList);

            manifest.Files = new List<ReplayManifestFile>
            {
                new ReplayManifestFile { Name = "header.json", Bytes = headerBytes.LongLength, Sha256 = Digest.Sha256Hex(headerBytes) },
                new ReplayManifestFile { Name = "input.inputtrace", Bytes = inputTrace.LongLength, Sha256 = Digest.Sha256Hex(inputTrace) },
                new ReplayManifestFile { Name = "frames.jsonl", Bytes = framesBytes.LongLength, Sha256 = Digest.Sha256Hex(framesBytes) },
                new ReplayManifestFile { Name = "markers.jsonl", Bytes = markersBytes.LongLength, Sha256 = Digest.Sha256Hex(markersBytes) },
            };
            byte[] manifestBytes = Digest.Utf8(Json.Serialize(manifest.ToJson()));

            string fullPath = System.IO.Path.GetFullPath(path);
            string dir = System.IO.Path.GetDirectoryName(fullPath);
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            string tmp = fullPath + ".tmp." + Guid.NewGuid().ToString("N");
            try
            {
                using (var fs = new FileStream(tmp, FileMode.CreateNew, FileAccess.Write))
                using (var zip = new ZipArchive(fs, ZipArchiveMode.Create, false))
                {
                    WriteEntry(zip, "header.json", headerBytes);
                    WriteEntry(zip, "input.inputtrace", inputTrace);
                    WriteEntry(zip, "frames.jsonl", framesBytes);
                    WriteEntry(zip, "markers.jsonl", markersBytes);
                    WriteEntry(zip, "manifest.json", manifestBytes);
                }
                File.Move(tmp, fullPath);
            }
            catch
            {
                if (File.Exists(tmp)) File.Delete(tmp);
                throw;
            }
        }

        static byte[] WriteLines<T>(List<T> items) where T : class
        {
            var sb = new StringBuilder();
            for (int i = 0; i < items.Count; i++)
            {
                var frame = items[i] as ReplayFrame;
                if (frame != null) sb.Append(Json.Serialize(frame.ToJson()));
                else { var marker = items[i] as ReplayMarker; if (marker != null) sb.Append(Json.Serialize(marker.ToJson())); }
                sb.Append('\n');
            }
            return Digest.Utf8(sb.ToString());
        }

        static void WriteEntry(ZipArchive zip, string name, byte[] bytes)
        {
            var entry = zip.CreateEntry(name, CompressionLevel.Optimal);
            using (var stream = entry.Open())
            {
                stream.Write(bytes, 0, bytes.Length);
            }
        }

        public static ReplayArchive Read(string path, int maxBytes = 536870912)
        {
            if (path == null) throw new ArgumentNullException(nameof(path));
            if (maxBytes <= 0 || (long)maxBytes > MaxArchiveBytes) throw new ReplayStateException("invalid maxBytes");

            var info = new FileInfo(path);
            if (!info.Exists) throw new FileNotFoundException("archive not found", path);
            if (info.Length > maxBytes || info.Length > MaxArchiveBytes) throw new ReplayCompatibilityException("archive too large");

            byte[] archiveBytes = File.ReadAllBytes(path);
            string sha256 = Digest.Sha256Hex(archiveBytes);

            ReplayHeader header = null;
            var frames = new List<ReplayFrame>();
            var markers = new List<ReplayMarker>();
            ReplayManifest manifest = null;
            byte[] inputTrace = new byte[0];
            byte[] headerRaw = null;
            byte[] framesRaw = null;
            byte[] markersRaw = null;
            long uncompressed = 0;
            var seen = new HashSet<string>(StringComparer.Ordinal);

            using (var ms = new MemoryStream(archiveBytes, false))
            using (var zip = new ZipArchive(ms, ZipArchiveMode.Read, false))
            {
                if (zip.Entries.Count > MaxEntries) throw new ReplayCompatibilityException("too many archive entries");
                foreach (var entry in zip.Entries)
                {
                    ValidateEntryName(entry.FullName);
                    if (!seen.Add(entry.FullName)) throw new ReplayCompatibilityException("duplicate archive entry: " + entry.FullName);
                    if (entry.Length > MaxMemberBytes) throw new ReplayCompatibilityException("archive entry too large: " + entry.FullName);
                    if (entry.Length > 0 && entry.CompressedLength > 0 && entry.Length > entry.CompressedLength * MaxCompressionRatio)
                        throw new ReplayCompatibilityException("compression ratio too high: " + entry.FullName);

                    byte[] bytes = ReadEntry(entry);
                    uncompressed += bytes.LongLength;
                    if (uncompressed > MaxArchiveBytes) throw new ReplayCompatibilityException("uncompressed archive too large");

                    switch (entry.FullName)
                    {
                        case "header.json":
                            if (bytes.LongLength > MaxHeaderBytes) throw new ReplayCompatibilityException("header too large");
                            headerRaw = bytes;
                            header = ReplayHeader.FromJson(ParseJson(bytes, "header.json"));
                            break;
                        case "input.inputtrace":
                            inputTrace = bytes;
                            break;
                        case "frames.jsonl":
                            framesRaw = bytes;
                            frames = ParseFrames(bytes);
                            break;
                        case "markers.jsonl":
                            markersRaw = bytes;
                            markers = ParseMarkers(bytes);
                            break;
                        case "manifest.json":
                            manifest = ReplayManifest.FromJson(ParseJson(bytes, "manifest.json"));
                            break;
                        default:
                            throw new ReplayCompatibilityException("unexpected archive entry: " + entry.FullName);
                    }
                }
            }

            if (header == null) throw new ReplayCompatibilityException("missing header.json");
            if (manifest == null) throw new ReplayCompatibilityException("missing manifest.json (incomplete archive)");

            VerifyManifest(manifest, headerRaw, framesRaw, markersRaw, inputTrace);

            return new ReplayArchive
            {
                Path = System.IO.Path.GetFullPath(path),
                Sha256 = sha256,
                Header = header,
                Frames = frames,
                Markers = markers,
                Manifest = manifest,
                InputTrace = inputTrace,
                InputTraceSize = inputTrace.LongLength,
                UncompressedSize = uncompressed,
            };
        }

        static void ValidateEntryName(string name)
        {
            if (string.IsNullOrEmpty(name)) throw new ReplayCompatibilityException("empty archive entry");
            if (name.IndexOf('/') >= 0 || name.IndexOf('\\') >= 0 || name.IndexOf("..", StringComparison.Ordinal) >= 0 || name.StartsWith(".", StringComparison.Ordinal))
                throw new ReplayCompatibilityException("unsafe archive entry: " + name);
        }

        static byte[] ReadEntry(ZipArchiveEntry entry)
        {
            if (entry.Length > int.MaxValue) throw new ReplayCompatibilityException("archive entry too large: " + entry.FullName);
            var bytes = new byte[(int)entry.Length];
            using (var stream = entry.Open())
            {
                int offset = 0;
                while (offset < bytes.Length)
                {
                    int read = stream.Read(bytes, offset, bytes.Length - offset);
                    if (read <= 0) throw new ReplayCompatibilityException("truncated archive entry: " + entry.FullName);
                    offset += read;
                }
            }
            return bytes;
        }

        static JsonValue ParseJson(byte[] bytes, string member)
        {
            try { return Json.Parse(Encoding.UTF8.GetString(bytes)); }
            catch (Exception e) when (e is FormatException || e is InvalidOperationException)
            {
                throw new ReplayCompatibilityException("invalid JSON in " + member + ": " + e.Message, e);
            }
        }

        static List<ReplayFrame> ParseFrames(byte[] bytes)
        {
            var frames = new List<ReplayFrame>();
            string text = Encoding.UTF8.GetString(bytes);
            int start = 0;
            while (start < text.Length)
            {
                int nl = text.IndexOf('\n', start);
                int end = nl < 0 ? text.Length : nl;
                string line = text.Substring(start, end - start);
                if (line.Length > 0) frames.Add(ReplayFrame.FromJson(Json.Parse(line)));
                start = end + 1;
            }
            return frames;
        }

        static List<ReplayMarker> ParseMarkers(byte[] bytes)
        {
            var markers = new List<ReplayMarker>();
            string text = Encoding.UTF8.GetString(bytes);
            int start = 0;
            while (start < text.Length)
            {
                int nl = text.IndexOf('\n', start);
                int end = nl < 0 ? text.Length : nl;
                string line = text.Substring(start, end - start);
                if (line.Length > 0) markers.Add(ReplayMarker.FromJson(Json.Parse(line)));
                start = end + 1;
            }
            return markers;
        }

        static void VerifyManifest(ReplayManifest manifest, byte[] headerBytes, byte[] framesBytes, byte[] markersBytes, byte[] inputTrace)
        {
            if (manifest.Files == null || manifest.Files.Count == 0) return;
            var expected = new Dictionary<string, ReplayManifestFile>(StringComparer.Ordinal);
            foreach (var f in manifest.Files)
            {
                if (!expected.ContainsKey(f.Name)) expected.Add(f.Name, f);
            }
            var actual = new Dictionary<string, byte[]>(StringComparer.Ordinal)
            {
                ["header.json"] = headerBytes ?? new byte[0],
                ["input.inputtrace"] = inputTrace,
                ["frames.jsonl"] = framesBytes ?? new byte[0],
                ["markers.jsonl"] = markersBytes ?? new byte[0],
            };
            foreach (var kv in actual)
            {
                if (!expected.TryGetValue(kv.Key, out var file))
                    throw new ReplayCompatibilityException("manifest missing file entry: " + kv.Key);
                if (file.Bytes != kv.Value.LongLength || file.Sha256 != Digest.Sha256Hex(kv.Value))
                    throw new ReplayCompatibilityException("manifest digest mismatch for: " + kv.Key);
            }
        }
    }
}
