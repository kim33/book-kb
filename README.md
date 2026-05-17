# 📚 Bookshelf Knowledge Graph & Recommendation Engine

An end-to-end, domain-specific knowledge elicitation pipeline modeled after the GPTKB framework. This system transforms unstructured literary knowledge into a highly dense, semantic graph database to power explainable path-based recommendations.

<p align="center">
  <img src="bookshelf_graph.jpg" alt="Bookshelf Knowledge Graph Visual Mapping" width="100%">
</p>

## 🚀 Overview

Traditional book recommendation engines rely on statistical collaborative filtering, which suffers from severe cold-start limitations and produces "filter bubbles." This project approaches recommendations through **Semantic Knowledge Graphs** and **Domain-Specific Logic Elicitation**. 

Using a custom, multi-threaded orchestration engine, the system drives an LLM (`claude-haiku-4-5`) to systematically trace open-ended factual triples across literature—mapping books, authors, characters, settings, genres, and historical movements into a high-density schema. 

## 🛠️ Architecture Highlights

* **High-Performance Multi-Threading**: Features an asynchronous task runner powered by Python’s `ThreadPoolExecutor`. It implements a thread-safe synchronized node sieve to manage network I/O gracefully and guarantee zero duplicate entity expansions across workers.
* **Deterministic Normalization**: Protects against graph mutation anomalies through dynamic label sanitization, automatically standardizing free-form model properties into canonical PascalCase labels and UPPERCASE_SNAKE_CASE relationship verbs.
* **Explainable AI (XAI)**: Because the database utilizes natively structured connections (e.g., `[:INFLUENCED_BY]`, `[:PROTAGONIST_OF]`), recommendation calculations transcend "black-box" vector similarities, generating human-readable reasoning alongside results.
