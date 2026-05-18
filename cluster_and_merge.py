from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering
import numpy as np
from dotenv import load_dotenv
import os

load_dotenv()

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PW = os.environ.get("NEO4J_PW")

# 1. CONNECT TO NEO4J & LOAD LIGHTWEIGHT EMBEDDING MODEL
db_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PW))
encoder = SentenceTransformer('all-MiniLM-L6-v2')

def consolidate_graph_relations(similarity_threshold=0.75):
    print("Fetching all unique dynamic relationship types from Neo4j...")
    
    # Step 1: Pull every unique relationship property type Claude has created
    fetch_query = """
    MATCH ()-[r]->()
    RETURN DISTINCT type(r) AS rel_type
    """
    with db_driver.session() as session:
        result = session.run(fetch_query)
        raw_relations = [record["rel_type"] for record in result if record["rel_type"]]

    if len(raw_relations) < 2:
        print("Not enough distinct relations to cluster.")
        return

    print(f" Found {len(raw_relations)} distinct relation strings. Calculating embeddings...")
    
    # Step 2: Convert textual relation tokens into vectors
    embeddings = encoder.encode(raw_relations)

    # Step 3: Perform Agglomerative Clustering based on cosine similarity
    clustering = AgglomerativeClustering(
        n_clusters=None, 
        distance_threshold=1.0 - similarity_threshold, 
        metric='cosine', 
        linkage='average'
    )
    cluster_labels = clustering.fit_predict(embeddings)

    # Organize relations into their designated semantic clusters
    groups = {}
    for rel, cluster_id in zip(raw_relations, cluster_labels):
        groups.setdefault(cluster_id, []).append(rel)

    print("🧙‍♂️ Mapping messy variants to canonical taxonomies...")
    
    # Step 4: Write standardizations back to Neo4j
    with db_driver.session() as session:
        for cluster_id, rel_variants in groups.items():
            if len(rel_variants) > 1:
                # Select the most common or shortest string as the 'Canonical' master label
                canonical_label = min(rel_variants, key=len)
                print(f"🔗 Merging variants {rel_variants} ➡️ Heading to canonical: '{canonical_label}'")
                
                # Cypher query to rewrite property tags safely inside your database
                merge_query = """
                MATCH (a)-[r]->(b)
                WHERE type(r) IN $variants
                CALL apoc.create.relationship(a, $canonical, properties(r), b) YIELD rel
                DELETE r
                """
                session.run(merge_query, variants=rel_variants, canonical=canonical_label)
                
    print("Graph relation consolidation complete!")

def consolidate_node_labels(similarity_threshold=0.70):
    print("Fetching all distinct node labels from Neo4j...")
    
    # Query to get all unique labels in the database
    fetch_query = """
    MATCH (n)
    UNWIND labels(n) AS label
    RETURN DISTINCT label
    """
    
    with db_driver.session() as session:
        result = session.run(fetch_query)
        raw_labels = [record["label"] for record in result if record["label"]]

    if len(raw_labels) < 2:
        print("Not enough distinct labels to cluster.")
        return

    print(f"Found {len(raw_labels)} distinct node labels. Calculating embeddings...")
    embeddings = encoder.encode(raw_labels)

    # Cluster semantically similar label names
    clustering = AgglomerativeClustering(
        n_clusters=None, 
        distance_threshold=1.0 - similarity_threshold, 
        metric='cosine', 
        linkage='average'
    )
    cluster_labels = clustering.fit_predict(embeddings)

    groups = {}
    for label, cluster_id in zip(raw_labels, cluster_labels):
        groups.setdefault(cluster_id, []).append(label)

    print("🧙‍♂️ Mapping messy node labels to canonical taxonomies...")
    
    with db_driver.session() as session:
        for cluster_id, label_variants in groups.items():
            if len(label_variants) > 1:
                # Pick the shortest/cleanest label as the master canonical name
                canonical_label = min(label_variants, key=len)
                print(f"🏷️ Unifying variants {label_variants} ➡️ Heading to canonical label: '{canonical_label}'")
                
                # add the canonical label to all matching nodes, then strip the old variant names.
                for variant in label_variants:
                    if variant != canonical_label:
                        merge_query = f"""
                        MATCH (n:`{variant}`)
                        SET n:`{canonical_label}`
                        REMOVE n:`{variant}`
                        """
                        session.run(merge_query)
                        
    print("Node label consolidation complete!")

if __name__ == "__main__":
    try:
        consolidate_graph_relations(similarity_threshold=0.75)
        consolidate_node_labels(similarity_threshold=0.75)
    finally:
        db_driver.close()