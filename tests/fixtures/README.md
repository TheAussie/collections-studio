# Collection compatibility fixtures

These fixtures contain synthetic names, hashes and labels only. The JSON models
the version-1 collection-link response; the hex text models its collection.db
bytes (version marker 20261026), including an empty Unicode-named collection.
The server's ExportedAt timestamp varies and is excluded from exact comparison.

Keep both files byte-identical in the web and desktop projects. Each project's
tests verify its side independently. Version incompatible protocol changes;
never replace these with personal databases or real capability URLs.
