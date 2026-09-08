import requests

BASE = "http://localhost:8000"

print("--- Signing up one user per role ---")
for role in ["lawyer", "judge", "student", "public"]:
    r = requests.post(f"{BASE}/auth/signup", json={
        "username": f"test_{role}", "password": "testpass123", "role": role
    })
    print(role, "->", r.status_code, r.json())

print("\n--- Logging in as test_judge ---")
r = requests.post(f"{BASE}/auth/login", json={"username": "test_judge", "password": "testpass123"})
print(r.status_code, r.json())

print("\n--- Wrong password (should be 401) ---")
r = requests.post(f"{BASE}/auth/login", json={"username": "test_judge", "password": "wrongpass"})
print(r.status_code)

print("\n--- Duplicate username (should be 400) ---")
r = requests.post(f"{BASE}/auth/signup", json={"username": "test_judge", "password": "x", "role": "lawyer"})
print(r.status_code, r.json())

print("\n--- Duplicate username, valid password this time (should be 400) ---")
r = requests.post(f"{BASE}/auth/signup", json={
    "username": "test_judge", "password": "somevalidpass123", "role": "lawyer"
})
print(r.status_code, r.json())