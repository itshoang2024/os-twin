#!/usr/bin/env python3
"""CLI wrapper for Agentic Memory — use when MCP stdio is unavailable.

Usage:
    memory_cli.py save "content here" [--name NAME] [--path PATH] [--tags t1,t2]
    memory_cli.py search "query" [--k 5]
    memory_cli.py tree
"""

import argparse
import json
import os
import sys
import time


def _get_persist_dir():
    d = os.getenv("MEMORY_PERSIST_DIR", "")
    if d and os.path.isabs(d):
        return d
    root = os.getenv("AGENT_OS_ROOT", "")
    if root and os.path.isabs(root):
        return os.path.join(root, ".memory")
    return os.path.join(os.getcwd(), ".memory")


def _get_memory():
    persist_dir = _get_persist_dir()
    from dashboard.agentic_memory.memory_system import AgenticMemorySystem

    return AgenticMemorySystem(
        model_name=os.getenv("MEMORY_EMBEDDING_MODEL", "gemini-embedding-001"),
        embedding_backend=os.getenv("MEMORY_EMBEDDING_BACKEND", "gemini"),
        vector_backend=os.getenv("MEMORY_VECTOR_BACKEND", "zvec"),
        llm_backend=os.getenv("MEMORY_LLM_BACKEND", "gemini"),
        llm_model=os.getenv("MEMORY_LLM_MODEL", "gemini-3-flash-preview"),
        persist_dir=persist_dir,
    )


def cmd_save(args):
    mem = _get_memory()
    kwargs = {}
    if args.name:
        kwargs["name"] = args.name
    if args.path:
        kwargs["path"] = args.path
    if args.tags:
        kwargs["tags"] = [t.strip() for t in args.tags.split(",")]
    mid = mem.add_note(args.content, **kwargs)
    note = mem.read(mid)
    print(
        json.dumps(
            {
                "id": note.id,
                "name": note.name,
                "path": note.path,
                "tags": note.tags,
                "keywords": note.keywords,
            },
            indent=2,
        )
    )


def cmd_search(args):
    mem = _get_memory()
    results = mem.search(args.query, k=args.k)
    for r in results:
        note = mem.read(r["id"])
        print(
            json.dumps(
                {
                    "id": r["id"],
                    "name": note.name if note else None,
                    "path": note.path if note else None,
                    "content": r["content"][:500],
                    "tags": r.get("tags", []),
                }
            )
        )


def cmd_tree(_args):
    mem = _get_memory()
    print(mem.tree())


def main():
    parser = argparse.ArgumentParser(description="Agentic Memory CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_save = sub.add_parser("save", help="Save a memory")
    p_save.add_argument("content", help="Memory content")
    p_save.add_argument("--name", help="Optional name")
    p_save.add_argument("--path", help="Optional directory path")
    p_save.add_argument("--tags", help="Comma-separated tags")

    p_search = sub.add_parser("search", help="Search memories")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--k", type=int, default=5, help="Max results")

    sub.add_parser("tree", help="Show memory tree")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    {"save": cmd_save, "search": cmd_search, "tree": cmd_tree}[args.cmd](args)


if __name__ == "__main__":
    main()
