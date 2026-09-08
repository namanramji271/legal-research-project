import requests

BASE = "http://localhost:8000"

judge_token = requests.post(f"{BASE}/auth/login", json={
    "username": "test_judge", "password": "testpass123"
}).json()["access_token"]

student_token = requests.post(f"{BASE}/auth/login", json={
    "username": "test_student", "password": "testpass123"
}).json()["access_token"]

r = requests.get(f"{BASE}/search", params={"q": "private defence"},
                  headers={"Authorization": f"Bearer {judge_token}"})
print("judge ->", r.status_code)

r = requests.get(f"{BASE}/search", params={"q": "private defence"},
                  headers={"Authorization": f"Bearer {student_token}"})
print("student ->", r.status_code)

r = requests.get(f"{BASE}/search", params={"q": "private defence"})
print("no token ->", r.status_code)
