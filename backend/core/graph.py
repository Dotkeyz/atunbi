"""Entity graph — NetworkX-powered multi-hop reasoning and traversal."""
import datetime
import logging
from typing import Optional
import networkx as nx

logger = logging.getLogger("atunbi.graph")

# Module-level cache: one graph per user_id
_graphs: dict[int, nx.MultiDiGraph] = {}
_dirty: set[int] = set()  # user_ids with pending invalidation


def invalidate_graph(user_id: int):
    """Mark a user's graph for rebuild on next access."""
    _dirty.add(user_id)
    _graphs.pop(user_id, None)


def _build_graph(entities: list) -> nx.MultiDiGraph:
    """Build a directed multigraph from entity rows (supports multiple edges
    between the same two nodes — e.g. Ada → Hackathon via both 'participated_in'
    and 'won').

    Each entity is (entity_name, entity_type, relation, target_name, target_type, confidence).
    """
    G = nx.MultiDiGraph()
    for ent in entities:
        src, src_type, rel, tgt, tgt_type, conf = ent
        if src not in G:
            G.add_node(src, node_type=src_type)
        if tgt not in G:
            G.add_node(tgt, node_type=tgt_type)
        G.add_edge(src, tgt, relation=rel, confidence=conf)
    return G


def get_graph(user_id: int, entities: list) -> nx.MultiDiGraph:
    """Build entity graph. Always rebuilds to avoid stale cache across requests."""
    _dirty.discard(user_id)
    G = _build_graph(entities)
    _graphs[user_id] = G
    return G


def traverse_from(user_id: int, entities: list, start_nodes: list[str], max_depth: int = 3) -> list[dict]:
    """Bidirectional BFS traversal from starting entities.
    Returns [{from, relation, to, depth, confidence}] for visualization."""
    G = get_graph(user_id, entities)
    paths = []
    visited_edges = set()
    
    for start in start_nodes:
        # Case-insensitive node lookup
        node_lower = start.lower()
        actual = None
        for n in G.nodes():
            if n.lower() == node_lower:
                actual = n
                break
        if actual:
            start = actual
        if start not in G:
            continue
        # BFS with depth tracking — follows BOTH successors and predecessors
        # to find shared connections (e.g. Ada → Hackathon ← Kai)
        queue = [(start, 0)]
        visited_nodes = {start}
        
        while queue:
            node, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            
            # Outgoing edges: node → neighbor (all parallel edges)
            for neighbor in G.successors(node):
                for edge_key, edge_data in G.get_edge_data(node, neighbor).items():
                    edge_id = (node, neighbor, edge_data.get("relation", ""))
                    if edge_id not in visited_edges:
                        visited_edges.add(edge_id)
                        paths.append({
                            "from": node,
                            "relation": edge_data.get("relation", "related_to"),
                            "to": neighbor,
                            "depth": depth + 1,
                            "confidence": edge_data.get("confidence", 1.0),
                        })
                if neighbor not in visited_nodes:
                    visited_nodes.add(neighbor)
                    queue.append((neighbor, depth + 1))
            
            # Incoming edges: predecessor → node (shared connections)
            for predecessor in G.predecessors(node):
                for edge_key, edge_data in G.get_edge_data(predecessor, node).items():
                    edge_id = (predecessor, node, edge_data.get("relation", ""))
                    if edge_id not in visited_edges:
                        visited_edges.add(edge_id)
                        paths.append({
                            "from": predecessor,
                            "relation": edge_data.get("relation", "related_to"),
                            "to": node,
                            "depth": depth + 1,
                            "confidence": edge_data.get("confidence", 1.0),
                        })
                if predecessor not in visited_nodes:
                    visited_nodes.add(predecessor)
                    queue.append((predecessor, depth + 1))
    
    return paths


def find_structural_gaps(entities: list, min_confidence: float = 0.5) -> list[dict]:
    """Find disconnected entities sharing a common neighbor (structural holes).
    Returns up to 5 gaps sorted by connection strength."""
    G = _build_graph(entities)
    gaps = []
    
    for node in G.nodes():
        neighbors = list(set(G.successors(node)) | set(G.predecessors(node)))
        
        if len(neighbors) < 2:
            continue
        
        for i in range(len(neighbors)):
            for j in range(i + 1, len(neighbors)):
                a, b = neighbors[i], neighbors[j]
                
                # Skip if already directly connected
                if G.has_edge(a, b) or G.has_edge(b, a):
                    continue
                
                # Get first edge's data for each connection (MultiDiGraph compatible)
                edges_a = G.get_edge_data(a, node) or G.get_edge_data(node, a) or {}
                edges_b = G.get_edge_data(b, node) or G.get_edge_data(node, b) or {}
                data_a = next(iter(edges_a.values()), {}) if edges_a else {}
                data_b = next(iter(edges_b.values()), {}) if edges_b else {}
                
                conf_a = data_a.get('confidence', 0.5)
                conf_b = data_b.get('confidence', 0.5)
                
                if conf_a < min_confidence or conf_b < min_confidence:
                    continue
                
                strength = conf_a + conf_b
                gaps.append({
                    "entity_a": a,
                    "entity_b": b,
                    "shared_neighbor": node,
                    "relation_a": data_a.get('relation', 'connected_to'),
                    "relation_b": data_b.get('relation', 'connected_to'),
                    "strength": round(strength, 2),
                    "type_a": G.nodes.get(a, {}).get('node_type', 'unknown'),
                    "type_b": G.nodes.get(b, {}).get('node_type', 'unknown'),
                })
    
    gaps.sort(key=lambda g: g["strength"], reverse=True)
    return gaps[:5]


def _sanitize_mermaid_label(text: str) -> str:
    text = text.replace('"', "'")
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def build_mermaid_paths(paths: list[dict], highlight_color: str = "#5046e5") -> str:
    """Convert graph paths to a Mermaid flowchart string for frontend rendering.
    
    Returns a ready-to-render Mermaid flowchart with semantic coloring.
    Entity names are sanitized to prevent Mermaid syntax errors.
    """
    if not paths:
        return ""
    
    lines = ["flowchart LR"]
    seen_nodes = set()
    node_ids = {}
    node_counter = [0]
    
    def node_id(name: str) -> str:
        if name not in node_ids:
            node_ids[name] = f"N{node_counter[0]}"
            node_counter[0] += 1
        return node_ids[name]
    
    # Collect all unique nodes with types
    for p in paths:
        nid_from = node_id(p["from"])
        nid_to = node_id(p["to"])
        if nid_from not in seen_nodes:
            node_type = _infer_node_type(p["from"], paths)
            safe_label = _sanitize_mermaid_label(p["from"])
            lines.append(f'    {nid_from}["{safe_label}"]:::{node_type}')
            seen_nodes.add(nid_from)
        if nid_to not in seen_nodes:
            node_type = _infer_node_type(p["to"], paths)
            safe_label = _sanitize_mermaid_label(p["to"])
            lines.append(f'    {nid_to}["{safe_label}"]:::{node_type}')
            seen_nodes.add(nid_to)
    
    # Add edges — sanitize relation labels too
    for p in paths:
        nid_from = node_id(p["from"])
        nid_to = node_id(p["to"])
        safe_rel = _sanitize_mermaid_label(p["relation"])
        lines.append(f'    {nid_from} -->|"{safe_rel}"| {nid_to}')
    
    # Style classes for semantic node types
    lines.append("")
    lines.append(f"    classDef person fill:#eef2ff,stroke:#818cf8,color:#3730a3")
    lines.append(f"    classDef company fill:#fef3c7,stroke:#f59e0b,color:#92400e")
    lines.append(f"    classDef technology fill:#dcfce7,stroke:#86efac,color:#166534")
    lines.append(f"    classDef location fill:#ede9fe,stroke:#c4b5fd,color:#5b21b6")
    lines.append(f"    classDef concept fill:#f0fdf4,stroke:#34d399,color:#065f46")
    lines.append(f"    classDef unknown fill:#f8fafc,stroke:#94a3b8,color:#475569")
    
    return "\n".join(lines)


def _infer_node_type(name: str, paths: list[dict]) -> str:
    """Infer a node's type from the paths it appears in."""
    for p in paths:
        if p["from"] == name:
            return _type_from_context(name, p["relation"])
        if p["to"] == name:
            return _type_from_context(name, p["relation"])
    return "unknown"


def _type_from_context(name: str, relation: str) -> str:
    """Heuristic type inference from relation context."""
    person_rels = {"works_at", "founded", "leads", "reports_to", "prefers", "uses"}
    company_rels = {"works_at", "expanding_to", "headquartered_in", "acquired"}
    tech_rels = {"uses", "migrated_to", "deployed", "built_with"}
    location_rels = {"expanding_to", "located_in", "requires"}
    
    if name[0].isupper() and len(name.split()) == 1 and not name.isupper():
        return "person"
    if relation in tech_rels:
        return "technology"
    if relation in location_rels:
        return "location"
    if any(word in name.lower() for word in ["inc", "corp", "ltd", "pay", "bank"]):
        return "company"
    return "concept"
