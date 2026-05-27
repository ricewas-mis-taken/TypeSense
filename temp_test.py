import requests

response = requests.post(
    "http://localhost:5000/data",
    json={
        "token": "we-like-video-editing",
        "data": {
            "session":          "testtest",
            "ts_ns":            123456789,
            "total press":      100,
            "total release":    100,
            "avg_dwell":        67.5,
            "shortest dwell":   14.9,
            "longest dwell":    210.3,
            "avg_flight":       110.2,
            "shortest flight":  30.1,
            "longest flight":   290.5,
            "avg_burst":        8.4,
            "max_burst":        18,
            "num_bursts":       14,
        }
    }
)

print(response.status_code)
try:
    print(response.json())
except:
    print("raw response:", response.text)