
import re
from pathlib import Path

plan_file = Path("/Users/paulaan/PycharmProjects/agent-os/.agents/plans/PLAN.template.md")
if plan_file.exists():
    content = plan_file.read_text()
else:
    content = "> Status: draft\n> Created: 2026-03-13T21:17:47+08:00\n"

status_match = re.search(r"> Status:\s*(.*)", content)
created_match = re.search(r"> Created:\s*(.*)", content)

print(f"Status Match: {status_match.group(1) if status_match else 'None'}")
print(f"Created Match: {created_match.group(1) if created_match else 'None'}")
