// Retrieval Chunk node identity, lookup indexes, and default vector index.
// Chunk nodes project from PostgreSQL document_chunks joined to chunk_embeddings.
// PostgreSQL stays authoritative; Neo4j can always rebuild these nodes.

CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS
FOR (c:Chunk)
REQUIRE c.id IS UNIQUE;

CREATE INDEX chunk_tenant_index_version IF NOT EXISTS
FOR (c:Chunk)
ON (c.tenant_id, c.retrieval_index_version_id);

CREATE INDEX chunk_document_version IF NOT EXISTS
FOR (c:Chunk)
ON (c.document_version_id, c.chunk_id);

CREATE VECTOR INDEX chunk_embedding_default IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
