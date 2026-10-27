using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Realms;
using Realms.Schema;

namespace RealmCollectionImport;

internal static class SelfTests
{
    private static int assertions;
    private static readonly string A = new('a', 32), B = new('b', 32), D = new('d', 32), E = new('e', 32);

    internal static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), "realm-import-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            ReaderTests();
            string source = Path.Combine(root, "source.realm");
            CreateRealm(source);
            string input = Path.Combine(root, "collection.db");
            File.WriteAllBytes(input, Encode(new LegacyCollection("Main", [A, B, B.ToUpperInvariant()]),
                new LegacyCollection("練習 🎵", [B]), new LegacyCollection("Empty", [])));
            string original = Digest(source);
            var preview = Program.Execute(input, source, null);
            Check(preview.Status == "preview" && !preview.VerifiedAfterReopen, "preview creates no merged output");
            Check(preview.CollectionsBefore == 3 && preview.CollectionsAfter == 5, "preview preserves unrelated and case-distinct names");
            Check(preview.Changes.Single(c => c.Name == "Main").AddedHashes.SequenceEqual([B]), "preview plans a deduplicated union");
            Check(Digest(source) == original, "preview preserves the input bytes");

            string output = Path.Combine(root, "result");
            var merged = Program.Execute(input, source, output);
            string result = Path.Combine(output, "client.realm");
            Check(merged.Status == "merged" && merged.VerifiedAfterReopen, "merged output verified after reopen");
            Check(Digest(source) == original, "merge preserves the source bytes");
            Check(merged.PreservedData!.OtherTables["Sentinel"].Rows == 1, "unrelated scalar/list/dictionary/set/reference data audited");
            using (var realm = RealmMerger.Open(result, readOnly: true))
            {
                var collections = RealmMerger.Collections(realm);
                Check(collections.Single(c => c.Name == "Main").Hashes.SequenceEqual([A, D, B]), "existing collection gains only missing hashes");
                Check(collections.Single(c => c.Name == "Keep").Hashes.SequenceEqual([E]), "unrelated collection unchanged");
                Check(collections.Single(c => c.Name == "main").Hashes.SequenceEqual([E]), "names remain case sensitive");
                Check(collections.Single(c => c.Name == "練習 🎵").Hashes.SequenceEqual([B]), "Unicode name and shared difficulty preserved");
                Check(collections.Single(c => c.Name == "Empty").Hashes.Count == 0, "empty collection preserved");
                var sentinel = RealmMerger.Objects(realm, "Sentinel").Single();
                Check(sentinel.DynamicApi.Get<string>("Name") == "private unrelated value", "unrelated string value preserved");
                Check(sentinel.DynamicApi.Get<long>("Counter") == 987654321, "unrelated integer value preserved");
                Check(sentinel.DynamicApi.GetList<long>("Numbers").SequenceEqual([1L, 3L, 9L]), "unrelated list values preserved");
                Check(sentinel.DynamicApi.GetDictionary<string>("Tags")["unicode"] == "星", "unrelated dictionary values preserved");
                Check(sentinel.DynamicApi.GetSet<bool>("Flags").SetEquals([true, false]), "unrelated set values preserved");
                Check(sentinel.DynamicApi.Get<byte[]>("Blob").SequenceEqual(new byte[] { 0, 255, 127 }), "unrelated binary data preserved");
            }
            // A dynamic edit must retain the original application schema version, not migrate it to zero.
            using (Realm.GetInstance(new RealmConfiguration(result)
            {
                Schema = TestSchema(),
                SchemaVersion = 52,
                MigrationCallback = (_, _) => throw new InvalidDataException("Unexpected migration"),
            })) { }
            Check(true, "application schema version remains readable at 52 without migration");

            string second = Path.Combine(root, "second");
            var repeated = Program.Execute(input, result, second);
            Check(repeated.Changes.All(c => c.Action == "unchanged"), "repeated import is idempotent");
            using (var first = RealmMerger.Open(result, readOnly: true))
            using (var again = RealmMerger.Open(Path.Combine(second, "client.realm"), readOnly: true))
                Check(JsonSerializer.Serialize(RealmMerger.Collections(first).OrderBy(c => c.Id)) == JsonSerializer.Serialize(RealmMerger.Collections(again).OrderBy(c => c.Id)), "no-op import preserves IDs, timestamps, order, and membership");
            EditorTests(root, result);
            Throws(() => Program.Execute(input, source, output), "existing output is never overwritten");
            Check(Digest(source) == original, "refused overwrite leaves source unchanged");
            File.WriteAllBytes(input, [1, 2, 3]);
            string refused = Path.Combine(root, "refused");
            Throws(() => Program.Execute(input, source, refused), "malformed collection.db rejected before publishing");
            Check(!Directory.Exists(refused) && Digest(source) == original, "failed import leaves no result and no source edits");

            File.WriteAllBytes(input, Encode(new LegacyCollection("Main", [B])));
            string duplicate = Path.Combine(root, "duplicate.realm");
            CreateRealm(duplicate, duplicateName: true);
            string duplicateHash = Digest(duplicate);
            Throws(() => Program.Execute(input, duplicate, Path.Combine(root, "ambiguous")), "ambiguous existing names fail closed");
            Check(Digest(duplicate) == duplicateHash, "ambiguous merge leaves source intact");

            string unsupported = Path.Combine(root, "unsupported.realm");
            using (Realm.GetInstance(new RealmConfiguration(unsupported) { Schema = new RealmSchema.Builder { new ObjectSchema.Builder("Other") { Property.Primitive("Name", RealmValueType.String) } }.Build() })) { }
            Throws(() => Program.Execute(input, unsupported, Path.Combine(root, "unsupported-output")), "non-lazer schema is rejected");
            Check(!Directory.Exists(Path.Combine(root, "unsupported-output")), "schema failure publishes nothing");
            Check(!Directory.EnumerateDirectories(root, ".realm-collection-import-*").Any(), "staging directories are cleaned up on success and failure");
            Console.WriteLine(JsonSerializer.Serialize(new { self_tests = "passed", assertions, realm_sdk = "20.1.0" }, Program.JsonOptions));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static void EditorTests(string root, string source)
    {
        string original = Digest(source);
        var document = Program.Inspect(source);
        Check(document.Collections.Count == 5 && document.SourceRealmSha256 == original.ToLowerInvariant(), "editor inspects a copied Realm without changing it");
        Check(document.Beatmaps[new string('c', 32)].Available, "active beatmap set is available");
        Check(!document.Beatmaps[new string('f', 32)].Available, "soft-deleted set remains missing despite cached metadata");
        Check(!document.Beatmaps[new string('0', 32)].Available, "detached beatmap metadata is not treated as installed");
        var main = document.Collections.Single(c => c.Name == "Main");
        var keep = document.Collections.Single(c => c.Name == "Keep");
        var targets = document.Collections.Where(c => c.Id != keep.Id).Select(c => c.Id == main.Id
            ? c with { Name = "Renamed 練習 🎵", Hashes = [A, B] } : c).ToList();
        targets.Add(new EditorCollection(Guid.NewGuid(), "New empty", []));
        string plan = Path.Combine(root, "edits.json");
        File.WriteAllText(plan, JsonSerializer.Serialize(new EditorPlan(document.SourceRealmSha256, targets)));
        string output = Path.Combine(root, "edited");
        var report = Program.Execute(plan, source, output, editMode: true);
        Check(report.VerifiedAfterReopen && report.EditPlanSha256 != null, "GUI edit plan verifies after reopening");
        Check(report.Changes.Any(c => c.Action == "delete" && c.Id == keep.Id), "collection deletion recorded");
        Check(report.Changes.Single(c => c.Id == main.Id).RemovedHashes!.SequenceEqual([D]), "removed membership recorded");
        var edited = Program.Inspect(Path.Combine(output, "client.realm"));
        Check(edited.Collections.Single(c => c.Id == main.Id).Name == "Renamed 練習 🎵", "collection renamed with original ID");
        Check(edited.Collections.Single(c => c.Id == main.Id).Hashes.SequenceEqual([A, B]), "selected map membership removed");
        Check(edited.Collections.Single(c => c.Name == "練習 🎵").Hashes.SequenceEqual([B]), "shared map retained in other collection");
        Check(!edited.Collections.Any(c => c.Id == keep.Id) && edited.Collections.Single(c => c.Name == "New empty").Hashes.Count == 0, "delete and create persist together");
        Check(Digest(source) == original, "GUI edits preserve input bytes");

        File.WriteAllText(plan, JsonSerializer.Serialize(new EditorPlan(new string('0', 64), targets)));
        string stale = Path.Combine(root, "stale");
        Throws(() => Program.Execute(plan, source, stale, editMode: true), "stale GUI source hash rejected");
        Check(!Directory.Exists(stale), "stale editor publishes no output");
        // Deleting Main would null Sentinel's external link. The unrelated-data audit must reject it.
        File.WriteAllText(plan, JsonSerializer.Serialize(new EditorPlan(document.SourceRealmSha256,
            document.Collections.Where(c => c.Id != main.Id).ToList())));
        string linked = Path.Combine(root, "linked");
        Throws(() => Program.Execute(plan, source, linked, editMode: true), "external reference alteration rejected");
        Check(!Directory.Exists(linked) && Digest(source) == original, "audit failure publishes nothing and leaves source unchanged");
        File.WriteAllText(plan, JsonSerializer.Serialize(new EditorPlan(document.SourceRealmSha256, [main, main])));
        Throws(() => Program.Execute(plan, source, Path.Combine(root, "repeated-id"), editMode: true), "duplicate editor IDs rejected");
    }

    private static void ReaderTests()
    {
        byte[] valid = Encode(new LegacyCollection(new string('星', 50), [A, A.ToUpperInvariant()]), new LegacyCollection("Empty", []));
        var parsed = LegacyCollections.Read(valid);
        Check(parsed.Version == 20261026 && parsed.Collections[0].Name == new string('星', 50), "UTF-8 byte lengths and multi-byte ULEB128");
        Check(parsed.Collections[0].Hashes.SequenceEqual([A]), "incoming case-insensitive hash deduplication");
        Check(parsed.Collections[1].Hashes.Count == 0, "reader accepts empty collections");
        var repeated = LegacyCollections.Read(Encode(new LegacyCollection("Main", [A]), new LegacyCollection("Main", [B])));
        Check(repeated.Collections.Single().Hashes.SequenceEqual([A, B]), "repeated incoming names combine exactly");
        foreach (byte[] malformed in new[] { Array.Empty<byte>(), valid[..^1], valid.Concat(new byte[] { 0 }).ToArray(), Encode(new LegacyCollection("Bad", ["not-md5"])) })
            Throws(() => LegacyCollections.Read(malformed), "malformed/truncated/checksum/trailing data rejected");
        byte[] negative = Encode();
        Array.Fill(negative, (byte)255, 4, 4);
        Throws(() => LegacyCollections.Read(negative), "negative collection counts rejected");
        byte[] marker = Encode(new LegacyCollection("Name", []));
        marker[8] = 0x7f;
        Throws(() => LegacyCollections.Read(marker), "invalid string marker rejected");
        byte[] invalidUtf8 = Encode(new LegacyCollection("x", []));
        invalidUtf8[10] = 0xff;
        Throws(() => LegacyCollections.Read(invalidUtf8), "invalid UTF-8 rejected");
        Throws(() => LegacyCollections.Read(new byte[LegacyCollections.MaximumBytes + 1]), "oversized inputs rejected");
    }

    private static RealmSchema TestSchema() => new RealmSchema.Builder
    {
        new ObjectSchema.Builder("BeatmapSet")
        {
            Property.Primitive("ID", RealmValueType.Guid, isPrimaryKey: true),
            Property.Primitive("DeletePending", RealmValueType.Bool),
        },
        new ObjectSchema.Builder("Beatmap")
        {
            Property.Primitive("ID", RealmValueType.Guid, isPrimaryKey: true),
            Property.Primitive("MD5Hash", RealmValueType.String),
            Property.Object("BeatmapSet", "BeatmapSet"),
        },
        new ObjectSchema.Builder("BeatmapCollection")
        {
            Property.Primitive("ID", RealmValueType.Guid, isPrimaryKey: true),
            Property.Primitive("Name", RealmValueType.String, isNullable: true),
            Property.PrimitiveList("BeatmapMD5Hashes", RealmValueType.String),
            Property.Primitive("LastModified", RealmValueType.Date),
        },
        new ObjectSchema.Builder("Sentinel")
        {
            Property.Primitive("ID", RealmValueType.Guid, isPrimaryKey: true),
            Property.Primitive("Name", RealmValueType.String),
            Property.Primitive("Counter", RealmValueType.Int),
            Property.Primitive("Blob", RealmValueType.Data, isNullable: true),
            Property.PrimitiveList("Numbers", RealmValueType.Int),
            Property.PrimitiveSet("Flags", RealmValueType.Bool),
            Property.PrimitiveDictionary("Tags", RealmValueType.String),
            Property.Object("Collection", "BeatmapCollection"),
        },
    }.Build();

    private static void CreateRealm(string path, bool duplicateName = false)
    {
        using var realm = Realm.GetInstance(new RealmConfiguration(path) { Schema = TestSchema(), SchemaVersion = 52, IsDynamic = true });
        realm.Write(() =>
        {
            foreach (char character in new[] { 'c', 'f', '0' })
            {
                IRealmObjectBase map = realm.DynamicApi.CreateObject("Beatmap", (Guid?)Guid.NewGuid());
                map.DynamicApi.Set("MD5Hash", new string(character, 32));
                if (character != '0')
                {
                    IRealmObjectBase set = realm.DynamicApi.CreateObject("BeatmapSet", (Guid?)Guid.NewGuid());
                    set.DynamicApi.Set("DeletePending", character == 'f');
                    ((dynamic)map).BeatmapSet = (dynamic)set;
                }
            }
            var main = Collection(realm, "Main", [A, D]);
            Collection(realm, "Keep", [E]);
            Collection(realm, "main", [E]);
            if (duplicateName)
                Collection(realm, "Main", [E]);
            IRealmObjectBase sentinel = realm.DynamicApi.CreateObject("Sentinel", (Guid?)Guid.NewGuid());
            sentinel.DynamicApi.Set("Name", "private unrelated value");
            sentinel.DynamicApi.Set("Counter", 987654321L);
            sentinel.DynamicApi.Set("Blob", new byte[] { 0, 255, 127 });
            ((dynamic)sentinel).Collection = (dynamic)main;
            foreach (long value in new[] { 1L, 3L, 9L }) sentinel.DynamicApi.GetList<long>("Numbers").Add(value);
            sentinel.DynamicApi.GetSet<bool>("Flags").UnionWith([true, false]);
            sentinel.DynamicApi.GetDictionary<string>("Tags").Add("unicode", "星");
        });
    }

    private static IRealmObjectBase Collection(Realm realm, string name, List<string> hashes)
    {
        IRealmObjectBase item = realm.DynamicApi.CreateObject("BeatmapCollection", (Guid?)Guid.NewGuid());
        item.DynamicApi.Set("Name", name);
        item.DynamicApi.Set("LastModified", new DateTimeOffset(2020, 1, 2, 3, 4, 5, TimeSpan.Zero));
        foreach (string hash in hashes) item.DynamicApi.GetList<string>("BeatmapMD5Hashes").Add(hash);
        return item;
    }

    private static byte[] Encode(params LegacyCollection[] collections)
    {
        using var stream = new MemoryStream();
        using (var writer = new BinaryWriter(stream, Encoding.UTF8, leaveOpen: true))
        {
            writer.Write(20261026);
            writer.Write(collections.Length);
            foreach (var collection in collections)
            {
                WriteString(writer, collection.Name);
                writer.Write(collection.Hashes.Count);
                foreach (string hash in collection.Hashes) WriteString(writer, hash);
            }
        }
        return stream.ToArray();
    }

    private static void WriteString(BinaryWriter writer, string value)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(value);
        writer.Write((byte)0x0b);
        writer.Write7BitEncodedInt(bytes.Length);
        writer.Write(bytes);
    }

    private static string Digest(string path)
    {
        using var input = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(input));
    }

    private static void Check(bool valid, string label)
    {
        if (!valid) throw new InvalidDataException("Self-test failed: " + label);
        assertions++;
    }

    private static void Throws(Action action, string label)
    {
        bool failed = false;
        try { action(); }
        catch (Exception) { failed = true; }
        Check(failed, label);
    }
}
