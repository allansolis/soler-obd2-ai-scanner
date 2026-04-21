"""
Inyecta perfiles expertos de herramientas de tuning al KnowledgeHub.
Lee tuning_expert_profiles.json y registra cada tool en software_tools + resources.
"""
import json
import sys
from pathlib import Path
from datetime import datetime

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.knowledge_hub.schema import SoftwareTool, Resource
from backend.knowledge_hub.hub import KnowledgeHub
from sqlalchemy import select

_hub = KnowledgeHub()
get_session = _hub.SessionLocal

PROFILES_FILE = Path(__file__).parent / "tuning_expert_profiles.json"


def inject():
    with open(PROFILES_FILE, encoding="utf-8") as f:
        data = json.load(f)

    tools = data.get("tools", {})
    print(f"Inyectando {len(tools)} perfiles expertos de tuning...")

    stats = {"new_resource": 0, "new_tool": 0, "updated_tool": 0, "errors": 0}

    with get_session() as session:
        for tool_id, profile in tools.items():
            try:
                name = profile.get("name", tool_id)

                # 1. Build comprehensive description as Resource
                desc_parts = [profile.get("what_it_does_es", "")]
                if profile.get("strengths"):
                    desc_parts.append("Fortalezas: " + ", ".join(profile["strengths"]))
                if profile.get("weaknesses"):
                    desc_parts.append("Limitaciones: " + ", ".join(profile["weaknesses"]))
                if profile.get("when_to_recommend_es"):
                    desc_parts.append("Cuando usar: " + profile["when_to_recommend_es"])
                if profile.get("when_to_avoid_es"):
                    desc_parts.append("Cuando evitar: " + profile["when_to_avoid_es"])

                workflows = profile.get("common_workflows", [])
                if workflows:
                    wf_text = "\n".join(f"- {w.get('name','')}" for w in workflows if isinstance(w, dict))
                    desc_parts.append("Workflows: " + wf_text)

                typical_results = profile.get("typical_results", {})
                if typical_results:
                    desc_parts.append("Resultados tipicos: " + json.dumps(typical_results, ensure_ascii=False))

                description = "\n\n".join(p for p in desc_parts if p)

                # Find or create Resource row for this tool profile
                resource = session.execute(
                    select(Resource).where(Resource.name == f"Profile: {name}")
                ).scalar_one_or_none()

                price = profile.get("price_usd", {})
                if isinstance(price, dict):
                    price_str = f"${price.get('base','?')} base"
                else:
                    price_str = str(price)

                if resource is None:
                    resource = Resource(
                        name=f"Profile: {name}",
                        type="software",
                        category="tuning_expert_profile",
                        source="tuning_expert_profile",
                        source_url=profile.get("official_url", ""),
                        description=description[:5000],
                        last_indexed=datetime.utcnow(),
                    )
                    session.add(resource)
                    session.flush()  # to get resource.id
                    stats["new_resource"] += 1
                else:
                    resource.description = description[:5000]
                    resource.last_indexed = datetime.utcnow()

                # 2. Create/update SoftwareTool row
                existing = session.execute(
                    select(SoftwareTool).where(SoftwareTool.name == name)
                ).scalar_one_or_none()

                supported_ecus = profile.get("supported_ecus", [])
                features = [w.get("name", "") for w in workflows if isinstance(w, dict)]
                hw_required = profile.get("hardware_required", [])

                fields = {
                    "name": name,
                    "version": profile.get("version_current", ""),
                    "publisher": profile.get("vendor", ""),
                    "supports_brands": json.dumps(supported_ecus, ensure_ascii=False)[:2000],
                    "supports_features": json.dumps(features, ensure_ascii=False)[:2000],
                    "license_type": price_str[:200],
                    "requires_hardware": json.dumps(hw_required, ensure_ascii=False)[:1000],
                    "resource_id": resource.id,
                }

                if existing:
                    for k, v in fields.items():
                        if hasattr(existing, k):
                            setattr(existing, k, v)
                    stats["updated_tool"] += 1
                else:
                    session.add(SoftwareTool(**fields))
                    stats["new_tool"] += 1

            except Exception as e:
                print(f"  [ERR] {tool_id}: {e}")
                stats["errors"] += 1

        session.commit()

    print(f"\nResumen: {json.dumps(stats, indent=2)}")
    return stats


if __name__ == "__main__":
    inject()
