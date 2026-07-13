// Knowledge graph Entity node identity and lookup indexes.
// Entities project from PostgreSQL canonical_entities. The Neo4j e.id property
// equals the PostgreSQL canonical_entities.id (a UUID string). PostgreSQL stays
// the system of record and Neo4j can always be rebuilt from it.

CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
FOR (e:Entity)
REQUIRE e.id IS UNIQUE;

CREATE INDEX entity_tenant_type_name IF NOT EXISTS
FOR (e:Entity)
ON (e.tenant_id, e.type, e.normalized_name);
