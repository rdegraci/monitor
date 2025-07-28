import chromadb
from sentence_transformers import SentenceTransformer
import uuid
import hashlib
from datetime import datetime

class TextVectorStore:
    """
    A class to embed text documents into a ChromaDB vector database and manage them.
    
    Uses SentenceTransformers for embeddings (local and free).
    Install dependencies: pip install chromadb sentence-transformers
    
    Note: This client is not thread-safe by default; use locks for multi-threaded access.
    
    Example usage:
    store = TextVectorStore(db_path="./my_custom_chroma_db")
    doc_id = store.add_document("Sample text.", metadata={"session_id": "123"})
    store.add_documents(["Text1", "Text2"], metadatas=[{"session_id": "123"}, {"session_id": "456"}])
    print(store.get_document(doc_id))
    print(store.count_documents())
    store.clear_collection()
    """
    
    def __init__(self, collection_name="documents", embedder_model='all-MiniLM-L6-v2', db_path="./chroma_db"):
        """
        Initialize the vector store with a ChromaDB collection and embedding model.
        
        :param collection_name: Name of the ChromaDB collection (default: "documents")
        :param embedder_model: Name of the SentenceTransformer model to use (default: 'all-MiniLM-L6-v2')
        :param db_path: Path to the directory where ChromaDB will persist data (default: "./chroma_db")
        """
        self.client = chromadb.PersistentClient(path=db_path)  # Persistent client with customizable path
        self.collection = self.client.get_or_create_collection(name=collection_name)
        self.embedder = SentenceTransformer(embedder_model)  # Load the specified embedding model
    
    def _compute_hash(self, text):
        """Compute SHA-256 hash of the text for duplicate checking."""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
    
    def _add_timestamp(self, metadata):
        """Add or update timestamps in metadata."""
        now = datetime.utcnow().isoformat()
        if 'created_at' not in metadata:
            metadata['created_at'] = now
        metadata['updated_at'] = now
        return metadata
    
    def add_document(self, text, metadata=None, check_duplicates=True):
        """
        Embed and add a single document. See add_documents for batch.
        """
        return self.add_documents([text], [metadata] if metadata else None, check_duplicates)[0]
    
    def add_documents(self, texts, metadatas=None, check_duplicates=True):
        """
        Embed and add multiple documents in batch for efficiency.
        
        :param texts: List of text documents to add (list[str])
        :param metadatas: Optional list of metadata dicts (list[dict]); must match texts length
        :param check_duplicates: If True, skip duplicates based on hash (default: True)
        :return: List of unique IDs for added (or existing) documents
        """
        if not isinstance(texts, list) or not texts:
            raise ValueError("Texts must be a non-empty list of strings.")
        if metadatas and (not isinstance(metadatas, list) or len(metadatas) != len(texts)):
            raise ValueError("Metadatas must be a list matching texts length.")
        
        if not metadatas:
            metadatas = [{} for _ in texts]
        
        to_add_texts = []
        to_add_embeddings = []
        to_add_metadatas = []
        to_add_ids = []
        returned_ids = []
        
        for text, meta in zip(texts, metadatas):
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Each text must be a non-empty string.")
            if not isinstance(meta, dict):
                raise ValueError("Each metadata must be a dictionary.")
            
            doc_hash = self._compute_hash(text)
            meta = self._add_timestamp(meta.copy())  # Copy to avoid mutating original
            meta['hash'] = doc_hash
            
            if check_duplicates:
                existing = self.collection.get(where={"hash": doc_hash}, include=[])
                if existing['ids']:
                    returned_ids.append(existing['ids'][0])
                    continue
            
            embedding = self.embedder.encode(text).tolist()
            doc_id = str(uuid.uuid4())
            
            to_add_texts.append(text)
            to_add_embeddings.append(embedding)
            to_add_metadatas.append(meta)
            to_add_ids.append(doc_id)
            returned_ids.append(doc_id)
        
        if to_add_texts:
            self.collection.add(
                documents=to_add_texts,
                embeddings=to_add_embeddings,
                ids=to_add_ids,
                metadatas=to_add_metadatas
            )
        
        return returned_ids
    
    def query_documents(self, query, top_k=5, max_distance=1.0, filter=None):
        """
        Query the database with a text query and return relevant hits, sorted from most to least relevant.
        
        :param query: The query text (str)
        :param top_k: Number of top results to return (default: 5)
        :param max_distance: Maximum distance threshold for relevance (default: 1.0; lower is more similar)
        :param filter: Optional filter dictionary for metadata (e.g., {"session_id": "session123"})
        :return: List of dicts, each with 'document' (str), 'distance' (float), and 'metadata' (dict), sorted by ascending distance
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")
        
        query_embedding = self.embedder.encode(query).tolist()
        
        query_params = {
            "query_embeddings": [query_embedding],
            "n_results": top_k,
            "include": ["documents", "distances", "metadatas"]
        }
        
        if filter:
            query_params["where"] = filter
        
        results = self.collection.query(**query_params)
        
        hits = []
        for dist, doc, meta in zip(results['distances'][0], results['documents'][0], results['metadatas'][0]):
            if dist <= max_distance:
                hits.append({
                    "document": doc,
                    "distance": dist,
                    "metadata": meta or {}
                })
        
        return hits
    
    def get_document(self, doc_id):
        """
        Retrieve a document by its ID, including metadata.
        
        :param doc_id: The unique ID of the document (str)
        :return: Dict with 'document' (str) and 'metadata' (dict), or None if not found
        """
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ValueError("Document ID must be a non-empty string.")
        
        result = self.collection.get(ids=[doc_id], include=["documents", "metadatas"])
        if not result['ids']:
            return None
        
        return {
            "document": result['documents'][0],
            "metadata": result['metadatas'][0] or {}
        }
    
    def delete_document(self, doc_id):
        """
        Delete a document from the ChromaDB collection by its ID.
        
        :param doc_id: The unique ID of the document to delete (str)
        :return: True if the document was found and deleted, False if not found
        """
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ValueError("Document ID must be a non-empty string.")
        
        existing = self.collection.get(ids=[doc_id])
        if not existing['ids']:
            return False
        
        self.collection.delete(ids=[doc_id])
        return True
    
    def edit_document(self, doc_id, new_text=None, new_metadata=None):
        """
        Edit (replace/update) an existing document in the ChromaDB collection by its ID.
        Supports partial updates: provide only new_text, only new_metadata, or both.
        
        :param doc_id: The unique ID of the document to edit (str)
        :param new_text: Optional new text for the document (str); if provided, re-embeds automatically
        :param new_metadata: Optional new metadata dictionary (dict); replaces existing metadata
        :return: True if the document was found and updated, False if not found
        """
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ValueError("Document ID must be a non-empty string.")
        
        existing = self.collection.get(ids=[doc_id], include=["documents", "metadatas"])
        if not existing['ids']:
            return False
        
        update_kwargs = {"ids": [doc_id]}
        updated_meta = (new_metadata or existing['metadatas'][0] or {}).copy()
        updated_meta = self._add_timestamp(updated_meta)
        
        if new_text is not None:
            if not isinstance(new_text, str) or not new_text.strip():
                raise ValueError("New text must be a non-empty string if provided.")
            new_embedding = self.embedder.encode(new_text).tolist()
            update_kwargs["documents"] = [new_text]
            update_kwargs["embeddings"] = [new_embedding]
            new_hash = self._compute_hash(new_text)
            updated_meta['hash'] = new_hash
        
        update_kwargs["metadatas"] = [updated_meta]
        
        self.collection.update(**update_kwargs)
        return True
    
    def count_documents(self):
        """
        Return the number of documents in the collection.
        """
        return self.collection.count()
    
    def clear_collection(self):
        """
        Delete all documents in the collection (irreversible).
        """
        self.client.delete_collection(self.collection.name)
        self.collection = self.client.get_or_create_collection(name=self.collection.name)

TEXT_VECTOR_STORE_SCHEMA=
[
    {
        "type": "function",
        "function": {
            "name": "add_document",
            "description": "Add a new document to the vector store with optional metadata and duplicate checking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text document to add."
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional metadata dictionary to associate with the document.",
                        "additionalProperties": true
                    },
                    "check_duplicates": {
                        "type": "boolean",
                        "description": "If true, prevent adding if an exact duplicate exists (default: true).",
                        "default": true
                    }
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_documents",
            "description": "Add multiple documents to the vector store in batch with optional metadatas and duplicate checking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "texts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of text documents to add."
                    },
                    "metadatas": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": true
                        },
                        "description": "Optional list of metadata dictionaries (must match texts length)."
                    },
                    "check_duplicates": {
                        "type": "boolean",
                        "description": "If true, prevent adding duplicates (default: true).",
                        "default": true
                    }
                },
                "required": ["texts"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_documents",
            "description": "Query the vector store for relevant documents based on a text query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The query text."
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of top results to return (default: 5).",
                        "default": 5
                    },
                    "max_distance": {
                        "type": "number",
                        "description": "Maximum distance threshold for relevance (default: 1.0).",
                        "default": 1.0
                    },
                    "filter": {
                        "type": "object",
                        "description": "Optional metadata filter (e.g., {'session_id': '123'}).",
                        "additionalProperties": true
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_document",
            "description": "Retrieve a document by its ID, including metadata.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "The unique ID of the document."
                    }
                },
                "required": ["doc_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_document",
            "description": "Edit an existing document by ID, with optional new text and/or metadata.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "The unique ID of the document to edit."
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Optional new text for the document."
                    },
                    "new_metadata": {
                        "type": "object",
                        "description": "Optional new metadata dictionary.",
                        "additionalProperties": true
                    }
                },
                "required": ["doc_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_document",
            "description": "Delete a document by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "The unique ID of the document to delete."
                    }
                },
                "required": ["doc_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "count_documents",
            "description": "Return the number of documents in the collection.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_collection",
            "description": "Clear all documents from the collection.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


SUPPLEMENTAL_SYSTEM_PROMPT= """
You are an intelligent assistant with access to a long-term memory module implemented as a vector store. This module allows you to store, retrieve, update, and manage persistent information across conversations, such as summaries, insights, user preferences, or historical context. Use it to make responses more adaptive and efficient by:Querying for retrieval: Before responding, if the query relates to past conversations, summaries, or stored knowledge, use the query_documents tool to fetch relevant documents. For example, search for similar summaries to avoid redundancy or build on prior insights.
Storing new insights: After generating key summaries, decisions, or new information during a conversation, use the add_document or add_documents tool to save them with appropriate metadata (e.g., session ID, timestamps) for future reference.
Updating or managing: If stored information becomes outdated or needs correction, use edit_document to update it, or delete_document to remove irrelevant entries. Check counts with count_documents if managing storage limits, and clear with clear_collection only if explicitly needed for resets.
On-the-fly decisions: Dynamically decide to interact with the vector store based on the conversation flow—e.g., retrieve past summaries for continuity in long sessions or store new ones after trimming history.

Always prioritize using the vector store for tasks involving memory persistence, but only invoke tools when necessary to avoid unnecessary operations. If no relevant stored data exists, proceed without it.
"""


def add_tool_descriptions(tool_descriptions):
    extended_tool_descriptions = tool_descriptions.extend(TEXT_VECTOR_STORE_SCHEMA)
    return extended_tool_descriptions

def add_supplemental_system_prompt(system_prompt)
    extended_system_prompt = system_prompt + SUPPLEMENTAL_SYSTEM_PROMPT
    return extended_system_prompt
