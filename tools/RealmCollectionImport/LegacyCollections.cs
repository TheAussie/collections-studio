using System.Text;

namespace RealmCollectionImport;

internal sealed record LegacyCollection(string Name, List<string> Hashes);
internal sealed record LegacyFile(int Version, List<LegacyCollection> Collections);

internal static class LegacyCollections
{
    internal const int MaximumBytes = 32 * 1024 * 1024;
    private static readonly UTF8Encoding Utf8 = new(false, true);

    internal static LegacyFile Read(byte[] data)
    {
        if (data.Length > MaximumBytes)
            throw new InvalidDataException("collection.db exceeds 32 MiB.");
        try
        {
            using var stream = new MemoryStream(data, writable: false);
            using var reader = new BinaryReader(stream, Utf8);
            int version = reader.ReadInt32();
            if (version < 0)
                throw new InvalidDataException("Invalid collection.db version.");
            int count = Count(reader, 10_000, "collections");
            var collections = new List<LegacyCollection>();
            var names = new Dictionary<string, LegacyCollection>(StringComparer.Ordinal);
            int total = 0;
            for (int index = 0; index < count; index++)
            {
                string name = ReadString(reader);
                int hashes = Count(reader, 1_000_000, "difficulty hashes");
                total = checked(total + hashes);
                if (total > 1_000_000)
                    throw new InvalidDataException("Too many difficulty hashes.");
                if (!names.TryGetValue(name, out var collection))
                {
                    collection = new LegacyCollection(name, []);
                    names.Add(name, collection);
                    collections.Add(collection);
                }
                var unique = collection.Hashes.ToHashSet(StringComparer.Ordinal);
                for (int hashIndex = 0; hashIndex < hashes; hashIndex++)
                {
                    string hash = ReadString(reader);
                    if (!ValidHash(hash))
                        throw new InvalidDataException("A difficulty checksum is not a 32-character MD5.");
                    hash = hash.ToLowerInvariant();
                    if (unique.Add(hash))
                        collection.Hashes.Add(hash);
                }
            }
            if (stream.Position != stream.Length)
                throw new InvalidDataException("Unexpected trailing bytes in collection.db.");
            return new LegacyFile(version, collections);
        }
        catch (Exception error) when (error is EndOfStreamException or DecoderFallbackException or OverflowException)
        {
            throw new InvalidDataException("collection.db is truncated or contains invalid encoding.", error);
        }
    }

    private static int Count(BinaryReader reader, int maximum, string label)
    {
        int value = reader.ReadInt32();
        if (value < 0 || value > maximum)
            throw new InvalidDataException($"Invalid number of {label}.");
        return value;
    }

    private static string ReadString(BinaryReader reader)
    {
        int marker = reader.ReadByte();
        if (marker == 0)
            return string.Empty;
        if (marker != 0x0b)
            throw new InvalidDataException("Invalid legacy string marker.");
        uint length = 0;
        bool finished = false;
        for (int shift = 0; shift < 35; shift += 7)
        {
            byte next = reader.ReadByte();
            if (shift == 28 && next > 0x0f)
                throw new InvalidDataException("Invalid legacy string length.");
            length |= (uint)(next & 0x7f) << shift;
            if ((next & 0x80) == 0)
            {
                finished = true;
                break;
            }
        }
        if (!finished || length > 1024 * 1024 || length > reader.BaseStream.Length - reader.BaseStream.Position)
            throw new InvalidDataException("Legacy string exceeds its length limit.");
        return Utf8.GetString(reader.ReadBytes((int)length));
    }

    internal static bool ValidHash(string value) => value.Length == 32 && value.All(char.IsAsciiHexDigit);
}
