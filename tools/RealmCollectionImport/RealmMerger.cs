using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Realms;
using Realms.Schema;

namespace RealmCollectionImport;

internal sealed record CollectionState(Guid Id, string Name, List<string> Hashes, DateTimeOffset LastModified);
internal sealed record CollectionChange(string Name, string Action, Guid Id, int Before, int After, List<string> AddedHashes, List<string>? RemovedHashes = null);
internal sealed record EditorCollection(Guid Id, string Name, List<string> Hashes);
internal sealed record EditorPlan(string SourceRealmSha256, List<EditorCollection> Collections);
internal sealed record BeatmapDetails(string Title, string Artist, string Difficulty, string Mode, long? BeatmapId, bool Available);
internal sealed record EditorDocument(string SourceRealmSha256, List<EditorCollection> Collections, Dictionary<string, BeatmapDetails> Beatmaps);
internal sealed record TableAudit(int Rows, string Sha256);
internal sealed record RealmAudit(string SchemaSha256, SortedDictionary<string, TableAudit> OtherTables);

internal sealed class ImportReport
{
    public string Status { get; set; } = "preview";
    public string RealmSdk { get; set; } = "20.1.0";
    public string SourceRealmSha256 { get; set; } = "";
    public string CollectionDbSha256 { get; set; } = "";
    public string? EditPlanSha256 { get; set; }
    public int LegacyVersion { get; set; }
    public int CollectionsBefore { get; set; }
    public int CollectionsAfter { get; set; }
    public List<CollectionChange> Changes { get; set; } = [];
    public RealmAudit? PreservedData { get; set; }
    public bool VerifiedAfterReopen { get; set; }
    public string? OutputRealm { get; set; }
    public string? OutputRealmSha256 { get; set; }
}

internal static class RealmMerger
{
    internal static Realm Open(string path, bool readOnly = false) => Realm.GetInstance(
        new RealmConfiguration(path) { IsDynamic = true, IsReadOnly = readOnly, ShouldDeleteIfMigrationNeeded = false });

    internal static IEnumerable<IRealmObjectBase> Objects(Realm realm, string type) =>
        realm.DynamicApi.All(type).AsEnumerable().Cast<IRealmObjectBase>();

    internal static void ValidateSchema(Realm realm)
    {
        var schema = realm.Schema.SingleOrDefault(s => s.Name == "BeatmapCollection")
            ?? throw new InvalidDataException("Realm has no BeatmapCollection schema. Supply a copy made by osu!lazer.");
        var expected = new Dictionary<string, PropertyType>
        {
            ["ID"] = PropertyType.Guid,
            ["Name"] = PropertyType.String,
            ["BeatmapMD5Hashes"] = PropertyType.String | PropertyType.Array,
            ["LastModified"] = PropertyType.Date,
        };
        if (schema.Count != expected.Count || schema.Any(p => !expected.TryGetValue(p.Name, out var type) || (p.Type & ~PropertyType.Nullable) != type)
            || !schema.Single(p => p.Name == "ID").IsPrimaryKey)
            throw new InvalidDataException("Unsupported BeatmapCollection schema. No migration or output will be created.");
    }

    internal static List<CollectionState> Collections(Realm realm) => Objects(realm, "BeatmapCollection")
        .Select(item => new CollectionState(item.DynamicApi.Get<Guid>("ID"),
            item.DynamicApi.Get<string>("Name") ?? throw new InvalidDataException("A collection has a null name."),
            item.DynamicApi.GetList<string>("BeatmapMD5Hashes").ToList(),
            item.DynamicApi.Get<DateTimeOffset>("LastModified"))).ToList();

    internal static ImportReport Process(string path, LegacyFile incoming, bool apply, List<EditorCollection>? replacement = null)
    {
        List<CollectionState> expected;
        var report = new ImportReport { LegacyVersion = incoming.Version };
        Console.Error.WriteLine("Opening the staged Realm and auditing its schema and data…");
        using (var realm = Open(path, readOnly: !apply))
        {
            ValidateSchema(realm);
            var before = Collections(realm);
            expected = before.Select(c => c with { Hashes = c.Hashes.ToList() }).ToList();
            report.CollectionsBefore = before.Count;
            report.PreservedData = DataAudit.Capture(realm);
            foreach (var collection in incoming.Collections)
            {
                var matches = expected.Where(c => c.Name == collection.Name).ToList();
                if (matches.Count > 1)
                    throw new InvalidDataException("Multiple existing collections have an incoming name. Resolve that ambiguity before importing.");
                var old = matches.SingleOrDefault();
                var known = old?.Hashes.ToHashSet(StringComparer.OrdinalIgnoreCase) ?? [];
                var added = collection.Hashes.Where(known.Add).ToList();
                Guid id = old?.Id ?? Guid.NewGuid();
                string action = old == null ? "create" : added.Count == 0 ? "unchanged" : "merge";
                report.Changes.Add(new CollectionChange(collection.Name, action, id, old?.Hashes.Count ?? 0,
                    (old?.Hashes.Count ?? 0) + added.Count, added));
                if (old == null)
                    expected.Add(new CollectionState(id, collection.Name, added.ToList(), DateTimeOffset.UtcNow));
                else if (added.Count != 0)
                {
                    expected.Remove(old);
                    expected.Add(old with { Hashes = [.. old.Hashes, .. added], LastModified = DateTimeOffset.UtcNow });
                }
            }
            if (replacement != null)
            {
                if (replacement.Count > 10_000 || replacement.Any(c => c.Name == null || c.Name.Length > 1024 * 1024 || c.Id == Guid.Empty || c.Hashes == null || c.Hashes.Any(h => h == null || !LegacyCollections.ValidHash(h))))
                    throw new InvalidDataException("Invalid collection edit plan.");
                if (replacement.Select(c => c.Id).Distinct().Count() != replacement.Count || replacement.Select(c => c.Name).Distinct(StringComparer.Ordinal).Count() != replacement.Count)
                    throw new InvalidDataException("The edit plan contains duplicate collection IDs or names.");
                if (replacement.Sum(c => (long)c.Hashes.Count) > 1_000_000)
                    throw new InvalidDataException("Too many collection memberships in the edit plan.");
                expected.Clear();
                report.Changes.Clear();
                foreach (var target in replacement)
                {
                    var old = before.SingleOrDefault(c => c.Id == target.Id);
                    bool unchanged = old != null && old.Name == target.Name && old.Hashes.SequenceEqual(target.Hashes);
                    var state = new CollectionState(target.Id, target.Name, target.Hashes.ToList(), unchanged ? old!.LastModified : DateTimeOffset.UtcNow);
                    expected.Add(state);
                    report.Changes.Add(new CollectionChange(target.Name, old == null ? "create" : unchanged ? "unchanged" : "edit", target.Id,
                        old?.Hashes.Count ?? 0, target.Hashes.Count,
                        target.Hashes.Except(old?.Hashes ?? [], StringComparer.OrdinalIgnoreCase).ToList(),
                        old?.Hashes.Except(target.Hashes, StringComparer.OrdinalIgnoreCase).ToList() ?? []));
                }
                foreach (var old in before.Where(c => replacement.All(target => target.Id != c.Id)))
                    report.Changes.Add(new CollectionChange(old.Name, "delete", old.Id, old.Hashes.Count, 0, [], old.Hashes.ToList()));
            }
            report.CollectionsAfter = expected.Count;
            if (!apply)
                return report;

            using (var transaction = realm.BeginWrite())
            {
                foreach (var change in report.Changes.Where(c => c.Action != "unchanged"))
                {
                    IRealmObjectBase item = change.Action == "create"
                        ? realm.DynamicApi.CreateObject("BeatmapCollection", (Guid?)change.Id)
                        : Objects(realm, "BeatmapCollection").Single(o => o.DynamicApi.Get<Guid>("ID") == change.Id);
                    if (change.Action == "delete")
                    {
                        realm.Remove((IRealmObject)item);
                        continue;
                    }
                    var state = expected.Single(c => c.Id == change.Id);
                    item.DynamicApi.Set("Name", state.Name);
                    var hashes = item.DynamicApi.GetList<string>("BeatmapMD5Hashes");
                    hashes.Clear();
                    foreach (string hash in state.Hashes)
                        hashes.Add(hash);
                    item.DynamicApi.Set("LastModified", state.LastModified);
                }
                VerifyCollections(realm, expected);
                VerifyAudit(report.PreservedData, DataAudit.Capture(realm));
                transaction.Commit();
            }
        }
        Console.Error.WriteLine("Reopening the result and verifying collections and preserved data…");
        using (var reopened = Open(path, readOnly: true))
        {
            ValidateSchema(reopened);
            VerifyCollections(reopened, expected);
            VerifyAudit(report.PreservedData, DataAudit.Capture(reopened));
        }
        report.Status = "merged";
        report.VerifiedAfterReopen = true;
        return report;
    }

    internal static EditorDocument Inspect(string path, string sourceHash)
    {
        using var realm = Open(path, readOnly: true);
        ValidateSchema(realm);
        var collections = Collections(realm).Select(c => new EditorCollection(c.Id, c.Name, c.Hashes)).ToList();
        var maps = new Dictionary<string, BeatmapDetails>(StringComparer.OrdinalIgnoreCase);
        if (realm.Schema.Any(s => s.Name == "Beatmap"))
        {
            foreach (var map in Objects(realm, "Beatmap"))
            {
                string hash = Text(map, "MD5Hash");
                if (!LegacyCollections.ValidHash(hash)) continue;
                var metadata = Related(map, "Metadata");
                var ruleset = Related(map, "Ruleset");
                var set = Related(map, "BeatmapSet");
                bool available = set != null && set.ObjectSchema?.Any(p => p.Name == "DeletePending") == true
                    && !set.DynamicApi.Get<bool>("DeletePending");
                string key = hash.ToLowerInvariant();
                if (available || !maps.ContainsKey(key))
                    maps[key] = new BeatmapDetails(Text(metadata, "Title"), Text(metadata, "Artist"),
                        Text(map, "DifficultyName"), Text(ruleset, "ShortName"), Number(map, "OnlineID"), available);
            }
        }
        return new EditorDocument(sourceHash, collections, maps);
    }

    private static string Text(IRealmObjectBase? item, string property)
    {
        if (item?.ObjectSchema?.Any(p => p.Name == property) != true) return "";
        var value = item.DynamicApi.Get<RealmValue>(property);
        return value.Type == RealmValueType.String ? value.AsString() : "";
    }

    private static long? Number(IRealmObjectBase item, string property)
    {
        if (item.ObjectSchema?.Any(p => p.Name == property) != true) return null;
        var value = item.DynamicApi.Get<RealmValue>(property);
        return value.Type == RealmValueType.Int ? value.AsInt64() : null;
    }

    private static IRealmObjectBase? Related(IRealmObjectBase item, string property)
    {
        if (item.ObjectSchema?.Any(p => p.Name == property) != true) return null;
        var value = item.DynamicApi.Get<RealmValue>(property);
        return value.Type == RealmValueType.Object ? value.AsAny() as IRealmObjectBase : null;
    }

    private static void VerifyCollections(Realm realm, List<CollectionState> expected)
    {
        var actual = Collections(realm).OrderBy(c => c.Id).ToList();
        var sorted = expected.OrderBy(c => c.Id).ToList();
        if (JsonSerializer.Serialize(actual) != JsonSerializer.Serialize(sorted))
            throw new InvalidDataException("Collection verification failed; no result will be published.");
    }

    private static void VerifyAudit(RealmAudit expected, RealmAudit actual)
    {
        if (JsonSerializer.Serialize(expected) != JsonSerializer.Serialize(actual))
            throw new InvalidDataException("An unrelated table or the schema changed; no result will be published.");
    }
}

internal static class DataAudit
{
    internal static RealmAudit Capture(Realm realm)
    {
        var schemas = realm.Schema.OrderBy(s => s.Name, StringComparer.Ordinal).ToList();
        var description = schemas.Select(s => new
        {
            s.Name,
            BaseType = s.BaseType.ToString(),
            Properties = s.OrderBy(p => p.Name, StringComparer.Ordinal).Select(p => new
            { p.Name, Type = p.Type.ToString(), p.IsPrimaryKey, p.ObjectType, p.LinkOriginPropertyName, p.IndexType }),
        });
        string schemaHash = Hash(JsonSerializer.SerializeToUtf8Bytes(description));
        var tables = new SortedDictionary<string, TableAudit>(StringComparer.Ordinal);
        foreach (var schema in schemas.Where(s => s.Name != "BeatmapCollection" && s.BaseType == ObjectSchema.ObjectType.RealmObject))
        {
            var rows = new List<string>();
            foreach (var item in RealmMerger.Objects(realm, schema.Name))
                rows.Add(Hash(ObjectBytes(item)));
            rows.Sort(StringComparer.Ordinal);
            using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            foreach (string row in rows)
                hash.AppendData(Encoding.ASCII.GetBytes(row));
            tables.Add(schema.Name, new TableAudit(rows.Count, Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant()));
        }
        return new RealmAudit(schemaHash, tables);
    }

    private static string Hash(byte[] data) => Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant();

    private static byte[] ObjectBytes(IRealmObjectBase item)
    {
        using var stream = new MemoryStream();
        using (var json = new Utf8JsonWriter(stream))
            WriteObject(json, item, new Dictionary<IRealmObjectBase, string>(), "$", 0);
        return stream.ToArray();
    }

    private static void WriteObject(Utf8JsonWriter json, IRealmObjectBase item,
        Dictionary<IRealmObjectBase, string> active, string path, int depth)
    {
        if (depth > 64)
            throw new InvalidDataException("An object graph exceeds the audit depth limit.");
        if (active.TryGetValue(item, out var cycle))
        {
            json.WriteStringValue("cycle:" + cycle);
            return;
        }
        active.Add(item, path);
        json.WriteStartObject();
        foreach (var property in item.ObjectSchema!.OrderBy(p => p.Name, StringComparer.Ordinal))
        {
            if ((property.Type & ~PropertyType.Flags) == PropertyType.LinkingObjects)
                continue;
            json.WritePropertyName(property.Name);
            var api = item.DynamicApi;
            if (property.Type.HasFlag(PropertyType.Dictionary))
            {
                json.WriteStartObject();
                foreach (var pair in api.GetDictionary<RealmValue>(property.Name).OrderBy(p => p.Key, StringComparer.Ordinal))
                {
                    json.WritePropertyName(pair.Key);
                    WriteValue(json, pair.Value, active, path + "." + property.Name + "." + pair.Key, depth + 1);
                }
                json.WriteEndObject();
            }
            else if (property.Type.HasFlag(PropertyType.Set))
            {
                var values = api.GetSet<RealmValue>(property.Name).Select(value => ValueBytes(value, active, path, depth + 1))
                    .Select(Convert.ToBase64String).Order(StringComparer.Ordinal);
                json.WriteStartArray();
                foreach (string value in values)
                    json.WriteStringValue(value);
                json.WriteEndArray();
            }
            else if (property.Type.HasFlag(PropertyType.Array))
            {
                json.WriteStartArray();
                int index = 0;
                foreach (var value in api.GetList<RealmValue>(property.Name))
                    WriteValue(json, value, active, path + "." + property.Name + "[" + index++ + "]", depth + 1);
                json.WriteEndArray();
            }
            else
                WriteValue(json, api.Get<RealmValue>(property.Name), active, path + "." + property.Name, depth + 1);
        }
        json.WriteEndObject();
        active.Remove(item);
    }

    private static byte[] ValueBytes(RealmValue value, Dictionary<IRealmObjectBase, string> active, string path, int depth)
    {
        using var stream = new MemoryStream();
        using (var json = new Utf8JsonWriter(stream))
            WriteValue(json, value, active, path, depth);
        return stream.ToArray();
    }

    private static void WriteValue(Utf8JsonWriter json, RealmValue value,
        Dictionary<IRealmObjectBase, string> active, string path, int depth)
    {
        if (depth > 64)
            throw new InvalidDataException("A mixed value exceeds the audit depth limit.");
        switch (value.Type)
        {
            case RealmValueType.Null: json.WriteNullValue(); break;
            case RealmValueType.Data: json.WriteBase64StringValue(value.AsData()); break;
            case RealmValueType.Float: json.WriteStringValue("float:" + BitConverter.SingleToInt32Bits(value.AsFloat()).ToString("X8")); break;
            case RealmValueType.Double: json.WriteStringValue("double:" + BitConverter.DoubleToInt64Bits(value.AsDouble()).ToString("X16")); break;
            case RealmValueType.Date: json.WriteStringValue("date:" + value.AsDate().ToString("O", CultureInfo.InvariantCulture)); break;
            case RealmValueType.Object:
                var target = (IRealmObjectBase)value.AsAny()!;
                var targetSchema = target.ObjectSchema ?? throw new InvalidDataException("An object has no schema.");
                var key = targetSchema.FirstOrDefault(p => p.IsPrimaryKey);
                if (key.IsPrimaryKey)
                {
                    json.WriteStartObject();
                    json.WriteString("type", targetSchema.Name);
                    json.WritePropertyName("key");
                    WriteValue(json, target.DynamicApi.Get<RealmValue>(key.Name), active, path, depth + 1);
                    json.WriteEndObject();
                }
                else
                    WriteObject(json, target, active, path, depth + 1);
                break;
            case RealmValueType.List:
                json.WriteStartArray();
                foreach (var element in value.AsList())
                    WriteValue(json, element, active, path, depth + 1);
                json.WriteEndArray();
                break;
            case RealmValueType.Dictionary:
                json.WriteStartObject();
                foreach (var pair in value.AsDictionary().OrderBy(p => p.Key, StringComparer.Ordinal))
                {
                    json.WritePropertyName(pair.Key);
                    WriteValue(json, pair.Value, active, path, depth + 1);
                }
                json.WriteEndObject();
                break;
            default:
                json.WriteStringValue(value.Type + ":" + Convert.ToString(value.AsAny(), CultureInfo.InvariantCulture));
                break;
        }
    }
}
