from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def _now_ms() -> int:
    return int(time.time() * 1000)


def _id64(uid: str) -> int:
    h = hashlib.sha1((uid or "").encode("utf-8", errors="ignore")).digest()
    return int.from_bytes(h[:8], "big") & ((1 << 63) - 1)


@dataclass
class QdrantMemoryConfig:
    # Use default_factory so env is read at instance creation (after load_dotenv),
    # not at import time.
    url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://localhost:6333") or "http://localhost:6333")
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("QDRANT_API_KEY"))
    collection: str = os.getenv("QDRANT_COLLECTION", "memory_items") or "memory_items"
    dim: int = int(os.getenv("QDRANT_DIM", os.getenv("EMBED_DIM", "768")) or 768)
    distance: str = os.getenv("QDRANT_DISTANCE", "Cosine") or "Cosine"  # Cosine | Dot | Euclid
    top_k: int = int(os.getenv("MEMORY_TOP_K", "24") or 24)
    working_turns: int = int(os.getenv("MEMORY_WORKING_TURNS", "12") or 12)
    importance_threshold: int = int(os.getenv("MEMORY_IMPORTANCE_THRESHOLD", "6") or 6)
    multi_user: bool = str(os.getenv("MEMORY_MULTI_USER", "1")).strip().lower() not in {"0", "false", "no"}
    store_summaries_only: bool = str(os.getenv("MEMORY_STORE_SUMMARIES_ONLY", "1")).strip().lower() not in {"0", "false", "no"}
    default_user_id: str = os.getenv("MEMORY_USER_ID", "default") or "default"
    embedding_model: Optional[str] = os.getenv("EMBEDDING_MODEL")
    reranker_model: Optional[str] = os.getenv("RERANKER_MODEL")
    dedup_enable: bool = str(os.getenv("MEMORY_DEDUP_ENABLE", "1")).strip().lower() not in {"0", "false", "no"}
    dedup_vector_threshold: float = float(os.getenv("MEMORY_DEDUP_VECTOR_THRESHOLD", "0.9") or 0.9)
    dedup_lexical_threshold: float = float(os.getenv("MEMORY_DEDUP_LEXICAL_THRESHOLD", "0.85") or 0.85)
    # Consolidation / promotion knobs (Qdrant)
    promote_min_mentions: int = int(os.getenv("MEMORY_PROMOTE_MIN_MENTIONS", "3") or 3)
    promote_min_importance: int = int(os.getenv("MEMORY_PROMOTE_MIN_IMPORTANCE", "6") or 6)
    decay_days: int = int(os.getenv("MEMORY_DECAY_DAYS", "30") or 30)
    decay_amount: int = int(os.getenv("MEMORY_DECAY_AMOUNT", "1") or 1)


class QdrantRAGMemory:
    def __init__(self, cfg: Optional[QdrantMemoryConfig] = None):
        from qdrant_client import QdrantClient  # type: ignore
        from qdrant_client.models import Distance, VectorParams  # type: ignore

        self.cfg = cfg or QdrantMemoryConfig()
        self._user_id: str = self.cfg.default_user_id
        self._embedder = None
        self._embedder_dim: Optional[int] = None

        self.client = QdrantClient(
            url=self.cfg.url,
            api_key=self.cfg.api_key,
            timeout=30.0,
            prefer_grpc=True,
            check_compatibility=False,
        )

        # Ensure collection exists with configured dimension and distance
        try:
            exists = True
            try:
                # Prefer checking the specific collection; some API keys cannot list all collections
                self.client.get_collection(self.cfg.collection)
            except Exception as ex:
                msg = str(ex).lower()
                # If forbidden/unauthorized, assume it exists but we lack manage/list perms
                if ("403" in msg or "forbidden" in msg or "401" in msg or "unauthorized" in msg):
                    exists = True
                else:
                    exists = False
            if not exists:
                try:
                    dist = (self.cfg.distance or "Cosine").lower()
                    dist_enum = Distance.COSINE if dist.startswith("cos") else (Distance.DOT if dist.startswith("dot") else Distance.EUCLID)
                    self.client.create_collection(
                        collection_name=self.cfg.collection,
                        vectors_config=VectorParams(size=int(self.cfg.dim), distance=dist_enum),
                    )
                except Exception as ex:
                    # If we cannot create (forbidden/conflict), continue assuming it exists
                    if not any(s in str(ex).lower() for s in ("forbidden", "403", "already exists", "409")):
                        raise
            # Ensure payload indexes for filters we use (ignore permission errors)
            try:
                from qdrant_client.models import PayloadSchemaType  # type: ignore
                for fname in ("label", "user_id", "uid"):
                    try:
                        self.client.create_payload_index(
                            collection_name=self.cfg.collection,
                            field_name=fname,
                            field_schema=PayloadSchemaType.KEYWORD,
                            wait=True,
                        )
                    except Exception:
                        # Already exists or insufficient permissions — safe to proceed
                        pass
            except Exception:
                pass
        except Exception as e:
            raise RuntimeError(f"[qdrant] ensure collection failed: {e}")

    # --- embedding helpers ---
    def _ensure_embedder(self):
        if self._embedder is not None:
            return self._embedder
        mid = self.cfg.embedding_model
        if not mid:
            return None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._embedder = SentenceTransformer(mid)
            try:
                self._embedder_dim = int(getattr(self._embedder, "get_sentence_embedding_dimension", lambda: self.cfg.dim)())
            except Exception:
                self._embedder_dim = None
        except Exception as e:
            print(f"[memory.qdrant] embedder init failed: {e}")
            self._embedder = None
        return self._embedder

    def _encode_docs(self, texts: List[str]) -> List[List[float]]:
        emb = self._ensure_embedder()
        if emb is None:
            # fallback deterministic pseudo-embeddings to keep flow running (low quality)
            dim = int(self.cfg.dim)
            out: List[List[float]] = []
            for t in texts:
                h = hashlib.sha1((t or "").encode("utf-8", errors="ignore")).digest()
                vec = [(h[i % len(h)] / 255.0) for i in range(dim)]
                out.append(vec)
            return out
        try:
            import numpy as np  # type: ignore
            vecs = emb.encode(texts)
            return [list(np.asarray(v, dtype="float32")) for v in vecs]
        except Exception as e:
            print(f"[memory.qdrant] encode failed: {e}")
            return [[] for _ in texts]

    # --- similarity helpers ---
    def _lexical_similarity(self, a: str, b: str) -> float:
        try:
            from rapidfuzz import fuzz  # type: ignore
            return float(fuzz.token_set_ratio(a or "", b or "")) / 100.0
        except Exception:
            sa = set((a or "").lower().split())
            sb = set((b or "").lower().split())
            if not sa or not sb:
                return 0.0
            inter = len(sa & sb)
            uni = len(sa | sb)
            return inter / max(1, uni)

    # --- upsert helpers ---
    def _upsert_point(self, payload: Dict[str, Any], text: str | None) -> str:
        from qdrant_client.models import PointStruct  # type: ignore
        uid = payload.get("uid") or uuid.uuid4().hex
        payload["uid"] = uid
        pid = _id64(uid)
        vec: Optional[List[float]] = None
        if text:
            vecs = self._encode_docs([text])
            vec = vecs[0] if vecs else None
        if vec is None:
            vec = [0.0] * int(self.cfg.dim)
        try:
            self.client.upsert(
                collection_name=self.cfg.collection,
                points=[PointStruct(id=pid, vector=vec, payload=payload)],
            )
        except Exception as e:
            print(f"[memory.qdrant] upsert failed: {e}")
        return uid

    def _find_by_uid(self, uid: str) -> Optional[Tuple[int, Dict[str, Any]]]:
        from qdrant_client.models import Filter, FieldCondition, MatchValue  # type: ignore
        try:
            res = self.client.scroll(
                collection_name=self.cfg.collection,
                scroll_filter=Filter(must=[FieldCondition(key="uid", match=MatchValue(value=str(uid)))]),
                limit=10,
                with_payload=True,
            )
            points = res[0] if isinstance(res, tuple) else res
            if points:
                p = points[0]
                return int(p.id), dict(p.payload or {})
        except Exception:
            pass
        return None

    # --- public API (subset used by MemoryClient) ---
    def ensure_persona(self, persona_text: str) -> None:
        persona = (persona_text or "").strip()
        if not persona:
            return
        now = _now_ms()
        payload = {
            "uid": uuid.uuid4().hex,
            "user_id": "__global__",
            "label": "persona",
            "type": "persona",
            "title": "Agent persona",
            "text": persona,
            "importance": 10,
            "created_ts": now,
            "recency_ts": now,
        }
        self._upsert_point(payload, text=persona)

    def ensure_user(self, user_label: str) -> str:
        label = (user_label or "User").strip()
        lowered = label.lower()
        name = label
        for sep in ["user is", "user:", "user=", "name:", "name is"]:
            if sep in lowered:
                after = lowered.split(sep, 1)[1].strip()
                name = after.split()[0].strip(".,!;") or label
                break
        user_id = "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-") or "default"
        self._user_id = user_id
        now = _now_ms()
        payload = {
            "uid": uuid.uuid4().hex,
            "user_id": user_id,
            "label": "user",
            "type": "user",
            "title": "User label",
            "text": label,
            "importance": 8,
            "created_ts": now,
            "recency_ts": now,
        }
        self._upsert_point(payload, text=label)
        return user_id

    def add_label_value(self, label: str, value: str, replace: bool = False) -> str:
        label = (label or "facts").strip()
        t = {
            "persona": "persona",
            "user": "user",
            "profile": "semantic",
            "preferences": "semantic",
            "facts": "semantic",
            "goals": "semantic",
            "general": "general",
        }.get(label, "semantic")
        uid = "__global__" if label == "persona" or t == "general" else self._user_id
        now = _now_ms()
        payload = {
            "uid": uuid.uuid4().hex,
            "user_id": uid,
            "label": label,
            "type": t,
            "title": None,
            "text": value or "",
            "importance": 6,
            "created_ts": now,
            "recency_ts": now,
        }
        return self._upsert_point(payload, text=value)

    def update_item_text(self, item_id: str, new_text: str) -> bool:
        found = self._find_by_uid(item_id)
        if not found:
            return False
        _, payload = found
        payload = dict(payload)
        payload["text"] = new_text
        payload["recency_ts"] = _now_ms()
        payload["uid"] = item_id
        self._upsert_point(payload, text=new_text)
        return True

    def delete_item(self, item_id: str) -> bool:
        from qdrant_client.models import Filter, FieldCondition, MatchValue  # type: ignore
        try:
            self.client.delete(
                collection_name=self.cfg.collection,
                filter=Filter(must=[FieldCondition(key="uid", match=MatchValue(value=str(item_id)))]),
            )
            return True
        except Exception:
            return False

    def delete_by_query(self, query: str, labels: Optional[List[str]] = None, include_global: bool = False) -> int:
        # Without full-text index, we filter by label and user scope; query not applied.
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny  # type: ignore
        must: List[Any] = []
        if labels:
            if len(labels) == 1:
                must.append(FieldCondition(key="label", match=MatchValue(value=labels[0])))
            else:
                must.append(FieldCondition(key="label", match=MatchAny(any=labels)))
        uids = [self._user_id]
        if include_global:
            uids.append("__global__")
        if len(uids) == 1:
            must.append(FieldCondition(key="user_id", match=MatchValue(value=uids[0])))
        else:
            must.append(FieldCondition(key="user_id", match=MatchAny(any=uids)))
        try:
            self.client.delete(collection_name=self.cfg.collection, filter=Filter(must=must))
            return 1
        except Exception:
            return 0

    def find_items_by_query(self, query: str, labels: Optional[List[str]] = None, limit: int = 50, include_global: bool = False) -> List[Dict[str, Any]]:
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny  # type: ignore
        # Build filter for user scope and labels
        must: List[Any] = []
        if labels:
            if len(labels) == 1:
                must.append(FieldCondition(key="label", match=MatchValue(value=labels[0])))
            else:
                must.append(FieldCondition(key="label", match=MatchAny(any=labels)))
        uids = [self._user_id]
        if include_global:
            uids.append("__global__")
        if len(uids) == 1:
            must.append(FieldCondition(key="user_id", match=MatchValue(value=uids[0])))
        else:
            must.append(FieldCondition(key="user_id", match=MatchAny(any=uids)))

        # If we have an embedder, prefer vector search
        embedder_available = self._ensure_embedder() is not None
        if embedder_available:
            try:
                vecs = self._encode_docs([query or ""]) if query else [[0.0] * int(self.cfg.dim)]
                qv = vecs[0]
                hits = self.client.search(
                    collection_name=self.cfg.collection,
                    query_vector=qv,
                    limit=int(limit or self.cfg.top_k),
                    with_payload=True,
                    query_filter=Filter(must=must) if must else None,
                )
                out: List[Dict[str, Any]] = []
                for h in hits:
                    p = h.payload or {}
                    out.append({
                        "id": str(p.get("uid") or str(h.id)),
                        "user_id": str(p.get("user_id") or self._user_id),
                        "label": str(p.get("label") or "facts"),
                        "type": str(p.get("type") or "semantic"),
                        "title": p.get("title"),
                        "text": str(p.get("text") or ""),
                        "importance": int(p.get("importance") or 0),
                        "created_ts": int(p.get("created_ts") or 0),
                        "recency_ts": int(p.get("recency_ts") or 0),
                    })
                return out
            except Exception as e:
                print(f"[memory.qdrant] vector search failed, falling back to lexical: {e}")

        # Lexical fallback: scan a limited page of items and filter by substring
        try:
            out: List[Dict[str, Any]] = []
            seen: set[str] = set()
            query_lc = (query or "").strip().lower()
            next_offset = None
            page = 0
            per_page = 128
            while page < 8 and len(out) < int(limit or self.cfg.top_k):
                res = self.client.scroll(
                    collection_name=self.cfg.collection,
                    scroll_filter=Filter(must=must) if must else None,
                    limit=per_page,
                    with_payload=True,
                    offset=next_offset,
                )
                points, next_offset = (res if isinstance(res, tuple) else (res, None))
                if not points:
                    break
                for p in points:
                    pay = p.payload or {}
                    uid = str(pay.get("uid") or str(p.id))
                    if uid in seen:
                        continue
                    seen.add(uid)
                    text = str(pay.get("text") or "")
                    if not query_lc or (query_lc in text.lower()):
                        out.append({
                            "id": uid,
                            "user_id": str(pay.get("user_id") or self._user_id),
                            "label": str(pay.get("label") or "facts"),
                            "type": str(pay.get("type") or "semantic"),
                            "title": pay.get("title"),
                            "text": text,
                            "importance": int(pay.get("importance") or 0),
                            "created_ts": int(pay.get("created_ts") or 0),
                            "recency_ts": int(pay.get("recency_ts") or 0),
                        })
                        if len(out) >= int(limit or self.cfg.top_k):
                            break
                if len(out) >= int(limit or self.cfg.top_k):
                    break
                page += 1
            return out
        except Exception as e:
            print(f"[memory.qdrant] lexical fallback failed: {e}")
            return []

    # --- consolidation & decay (Qdrant) ---
    def consolidate(self, user_id: Optional[str] = None) -> Dict[str, int]:
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny, Range  # type: ignore
        uid = user_id or self._user_id
        merged = 0
        decayed = 0
        try:
            # 1) Merge near-duplicates within key labels using lexical + optional vector sim
            labels = ("facts", "preferences", "goals", "profile")
            for lab in labels:
                must = [FieldCondition(key="user_id", match=MatchValue(value=uid)), FieldCondition(key="label", match=MatchValue(value=lab))]
                # Page through to collect a bounded set
                items: List[Tuple[str, str, int, Dict[str, Any]]] = []  # (uid, text, importance, payload)
                next_offset = None
                page = 0
                per_page = 256
                while page < 4 and len(items) < 800:
                    res = self.client.scroll(
                        collection_name=self.cfg.collection,
                        scroll_filter=Filter(must=must),
                        limit=per_page,
                        with_payload=True,
                        offset=next_offset,
                    )
                    points, next_offset = (res if isinstance(res, tuple) else (res, None))
                    if not points:
                        break
                    for p in points:
                        pay = dict(p.payload or {})
                        items.append((str(pay.get("uid") or str(p.id)), str(pay.get("text") or ""), int(pay.get("importance") or 0), pay))
                    page += 1
                if not items:
                    continue

                # Precompute embeddings if available
                emb = self._ensure_embedder()
                vecs = None
                if emb:
                    try:
                        texts = [t for (_, t, _, _) in items]
                        vecs = self._encode_docs(texts)
                    except Exception:
                        vecs = None

                kept: List[Tuple[int, str, str, int, Dict[str, Any]]] = []  # (idx, uid, text, imp, payload)
                for idx, (iid, txt, imp, pay) in enumerate(items):
                    if not txt:
                        kept.append((idx, iid, txt, imp, pay))
                        continue
                    found_dup = False
                    for kidx, kuid, ktxt, kimp, kpay in list(kept):
                        # exact/substring or lexical duplicate
                        if txt == ktxt or (txt in ktxt) or (ktxt in txt) or self._lexical_similarity(txt, ktxt) >= float(self.cfg.dedup_lexical_threshold):
                            primary_uid = kuid
                            primary_payload = dict(kpay)
                            new_txt = ktxt if (txt in ktxt) else (ktxt + "\n" + txt)
                            primary_payload["text"] = new_txt
                            primary_payload["importance"] = min(10, max(int(imp or 0), int(kimp or 0)) + 1)
                            primary_payload["recency_ts"] = _now_ms()
                            primary_payload["uid"] = primary_uid
                            # Upsert merged primary (recompute vector from text)
                            self._upsert_point(primary_payload, text=new_txt)
                            # Delete duplicate point
                            if iid != primary_uid:
                                try:
                                    self.delete_item(iid)
                                except Exception:
                                    pass
                            # Replace kept with updated values
                            kept = [(kidx if ku != kuid else kidx, ku if ku != kuid else primary_uid, (kt if ku != kuid else new_txt), (ki if ku != kuid else primary_payload["importance"]), (kp if ku != kuid else primary_payload)) for (kidx, ku, kt, ki, kp) in kept]
                            merged += 1
                            found_dup = True
                            break
                        # vector duplicate if embedder available
                        if vecs is not None:
                            try:
                                import numpy as _np  # type: ignore
                                v1 = _np.asarray(vecs[idx], dtype="float32")
                                v2 = _np.asarray(vecs[kidx], dtype="float32")
                                denom = (float(_np.linalg.norm(v1) * _np.linalg.norm(v2)) + 1e-9)
                                cos = float(_np.dot(v1, v2) / denom)
                                if cos >= float(self.cfg.dedup_vector_threshold):
                                    primary_uid = kuid
                                    primary_payload = dict(kpay)
                                    new_txt = ktxt if (txt in ktxt) else (ktxt + "\n" + txt)
                                    primary_payload["text"] = new_txt
                                    primary_payload["importance"] = min(10, max(int(imp or 0), int(kimp or 0)) + 1)
                                    primary_payload["recency_ts"] = _now_ms()
                                    primary_payload["uid"] = primary_uid
                                    self._upsert_point(primary_payload, text=new_txt)
                                    if iid != primary_uid:
                                        try:
                                            self.delete_item(iid)
                                        except Exception:
                                            pass
                                    kept = [(kidx if ku != kuid else kidx, ku if ku != kuid else primary_uid, (kt if ku != kuid else new_txt), (ki if ku != kuid else primary_payload["importance"]), (kp if ku != kuid else primary_payload)) for (kidx, ku, kt, ki, kp) in kept]
                                    merged += 1
                                    found_dup = True
                                    break
                            except Exception:
                                pass
                    if not found_dup:
                        kept.append((idx, iid, txt, imp, pay))

            # 2) Decay older items (labels under semantic scope)
            if int(self.cfg.decay_days) > 0 and int(self.cfg.decay_amount) > 0:
                cutoff = _now_ms() - int(self.cfg.decay_days) * 24 * 3600 * 1000
                must_base = [FieldCondition(key="user_id", match=MatchValue(value=uid)), FieldCondition(key="recency_ts", range=Range(lt=int(cutoff)))]
                # We'll page through relevant labels
                dec_labels = ("facts", "preferences", "goals", "profile", "episode")
                for lab in dec_labels:
                    must = list(must_base) + [FieldCondition(key="label", match=MatchValue(value=lab))]
                    next_offset = None
                    page = 0
                    per_page = 512
                    while page < 8:
                        res = self.client.scroll(
                            collection_name=self.cfg.collection,
                            scroll_filter=Filter(must=must),
                            limit=per_page,
                            with_payload=True,
                            offset=next_offset,
                        )
                        points, next_offset = (res if isinstance(res, tuple) else (res, None))
                        if not points:
                            break
                        updated = 0
                        for p in points:
                            pay = dict(p.payload or {})
                            cur_imp = int(pay.get("importance") or 0)
                            if cur_imp <= 0:
                                continue
                            pay["importance"] = max(0, cur_imp - int(self.cfg.decay_amount))
                            pay["uid"] = str(pay.get("uid") or str(p.id))
                            # Keep same text so vector remains consistent with payload
                            self._upsert_point(pay, text=str(pay.get("text") or ""))
                            decayed += 1
                            updated += 1
                        if not next_offset or updated == 0:
                            break
                        page += 1
        except Exception as e:
            print(f"[memory.qdrant] consolidate failed: {e}")
        return {"merged": int(merged), "decayed": int(decayed)}

    def log_turn(self, user_text: str, assistant_text: str) -> None:
        # Maintain a rolling working summary document per user
        def first_sentence(s: str, max_len: int = 160) -> str:
            s = (s or "").strip().replace("\n", " ")
            for dot in [". ", "? ", "! "]:
                if dot in s:
                    s = s.split(dot, 1)[0]
                    break
            return (s[:max_len] + ("…" if len(s) > max_len else "")).strip()

        turn_summary = f"User: {first_sentence(user_text, 140)} | Assistant: {first_sentence(assistant_text, 140)}"
        # Fetch last working summary
        ws_items = self.find_items_by_query("", labels=["working_summary"], limit=1)
        bullets: List[str] = []
        if ws_items:
            prev = (ws_items[0].get("text") or "").splitlines()
            bullets = [ln for ln in prev if ln.strip().startswith("- ")]
        bullets.append(f"- {turn_summary}")
        bullets = bullets[-int(self.cfg.working_turns):]
        new_summary = "\n".join(bullets)
        now = _now_ms()
        payload = {
            "uid": f"ws:{self._user_id}",
            "user_id": self._user_id,
            "label": "working_summary",
            "type": "working",
            "title": "working summary",
            "text": new_summary,
            "importance": 0,
            "created_ts": now,
            "recency_ts": now,
        }
        self._upsert_point(payload, text=new_summary)
        # Append a short episodic summary too
        self.add_label_value("episode", turn_summary)

    def retrieve_context(self, query: str, budget_tokens: int = 1024) -> Dict[str, Any]:
        # Persona
        # Use empty query so lexical fallback returns persona even without a matching substring
        persona_items = self.find_items_by_query("", labels=["persona"], limit=1, include_global=True)
        persona = [{"label": "persona", "value": (persona_items[0]["text"] if persona_items else "").strip()}]
        # User facts
        user_labels = ["user", "profile", "preferences", "facts", "goals"]
        user_items = self.find_items_by_query("", labels=user_labels, limit=64)
        user = [{"label": it["label"], "value": it.get("text", "")} for it in user_items]
        # Working summary
        ws_items = self.find_items_by_query("", labels=["working_summary"], limit=1)
        working = {"summary": (ws_items[0].get("text") if ws_items else "") or "", "recent_turns": []}
        # Long-term memories
        # Prefer vector/keyword search using the provided query when available; otherwise show recent important items.
        # Include profile along with facts/preferences/goals so user facts like name/pronouns are considered.
        q = (query or "").strip()
        items = self.find_items_by_query(q, labels=["facts", "preferences", "goals", "profile"], limit=min(24, self.cfg.top_k))
        long_term = [{"label": it.get("label", "facts"), "value": it.get("text", "")} for it in items]
        return {"persona": persona, "user": user, "working": working, "long_term": long_term}

    # Optional utilities (stubs)
    def index_files(self, paths: Optional[List[str]] = None) -> int:
        # Not implemented for Qdrant in this repo
        return 0

    def export_json(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        uid = user_id or self._user_id
        items = self.find_items_by_query("", labels=None, limit=256, include_global=True)
        items = [it for it in items if (it.get("user_id") in {uid, "__global__"})]
        return {"user_id": uid, "items": items}
