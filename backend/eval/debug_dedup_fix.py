import sys
sys.path.insert(0, "backend")
from qa import ask_question

response = ask_question("How do courts distinguish murder under IPC Section 300 from culpable homicide?")
print("sources_used:", response["sources_used"])
print("verified:", response["verified"])
print("unverified_citations:", response["unverified_citations"])