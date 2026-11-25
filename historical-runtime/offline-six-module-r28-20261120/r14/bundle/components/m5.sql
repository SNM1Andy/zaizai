
            PRAGMA synchronous=FULL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE authority(namespace TEXT PRIMARY KEY);
            CREATE TABLE action(original_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('PLANNED','RESERVED','UNKNOWN','COMPLETED')),
                claim TEXT);
            CREATE TABLE binding(job TEXT NOT NULL, campaign TEXT NOT NULL,
                original_id TEXT NOT NULL REFERENCES action(original_id), PRIMARY KEY(job,campaign));
        