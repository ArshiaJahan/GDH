using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Gdw.Replay
{
    internal enum JsonKind { Null, Bool, Number, String, Array, Object }

    internal sealed class JsonValue
    {
        public JsonKind Kind { get; }
        public bool BoolValue { get; }
        public double NumberValue { get; }
        public string NumberText { get; }
        public string StringValue { get; }
        public List<JsonValue> ArrayValue { get; }
        public Dictionary<string, JsonValue> ObjectValue { get; }

        internal JsonValue(JsonKind kind, bool b, double num, string numText, string s, List<JsonValue> arr, Dictionary<string, JsonValue> obj)
        {
            Kind = kind; BoolValue = b; NumberValue = num; NumberText = numText; StringValue = s; ArrayValue = arr; ObjectValue = obj;
        }

        public static JsonValue Null => new JsonValue(JsonKind.Null, false, 0, null, null, null, null);
        public static JsonValue Bool(bool v) => new JsonValue(JsonKind.Bool, v, 0, null, null, null, null);
        public static JsonValue Number(long v) => new JsonValue(JsonKind.Number, false, v, v.ToString(CultureInfo.InvariantCulture), null, null, null);
        public static JsonValue Number(double v) => new JsonValue(JsonKind.Number, false, v, null, null, null, null);
        public static JsonValue String(string v) => new JsonValue(JsonKind.String, false, 0, null, v, null, null);
        public static JsonValue Array(List<JsonValue> v) => new JsonValue(JsonKind.Array, false, 0, null, null, v, null);
        public static JsonValue Object(Dictionary<string, JsonValue> v) => new JsonValue(JsonKind.Object, false, 0, null, null, null, v);

        public bool IsNumber => Kind == JsonKind.Number;

        public long AsLong()
        {
            if (Kind != JsonKind.Number) throw new InvalidOperationException("JSON value is not a number");
            return NumberText != null ? long.Parse(NumberText, CultureInfo.InvariantCulture) : (long)NumberValue;
        }

        public int AsInt() => (int)AsLong();

        public uint AsUInt()
        {
            if (Kind != JsonKind.Number) throw new InvalidOperationException("JSON value is not a number");
            return NumberText != null ? uint.Parse(NumberText, CultureInfo.InvariantCulture) : (uint)AsLong();
        }

        public ulong AsULong()
        {
            if (Kind != JsonKind.Number) throw new InvalidOperationException("JSON value is not a number");
            return NumberText != null ? ulong.Parse(NumberText, CultureInfo.InvariantCulture) : (ulong)AsLong();
        }

        public double AsDouble()
        {
            if (Kind != JsonKind.Number) throw new InvalidOperationException("JSON value is not a number");
            return NumberValue;
        }

        public bool AsBool()
        {
            if (Kind != JsonKind.Bool) throw new InvalidOperationException("JSON value is not a bool");
            return BoolValue;
        }

        public string AsString()
        {
            if (Kind != JsonKind.String) throw new InvalidOperationException("JSON value is not a string");
            return StringValue;
        }

        public List<JsonValue> AsArray()
        {
            if (Kind != JsonKind.Array) throw new InvalidOperationException("JSON value is not an array");
            return ArrayValue;
        }

        public Dictionary<string, JsonValue> AsObject()
        {
            if (Kind != JsonKind.Object) throw new InvalidOperationException("JSON value is not an object");
            return ObjectValue;
        }

        public JsonValue Get(string key) => ObjectValue != null && ObjectValue.TryGetValue(key, out var v) ? v : Null;

        public bool Has(string key) => ObjectValue != null && ObjectValue.ContainsKey(key);
    }

    /// <summary>Minimal, deterministic UTF-8 JSON reader/writer used by the archive and request/report DTOs.</summary>
    internal static class Json
    {
        public static string Serialize(JsonValue value)
        {
            var sb = new StringBuilder();
            Write(sb, value);
            return sb.ToString();
        }

        static void Write(StringBuilder sb, JsonValue v)
        {
            switch (v.Kind)
            {
                case JsonKind.Null: sb.Append("null"); break;
                case JsonKind.Bool: sb.Append(v.BoolValue ? "true" : "false"); break;
                case JsonKind.Number:
                    if (v.NumberText != null) sb.Append(v.NumberText);
                    else sb.Append(v.NumberValue.ToString("R", CultureInfo.InvariantCulture));
                    break;
                case JsonKind.String: WriteString(sb, v.StringValue); break;
                case JsonKind.Array:
                    sb.Append('[');
                    for (int i = 0; i < v.ArrayValue.Count; i++)
                    {
                        if (i > 0) sb.Append(',');
                        Write(sb, v.ArrayValue[i]);
                    }
                    sb.Append(']');
                    break;
                case JsonKind.Object:
                    sb.Append('{');
                    bool first = true;
                    foreach (var kv in v.ObjectValue)
                    {
                        if (!first) sb.Append(',');
                        first = false;
                        WriteString(sb, kv.Key);
                        sb.Append(':');
                        Write(sb, kv.Value);
                    }
                    sb.Append('}');
                    break;
            }
        }

        static void WriteString(StringBuilder sb, string s)
        {
            sb.Append('"');
            if (s != null)
            {
                foreach (char c in s)
                {
                    switch (c)
                    {
                        case '"': sb.Append("\\\""); break;
                        case '\\': sb.Append("\\\\"); break;
                        case '\b': sb.Append("\\b"); break;
                        case '\f': sb.Append("\\f"); break;
                        case '\n': sb.Append("\\n"); break;
                        case '\r': sb.Append("\\r"); break;
                        case '\t': sb.Append("\\t"); break;
                        default:
                            if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                            else sb.Append(c);
                            break;
                    }
                }
            }
            sb.Append('"');
        }

        public static JsonValue Parse(string text)
        {
            if (text == null) throw new ArgumentNullException(nameof(text));
            int i = 0;
            var value = ParseValue(text, ref i);
            SkipWhitespace(text, ref i);
            if (i != text.Length) throw new FormatException("trailing characters in JSON");
            return value;
        }

        static void SkipWhitespace(string s, ref int i)
        {
            while (i < s.Length && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r')) i++;
        }

        static JsonValue ParseValue(string s, ref int i)
        {
            SkipWhitespace(s, ref i);
            if (i >= s.Length) throw new FormatException("unexpected end of JSON");
            char c = s[i];
            switch (c)
            {
                case '{': return ParseObject(s, ref i);
                case '[': return ParseArray(s, ref i);
                case '"': return Json.String(ParseString(s, ref i));
                case 't': Expect(s, ref i, "true"); return Json.Bool(true);
                case 'f': Expect(s, ref i, "false"); return Json.Bool(false);
                case 'n': Expect(s, ref i, "null"); return Json.Null;
                default: return ParseNumber(s, ref i);
            }
        }

        static void Expect(string s, ref int i, string word)
        {
            if (i + word.Length > s.Length || string.CompareOrdinal(s, i, word, 0, word.Length) != 0)
                throw new FormatException("invalid JSON literal");
            i += word.Length;
        }

        static JsonValue ParseObject(string s, ref int i)
        {
            i++; // '{'
            var obj = new Dictionary<string, JsonValue>(StringComparer.Ordinal);
            SkipWhitespace(s, ref i);
            if (i < s.Length && s[i] == '}') { i++; return Json.Object(obj); }
            while (true)
            {
                SkipWhitespace(s, ref i);
                if (i >= s.Length || s[i] != '"') throw new FormatException("expected object key");
                string key = ParseString(s, ref i);
                SkipWhitespace(s, ref i);
                if (i >= s.Length || s[i] != ':') throw new FormatException("expected ':'");
                i++;
                obj[key] = ParseValue(s, ref i);
                SkipWhitespace(s, ref i);
                if (i < s.Length && s[i] == ',') { i++; continue; }
                if (i < s.Length && s[i] == '}') { i++; return Json.Object(obj); }
                throw new FormatException("expected ',' or '}'");
            }
        }

        static JsonValue ParseArray(string s, ref int i)
        {
            i++; // '['
            var arr = new List<JsonValue>();
            SkipWhitespace(s, ref i);
            if (i < s.Length && s[i] == ']') { i++; return Json.Array(arr); }
            while (true)
            {
                arr.Add(ParseValue(s, ref i));
                SkipWhitespace(s, ref i);
                if (i < s.Length && s[i] == ',') { i++; continue; }
                if (i < s.Length && s[i] == ']') { i++; return Json.Array(arr); }
                throw new FormatException("expected ',' or ']'");
            }
        }

        static string ParseString(string s, ref int i)
        {
            i++; // opening quote
            var sb = new StringBuilder();
            while (i < s.Length)
            {
                char c = s[i];
                if (c == '"') { i++; return sb.ToString(); }
                if (c == '\\')
                {
                    i++;
                    if (i >= s.Length) throw new FormatException("bad string escape");
                    char e = s[i++];
                    switch (e)
                    {
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'u':
                            if (i + 4 > s.Length) throw new FormatException("bad unicode escape");
                            sb.Append((char)Convert.ToInt32(s.Substring(i, 4), 16));
                            i += 4;
                            break;
                        default: throw new FormatException("bad string escape");
                    }
                }
                else { sb.Append(c); i++; }
            }
            throw new FormatException("unterminated string");
        }

        static JsonValue ParseNumber(string s, ref int i)
        {
            int start = i;
            if (i < s.Length && (s[i] == '-' || s[i] == '+')) i++;
            bool integral = true;
            while (i < s.Length && char.IsDigit(s[i])) i++;
            if (i < s.Length && s[i] == '.') { integral = false; i++; while (i < s.Length && char.IsDigit(s[i])) i++; }
            if (i < s.Length && (s[i] == 'e' || s[i] == 'E'))
            {
                integral = false;
                i++;
                if (i < s.Length && (s[i] == '-' || s[i] == '+')) i++;
                while (i < s.Length && char.IsDigit(s[i])) i++;
            }
            string token = s.Substring(start, i - start);
            if (token.Length == 0) throw new FormatException("invalid number");
            double d = double.Parse(token, NumberStyles.Float, CultureInfo.InvariantCulture);
            if (double.IsNaN(d) || double.IsInfinity(d)) throw new FormatException("non-finite number");
            return integral ? new JsonValue(JsonKind.Number, false, d, token, null, null, null) : Json.Number(d);
        }

        // Factory forwarding (delegate to JsonValue — allows Json.String(...) call syntax).
        public static JsonValue String(string v) => JsonValue.String(v);
        public static JsonValue Number(long v) => JsonValue.Number(v);
        public static JsonValue Number(double v) => JsonValue.Number(v);
        public static JsonValue Bool(bool v) => JsonValue.Bool(v);
        public static JsonValue Null => JsonValue.Null;
        public static JsonValue Object(Dictionary<string, JsonValue> v) => JsonValue.Object(v);
        public static JsonValue Array(List<JsonValue> v) => JsonValue.Array(v);

        // Typed accessors used by DTO mapping.
        public static Dictionary<string, JsonValue> Obj() => new Dictionary<string, JsonValue>(StringComparer.Ordinal);
        public static void Set(Dictionary<string, JsonValue> o, string key, JsonValue v) => o[key] = v;
        public static string Str(JsonValue o, string key, string def = null) => o.Has(key) ? o.Get(key).AsString() : def;
        public static long Long(JsonValue o, string key, long def = 0) => o.Has(key) ? o.Get(key).AsLong() : def;
        public static int Int(JsonValue o, string key, int def = 0) => o.Has(key) ? o.Get(key).AsInt() : def;
        public static uint UInt(JsonValue o, string key, uint def = 0) => o.Has(key) ? o.Get(key).AsUInt() : def;
        public static ulong ULong(JsonValue o, string key, ulong def = 0) => o.Has(key) ? o.Get(key).AsULong() : def;
        public static bool Bool(JsonValue o, string key, bool def = false) => o.Has(key) ? o.Get(key).AsBool() : def;
        public static double Double(JsonValue o, string key, double def = 0) => o.Has(key) ? o.Get(key).AsDouble() : def;
    }
}
