"""Kuzu DB implementation of LabelledPropertyGraph for graph storage.

This module provides a Kuzu-compatible graph store implementation
that supports vector similarity search and graph operations.

Heavy deps (`kuzu`, `networkx`) are imported lazily inside the methods that
need them, so just importing this module is fast.
"""

import json
import logging
import os
import shutil
from functools import wraps
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, TYPE_CHECKING

from llama_index.core.graph_stores.types import (
    ChunkNode,
    EntityNode,
    LabelledNode,
    LabelledPropertyGraph,
    Relation,
    Triplet,
)
from pydantic import ConfigDict, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from dashboard.knowledge.config import (
    EMBEDDING_DIMENSION,
    KNOWLEDGE_DIR,
    KUZU_MIGRATE,
    PAGERANK_SCORE_THRESHOLD,
)

if TYPE_CHECKING:  # pragma: no cover
    import kuzu

logger = logging.getLogger(__name__)


# Default DB-storage directory (per-namespace files placed inside).
KUZU_DATABASE_PATH = str(KNOWLEDGE_DIR)


# Module-level embedder cache — lazy-instantiated on first call so that
# importing this module doesn't trigger embedding client setup.
_embedder_singleton = None


def _get_embedder():
    """Return a cached KnowledgeEmbedder; lazy-instantiate on first call."""
    global _embedder_singleton
    if _embedder_singleton is None:
        from dashboard.knowledge.embeddings import KnowledgeEmbedder  # noqa: WPS433

        _embedder_singleton = KnowledgeEmbedder()
    return _embedder_singleton


def cleanup_all_kuzu_connections():
    """
    Module-level function to clean up all KuzuDB connections.

    This can be called from anywhere in the application to ensure
    proper cleanup of all cached KuzuDB connections.
    """
    try:
        KuzuLabelledPropertyGraph.close_all_connections()
    except Exception as e:
        logger.error(f"Error during KuzuDB cleanup: {e}")


def kuzu_retry_decorator(func):
    """Decorator that adds retry logic with connection reset for Kuzu operations."""

    @wraps(func)
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((Exception, ConnectionError, OSError)),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying {func.__name__} (attempt {retry_state.attempt_number})"
        ),
    )
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            # Reset connection on any connection-related error
            if any(
                keyword in str(e).lower()
                for keyword in [
                    "connection reset",
                    "transport endpoint",
                    "connection refused",
                    "connection closed",
                    "broken pipe",
                    "network unreachable",
                ]
            ):
                logger.warning(f"Connection error in {func.__name__}: {e}. Resetting connection.")
                self._reset_connection()
            raise e

    return wrapper


class KuzuLabelledPropertyGraph(LabelledPropertyGraph):
    """
    High-performance KuzuDB implementation of LabelledPropertyGraph for persistent graph storage.

    This class provides a production-ready graph database backend using KuzuDB, offering
    excellent performance for complex graph queries and supporting large-scale knowledge
    graphs with efficient storage and retrieval mechanisms.

    WARNING: KuzuDB 0.11.0 has known limitations with multiple database instances in the same process.
    Creating multiple KuzuLabelledPropertyGraph instances simultaneously may cause segmentation faults.
    For concurrent access, consider using separate processes or implementing proper synchronization.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    database_: Optional[Any] = Field(default=None)
    database_path: str = Field(default="")
    index: str = Field(default="")
    ws_id: str = Field(default="")
    kuzu_database_cache: ClassVar[dict[str, Any]] = {}

    def __init__(
        self,
        /,
        index: str,
        ws_id: str,
        database_path: str = None,
        **data,
    ):
        # Initialize Kuzu client
        super().__init__(stores_text=False, **data)
        self.index = self._sanitize_table_name(index)
        self.ws_id = ws_id
        self.database_path = database_path or KUZU_DATABASE_PATH
        self._database()

    def _database(self) -> Any:
        """Get or initialize a shared Kuzu database instance."""
        import kuzu  # noqa: WPS433 — lazy import

        actual_db_path = self._resolve_db_path()

        if actual_db_path not in KuzuLabelledPropertyGraph.kuzu_database_cache:
            db_path = Path(actual_db_path)
            parent_dir = db_path.parent

            try:
                parent_dir.mkdir(parents=True, exist_ok=True)
                logger.debug(f"Ensured parent directory exists: {parent_dir}")
            except Exception as e:
                logger.error(f"Failed to create parent directory {parent_dir}: {e}")
                raise RuntimeError(f"Cannot create database directory: {e}")

            try:
                logger.debug(f"Initializing KuzuDB database at: {actual_db_path}")
                db = kuzu.Database(actual_db_path)
                KuzuLabelledPropertyGraph.kuzu_database_cache[actual_db_path] = db
                logger.debug(f"KuzuDB database initialized successfully at: {actual_db_path}")

                if KUZU_MIGRATE:
                    logger.debug(f"Setting up schema for index: {self.index}")
                    self._setup_schema()
                    logger.debug(f"Schema setup completed for index: {self.index}")
            except Exception as e:
                logger.error(f"Failed to initialize KuzuDB at {actual_db_path}: {e}")
                raise RuntimeError(f"KuzuDB initialization failed: {e}")

        return KuzuLabelledPropertyGraph.kuzu_database_cache[actual_db_path]

    def _resolve_db_path(self) -> str:
        """Resolve actual DB path based on given database_path and index.

        Behaviour (in order):

        1. If ``database_path`` ends with ``.db`` it is treated as an exact
           single-file Kuzu DB path and used verbatim. This is the per-namespace
           layout used by :class:`NamespaceManager` (``{kb}/{ns}/graph.db``).
        2. Otherwise (legacy directory-style path), append ``{index}.db`` to it.
        """
        path_str = str(self.database_path)
        if path_str.endswith(".db"):
            actual_db_path = path_str
        elif (
            os.path.isdir(path_str)
            or path_str == KUZU_DATABASE_PATH
            or path_str.endswith("/")
        ):
            actual_db_path = os.path.join(path_str, f"{self.index}.db")
        else:
            actual_db_path = path_str
        return str(Path(actual_db_path).resolve())

    @classmethod
    def for_namespace(cls, namespace: str) -> "KuzuLabelledPropertyGraph":
        """Construct a graph bound to a namespace's per-namespace ``graph.db``.

        Convenience constructor used by :class:`NamespaceManager` and by the
        per-namespace storage layer. The Kuzu file lives at
        ``{KNOWLEDGE_DIR}/{namespace}/graph.db``.
        """
        from dashboard.knowledge.config import kuzu_db_path  # noqa: WPS433

        return cls(
            index=namespace,
            ws_id=namespace,
            database_path=str(kuzu_db_path(namespace)),
        )

    @property
    def connection(self) -> Any:
        """Get a new connection from the shared database instance."""
        import kuzu  # noqa: WPS433 — lazy import

        return kuzu.Connection(self._database(), num_threads=2)

    @staticmethod
    def _sanitize_table_name(name: str) -> str:
        """Replace special characters with underscore"""
        import re

        # Replace hyphens first, then other special chars
        name = name.replace("-", "_")
        return re.sub(r"[^a-zA-Z0-9_]", "", name)

    @staticmethod
    def _escape_string(value: str) -> str:
        """Escape string for safe use in Kuzu queries."""
        if value is None:
            return ""
        # Escape backslashes and double quotes for use with double-quoted strings
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    def _setup_schema(self):
        """Create tables and indexes for the graph."""
        try:
            conn = self.connection

            # First, install and load VECTOR extension before any table operations
            try:
                conn.execute("INSTALL vector")
                logger.debug("VECTOR extension installed")
            except Exception as e:
                logger.debug(f"VECTOR extension already installed or install failed: {e}")

            try:
                conn.execute("LOAD vector")
                logger.debug("VECTOR extension loaded")
            except Exception as e:
                logger.debug(f"VECTOR extension already loaded or load failed: {e}")

            # Check if Node table already exists by trying to query it
            try:
                # Try a simple query to see if the table exists
                conn.execute("MATCH (n:Node) RETURN n LIMIT 1")
                logger.debug(f"Node table already exists for index: {self.index}")
                return
            except:
                # Table doesn't exist, create it
                pass

            # Create Node table with required properties
            # Note: Kuzu requires fixed-size arrays for vector fields
            # Dimension is configurable via EMBEDDING_DIMENSION
            conn.execute(
                f"""
                CREATE NODE TABLE Node(
                    id STRING PRIMARY KEY,
                    text STRING,
                    name STRING,
                    label STRING,
                    properties STRING,
                    embedding DOUBLE[{EMBEDDING_DIMENSION}],
                    ws_id STRING,
                    index_ STRING,
                    category_id STRING DEFAULT "",
                    weight DOUBLE DEFAULT 1.0
                )
            """
            )

            # Create Relation table for relationships
            conn.execute(
                """
                CREATE REL TABLE RELATES(
                    FROM Node TO Node,
                    relation_label STRING,
                    relation_properties STRING,
                    index_ STRING,
                    weight DOUBLE DEFAULT 1.0
                )
            """
            )
            logger.debug("RELATES table created successfully")

            # Create vector index for embedding similarity search
            self._create_vector_index(conn)

            logger.debug(f"Schema setup completed for index: {self.index}")
        except Exception as e:
            logger.error(f"Failed to create schema: {e}")

    def _ensure_vector_index_exists(self, conn):
        """Ensure vector index exists on existing table."""
        try:
            # Try to create vector index (will fail gracefully if exists)
            self._create_vector_index(conn)
        except Exception as e:
            logger.debug(f"Vector index might already exist: {e}")

    def _create_vector_index(self, conn):
        """Create vector index for embedding similarity search."""
        try:
            conn.execute(
                """
                CALL CREATE_VECTOR_INDEX(
                    'Node',
                    'node_embedding_index',
                    'embedding',
                    metric := 'cosine'
                )
                """
            )
            logger.debug(f"Vector index 'node_embedding_index' created successfully for index: {self.index}")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                logger.debug(f"Vector index already exists: {e}")
            else:
                logger.warning(f"Could not create vector index: {e}")
                # This is not a fatal error - the system can still work without vector search

    @kuzu_retry_decorator
    def get_all_nodes(self, **kwargs) -> List[LabelledNode]:
        """Get all nodes with optional label type filter and vector similarity search."""
        label_type = kwargs.get("label_type", None)
        context_ = kwargs.get("context", "")

        category_id = kwargs.get("category_id", None)

        conn = self.connection

        # For Kuzu, we'll use simpler syntax without complex parameter binding
        try:
            if context_ != "":
                # Get embedding for the context (but don't use it for now in the query)

                embedder = _get_embedder()
                query_embedding = embedder.embed_one(context_)
                logger.info(f"Query embedding length: {len(query_embedding)}")
                # Use vector similarity search if we have a context embedding
                if query_embedding is not None:
                    # Vector similarity search using QUERY_VECTOR_INDEX
                    try:
                        # Get limit from kwargs, default to 50 for vector search
                        limit = kwargs.get("limit", 50)
                        vector_parameters = {"query_vector": query_embedding, "limit": limit}

                        # Use simple vector query and filter results in Python
                        vector_query = """
                            CALL QUERY_VECTOR_INDEX(
                                'Node',
                                'node_embedding_index',
                                $query_vector,
                                $limit,
                                efs := 500
                            )
                            RETURN node
                            ORDER BY distance
                        """

                        result = conn.execute(vector_query, vector_parameters)
                        nodes = []
                        for row in result.get_n(limit):
                            node_data = dict(row[0])  # Convert to dict

                            # Filter by label_type if specified
                            if label_type == "entity" and node_data.get("label") == "text_chunk":
                                continue
                            elif label_type == "text_chunk" and node_data.get("label") != "text_chunk":
                                continue

                            # Filter by category_id if specified
                            if category_id is not None:
                                node_cat = node_data.get("category_id")
                                if str(node_cat) != str(category_id):
                                    continue

                            nodes.append(self._from_record_to_node(node_data, load_entity=label_type))

                            if len(nodes) >= limit:
                                break

                        return nodes

                    except Exception as e:
                        logger.error(f"Failed to query vector index: {e}")

            # Build dynamic query with parameterized conditions
            conditions = ["n.index_ = $index"]
            parameters = {"index": self.index}

            # Add label filter
            if label_type and label_type == "entity":
                conditions.append('n.label <> "text_chunk"')
            elif label_type and label_type == "text_chunk":
                conditions.append('n.label = "text_chunk"')
            elif label_type and label_type not in ["entity", "text_chunk"]:
                conditions.append("n.label = $label_type")
                parameters["label_type"] = label_type

            # Add category filter
            if category_id is not None:
                conditions.append("n.category_id = $category_id")
                parameters["category_id"] = str(category_id)

            # Build and execute query
            where_clause = " AND ".join(conditions)
            query = f"""
                MATCH (n:Node)
                WHERE {where_clause}
                RETURN n
            """
            # Check if user wants NetworkX graph instead of node list
            if kwargs.get("graph", False):
                try:
                    # Build dynamic graph query with parameterized conditions
                    graph_conditions = [
                        "u.index_ = $index",
                        "m.index_ = $index",
                        "u.ws_id = $ws_id",
                        "m.ws_id = $ws_id",
                        "r.index_ = $index",
                    ]
                    graph_parameters = {"index": self.index, "ws_id": self.ws_id}

                    # Add category filter for graph
                    if category_id is not None:
                        graph_conditions.append("(u.category_id = $category_id OR m.category_id = $category_id)")
                        graph_parameters["category_id"] = str(category_id)

                    graph_where_clause = " AND ".join(graph_conditions)
                    graph_query = f"""
                        MATCH (u:Node)-[r:RELATES]->(m:Node)
                        WHERE {graph_where_clause}
                        RETURN u, r, m
                    """

                    graph_result = conn.execute(graph_query, graph_parameters)
                    G = graph_result.get_as_networkx(directed=False)
                    return G
                except Exception as e:
                    logger.warning(f"Failed to build NetworkX graph: {e}, falling back to nodes")
                    # Fall through to regular node processing

            result = conn.execute(query, parameters)
            nodes = []
            for row in result.get_all():
                node_data = dict(row[0])  # Convert to dict
                nodes.append(self._from_record_to_node(node_data, load_entity=label_type))
            return nodes
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    def count_entities(self) -> int:
        """Count entity nodes (excluding text_chunk) via lightweight Cypher.

        Runs ``MATCH (a:Node) WHERE a.label <> 'text_chunk' AND a.index_ = $index
        RETURN count(a)`` — much cheaper than ``get_all_nodes(label_type='entity')``
        because it never materialises full node objects.

        Returns 0 on any failure (schema not set up yet, empty graph, etc.).
        """
        try:
            conn = self.connection
            result = conn.execute(
                """
                MATCH (a:Node)
                WHERE a.label <> 'text_chunk'
                RETURN count(a) AS no_entities
                """,
            )
            row = result.get_next()
            return int(row[0]) if row else 0
        except Exception as exc:
            logger.debug("count_entities failed for index=%s: %s", self.index, exc)
            return 0

    def count_chunks(self) -> int:
        """Count text_chunk nodes via lightweight Cypher.

        Returns 0 on any failure.
        """
        try:
            conn = self.connection
            result = conn.execute(
                """
                MATCH (a:Node)
                WHERE a.label = 'text_chunk'
                RETURN count(a) AS no_chunks
                """,
            )
            row = result.get_next()
            return int(row[0]) if row else 0
        except Exception as exc:
            logger.debug("count_chunks failed for index=%s: %s", self.index, exc)
            return 0

    def count_relations(self) -> int:
        """Count relation edges via lightweight Cypher.

        Returns 0 on any failure.
        """
        try:
            conn = self.connection
            result = conn.execute(
                """
                MATCH (:Node)-[r:RELATES]->(:Node)
                RETURN count(r) AS no_relations
                """,
            )
            row = result.get_next()
            return int(row[0]) if row else 0
        except Exception as exc:
            logger.debug("count_relations failed for index=%s: %s", self.index, exc)
            return 0

    @kuzu_retry_decorator
    def get_all_relations(self) -> List[Relation]:
        """Get all relations in the graph."""
        conn = self.connection

        try:
            result = conn.execute(
                """
                MATCH (source:Node)-[r:RELATES]->(target:Node)
                WHERE source.index_ = $index AND target.index_ = $index
                AND source.ws_id = $ws_id AND target.ws_id = $ws_id
                AND r.index_ = $index
                RETURN source, r, target
                """,
                parameters={"index": self.index, "ws_id": self.ws_id},
            )

            relations = []
            for row in result:
                source_node = self._from_record_to_node(dict(row[0]))
                rel = dict(row[1])
                target_node = self._from_record_to_node(dict(row[2]))

                relations.append(
                    Relation(
                        source_id=source_node.id,
                        target_id=target_node.id,
                        label=rel.get("relation_label", "RELATES"),
                        properties=json.loads(rel.get("relation_properties", "{}")),
                    )
                )

            return relations
        except Exception as e:
            logger.error(f"Get relations failed: {e}")
            return []

    @kuzu_retry_decorator
    def get_triplets(self, ids: list = None) -> List[Triplet]:
        """Get all triplets (subject, relation, object) from the graph.

        Args:
            ids: Optional list of node IDs to filter by. When provided, returns triplets
                 where either source.id OR target.id is in the ids list (neighbor network).
        """
        conn = self.connection

        try:
            # Build dynamic query based on whether ids are provided
            if ids and len(ids) > 0:
                # Filter by IDs - get neighbor network where source OR target is in ids list
                query = """
                MATCH (source:Node)-[r:RELATES]->(target:Node)
                WHERE (source.id IN $ids OR target.id IN $ids)
                RETURN source, r, target
                """
                parameters = {"ids": [str(id_) for id_ in ids]}
            else:
                # Get all triplets when no IDs specified
                query = """
                MATCH (source:Node)-[r:RELATES]->(target:Node)
                WHERE source.index_ = $index AND target.index_ = $index
                AND source.ws_id = $ws_id AND target.ws_id = $ws_id
                AND r.index_ = $index
                RETURN source, r, target
                """
                parameters = {"index": self.index, "ws_id": self.ws_id}

            result = conn.execute(query, parameters)

            triplets = []
            for row in result:
                source_node = self._from_record_to_node(dict(row[0]))
                rel = dict(row[1])
                target_node = self._from_record_to_node(dict(row[2]))

                relation_properties = rel.get("relation_properties", "{}")
                if isinstance(relation_properties, str):
                    try:
                        relation_properties = json.loads(relation_properties)
                    except json.JSONDecodeError:
                        relation_properties = {}

                relation = Relation(
                    source_id=str(source_node.id),
                    target_id=str(target_node.id),
                    label=rel.get("relation_label", "RELATES"),
                    properties=relation_properties,
                )

                triplets.append((source_node, relation, target_node))

            return triplets
        except Exception as e:
            logger.error(f"Get triplets failed: {e}")
            return []

    @kuzu_retry_decorator
    def add_node(self, node: LabelledNode) -> None:
        """Add a node to the graph."""
        logger.debug(f"Adding node {node.properties}. Length embedding: {len(node.embedding) if node.embedding else 0}")

        try:
            conn = self.connection
        except Exception as e:
            logger.debug(f"Got connection ERROR: {e}")
            raise e
        _text = ""
        _name = ""
        # Convert properties to JSON string for storage
        properties_json = json.dumps(node.properties) if node.properties else "{}"
        category_id = node.properties.get("category_id", "")
        weight = node.properties.get("weight", 0.1)

        if isinstance(node, ChunkNode):
            _text = node.text
            # For ChunkNode, name should be empty or the node label, not the label value
            _name = ""
        elif isinstance(node, EntityNode):
            _name = node.name

            # Check if this EntityNode already exists
            existing_node = self.get_node(node.id)

            if node.properties and "node_id" in node.properties:
                target_id = node.properties["node_id"]
                try:
                    target_node = self.get_node(target_id)

                    if target_node:
                        _text = target_node.text if hasattr(target_node, "text") else ""

                        # If the EntityNode already exists, create a relationship and merge embeddings
                        if existing_node:
                            logger.debug(
                                f"EntityNode already exists: {node.id}. Creating relationship to target: {target_id}"
                            )
                            # Generate new embedding from concatenated text
                            existing_text = ""
                            if hasattr(existing_node, "text") and existing_node.text:
                                existing_text = existing_node.text
                            elif existing_node.properties and "text" in existing_node.properties:
                                existing_text = existing_node.properties["text"]

                            new_text = ""
                            if hasattr(node, "text") and node.text:
                                new_text = node.text
                            elif node.properties and "text" in node.properties:
                                new_text = node.properties["text"]

                            # Concatenate text and generate new embedding
                            if existing_text or new_text:
                                concat_text = f"{existing_text} {new_text}".strip()
                                if concat_text:
                                    embedder = _get_embedder()
                                    new_embedding = embedder.embed_one(concat_text)

                                    # Update the node with the new embedding and text
                                    self._escape_string(str(node.id))
                                    self._escape_string(self.index)
                                    self._escape_string(self.ws_id)
                                    self._escape_string(concat_text)
                                    self._escape_string(str(category_id))

                                    # KuzuDB does not support UPDATE with embedding, so we need to delete and insert
                                    logger.debug("Updating embedding and text for existing node using delete+insert")
                                    existing_result = conn.execute(
                                        """
                                        MATCH (n:Node)
                                        WHERE n.id = $id AND n.index_ = $index AND n.ws_id = $ws_id
                                        RETURN n.name, n.label, n.properties, n.weight
                                        """,
                                        parameters={
                                            "id": str(node.id),
                                            "index": self.index,
                                            "ws_id": self.ws_id,
                                        },
                                    )

                                    existing_props = None
                                    for row in existing_result:
                                        existing_props = {
                                            "name": row[0],
                                            "label": row[1],
                                            "properties": row[2],
                                            "weight": row[3] if row[3] is not None else 1.0,
                                        }
                                        break

                                    if existing_props:
                                        # Save all relationships before deleting the node
                                        logger.debug("Saving relationships before node deletion")
                                        saved_relationships = self._save_node_relationships(conn, str(node.id))

                                        # Delete the existing node and its relationships
                                        conn.execute(
                                            """
                                            MATCH (n:Node)
                                            WHERE n.id = $id AND n.index_ = $index AND n.ws_id = $ws_id
                                            DETACH DELETE n
                                            """,
                                            parameters={
                                                "id": str(node.id),
                                                "index": self.index,
                                                "ws_id": self.ws_id,
                                            },
                                        )

                                        # Insert the node with updated embedding and text
                                        conn.execute(
                                            """
                                            CREATE (n:Node {
                                                id: $id,
                                                text: $text,
                                                name: $name,
                                                label: $label,
                                                properties: $properties,
                                                embedding: $embedding,
                                                ws_id: $ws_id,
                                                index_: $index,
                                                category_id: $category_id,
                                                weight: $weight
                                            })
                                            """,
                                            parameters={
                                                "id": str(node.id),
                                                "text": concat_text,
                                                "name": existing_props["name"],
                                                "label": existing_props["label"],
                                                "properties": existing_props["properties"],
                                                "embedding": new_embedding,
                                                "ws_id": self.ws_id,
                                                "index": self.index,
                                                "category_id": str(category_id),
                                                "weight": weight,
                                            },
                                        )

                                        # Restore all saved relationships
                                        logger.debug(f"Restoring {len(saved_relationships)} relationships")
                                        self._restore_node_relationships(conn, saved_relationships)

                            # Create relationship between existing EntityNode and target ChunkNode
                            relation = Relation(
                                source_id=str(node.id),
                                target_id=str(target_id),
                                label="in",
                                properties={},
                            )
                            self.add_relation(relation)
                            logger.debug(
                                f"Created 'in' relationship from EntityNode {node.id} to ChunkNode {target_id}"
                            )

                            return
                except Exception as e:
                    logger.error(f"Error processing EntityNode: {e}")

        # Create or merge the node
        try:
            # Handle embedding — every node MUST have an embedding so it is
            # discoverable via KuzuDB's QUERY_VECTOR_INDEX.  If the node
            # arrives without one (embedder failure, legacy path) we generate
            # it here from the node's textual content.
            embedding_value = node.embedding if node.embedding else None
            if not embedding_value:
                try:
                    embedder = _get_embedder()
                    if isinstance(node, EntityNode):
                        embed_text = ".".join([
                            str(getattr(node, "name", "")),
                            str(getattr(node, "label", "")),
                            str((node.properties or {}).get("entity_description", "")),
                        ])
                    else:
                        embed_text = _text or ""
                    if embed_text and embed_text.strip():
                        embedding_value = embedder.embed_one(embed_text)
                        logger.debug("Auto-generated embedding for node %s", node.id)
                except Exception as emb_exc:  # noqa: BLE001
                    logger.warning("Could not auto-generate embedding for node %s: %s", node.id, emb_exc)

            # Use CREATE instead of MERGE for simpler syntax in Kuzu
            # First check if node exists - use string formatting with escaping
            self._escape_string(str(node.id))
            self._escape_string(self.index)

            existing_check = conn.execute(
                """
                MATCH (n:Node)
                WHERE n.id = $node_id AND n.index_ = $index
                RETURN n
                """,
                parameters={"node_id": str(node.id), "index": self.index},
            )

            node_exists = False
            for row in existing_check:
                node_exists = True
                break

            # Use string escaping for safer execution with single quotes
            if node_exists:
                # Update existing node - use DELETE+INSERT if embedding needs update
                self._escape_string(_text)
                self._escape_string(_name)
                self._escape_string(str(node.label))
                self._escape_string(properties_json)
                self._escape_string(self.ws_id)
                self._escape_string(str(category_id))

                if embedding_value:
                    # If embedding needs to be updated, use DELETE+INSERT approach
                    # First get existing properties to preserve them
                    existing_result = conn.execute(
                        """
                        MATCH (n:Node)
                        WHERE n.id = $node_id AND n.index_ = $index
                        RETURN n.weight
                        """,
                        parameters={"node_id": str(node.id), "index": self.index},
                    )

                    for row in existing_result:
                        row[0] if row[0] is not None else 1.0
                        break

                    # Save all relationships before deleting the node
                    logger.debug("Saving relationships before node deletion")
                    saved_relationships = self._save_node_relationships(conn, str(node.id))

                    # Delete the existing node and its relationships
                    conn.execute(
                        """
                        MATCH (n:Node)
                        WHERE n.id = $node_id AND n.index_ = $index
                        DETACH DELETE n
                        """,
                        parameters={"node_id": str(node.id), "index": self.index},
                    )

                    # Insert the node with updated properties including embedding
                    conn.execute(
                        """
                        CREATE (n:Node {
                            id: $node_id,
                            text: $text,
                            name: $name,
                            label: $label,
                            properties: $properties,
                            embedding: $embedding,
                            ws_id: $ws_id,
                            index_: $index,
                            category_id: $category_id,
                            weight: $weight
                        })
                        """,
                        parameters={
                            "node_id": str(node.id),
                            "text": _text,
                            "name": _name,
                            "label": str(node.label),
                            "properties": properties_json,
                            "embedding": embedding_value,
                            "ws_id": self.ws_id,
                            "index": self.index,
                            "category_id": str(category_id),
                            "weight": weight,
                        },
                    )

                    # Restore all saved relationships
                    logger.debug(f"Restoring {len(saved_relationships)} relationships")
                    self._restore_node_relationships(conn, saved_relationships)
                else:
                    # No embedding update needed, use regular SET operation
                    set_clauses = [
                        "n.text = $text",
                        "n.name = $name",
                        "n.label = $label",
                        "n.properties = $properties",
                        "n.ws_id = $ws_id",
                        "n.category_id = $category_id",
                    ]

                    parameters = {
                        "node_id": str(node.id),
                        "index": self.index,
                        "text": _text,
                        "name": _name,
                        "label": str(node.label),
                        "properties": properties_json,
                        "ws_id": self.ws_id,
                        "category_id": str(category_id),
                    }

                    set_clause = ", ".join(set_clauses)

                    conn.execute(
                        f"""
                        MATCH (n:Node)
                        WHERE n.id = $node_id AND n.index_ = $index
                        SET {set_clause}
                        """,
                        parameters=parameters,
                    )
            else:
                # Guard: reject nodes that still have no embedding after all
                # upstream + auto-generation attempts. A node without an
                # embedding is invisible to QUERY_VECTOR_INDEX and would
                # silently pollute the graph.
                if not embedding_value:
                    logger.error(
                        "Node %s has no embedding after all generation attempts; "
                        "skipping persistence to avoid invisible nodes",
                        node.id,
                    )
                    return

                # Create new node
                self._escape_string(_text)
                self._escape_string(_name)
                self._escape_string(str(node.label))
                self._escape_string(properties_json)
                self._escape_string(self.ws_id)
                self._escape_string(str(category_id))

                # Build CREATE properties — embedding is always included
                # because the auto-generation logic above guarantees every
                # node has one.
                create_properties = {
                    "id": "$node_id",
                    "text": "$text",
                    "name": "$name",
                    "label": "$label",
                    "properties": "$properties",
                    "ws_id": "$ws_id",
                    "index_": "$index",
                    "category_id": "$category_id",
                    "weight": "$weight",
                    "embedding": "$embedding",
                }

                parameters = {
                    "node_id": str(node.id),
                    "text": _text,
                    "name": _name,
                    "label": str(node.label),
                    "properties": properties_json,
                    "ws_id": self.ws_id,
                    "index": self.index,
                    "category_id": str(category_id),
                    "weight": weight,
                    "embedding": embedding_value,
                }

                # Build the properties string for CREATE
                properties_str = ", ".join([f"{k}: {v}" for k, v in create_properties.items()])

                conn.execute(
                    f"""
                    CREATE (n:Node {{
                        {properties_str}
                    }})
                    """,
                    parameters=parameters,
                )

            # After successfully creating the node, check if it's an EntityNode with node_id
            # and create the relationship to the ChunkNode
            if isinstance(node, EntityNode) and node.properties and "node_id" in node.properties:
                target_id = node.properties["node_id"]
                # Create relationship between EntityNode and target ChunkNode
                relation = Relation(
                    source_id=str(node.id),
                    target_id=str(target_id),
                    label="in",
                    properties={},
                )
                self.add_relation(relation)
                logger.debug(f"Created 'in' relationship from EntityNode {node.id} to ChunkNode {target_id}")

        except Exception as e:
            logger.error(f"Failed to add node: {e}")

    def add_nodes(self, nodes: List[LabelledNode]) -> None:
        """Bulk insert nodes for better performance."""
        import time as _time

        if not nodes:
            return

        t0 = _time.monotonic()
        batch_size = 25
        for i in range(0, len(nodes), batch_size):
            batch = nodes[i : i + batch_size]
            for node in batch:
                self.add_node(node)
        dt = _time.monotonic() - t0
        logger.info(
            "[TRACE] kuzu/add_nodes: %.3fs, %d nodes",
            dt, len(nodes),
        )

    def _from_record_to_node(self, record: Dict[str, Any], load_entity: str = None) -> LabelledNode:
        """Convert a Kuzu record to a LabelledNode."""
        properties = record.get("properties", "{}")
        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except json.JSONDecodeError:
                properties = {}

        # Handle category_id from new column or fallback to properties for backward compatibility
        category_id = record.get("category_id", "")
        if not category_id and "category_id" in properties:
            category_id = properties["category_id"]

        # Ensure category_id is in properties for consistency
        if category_id:
            properties["category_id"] = category_id

        # Check the label to determine node type, or use load_entity hint
        node_label = record.get("label", "")
        node_name = record.get("name", "")

        # EntityNode has a non-empty name field, or specific label types, or load_entity hint
        if node_label != "text_chunk":  # name field is populated and different from label
            return EntityNode(
                name=node_name or record.get("text", ""),
                label=record.get("label", ""),
                properties=properties,
                embedding=record.get("embedding", []),
                id_=record.get("id"),
            )

        return ChunkNode(
            text=record.get("text", ""),
            id_=record.get("id"),
            label=record.get("label", ""),
            embedding=record.get("embedding", []),
            properties=properties,
        )

    @kuzu_retry_decorator
    def get_node(self, id_: str) -> Optional[LabelledNode]:
        """Get a node by ID."""
        conn = self.connection
        try:
            result = conn.execute(
                """
                MATCH (n:Node)
                WHERE n.id = $id AND n.index_ = $index AND n.ws_id = $ws_id
                RETURN n
                """,
                parameters={"id": str(id_), "index": self.index, "ws_id": self.ws_id},
            )

            for row in result:
                return self._from_record_to_node(dict(row[0]))
            return None
        except Exception as e:
            logger.error(f"Failed to get node: {e}")
            return None

    @kuzu_retry_decorator
    def add_relation(self, relation: Relation) -> None:
        """Add a relation between two nodes."""
        import time as _time

        conn = self.connection
        t0 = _time.monotonic()
        try:
            # Convert properties to JSON string
            properties_json = json.dumps(relation.properties) if relation.properties else "{}"

            # Use parameterized queries for safer execution
            conn.execute(
                """
                MATCH (source:Node), (target:Node)
                WHERE source.id = $source_id AND source.index_ = $index_ AND source.ws_id = $ws_id
                AND target.id = $target_id AND target.index_ = $index_ AND target.ws_id = $ws_id
                CREATE (source)-[:RELATES {
                    relation_label: $relation_label,
                    relation_properties: $relation_properties,
                    index_: $index_
                }]->(target)
            """,
                {
                    "source_id": str(relation.source_id),
                    "target_id": str(relation.target_id),
                    "relation_label": str(relation.label),
                    "relation_properties": properties_json,
                    "index_": self.index,
                    "ws_id": self.ws_id,
                },
            )
            dt = _time.monotonic() - t0
            logger.debug(
                "[TRACE] kuzu/add_relation: %.3fs, %s -[%s]-> %s",
                dt, relation.source_id, relation.label, relation.target_id,
            )

        except Exception as e:
            dt = _time.monotonic() - t0
            logger.error("Failed to add relation (%.3fs): %s", dt, e)

    @kuzu_retry_decorator
    def add_triplet(self, triplet: Triplet) -> None:
        """Add a triplet (subject, relation, object) to the graph."""
        subject, relation, obj = triplet

        # Add nodes first
        self.add_node(subject)
        self.add_node(obj)

        # Add relation
        relation_data = Relation(
            source_id=str(subject.id),
            target_id=str(obj.id),
            label=relation.label,
            properties=relation.properties,
        )
        self.add_relation(relation_data)

    @kuzu_retry_decorator
    def delete_node(self, node: LabelledNode) -> None:
        """Delete a node and its relationships."""
        conn = self.connection
        try:
            conn.execute(
                """
                MATCH (n:Node)
                WHERE n.id = $id AND n.index_ = $index_ AND n.ws_id = $ws_id
                DETACH DELETE n
            """,
                {"id": str(node.id), "index_": self.index, "ws_id": self.ws_id},
            )
        except Exception as e:
            logger.error(f"Failed to delete node: {e}")

    @kuzu_retry_decorator
    def delete_relation(self, rel: Relation) -> None:
        """Delete a specific relation."""
        conn = self.connection
        try:
            conn.execute(
                """
                MATCH (source:Node)-[r:RELATES]->(target:Node)
                WHERE source.id = $source_id AND source.index_ = $index_ AND source.ws_id = $ws_id
                AND target.id = $target_id AND target.index_ = $index_ AND target.ws_id = $ws_id
                AND r.relation_label = $relation_label AND r.index_ = $index_
                DELETE r
            """,
                {
                    "source_id": str(rel.source_id),
                    "target_id": str(rel.target_id),
                    "relation_label": str(rel.label),
                    "index_": self.index,
                    "ws_id": self.ws_id,
                },
            )
        except Exception as e:
            logger.error(f"Failed to delete relation: {e}")

    def delete_triplet(self, triplet: Triplet) -> None:
        """Delete a triplet (only the relation, not the nodes)."""
        subject, relation, obj = triplet
        relation_data = Relation(
            source_id=subject.id,
            target_id=obj.id,
            label=relation.label,
            properties=relation.properties,
        )
        self.delete_relation(relation_data)

    @kuzu_retry_decorator
    def get_by_ids(self, ids: List[str]) -> List[LabelledNode]:
        """Get multiple nodes by their IDs."""
        if not ids:
            return []

        conn = self.connection
        try:
            # Use parameterized queries for the IN clause
            result = conn.execute(
                """
                MATCH (n:Node)
                WHERE n.id IN $ids AND n.index_ = $index_ AND n.ws_id = $ws_id
                RETURN n
            """,
                {"ids": [str(id_) for id_ in ids], "index_": self.index, "ws_id": self.ws_id},
            )

            nodes = []
            for row in result:
                nodes.append(self._from_record_to_node(dict(row[0])))
            return nodes
        except Exception as e:
            logger.error(f"Failed to get nodes by IDs: {e}")
            return []

    def pagerank(self, personalize: dict, **kwargs):
        """
        Compute PageRank scores with personalization, category weighting, and centrality measures.

        Args:
            personalize: Dictionary of {node_id: score} for personalization
            **kwargs: Additional parameters including category_id for filtering

        Returns:
            List of tuples (node_id, score) sorted by PageRank score
        """
        import networkx as nx  # noqa: WPS433 — lazy import

        try:
            # Get category_id for weighting if provided
            category_id = kwargs.get("category_id", None)
            category_weight_boost = kwargs.get("category_weight_boost", 1.5)

            # Get entity graph with relationships (don't filter by category_id here)
            G = self.get_all_nodes(label_type="entity", graph=True, **kwargs)  # G networkx.MultiGraph

            # Calculate text-based personalization scores
            text_scores = self._calculate_text_personalization_scores(G, personalize)

            # Apply category weighting if category_id is specified
            category_scores = self._calculate_category_scores(G, category_id, category_weight_boost)

            # Calculate fast centrality for additional weighting
            centrality_algorithm = kwargs.get("centrality_algorithm", "eigenvector")
            centrality_scores = self._calculate_centrality_scores(G, centrality_algorithm)

            # Combine all scoring mechanisms
            combined_personalization = self._combine_personalization_scores(
                G, personalize, text_scores, category_scores, centrality_scores
            )

            # Update edge weights based on node importance and relationship types
            self._update_edge_weights(G, combined_personalization)

            # Run PageRank with enhanced personalization
            # Convert MultiGraph to simple Graph for PageRank if needed
            if isinstance(G, nx.MultiGraph):
                # Convert to simple graph for PageRank calculation
                pagerank_graph = nx.Graph()
                pagerank_graph.add_nodes_from(G.nodes(data=True))
                for u, v, key, data in G.edges(data=True, keys=True):
                    # Sum weights across multi-edges for clearer transition probabilities
                    weight = data.get("weight", 1.0)
                    if pagerank_graph.has_edge(u, v):
                        pagerank_graph.edges[u, v]["weight"] = pagerank_graph.edges[u, v].get("weight", 0.0) + weight
                    else:
                        pagerank_graph.add_edge(u, v, weight=weight)
            else:
                pagerank_graph = G

            # Prefer SciPy-based PageRank when available for performance on sparse graphs

            pagerank_scores = nx.pagerank(
                pagerank_graph,
                personalization=combined_personalization,
                alpha=0.85,
                weight="weight",
                max_iter=100,
                tol=1e-3,
            )

            # Map NetworkX node IDs back to original entity IDs and filter by score threshold
            original_results = []
            score_threshold = kwargs.get(
                "score_threshold", PAGERANK_SCORE_THRESHOLD
            )  # Use global threshold for filtering low scores

            for nx_node_id, score in pagerank_scores.items():
                # Filter out scores below threshold to focus on most relevant results
                if score > score_threshold:
                    # Get original entity ID from node data
                    original_id = G.nodes[nx_node_id].get("id", nx_node_id)
                    original_results.append((original_id, score))

            sorted_results = sorted(original_results, key=lambda x: x[1], reverse=True)

            logger.debug(
                f"PageRank computed for {len(G.nodes())} nodes, {len(G.edges())} edges, "
                f"filtered to {len(sorted_results)} results above threshold {score_threshold}"
            )
            return sorted_results

        except Exception as e:
            logger.error(f"PageRank computation failed: {e}")
            return []

    def _calculate_text_personalization_scores(self, G, personalize: dict) -> dict:
        """Text personalization disabled by default to simplify PageRank.

        Returns zeros for all nodes. Kept for API compatibility.
        """
        return {node_id: 0 for node_id in G.nodes()}

    def _calculate_category_scores(self, G, category_id: str = None, boost_factor: float = 0) -> dict:
        """Category boosting disabled by default to avoid category-based filtering in scoring.

        Returns zeros for all nodes. Kept for API compatibility.
        """
        return {node_id: 0 for node_id in G.nodes()}

    def _calculate_centrality_scores(self, G, algorithm: str = "eigenvector") -> dict:
        """Calculate fast centrality alternatives for PageRank enhancement.

        Handles disconnected graphs by processing connected components separately
        for eigenvector centrality, or using robust alternatives.

        **Algorithm Best Practices for Graph Types:**

        - **eigenvector**: Best for connected graphs. For disconnected graphs,
          calculates per component and normalizes globally. Excellent for finding
          influential nodes in well-connected networks.

        - **katz**: Most robust for disconnected graphs. Works well across all
          graph types and provides consistent results. Good general-purpose choice.

        - **degree**: Fastest baseline. Works for any graph structure. Simple but
          effective for basic node importance ranking.

        - **hits**: Best for knowledge graphs with authority relationships.
          Handles disconnected graphs per component. Good for academic/citation networks.

        - **disabled**: Returns zero scores for all nodes. Use when centrality
          enhancement is not needed.

        Args:
            algorithm: "disabled" | "eigenvector" | "hits" | "katz" | "degree"
                      Default: "eigenvector" for balanced performance

        Returns:
            Dict of centrality scores for each node. All scores are non-negative
            and normalized to [0, 1] range.

        Note:
            For disconnected graphs, eigenvector and HITS centrality are calculated
            per connected component to avoid mathematical inconsistencies, then
            normalized globally to maintain relative importance across components.
        """
        import networkx as nx  # noqa: WPS433 — lazy import

        if algorithm == "disabled":
            return {node_id: 0 for node_id in G.nodes()}

        # Handle empty graph
        if len(G.nodes()) == 0:
            return {}

        try:
            # Convert MultiGraph to simple Graph for centrality calculations if needed
            if isinstance(G, nx.MultiGraph):
                simple_G = nx.Graph()
                simple_G.add_nodes_from(G.nodes(data=True))
                for u, v, key, data in G.edges(data=True, keys=True):
                    if not simple_G.has_edge(u, v):
                        simple_G.add_edge(u, v, **data)
                calc_graph = simple_G
            else:
                calc_graph = G

            # Check if graph is connected
            is_connected = nx.is_connected(calc_graph)

            if algorithm == "eigenvector":
                if is_connected:
                    # For connected graphs, use standard eigenvector centrality
                    centrality = nx.eigenvector_centrality_numpy(calc_graph)
                else:
                    # For disconnected graphs, handle each component separately
                    centrality = self._calculate_eigenvector_per_component(calc_graph)
            elif algorithm == "hits":
                # HITS authority scores - Best for knowledge graphs
                if is_connected:
                    authority_scores, _ = nx.hits(calc_graph, max_iter=100)
                    centrality = authority_scores
                else:
                    # For disconnected graphs, calculate HITS per component
                    centrality = self._calculate_hits_per_component(calc_graph)
            elif algorithm == "katz":
                # Katz centrality - Most robust for disconnected graphs
                centrality = nx.katz_centrality_numpy(calc_graph, alpha=0.1)
            elif algorithm == "degree":
                # Degree centrality - Fastest baseline, works for any graph
                centrality = nx.degree_centrality(calc_graph)
            else:
                logger.warning(f"Unknown centrality algorithm: {algorithm}, falling back to degree")
                centrality = nx.degree_centrality(calc_graph)

            return centrality

        except Exception as e:
            logger.warning(f"Centrality calculation failed for {algorithm}: {e}")
            # Fallback to degree centrality
            try:
                return nx.degree_centrality(calc_graph)
            except:
                return {node_id: 0.1 for node_id in G.nodes()}

    def _calculate_eigenvector_per_component(self, G) -> dict:
        """Calculate eigenvector centrality per connected component.

        For disconnected graphs, eigenvector centrality is calculated separately
        for each connected component, then normalized globally.

        Args:
            G: NetworkX graph (should be simple graph, not MultiGraph)

        Returns:
            Dict of eigenvector centrality scores for all nodes
        """
        import networkx as nx  # noqa: WPS433 — lazy import

        all_centrality = {}

        try:
            components = list(nx.connected_components(G))

            for component in components:
                if len(component) == 1:
                    # Single node component gets a default score
                    node = list(component)[0]
                    all_centrality[node] = 1.0
                elif len(component) == 2:
                    # Two-node component: both nodes get equal scores
                    for node in component:
                        all_centrality[node] = 1.0
                else:
                    # Multi-node component: calculate eigenvector centrality
                    subgraph = G.subgraph(component)
                    try:
                        component_centrality = nx.eigenvector_centrality_numpy(subgraph)
                        all_centrality.update(component_centrality)
                    except Exception as e:
                        # If eigenvector fails for this component, use degree centrality
                        logger.warning(
                            f"Eigenvector centrality failed for component {component}: {e}, using degree centrality"
                        )
                        component_centrality = nx.degree_centrality(subgraph)
                        all_centrality.update(component_centrality)

            # Normalize scores across all components to maintain relative importance
            if all_centrality:
                max_score = max(all_centrality.values())
                if max_score > 0:
                    all_centrality = {node: score / max_score for node, score in all_centrality.items()}

            return all_centrality

        except Exception as e:
            logger.warning(f"Component-wise eigenvector calculation failed: {e}")
            # Final fallback to degree centrality
            return nx.degree_centrality(G)

    def _calculate_hits_per_component(self, G) -> dict:
        """Calculate HITS authority scores per connected component.

        Args:
            G: NetworkX graph (should be simple graph, not MultiGraph)

        Returns:
            Dict of HITS authority scores for all nodes
        """
        import networkx as nx  # noqa: WPS433 — lazy import

        all_authority = {}

        try:
            components = list(nx.connected_components(G))

            for component in components:
                if len(component) == 1:
                    # Single node component gets a default score
                    node = list(component)[0]
                    all_authority[node] = 1.0
                elif len(component) == 2:
                    # Two-node component: both nodes get equal scores
                    for node in component:
                        all_authority[node] = 1.0
                else:
                    # Multi-node component: calculate HITS
                    subgraph = G.subgraph(component)
                    try:
                        authority_scores, _ = nx.hits(subgraph, max_iter=100)

                        # Ensure all scores are non-negative (HITS can sometimes produce negative values)
                        min_score = min(authority_scores.values())
                        if min_score < 0:
                            # Shift all scores to be non-negative
                            authority_scores = {node: score - min_score for node, score in authority_scores.items()}

                        # If all scores are zero after normalization, use degree centrality
                        if all(score == 0 for score in authority_scores.values()):
                            logger.warning(
                                f"HITS produced all zero scores for component {component}, using degree centrality"
                            )
                            authority_scores = nx.degree_centrality(subgraph)

                        all_authority.update(authority_scores)

                    except Exception as e:
                        # If HITS fails for this component, use degree centrality
                        logger.warning(
                            f"HITS calculation failed for component {component}: {e}, using degree centrality"
                        )
                        component_centrality = nx.degree_centrality(subgraph)
                        all_authority.update(component_centrality)

            # Normalize scores across all components
            if all_authority:
                max_score = max(all_authority.values())
                if max_score > 0:
                    all_authority = {node: score / max_score for node, score in all_authority.items()}

            return all_authority

        except Exception as e:
            logger.warning(f"Component-wise HITS calculation failed: {e}")
            # Final fallback to degree centrality
            return nx.degree_centrality(G)

    def _combine_personalization_scores(
        self, G, personalize: dict, text_scores: dict, category_scores: dict, centrality_scores: dict
    ) -> dict:
        """Combine personalization scores with optional centrality enhancement."""
        combined_scores = {}

        # Check if any scoring mechanism is enabled
        has_centrality = any(score != 0 for score in centrality_scores.values())

        for node_id in G.nodes():
            # Get original entity ID for personalization lookup
            original_id = G.nodes[node_id].get("id", node_id)

            # Base personalization (direct ID matches only)
            base_score = personalize.get(node_id, 0) + personalize.get(original_id, 0)

            if has_centrality:
                # Include centrality if enabled
                centrality_score = centrality_scores.get(node_id, 0)
                final_score = base_score * 0.8 + centrality_score * 0.2  # 80% personalization, 20% centrality
            else:
                # Pure personalization mode
                final_score = base_score

            combined_scores[node_id] = max(final_score, 0.01)  # Ensure minimum score

        # Normalize scores to sum to 1 for proper personalization
        total_score = sum(combined_scores.values())
        if total_score > 0:
            combined_scores = {k: v / total_score for k, v in combined_scores.items()}
        else:
            num_nodes = len(G.nodes())
            if num_nodes > 0:
                uniform_score = 1.0 / num_nodes
                combined_scores = {node_id: uniform_score for node_id in G.nodes()}
            else:
                logger.warning("_combine_personalization_scores: No nodes found for uniform distribution")
                combined_scores = {}

        return combined_scores

    def _update_edge_weights(self, G, personalization_scores: dict):
        """Update edge weights based on node importance and relationship types."""
        import networkx as nx  # noqa: WPS433 — lazy import

        # Handle different NetworkX graph types (MultiGraph vs Graph)
        if isinstance(G, nx.MultiGraph):
            # For MultiGraph, edges have keys
            for source, target, key, edge_data in G.edges(data=True, keys=True):
                # Base weight from existing edge data
                base_weight = edge_data.get("weight", 1.0)

                # Node importance scores
                source_importance = personalization_scores.get(source, 0.1)
                target_importance = personalization_scores.get(target, 0.1)

                # Relationship type weighting - check various possible fields
                relation_type = (
                    edge_data.get("relation", None)
                    or edge_data.get("relation_label", None)
                    or edge_data.get("label", "RELATES")
                )
                rel_weight = self._get_relationship_weight(relation_type)

                # Combine weights
                final_weight = base_weight * 0.4 + (source_importance + target_importance) * 0.4 + rel_weight * 0.2

                # Ensure minimum weight for connectivity
                G.edges[source, target, key]["weight"] = max(final_weight, 0.1)
        else:
            # For regular Graph
            for source, target, edge_data in G.edges(data=True):
                # Base weight from existing edge data
                base_weight = edge_data.get("weight", 1.0)

                # Node importance scores
                source_importance = personalization_scores.get(source, 0.1)
                target_importance = personalization_scores.get(target, 0.1)

                # Relationship type weighting
                relation_type = (
                    edge_data.get("relation", None)
                    or edge_data.get("relation_label", None)
                    or edge_data.get("label", "RELATES")
                )
                rel_weight = self._get_relationship_weight(relation_type)

                # Combine weights
                final_weight = base_weight * 0.4 + (source_importance + target_importance) * 0.4 + rel_weight * 0.2

                # Ensure minimum weight for connectivity
                G.edges[source, target]["weight"] = max(final_weight, 0.1)

    def _get_relationship_weight(self, relation_type: str) -> float:
        """Get importance weight for different relationship types."""
        relationship_weights = {
            "CONTAINS": 1.5,
            "RELATED_TO": 1.2,
            "MENTIONS": 1.1,
            "REFERENCES": 1.0,
            "USES": 0.9,
            "ASSOCIATES": 0.8,
            "RELATES": 0.7,  # Default/generic relation
        }

        return relationship_weights.get(relation_type.upper(), 0.7)

    @kuzu_retry_decorator
    def get_nodes_with_relationships(
        self,
        source_category_id: Optional[str] = None,
        target_category_id: Optional[str] = None,
        source_label_type: Optional[str] = None,
        target_label_type: Optional[str] = None,
        relationship_label: Optional[str] = None,
        include_source: bool = False,
        include_target: bool = False,
        include_relationship: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get nodes with their relationships based on filtering criteria.

        Args:
            source_category_id: Filter by source node category ID
            target_category_id: Filter by target node category ID
            source_label_type: Filter by source node label type ('entity', 'chunk', etc.)
            target_label_type: Filter by target node label type ('entity', 'chunk', etc.)
            relationship_label: Filter by relationship label
            include_source: Include source node data in results
            include_target: Include target node data in results
            include_relationship: Include relationship data in results

        Returns:
            List of relationship dictionaries with optional node data
        """
        conn = self.connection

        # Build dynamic query based on filters using parameterized queries
        conditions = []
        parameters = {}

        if source_category_id:
            conditions.append("n.category_id = $source_category_id")
            parameters["source_category_id"] = source_category_id

        if target_category_id:
            conditions.append("m.category_id = $target_category_id")
            parameters["target_category_id"] = target_category_id

        if source_label_type:
            if source_label_type == "entity":
                conditions.append("n.label IN ['Person', 'Organization', 'Location']")
            elif source_label_type == "chunk":
                conditions.append("n.label = 'text_chunk'")

        if target_label_type:
            if target_label_type == "entity":
                conditions.append("m.label IN ['Person', 'Organization', 'Location']")
            elif target_label_type == "chunk":
                conditions.append("m.label = 'text_chunk'")

        if relationship_label:
            conditions.append("r.relation_label = $relationship_label")
            parameters["relationship_label"] = relationship_label

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        # Build return clause based on what should be included
        return_parts = []
        if include_source:
            return_parts.append("n")
        if include_target:
            return_parts.append("m")
        if include_relationship:
            return_parts.append("r")

        # Default to returning relationship info
        if not return_parts:
            return_parts = ["r"]

        return_clause = ", ".join(return_parts)

        query = f"""
        MATCH (n)-[r]->(m)
        WHERE {where_clause}
        RETURN {return_clause}
        """

        try:
            result = conn.execute(query, parameters)
            relationships = []

            while result.has_next():
                row = result.get_next()
                relationship_data = {}

                if include_source and "n" in return_parts:
                    n_idx = return_parts.index("n")
                    n_data = row[n_idx]
                    source_record = {
                        "id": n_data.get("id", ""),
                        "text": n_data.get("text", ""),
                        "name": n_data.get("name", ""),
                        "label": n_data.get("label", ""),
                        "properties": n_data.get("properties", "{}"),
                        "category_id": n_data.get("category_id", ""),
                    }
                    if isinstance(source_record["properties"], str):
                        try:
                            source_record["properties"] = json.loads(source_record["properties"])
                        except:
                            source_record["properties"] = {}
                    relationship_data["source"] = self._from_record_to_node(source_record)

                if include_target and "m" in return_parts:
                    m_idx = return_parts.index("m")
                    m_data = row[m_idx]
                    target_record = {
                        "id": m_data.get("id", ""),
                        "text": m_data.get("text", ""),
                        "name": m_data.get("name", ""),
                        "label": m_data.get("label", ""),
                        "properties": m_data.get("properties", "{}"),
                        "category_id": m_data.get("category_id", ""),
                    }
                    if isinstance(target_record["properties"], str):
                        try:
                            target_record["properties"] = json.loads(target_record["properties"])
                        except:
                            target_record["properties"] = {}
                    relationship_data["target"] = self._from_record_to_node(target_record)

                if include_relationship and "r" in return_parts:
                    r_idx = return_parts.index("r")
                    r_data = row[r_idx]
                    rel_props_str = r_data.get("relation_properties", "{}")
                    if isinstance(rel_props_str, str):
                        try:
                            rel_props = json.loads(rel_props_str)
                        except:
                            rel_props = {}
                    else:
                        rel_props = rel_props_str or {}
                    relationship_data["relationship"] = {
                        "label": r_data.get("relation_label", ""),
                        "properties": rel_props,
                    }

                relationships.append(relationship_data)

            return relationships

        except Exception as e:
            logger.error(f"Error getting nodes with relationships: {e}")
            return []

    @kuzu_retry_decorator
    def get_category_subgraph(self, category_id: str, include_cross_category: bool = True) -> Dict[str, Any]:
        """Extract a subgraph for a specific category.

        Args:
            category_id: The category ID to extract
            include_cross_category: Whether to include relationships to other categories

        Returns:
            Dictionary containing nodes, relationships, and statistics
        """
        conn = self.connection

        try:
            # Get all nodes in the category
            nodes_query = f"""
            MATCH (n)
            WHERE n.category_id = '{category_id}'
            RETURN n
            """

            result = conn.execute(nodes_query)
            nodes = []
            node_ids = set()

            while result.has_next():
                row = result.get_next()
                node_record = {
                    "id": row[0]["id"],
                    "text": row[0].get("text", ""),
                    "name": row[0].get("name", ""),
                    "label": row[0]["label"],
                    "properties": json.loads(row[0].get("properties", "{}")),
                    "category_id": row[0].get("category_id", ""),
                }
                nodes.append(self._from_record_to_node(node_record))
                node_ids.add(row[0]["id"])

            # Get relationships and target nodes
            if include_cross_category:
                # Get all relationships where source is in our category
                rel_query = f"""
                MATCH (n)-[r]->(m)
                WHERE n.category_id = '{category_id}'
                RETURN n, r, m
                """
            else:
                # Get only internal relationships
                rel_query = f"""
                MATCH (n)-[r]->(m)
                WHERE n.category_id = '{category_id}' AND m.category_id = '{category_id}'
                RETURN n, r, m
                """

            result = conn.execute(rel_query)
            relationships = []
            target_nodes = []
            target_node_ids = set()
            cross_category_targets = 0

            while result.has_next():
                row = result.get_next()
                source_id = row[0]["id"]
                target_id = row[2]["id"]
                target_category = row[2].get("category_id", "")

                # Count cross-category relationships
                if target_category != category_id:
                    cross_category_targets += 1

                # Collect target nodes (avoid duplicates)
                if target_id not in target_node_ids:
                    target_node_ids.add(target_id)
                    target_record = {
                        "id": row[2].get("id", ""),
                        "text": row[2].get("text", ""),
                        "name": row[2].get("name", ""),
                        "label": row[2].get("label", ""),
                        "properties": row[2].get("properties", "{}"),
                        "category_id": row[2].get("category_id", ""),
                    }
                    if isinstance(target_record["properties"], str):
                        try:
                            target_record["properties"] = json.loads(target_record["properties"])
                        except:
                            target_record["properties"] = {}
                    target_nodes.append(self._from_record_to_node(target_record))

                rel_props_str = row[1].get("relation_properties", "{}")
                if isinstance(rel_props_str, str):
                    try:
                        rel_props = json.loads(rel_props_str)
                    except:
                        rel_props = {}
                else:
                    rel_props = rel_props_str or {}
                relationships.append(
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "label": row[1].get("relation_label", ""),
                        "properties": rel_props,
                    }
                )

            # Calculate statistics
            stats = {
                "node_count": len(nodes),
                "relationship_count": len(relationships),
                "cross_category_targets": cross_category_targets,
            }

            return {
                "category_id": category_id,
                "nodes": nodes,
                "target_nodes": target_nodes,
                "relationships": relationships,
                "stats": stats,
            }

        except Exception as e:
            logger.error(f"Error getting category subgraph: {e}")
            return {
                "category_id": category_id,
                "nodes": [],
                "target_nodes": [],
                "relationships": [],
                "stats": {"node_count": 0, "relationship_count": 0, "cross_category_targets": 0},
            }

    def _has_weight_columns(self, conn=None) -> bool:
        """Check if weight columns exist in the database."""
        try:
            if conn is None:
                conn = self.connection

            # Try to query weight column from Node table
            result = conn.execute("DESCRIBE Node;")
            columns = result.get_all()

            # Check if weight column exists
            for col in columns:
                if col.get("column") == "weight" or col.get("name") == "weight":
                    return True

            return False
        except Exception as e:
            logger.debug(f"Error checking weight columns: {e}")
            return False

    def set_node_weight(self, node_id: str, weight: float) -> None:
        """
        Set node weight directly.

        Args:
            node_id: Node identifier
            weight: Weight value between 0 and 1
        """
        try:
            conn = self.connection

            if self._has_weight_columns(conn):
                # Use weight column if available
                conn.execute(
                    f"""
                    MATCH (n:Node {{id: '{node_id}'}})
                    SET n.weight = {weight}
                    """
                )
            else:
                # Fallback to properties JSON
                # First get current properties
                result = conn.execute(
                    f"""
                    MATCH (n:Node {{id: '{node_id}'}})
                    RETURN n.properties
                    """
                )
                rows = result.get_all()
                if rows:
                    current_props = json.loads(rows[0].get("n.properties", "{}"))
                    current_props["weight"] = weight

                    conn.execute(
                        f"""
                        MATCH (n:Node {{id: '{node_id}'}})
                        SET n.properties = '{json.dumps(current_props)}'
                        """
                    )

        except Exception as e:
            logger.error(f"Failed to set node weight: {e}")

    def adjust_node_weight(self, node_id: str, factor: float) -> None:
        """
        Multiply existing node weight by factor.

        Args:
            node_id: Node identifier
            factor: Multiplication factor
        """
        try:
            conn = self.connection

            if self._has_weight_columns(conn):
                # Get current weight and multiply
                result = conn.execute(
                    f"""
                    MATCH (n:Node {{id: '{node_id}'}})
                    RETURN n.weight
                    """
                )
                rows = result.get_all()
                if rows:
                    current_weight = rows[0].get("n.weight", 1.0)
                    new_weight = min(1.0, current_weight * factor)  # Cap at 1.0

                    conn.execute(
                        f"""
                        MATCH (n:Node {{id: '{node_id}'}})
                        SET n.weight = {new_weight}
                        """
                    )
            else:
                # Fallback to properties
                result = conn.execute(
                    f"""
                    MATCH (n:Node {{id: '{node_id}'}})
                    RETURN n.properties
                    """
                )
                rows = result.get_all()
                if rows:
                    current_props = json.loads(rows[0].get("n.properties", "{}"))
                    current_weight = current_props.get("weight", 1.0)
                    new_weight = min(1.0, current_weight * factor)
                    current_props["weight"] = new_weight

                    conn.execute(
                        f"""
                        MATCH (n:Node {{id: '{node_id}'}})
                        SET n.properties = '{json.dumps(current_props)}'
                        """
                    )

        except Exception as e:
            logger.error(f"Failed to adjust node weight: {e}")

    def decay_weights(self, filters: Dict[str, Any], decay_factor: float = 0.9) -> None:
        """
        Decay all weights in session by factor.

        Args:
            filters: Session filters (user_id, index_, ws_id, etc.)
            decay_factor: Decay factor (default 0.9)
        """
        try:
            conn = self.connection

            # Build WHERE clause from filters
            where_conditions = []
            for key, value in filters.items():
                where_conditions.append(f"n.{key} = '{value}'")

            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

            if self._has_weight_columns(conn):
                # Use weight column
                conn.execute(
                    f"""
                    MATCH (n:Node)
                    WHERE {where_clause}
                    SET n.weight = n.weight * {decay_factor}
                    """
                )

                conn.execute(
                    f"""
                    MATCH ()-[r:RELATES]->()
                    WHERE {where_clause.replace("n.", "r.")}
                    SET r.weight = r.weight * {decay_factor}
                    """
                )
            else:
                # Fallback to properties - more complex update needed
                logger.warning("Weight decay with properties fallback not yet implemented")

        except Exception as e:
            logger.error(f"Failed to decay weights: {e}")

    def _save_node_relationships(self, conn, node_id: str) -> List[Dict[str, Any]]:
        """Save all relationships (incoming and outgoing) for a node before deletion.

        Args:
            conn: KuzuDB connection
            node_id: ID of the node whose relationships to save

        Returns:
            List of relationship dictionaries with source, target, and properties
        """
        relationships = []

        try:
            # Get outgoing relationships (where this node is the source)
            outgoing_result = conn.execute(
                """
                MATCH (source:Node)-[r:RELATES]->(target:Node)
                WHERE source.id = $node_id AND source.index_ = $index AND source.ws_id = $ws_id
                AND target.index_ = $index AND target.ws_id = $ws_id
                AND r.index_ = $index
                RETURN source.id, target.id, r.relation_label, r.relation_properties, 'outgoing'
                """,
                parameters={"node_id": node_id, "index": self.index, "ws_id": self.ws_id},
            )

            for row in outgoing_result:
                relationships.append(
                    {
                        "source_id": row[0],
                        "target_id": row[1],
                        "label": row[2],
                        "properties": row[3],
                        "direction": "outgoing",
                    }
                )

            # Get incoming relationships (where this node is the target)
            incoming_result = conn.execute(
                """
                MATCH (source:Node)-[r:RELATES]->(target:Node)
                WHERE target.id = $node_id AND target.index_ = $index AND target.ws_id = $ws_id
                AND source.index_ = $index AND source.ws_id = $ws_id
                AND r.index_ = $index
                RETURN source.id, target.id, r.relation_label, r.relation_properties, 'incoming'
                """,
                parameters={"node_id": node_id, "index": self.index, "ws_id": self.ws_id},
            )

            for row in incoming_result:
                relationships.append(
                    {
                        "source_id": row[0],
                        "target_id": row[1],
                        "label": row[2],
                        "properties": row[3],
                        "direction": "incoming",
                    }
                )

            logger.debug(f"Saved {len(relationships)} relationships for node {node_id}")
            return relationships

        except Exception as e:
            logger.error(f"Failed to save relationships for node {node_id}: {e}")
            return []

    def _restore_node_relationships(self, conn, relationships: List[Dict[str, Any]]) -> None:
        """Restore saved relationships after node recreation.

        Args:
            conn: KuzuDB connection
            relationships: List of relationship dictionaries to restore
        """
        if not relationships:
            return

        restored_count = 0
        for rel in relationships:
            try:
                # Check if both source and target nodes still exist
                source_exists = conn.execute(
                    """
                    MATCH (n:Node)
                    WHERE n.id = $source_id AND n.index_ = $index AND n.ws_id = $ws_id
                    RETURN n.id
                    """,
                    parameters={"source_id": rel["source_id"], "index": self.index, "ws_id": self.ws_id},
                )

                target_exists = conn.execute(
                    """
                    MATCH (n:Node)
                    WHERE n.id = $target_id AND n.index_ = $index AND n.ws_id = $ws_id
                    RETURN n.id
                    """,
                    parameters={"target_id": rel["target_id"], "index": self.index, "ws_id": self.ws_id},
                )

                # Only restore if both nodes exist
                source_found = any(True for _ in source_exists)
                target_found = any(True for _ in target_exists)

                if source_found and target_found:
                    # Recreate the relationship
                    conn.execute(
                        """
                        MATCH (source:Node), (target:Node)
                        WHERE source.id = $source_id AND source.index_ = $index AND source.ws_id = $ws_id
                        AND target.id = $target_id AND target.index_ = $index AND target.ws_id = $ws_id
                        CREATE (source)-[:RELATES {
                            relation_label: $relation_label,
                            relation_properties: $relation_properties,
                            index_: $index
                        }]->(target)
                        """,
                        {
                            "source_id": rel["source_id"],
                            "target_id": rel["target_id"],
                            "relation_label": rel["label"],
                            "relation_properties": rel["properties"],
                            "index": self.index,
                            "ws_id": self.ws_id,
                        },
                    )
                    restored_count += 1
                else:
                    logger.warning(
                        f"Cannot restore relationship {rel['source_id']} -> {rel['target_id']}: "
                        f"source_exists={source_found}, target_exists={target_found}"
                    )

            except Exception as e:
                logger.error(f"Failed to restore relationship {rel['source_id']} -> {rel['target_id']}: {e}")

        logger.debug(f"Successfully restored {restored_count}/{len(relationships)} relationships")

    def _reset_connection(self):
        """Reset connection by clearing the database reference."""
        self.database_ = None

    def close_connection(self):
        """Explicitly close the connection and clean up resources."""
        # Guard against partial __init__ (Pydantic): if __init__ raised before
        # super().__init__ completed, the instance has no fields set and we
        # must NOT touch self.database_path / self.index (would AttributeError).
        if not hasattr(self, "__pydantic_fields_set__"):
            return
        try:
            # Clear the instance's database reference
            self.database_ = None

            # Remove from class-level cache if it exists
            actual_db_path = self._resolve_db_path()
            if actual_db_path in KuzuLabelledPropertyGraph.kuzu_database_cache:
                logger.debug(f"Closing KuzuDB database at: {actual_db_path}")
                # KuzuDB databases are automatically closed when the Python object is garbage collected
                # We just need to remove it from our cache
                del KuzuLabelledPropertyGraph.kuzu_database_cache[actual_db_path]
                logger.debug(f"KuzuDB database closed and removed from cache: {actual_db_path}")

        except Exception as e:
            logger.error(f"Error closing KuzuDB connection: {e}")

    @classmethod
    def close_all_connections(cls):
        """Close all cached database connections."""
        try:
            logger.debug(f"Closing {len(cls.kuzu_database_cache)} cached KuzuDB connections")
            # Clear all cached databases
            cls.kuzu_database_cache.clear()
            logger.debug("All KuzuDB connections closed")
        except Exception as e:
            logger.error(f"Error closing all KuzuDB connections: {e}")

    def __del__(self):
        """Clean up the connection when object is destroyed."""
        # Guard: if __init__ failed before Pydantic finished initialisation,
        # accessing self.database_path will raise. close_connection has its
        # own guard but we belt-and-brace to suppress any noise during GC.
        if not hasattr(self, "__pydantic_fields_set__"):
            return
        try:
            self.close_connection()
        except Exception:
            pass


class KuzuDatabaseManager:
    """Handles KuzuDB database operations."""

    @staticmethod
    def export_database(folder_id: str, export_path: str, database_path: str = None) -> None:
        """Export KuzuDB database to CSV format."""
        kuzu_graph = KuzuLabelledPropertyGraph(
            index=folder_id.replace("-", "_"),
            ws_id=folder_id,
            database_path=database_path or KUZU_DATABASE_PATH,
        )

        try:
            conn = kuzu_graph.connection

            # Ensure the export directory is clean
            if os.path.exists(export_path):
                if os.path.isfile(export_path):
                    os.remove(export_path)  # Remove if it's a file
                elif os.path.isdir(export_path):
                    shutil.rmtree(export_path)  # Remove if it's a directory

            export_query = f"EXPORT DATABASE '{export_path.replace(chr(92), '/')}' (format='csv', header=true)"
            conn.execute(export_query)
            kuzu_graph.close_connection()

            if not os.path.exists(export_path):
                raise RuntimeError(f"KuzuDB failed to create export directory: {export_path}")

            logger.info(f"Successfully exported KuzuDB database for folder {folder_id}")

        except Exception as e:
            logger.error(f"Failed to export KuzuDB database for folder {folder_id}: {e}")
            raise

    @staticmethod
    def import_database(import_path: str, new_folder_id: str) -> None:
        """Import CSV data into new KuzuDB database."""
        import kuzu  # noqa: WPS433 — lazy import

        target_db_path = os.path.join(KUZU_DATABASE_PATH, f"{new_folder_id.replace('-', '_')}.db")
        if os.path.exists(target_db_path):
            logger.warning(f"Target database already exists, removing to avoid extension conflicts: {target_db_path}")
            os.remove(target_db_path)

        kuzu_db = kuzu.Database(target_db_path)
        kuzu_conn = kuzu.Connection(kuzu_db)

        try:
            import_query = f"IMPORT DATABASE '{import_path.replace(chr(92), '/')}'"
            kuzu_conn.execute(import_query)

            # Update nodes with new folder ID only
            KuzuDatabaseManager.update_nodes_with_folder_id(kuzu_conn, new_folder_id)

            logger.info(f"Successfully imported KuzuDB database for folder {new_folder_id}")

        finally:
            del kuzu_conn
            del kuzu_db

    @staticmethod
    def update_nodes_with_folder_id(kuzu_conn, new_folder_id: str) -> None:
        """Update ws_id and index_ for all nodes and relationships to match new folder ID."""
        folder_id_str = str(new_folder_id)
        index_value = folder_id_str.replace("-", "_")

        # Count nodes first
        count_result = kuzu_conn.execute("MATCH (n:Node) RETURN count(n) as total_nodes")
        total_nodes = next(count_result)[0] if count_result else 0

        if total_nodes == 0:
            return

        # Update ws_id and index_ for all nodes
        update_query = f"""
        MATCH (n:Node)
        SET n.ws_id = '{folder_id_str}', n.index_ = '{index_value}'
        """
        kuzu_conn.execute(update_query)

        # Update relationships if they exist
        try:
            rel_query = f"MATCH ()-[r:RELATES]->() SET r.index_ = '{index_value}'"
            kuzu_conn.execute(rel_query)
        except Exception as rel_error:
            logger.warning(f"Could not update relationships: {rel_error}")

        # Verify ws_id and index_ update
        verify_query = f"""
        MATCH (n:Node)
        WHERE n.ws_id <> '{folder_id_str}' OR n.index_ <> '{index_value}'
        RETURN count(n) as incorrect_nodes
        """
        result = kuzu_conn.execute(verify_query)
        incorrect_nodes = next(result)[0] if result else 0

        if incorrect_nodes == 0:
            logger.info(f"Updated all nodes: ws_id='{folder_id_str}', index_='{index_value}'")
        else:
            logger.warning(f"{incorrect_nodes} nodes still have incorrect values")

    @staticmethod
    def update_nodes_properties(kuzu_conn, file_mapping_properties: Dict[str, Dict[str, Any]] = None) -> None:
        """Update node properties based on filename mapping."""
        if not file_mapping_properties:
            return

        # Count nodes first
        count_result = kuzu_conn.execute("MATCH (n:Node) RETURN count(n) as total_nodes")
        total_nodes = next(count_result)[0] if count_result else 0

        if total_nodes == 0:
            return

        logger.info(f"Updating node properties based on filename mapping for {len(file_mapping_properties)} files")

        # Get all nodes that have filename in their properties
        nodes_result = kuzu_conn.execute(
            """
            MATCH (n:Node)
            WHERE n.properties CONTAINS '"filename"'
            RETURN n.id, n.properties
            """
        )

        updated_count = 0
        for row in nodes_result:
            node_id = row[0]
            properties_str = row[1]

            try:
                # Parse current properties
                current_props = json.loads(properties_str) if properties_str else {}

                # Check if filename exists and matches mapping
                filename = current_props.get("filename")
                if filename and filename in file_mapping_properties:
                    # Merge new properties with existing ones
                    new_props = file_mapping_properties[filename]
                    current_props.update(new_props)

                    # Update node properties
                    updated_props_str = json.dumps(current_props)
                    update_props_query = """
                    MATCH (n:Node)
                    WHERE n.id = $node_id
                    SET n.properties = $properties
                    """
                    kuzu_conn.execute(update_props_query, {"node_id": node_id, "properties": updated_props_str})
                    updated_count += 1
                    logger.debug(f"Updated properties for node {node_id} with filename {filename}")

            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to update properties for node {node_id}: {e}")
                continue

        logger.info(f"Successfully updated properties for {updated_count} nodes based on filename mapping")
