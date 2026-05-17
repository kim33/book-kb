import json
import os
import time
from anthropic import Anthropic
from neo4j import GraphDatabase
from dotenv import load_dotenv

# Activate environment variables from .env file
load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PW = os.environ.get("NEO4J_PW")

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
db_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PW))

# =====================================================================
# GPTKB-INSPIRED OPEN ELICITATION SYSTEM PROMPT
# =====================================================================
SYSTEM_PROMPT = """
You are a specialized literary knowledge elicitation engine modeled after the GPTKB framework. Your single objective is to extract all discoverable factual assertions about a given entity from your internal knowledge base as an open-ended graph structure.

You MUST respond ONLY with a single, raw, valid JSON object.
Strictly follow these formatting rules:
- Do NOT wrap your answer in markdown blocks like '''json ...'''.
- Do NOT include introductory text, conversational pleasantries, or concluding notes.
- Output ONLY a raw JSON map.

Follow this exact JSON structure:
{
  "node": {
    "name": "The standard canonical name of the requested entity",
    "type": "A dynamic, free-form, short, PASCAL_CASE category string representing the entity type (e.g., Book, Author, LiteraryMovement, Character, Concept, Location, HistoricalEvent)",
    "properties": {
      "title_or_name": "String identifying the node",
      "release_or_birth_year": Integer or null,
      "description": "A concise 2-sentence summary or biography"
    }
  },
  "edges": [
    {
      "target_name": "Name of the connected target entity",
      "target_type": "A dynamic, free-form, short, PASCAL_CASE category string representing this target entity's type",
      "relationship_label": "A free-form, short, UPPERCASE_SNAKE_CASE verb string representing the precise extracted relationship (e.g., WROTE, INFLUENCED, SET_IN, MEMBER_OF, INSPIRED_BY, CRITICIZED)"
    }
  ]
}

Extraction Rules:
1. First, evaluate all facts you know about the requested entity.   
2. Generate between 5 to 8 highly descriptive, accurate edge connections. Both node types and relationship labels are fully open-ended.
3. CRITICAL CONTEXT FILTER: Your goal is to build a LITERARY graph. 
   - If the requested entity is a Book or Author, extract its core attributes (characters, settings, influences, awards).
   - If the requested entity is NOT a book (e.g., a Location like 'Edinburgh', or a Concept like 'Magical Realism'), you MUST ONLY extract relationships that tie it back to literature, authors, or books (e.g., BIRTHPLACE_OF_AUTHOR, SETTING_OF_BOOK, INSPIRED_MOVEMENT). 
   - Do NOT extract general trivia unrelated to books (e.g., do NOT output 'Edinburgh' -> CAPITAL_OF -> 'Scotland'). Every single edge must have a thematic anchor to the literary world.
4. To ensure the graph converges cleanly, you must normalize semantically identical relationship types. Prioritize common native graph standards over slight linguistic variations
"""

def sanitize_label(text, casing="pascal"):
    """
    Sanitizes LLM outputs to keep Cypher queries safe from syntax injection.
    """
    if not text:
        return "Unknown"
    
    # Strip out anything that isn't alphanumeric or an underscore/space
    cleaned = "".join(c for c in text if c.isalnum() or c in " _-")
    
    if casing == "upper_snake":
        # Turn "Won Award" or "won-award" into "WON_AWARD"
        return cleaned.strip().upper().replace(" ", "_").replace("-", "_")
    else:
        # Turn "literary movement" or "Literary-Movement" into "LiteraryMovement"
        # Neo4j labels look best in PascalCase
        words = cleaned.replace("-", " ").replace("_", " ").split()
        return "".join(word.capitalize() for word in words)


def upsert_graph_data(extracted_json):
    """
    Commits fully dynamic open-ended nodes and labels to Neo4j.
    """
    source_node = extracted_json["node"]
    source_props = source_node["properties"]
    
    # Dynamically sanitize the source node type (PascalCase)
    source_label = sanitize_label(source_node.get("type"), casing="pascal")

    with db_driver.session() as session:
        # 1. Upsert central node with dynamic label
        source_cypher = f"""
        MERGE (s:{source_label} {{name: $name}})
        SET s.year = $year, s.description = $description
        """
        session.run(
            source_cypher,
            name = source_node["name"],
            year = source_props.get("release_or_birth_year"),
            description = source_props.get("description")
        )

        # 2. Iterate through completely open-ended edge discoveries
        for edge in extracted_json.get("edges", []):
            target_name = edge["target_name"]
            
            # Dynamically sanitize target types and relationship labels
            target_label = sanitize_label(edge.get("target_type"), casing="pascal")
            dynamic_rel = sanitize_label(edge.get("relationship_label"), casing="upper_snake")

            # Inject safely sanitized dynamic types directly into Cypher
            edge_cypher = f"""
            MATCH (s:{source_label} {{name: $source_name}})
            MERGE (t:{target_label} {{name: $target_name}})
            MERGE (s) - [r:{dynamic_rel}] -> (t)
            """
            try:
                session.run(
                    edge_cypher, 
                    source_name=source_node["name"], 
                    target_name=target_name
                )
            except Exception as e:
                print(f"⚠️ Cypher Execution Failed for (:{source_label})-[:{dynamic_rel}]->(:{target_label}): {e}")

def query_claude_for_node(entity_name, entity_type):
    user_message = f"Generate graph schema data for the {entity_type}: '{entity_name}'."
    try:
        response = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",  # Note: ensure correct model string name if needed
            max_tokens=1500,
            temperature=0.1,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}]
        )
        cleaned_response = response.content[0].text.strip()
        
        # --- ADD THIS SANITIZATION BLOCK ---
        # Strip markdown code block wrappers if Claude ignored the prompt instructions
        if cleaned_response.startswith("```"):
            # Remove opening markdown line (e.g., ```json or ```)
            cleaned_response = cleaned_response.split("\n", 1)[1]
        if cleaned_response.endswith("```"):
            # Remove closing markdown
            cleaned_response = cleaned_response.rsplit("```", 1)[0]
            
        cleaned_response = cleaned_response.strip()
        # ------------------------------------

        return json.loads(cleaned_response)
    except json.JSONDecodeError:
        print(f"❌ Error: Claude returned an unparseable payload for '{entity_name}'.")
        # Print a snippet of what it actually returned to help you debug if needed:
        # print(f"Raw response snippet: {response.content[0].text[:200]}")
        return None
    except Exception as e:
        print(f"❌ API Failure for '{entity_name}': {e}")
        return None

# =====================================================================
# CONTINUOUS DEEP-CRAWL ENGINE (GPTKB STRATEGY)
# =====================================================================
def run_gptkb_style_crawler(target_total_nodes=50):
    """
    Recursively crawls outward through newly discovered uncrawled leaves,
    building a massive unbounded literary graph network.
    """
    print(f"🏗️ Starting GPTKB Open-Extraction Engine. Target: {target_total_nodes} nodes.")
    total_expanded_this_session = 0
    
    while total_expanded_this_session < target_total_nodes:
        # Dynamically scan the perimeter for ANY node lacking the crawled flag
        find_uncrawled_cypher = """
        MATCH (n)
        WHERE (n.crawled IS NULL OR n.crawled = false)
          AND (
            n:Book 
            OR n:Author 
            OR EXISTS { (n)-[]-(:Book) } 
            OR EXISTS { (n)-[]-(:Author) }
          )
        RETURN n.name AS name, labels(n)[0] AS type
        LIMIT 10
        """
        
        with db_driver.session() as session:
            result = session.run(find_uncrawled_cypher)
            mini_batch = [{"name": record["name"], "type": record["type"]} for record in result]
            
        # Seed fallback if the database canvas is entirely empty
        if not mini_batch:
            if total_expanded_this_session == 0:
                print("🌱 Database is completely empty. Seeding with 'Harry Potter' to trigger materialization...")
                mini_batch = [{"name": "Harry Potter and the Sorcerer's Stone", "type": "Book"}]
            else:
                print("🏁 No more leaf entities remain to trace. Extraction complete!")
                break

        print(f"\n📦 Pulled a fresh sub-batch of {len(mini_batch)} uncrawled leaves out of the graph...")

        for current_target in mini_batch:
            if total_expanded_this_session >= target_total_nodes:
                break
                
            print(f"⚙️ [{total_expanded_this_session + 1}/{target_total_nodes}] Eliciting facts for {current_target['type']}: '{current_target['name']}'...")
            
            payload = query_claude_for_node(current_target['name'], current_target['type'])
            
            if payload:
                upsert_graph_data(payload)
                
                # Turn the uncrawled leaf into a fully materialized branch
                with db_driver.session() as session:
                    mark_crawled_cypher = f"MATCH (n:{current_target['type']} {{name: $name}}) SET n.crawled = true"
                    session.run(mark_crawled_cypher, name=current_target['name'])
                    
                total_expanded_this_session += 1
                time.sleep(0.1) # Courteous pacing
            else:
                # Avoid loop-clogging on failed lookups
                with db_driver.session() as session:
                    mark_failed_cypher = f"MATCH (n:{current_target['type']} {{name: $name}}) SET n.crawled = true, n.failed = true"
                    session.run(mark_failed_cypher, name=current_target['name'])

    print(f"\n🎉 Extraction cycle complete! Successfully materialized {total_expanded_this_session} nodes.")

if __name__ == "__main__":
    try:
        # Increase this target boundary as large as your API budget allows!
        run_gptkb_style_crawler(target_total_nodes=300)
    finally:
        db_driver.close()