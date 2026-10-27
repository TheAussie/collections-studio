using System.Security.Cryptography;
using System.Text.Json;

namespace RealmCollectionImport;

internal static class Program
{
    internal static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    private const string Help = """
        Import legacy collection.db into a NEW copy of an osu!lazer Realm.

        preview --collections FILE --realm-copy FILE
        merge   --collections FILE --realm-copy FILE --output-directory NEW_DIRECTORY
        inspect --realm-copy FILE
        read-collections --collections FILE
        edit    --plan FILE --realm-copy FILE --output-directory NEW_DIRECTORY
        self-test

        Inputs are opened as ordinary read-only files, then inspected in private temporary storage.
        merge creates NEW_DIRECTORY/client.realm and import-report.json. It never replaces an input
        or an existing output. Close lazer before making the source copy. Realm SDK: 20.1.0.
        """;

    internal static int Main(string[] args)
    {
        try
        {
            if (args.Length == 0 || args[0] is "--help" or "-h")
            {
                Console.WriteLine(Help);
                return 0;
            }
            if (args.Length == 1 && args[0] == "self-test")
            {
                SelfTests.Run();
                return 0;
            }
            if (args[0] is not ("preview" or "merge" or "inspect" or "edit" or "read-collections"))
                throw new ArgumentException("Unknown command. Use --help for usage.");
            var options = new Dictionary<string, string>(StringComparer.Ordinal);
            for (int i = 1; i < args.Length; i += 2)
            {
                if (i + 1 >= args.Length || args[i] is not ("--collections" or "--realm-copy" or "--output-directory" or "--plan") || !options.TryAdd(args[i], args[i + 1]))
                    throw new ArgumentException("Invalid or repeated option. Use --help for usage.");
            }
            if (args[0] == "read-collections")
            {
                if (options.Count != 1 || !options.TryGetValue("--collections", out string? legacy)) throw new ArgumentException("Supply --collections FILE.");
                Console.WriteLine(JsonSerializer.Serialize(LegacyCollections.Read(ReadInput(legacy)), JsonOptions));
                return 0;
            }
            if (args[0] == "inspect")
            {
                if (options.Count != 1 || !options.TryGetValue("--realm-copy", out string? copied)) throw new ArgumentException("Supply --realm-copy FILE.");
                Console.WriteLine(JsonSerializer.Serialize(Inspect(copied), JsonOptions));
                return 0;
            }
            bool editMode = args[0] == "edit";
            if (!options.TryGetValue(editMode ? "--plan" : "--collections", out string? collections) || !options.TryGetValue("--realm-copy", out string? realmCopy))
                throw new ArgumentException(editMode ? "Supply --plan and --realm-copy." : "Supply --collections and --realm-copy.");
            options.TryGetValue("--output-directory", out string? output);
            if ((args[0] is "merge" or "edit") != (output != null) || options.Count != (output == null ? 2 : 3))
                throw new ArgumentException("merge and edit require --output-directory; preview creates no output.");
            var report = Execute(collections, realmCopy, output, editMode);
            Console.WriteLine(JsonSerializer.Serialize(report, JsonOptions));
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine($"Import failed: {error.Message}");
            return 1;
        }
    }

    internal static ImportReport Execute(string collectionsPath, string sourcePath, string? outputDirectory, bool editMode = false)
    {
        collectionsPath = Path.GetFullPath(collectionsPath);
        sourcePath = Path.GetFullPath(sourcePath);
        string? output = outputDirectory == null ? null : Path.GetFullPath(outputDirectory);
        if (output != null && (Directory.Exists(output) || File.Exists(output)))
            throw new IOException("Output directory already exists. Choose a new directory.");
        if (output != null && !Directory.Exists(Path.GetDirectoryName(output)))
            throw new IOException("The output parent directory must already exist.");

        using var input = new FileStream(collectionsPath, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (input.Length > LegacyCollections.MaximumBytes)
            throw new InvalidDataException("collection.db exceeds 32 MiB.");
        byte[] bytes = new byte[checked((int)input.Length)];
        input.ReadExactly(bytes);
        if (input.ReadByte() != -1)
            throw new IOException("collection.db changed while reading it.");
        var incoming = editMode ? new LegacyFile(0, []) : LegacyCollections.Read(bytes);
        var plan = editMode ? JsonSerializer.Deserialize<EditorPlan>(bytes) ?? throw new InvalidDataException("Invalid edit plan.") : null;
        string collectionHash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

        string parent = output == null ? Path.GetTempPath() : Path.GetDirectoryName(output)!;
        string work = Path.Combine(parent, $".realm-collection-import-{Guid.NewGuid():N}");
        Directory.CreateDirectory(work);
        PrivateDirectory(work);
        try
        {
            string workingRealm = Path.Combine(work, "working.realm");
            string sourceHash;
            using var source = new FileStream(sourcePath, FileMode.Open, FileAccess.Read, FileShare.Read);
            using (var destination = new FileStream(workingRealm, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                source.CopyTo(destination);
            PrivateFile(workingRealm);
            using (var copied = File.OpenRead(workingRealm))
                sourceHash = Convert.ToHexString(SHA256.HashData(copied)).ToLowerInvariant();
            source.Position = 0;
            if (sourceHash != Convert.ToHexString(SHA256.HashData(source)).ToLowerInvariant())
                throw new IOException("The source Realm changed while being copied. Make a closed-client copy and retry.");

            if (editMode && (plan?.Collections == null || plan.SourceRealmSha256 != sourceHash))
                throw new InvalidDataException("The source Realm changed since it was opened in the editor. Open the copy again.");
            var report = RealmMerger.Process(workingRealm, incoming, output != null, plan?.Collections);
            report.SourceRealmSha256 = sourceHash;
            if (editMode) report.EditPlanSha256 = collectionHash;
            else report.CollectionDbSha256 = collectionHash;
            source.Position = 0;
            if (sourceHash != Convert.ToHexString(SHA256.HashData(source)).ToLowerInvariant())
                throw new IOException("The source Realm changed during the operation. No result was published.");
            input.Position = 0;
            if (collectionHash != Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant())
                throw new IOException("collection.db changed during the operation. No result was published.");
            if (output != null)
            {
                string result = Path.Combine(work, "result");
                Directory.CreateDirectory(result);
                PrivateDirectory(result);
                File.Move(workingRealm, Path.Combine(result, "client.realm"), overwrite: false);
                report.OutputRealm = Path.Combine(output, "client.realm");
                using var final = File.OpenRead(Path.Combine(result, "client.realm"));
                report.OutputRealmSha256 = Convert.ToHexString(SHA256.HashData(final)).ToLowerInvariant();
                final.Dispose();
                string reportPath = Path.Combine(result, "import-report.json");
                File.WriteAllText(reportPath, JsonSerializer.Serialize(report, JsonOptions) + Environment.NewLine);
                PrivateFile(reportPath);
                // A directory rename publishes the verified result without replacing an existing directory.
                Directory.Move(result, output);
            }
            return report;
        }
        finally
        {
            Directory.Delete(work, recursive: true);
        }
    }

    private static byte[] ReadInput(string path)
    {
        using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (input.Length > LegacyCollections.MaximumBytes) throw new InvalidDataException("Input exceeds 32 MiB.");
        var data = new byte[checked((int)input.Length)];
        input.ReadExactly(data);
        if (input.ReadByte() != -1) throw new IOException("Input changed while reading it.");
        return data;
    }

    internal static EditorDocument Inspect(string sourcePath)
    {
        string work = Path.Combine(Path.GetTempPath(), ".realm-collection-import-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(work);
        PrivateDirectory(work);
        try
        {
            string copied = Path.Combine(work, "inspect.realm");
            using var input = new FileStream(Path.GetFullPath(sourcePath), FileMode.Open, FileAccess.Read, FileShare.Read);
            using (var output = new FileStream(copied, FileMode.CreateNew, FileAccess.Write, FileShare.None)) input.CopyTo(output);
            PrivateFile(copied);
            string hash;
            using (var copy = File.OpenRead(copied)) hash = Convert.ToHexString(SHA256.HashData(copy)).ToLowerInvariant();
            var document = RealmMerger.Inspect(copied, hash);
            input.Position = 0;
            if (hash != Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant()) throw new IOException("The source changed while opening. Make a closed-client copy and retry.");
            return document;
        }
        finally { Directory.Delete(work, recursive: true); }
    }

    private static void PrivateDirectory(string path)
    {
        if (!OperatingSystem.IsWindows())
            File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
    }

    private static void PrivateFile(string path)
    {
        if (!OperatingSystem.IsWindows())
            File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
    }
}
