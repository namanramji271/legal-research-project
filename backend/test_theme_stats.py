import requests
token = requests.post("http://localhost:8000/auth/login", json={
    "username": "test_judge", "password": "testpass123"
}).json()["access_token"]

r = requests.post("http://localhost:8000/judgments/theme-stats",
    json={"case_names": ["ILDC case 1961_222", "ILDC case 1966_254"]},
    headers={"Authorization": f"Bearer {token}"})
print(r.json())