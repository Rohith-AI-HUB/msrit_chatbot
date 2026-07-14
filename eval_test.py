import urllib.request, json, time, sys

questions = [
    "How to apply for admission to MSRIT?",
    "What is the admission process for B.E. programs?",
    "What are the eligibility criteria for M.Tech?",
    "Is there a management quota for admissions?",
    "What is the cutoff rank for CSE in KCET?",
    "Does MSRIT accept COMEDK scores?",
    "What documents are needed for admission?",
    "When do admissions start for 2025?",
    "List all undergraduate programs at MSRIT",
    "Does MSRIT offer MBA?",
    "What are the PG programs available?",
    "Is there a PhD program?",
    "Tell me about the Computer Science department",
    "Does MSRIT have an AI and Data Science program?",
    "What is the duration of B.Arch program?",
    "Are there any integrated courses?",
    "What is the fee structure for B.E.?",
    "How much are the tuition fees for M.Tech?",
    "What is the hostel fee per year?",
    "Is there a scholarship for merit students?",
    "What are the fees for management quota?",
    "Does MSRIT offer fee waivers?",
    "What is the application fee?",
    "Are there payment installment options?",
    "How many professors are in CSE department?",
    "Who is the head of the ECE department?",
    "What is the faculty-student ratio?",
    "Are there PhD qualified faculty?",
    "Tell me about the faculty in Mechanical Engineering",
    "What is the placement percentage at MSRIT?",
    "Which companies visit MSRIT for placements?",
    "What is the highest package offered?",
    "Does MSRIT have placement training?",
    "What is the average salary package?",
    "Are there internships during the course?",
    "What facilities are available in the hostel?",
    "Does MSRIT have a gym?",
    "Are there sports facilities?",
    "What clubs and extracurricular activities are there?",
    "Is there a library on campus?",
    "Does the campus have WiFi?",
    "What is the canteen like?",
    "Are there medical facilities on campus?",
    "What is MSRIT ranking in NIRF?",
    "Is MSRIT NBA accredited?",
    "Does MSRIT have NAAC accreditation?",
    "What is the grade given by NAAC?",
    "Where is MSRIT located?",
    "What is the official website of MSRIT?",
    "How can I contact the admission office?",
    "What are the college timings?",
    "Does MSRIT have transport facilities?",
    "What is the alumni network like?",
]

results = []
success = 0
failed = 0
fallback = 0
total_latency = 0

for i, q in enumerate(questions, 1):
    time.sleep(0.3)
    try:
        body = json.dumps({"question": q, "session_id": "eval-test", "debug": False}).encode()
        req = urllib.request.Request("http://localhost:8000/api/chat", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        start = time.time()
        r = urllib.request.urlopen(req, timeout=120)
        latency = int((time.time() - start) * 1000)
        total_latency += latency
        resp = json.loads(r.read())

        is_fallback = resp["answer"] == "I don't have that information. Please visit msrit.edu or contact the relevant department directly."
        has_content = not is_fallback and len(resp["answer"]) > 30

        if has_content:
            success += 1
        elif is_fallback:
            fallback += 1
        else:
            failed += 1

        results.append({
            "num": i, "question": q,
            "result": "OK" if has_content else ("FALLBACK" if is_fallback else "FAIL"),
            "answer_len": len(resp["answer"]),
            "answer": resp["answer"][:200],
            "sources": resp["sources"][:3],
            "num_docs": resp["retrieved_documents_count"],
            "rewrite": resp["rewritten_query"],
            "latency_ms": latency
        })
        print(f"  Q{i:2d}: {results[-1]['result']:8s} | {latency:5d}ms | {len(resp['answer']):4d} chars | {resp['rewritten_query'][:60]}", flush=True)
    except Exception as e:
        failed += 1
        results.append({"num": i, "question": q, "result": "ERROR", "answer": str(e)[:150], "latency_ms": 0})
        print(f"  Q{i:2d}: ERROR    | {str(e)[:80]}", flush=True)

print()
print("=" * 60)
print("EVALUATION SUMMARY")
print("=" * 60)
print(f"Total questions: {len(questions)}")
print(f"Good answers: {success}")
print(f"Fallback (no info): {fallback}")
print(f"Failed/Error: {failed}")
print(f"Success rate: {success/len(questions)*100:.1f}%")
print(f"Avg latency: {total_latency//max(len(questions),1)}ms")

categories = [
    ("Admissions", 1, 8), ("Programs", 9, 16), ("Fees", 17, 24),
    ("Faculty", 25, 29), ("Placements", 30, 35), ("Campus", 36, 43),
    ("Rankings", 44, 47), ("General", 48, 53),
]
for cat, start, end in categories:
    cat_r = [r for r in results if start <= r["num"] <= end]
    ok = sum(1 for r in cat_r if r["result"] == "OK")
    fb = sum(1 for r in cat_r if r["result"] == "FALLBACK")
    fl = sum(1 for r in cat_r if r["result"] in ("FAIL", "ERROR"))
    print(f"  {cat:12s}: {ok}/{len(cat_r)} OK, {fb} fallback, {fl} fail")

with open("eval_results.json", "w") as f:
    json.dump(results, f, indent=2)
print(f"\nFull results saved to eval_results.json")
