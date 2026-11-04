import time
import httpx

API_URL = "http://localhost:8000/api/v1"
HEALTH_URL = "http://localhost:8000/health"

def run_demo():
    print("🚀 Starting AegisMem Local Ollama Integration Demo...")
    
    # Wait for API to be ready
    for i in range(10):
        try:
            res = httpx.get(HEALTH_URL)
            if res.status_code == 200:
                print("✅ AegisMem API is online.")
                break
        except httpx.ConnectError:
            print(f"⏳ Waiting for API to spin up (Attempt {i+1}/10)...")
            time.sleep(3)
    else:
        print("❌ API failed to start. Ensure docker-compose is running.")
        return

    # 1. Ingest initial fact
    print("\n🧠 1. Ingesting first memory...")
    res1 = httpx.post(f"{API_URL}/ingest", json={
        "text": "I absolutely love working out in the morning, usually around 6 AM.",
        "user_id": "demo-user-1",
        "agent_id": "ollama-agent",
        "memory_type": "observation",
        "source_type": "user_message",
        "metadata": {}
    }, timeout=10.0)
    
    if res1.status_code == 201:
        mem1_id = res1.json().get("memory_id")
        print(f"✅ Ingested successfully. Memory ID: {mem1_id}")
    else:
        print(f"❌ Failed to ingest: {res1.text}")
        return

    # Wait briefly for vector store indexing
    time.sleep(2)

    # 2. Ingest contradicting fact
    print("\n🧠 2. Ingesting a contradicting memory...")
    res2 = httpx.post(f"{API_URL}/ingest", json={
        "text": "Actually, I changed my mind. I hate waking up early and only work out in the evenings now.",
        "user_id": "demo-user-1",
        "agent_id": "ollama-agent",
        "memory_type": "observation",
        "source_type": "user_message",
        "metadata": {}
    }, timeout=10.0)
    
    if res2.status_code == 201:
        mem2_id = res2.json().get("memory_id")
        print(f"✅ Ingested successfully. Memory ID: {mem2_id}")
    else:
        print(f"❌ Failed to ingest second memory: {res2.text}")
        return

    time.sleep(2)

    # 3. Trigger Ollama Contradiction Check
    print("\n🕵️‍♂️ 3. Asking local Ollama to scan for contradictions...")
    print("   (This might take a few seconds as the local LLM evaluates the logic)")
    scan_res = httpx.post(f"{API_URL}/contradictions/scan", json={
        "memory_id": mem2_id,
        "user_id": "demo-user-1"
    }, timeout=180.0)
    
    if scan_res.status_code == 200:
        data = scan_res.json()
        found = data.get("contradictions_found", 0)
        print(f"✅ Scanning complete! Contradictions found: {found}")
        
        for idx, report in enumerate(data.get("reports", [])):
            print(f"\n   🔴 Contradiction #{idx+1}:")
            print(f"      Description: {report.get('description')}")
            print(f"      Confidence:  {report.get('confidence')}")
            
    else:
        print(f"❌ Failed to scan for contradictions: {scan_res.text}")

    print("\n🎉 Demo complete! The local integration successfully hit the LLM layer.")

if __name__ == "__main__":
    run_demo()
