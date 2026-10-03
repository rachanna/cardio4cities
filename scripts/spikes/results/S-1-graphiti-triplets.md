# Spike S-1: Graphiti triplets (graphiti-core 0.30.2, Neo4j 5)

20 fictional relations, 13 entities, local embeddings (Sentence Transformers); Graphiti's model is a counting stub, so no paid call was made and every call shown is one the real system would make.

## Path A: add_triplet after saving our nodes

- (1) our UUIDs kept: PASS: 20/20 edge UUIDs ours, 0 foreign; 13/13 nodes
- (2) no re-resolution: FAIL: 23 model calls; 20 edges stored for 20 written
- (3) attributes returned by search: FAIL: 3 GOVERNS hits, 1 with claim_ids, e.g. {}
- (4) invalid_at without deletion: PASS: edge kept with invalid_at 2025-09-01 00:00:00+00:00; current-only search returns ['Tomas Vell heads the Halden Bay Health Office.']; unfiltered returns 2
- (5) model calls counted: 23 {'dedupe_edges.resolve_edge': 19, 'extract_edges.extract_timestamps': 4}; 136 texts embedded; 15.8 s to write

## Path B: our nodes and edges saved through Graphiti's model classes

- (1) our UUIDs kept: PASS: 20/20 edge UUIDs ours, 0 foreign; 13/13 nodes
- (2) no re-resolution: PASS: 0 model calls; 20 edges stored for 20 written
- (3) attributes returned by search: PASS: 3 GOVERNS hits, 3 with claim_ids, e.g. {'target_uuid': '487d0b45-2bdb-5c67-9fb1-eb1cda5cec9c', 'source_uuid': '4854b8b5-0ab8-5b90-88e4-74accf3b82be', 'source_ids': ['src_1'], 'proxy_date': False, 'claim_ids': ['clm_spike_s1_b_fa64a593_01'], 'status': 'supported'}
- (4) invalid_at without deletion: PASS: edge kept with invalid_at 2025-09-01 00:00:00+00:00; current-only search returns ['Tomas Vell heads the Halden Bay Health Office.']; unfiltered returns 2
- (5) model calls counted: 0 ; 36 texts embedded; 2.1 s to write

